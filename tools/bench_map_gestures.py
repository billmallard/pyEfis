#!/usr/bin/env python3
"""Offscreen gesture benchmark for the moving map (MP7, briefs/
map_gesture_perf_plan.md section 4; pyEfis #98).

Builds a real ``MovingMap`` under the Qt ``offscreen`` platform, wired to
the same in-memory mock FIX database ``conftest.py`` patches in for the
unit tests (no fix-gateway needed), and drives it through one of several
gesture scenarios exactly the way a touch pinch/rotate/pan or an HMI range
step would: by calling the widget's own ``zoom_by``/``rotate_by``/
``pan_by``/``range_up`` entry points and pumping the Qt event loop so its
own machinery -- the MP1 gesture-phase gating and settle debounce, the MP2
newest-wins worker publication, the MP3 frame clock, and the MP6 perf
counters -- all run exactly as they would live. Nothing here re-implements
or bypasses that logic; the harness only supplies input and reads
``widget.perf`` afterwards.

Scenarios (brief section 4, MP7):
    pinch_out   10 -> 160 NM, 90 zoom_by events at 60 Hz, then hold 5 s.
    pinch_in    160 -> 10 NM, mirror of pinch_out.
    rotate      3 s continuous rotate_by sweep at 60 Hz (180 events).
    pan         3 s continuous pan_by sweep at 60 Hz, then hold 3 s.
    ladder      HMI range_up() through the whole range_ladder, immediate
                (no gesture gating) -- the discrete-step counterpart to
                the continuous pinch scenarios.
    all         every scenario above, each against a fresh widget.

The "pan" event count/cadence and "rotate"'s exact sweep angle are not
pinned down by the brief beyond "3 s at 60 Hz" for rotate; this harness
documents its concrete choices as the ``_ROTATE_*``/``_PAN_*`` constants
below rather than leaving them implicit.

Output: one JSON record per scenario run (always a JSON array, even for a
single scenario) written to --out or stdout; schema documented in
docs/moving_map_spec.md section 9. Progress/summary lines go to stderr so
stdout stays pipeable JSON. --budget <path> checks the run against a
budgets file and exits non-zero on any violation.

Run (Windows, deps on C:/pylib):
    PYTHONPATH="C:/pylib;src" python tools/bench_map_gestures.py \\
        --scenario all --tile-path D:/EarthData/glo30hgt

Run (bench, real packs, alongside the live display):
    ssh pyefis@10.110.10.241
    cd ~/src/pyEfis && export QT_QPA_PLATFORM=offscreen PYTHONPATH=src
    nice -n 10 ~/pyefis-venv/bin/python tools/bench_map_gestures.py \\
        --scenario all \\
        --tile-path /data/makerplane-data/terrain/tiles \\
        --water-db /data/makerplane-data/water/current/water.sqlite \\
        --highway-db /data/makerplane-data/highways/current/highways.sqlite \\
        --nasr-db /data/makerplane-data/navdata/current/airports.sqlite \\
        --navaid-db /data/makerplane-data/navaids/current/navaids.sqlite
"""
import argparse
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # no display needed

SCHEMA_VERSION = 1

#: gesture-event injection rate the brief specifies for every scenario.
_EVENT_HZ = 60.0
#: Qt event-loop pump rate while a scenario runs (brief section 4: "1 kHz
#: event pump") -- this is what lets the widget's own QTimers (frame
#: clock, settle timer) and worker-thread update() calls run as they
#: would live, with no test-only shortcut.
_PUMP_HZ = 1000.0

#: pinch_out/pinch_in: 90 events at 60 Hz (brief section 4, MP7).
_PINCH_EVENTS = 90
_PINCH_RANGE_LO_NM = 10.0
_PINCH_RANGE_HI_NM = 160.0
#: hold after the last event so the settle timer + worker can finish and
#: publish -- long enough to observe settle_latency_ms on a cold cache.
_PINCH_HOLD_S = 5.0

#: rotate: "3 s at 60 Hz" (brief section 4) = 180 events; total sweep
#: angle is this harness's documented choice (not specified by the
#: brief), producing 1 deg/event.
_ROTATE_DURATION_S = 3.0
_ROTATE_EVENTS = int(_ROTATE_DURATION_S * _EVENT_HZ)
_ROTATE_SWEEP_DEG = 180.0

#: pan: the brief lists the scenario but not its shape. Documented choice:
#: the same 3 s / 60 Hz cadence as rotate (a steady screen-space drag),
#: plus a hold since panning re-keys the terrain/roads window the same
#: way zooming does (brief section 2, R2).
_PAN_DURATION_S = 3.0
_PAN_EVENTS = int(_PAN_DURATION_S * _EVENT_HZ)
_PAN_PX_PER_EVENT = 3.0
_PAN_HOLD_S = 3.0

#: ladder: HMI range steps are immediate (no gesture gating, brief
#: section 4 MP1 DoD), so events don't need 60 Hz pacing -- just enough
#: hold between steps for each step's render to land, plus a final hold.
_LADDER_STEP_HOLD_S = 0.2
_LADDER_FINAL_HOLD_S = 2.0

#: default widget size: the bench's tab_section map (brief section 1).
_DEFAULT_W = 650
_DEFAULT_H = 1040
#: default scene: Raleigh 35.8/-78.8 -- lakes + Pamlico/Albemarle coast at
#: 160 NM, the scene the brief's numbers were measured against.
_DEFAULT_LAT = 35.8
_DEFAULT_LON = -78.8


def _git_rev():
    """Short HEAD SHA, or "" outside a git checkout -- never raises (this
    is a data-gathering helper, not something a bad rev should abort)."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(Path(__file__).resolve().parent.parent),
            capture_output=True, text=True, timeout=5)
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:
        return ""


def _bootstrap_fix_db(lat, lon, track, alt_ft):
    """Patch pyavtools.fix onto the same in-memory mock client/scheduler
    conftest.py uses for the unit tests, then define the four FIX keys
    MovingMap subscribes to (LAT/LONG/TRACKM/ALT). Must patch
    sys.modules before pyavtools.fix is first imported anywhere in the
    process -- ``from . import client`` binds the submodule by value, so
    a patch after that import is a no-op (this is why conftest.py does
    the same patch at the top of the file, before any test collection)."""
    tests_dir = Path(__file__).resolve().parent.parent / "tests"
    if str(tests_dir) not in sys.path:
        sys.path.insert(0, str(tests_dir))
    import mock_db.client
    import mock_db.scheduler
    sys.modules["pyavtools.fix.client"] = mock_db.client
    sys.modules["pyavtools.scheduler"] = mock_db.scheduler

    import pyavtools.fix as fix
    fix.initialize({"main": {"FixServer": "localhost", "FixPort": "3490"}})

    def _def(key, lo, hi, unit, value):
        fix.db.define_item(key, key, "float", lo, hi, unit, 50000, "")
        fix.db.set_value(key, value)
        fix.db.get_item(key).bad = False
        fix.db.get_item(key).fail = False

    _def("LAT", -90.0, 90.0, "deg", lat)
    _def("LONG", -180.0, 180.0, "deg", lon)
    _def("TRACKM", 0.0, 359.9, "deg", track)
    _def("ALT", -2000.0, 60000.0, "ft", alt_ft)
    return fix


def _pump(app, seconds, hz=_PUMP_HZ):
    """Drain the Qt event loop for *seconds* wall-clock time at ~*hz*,
    servicing QTimers (frame clock, settle timer) and any queued
    update() call a worker thread posted -- this is the "1 kHz event
    pump" the brief calls for, and it's what makes the widget's own
    async machinery run exactly as it would live."""
    period = 1.0 / hz
    deadline = time.perf_counter() + seconds
    while True:
        app.processEvents()
        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            break
        time.sleep(min(period, remaining))
    app.processEvents()


def _run_events(app, events, event_hz=_EVENT_HZ):
    """Inject *events* (zero-arg callables) paced at event_hz, pumping
    the loop between each (brief section 4: "1 kHz event pump" servicing
    "90 zoom_by events at 60 Hz" and friends)."""
    dt = 1.0 / event_hz
    t0 = time.perf_counter()
    for i, fn in enumerate(events):
        target = t0 + i * dt
        remaining = target - time.perf_counter()
        if remaining > 0:
            _pump(app, remaining)
        fn()
    app.processEvents()


def _gesture_bracket(w):
    """(GestureStarted, GestureFinished) callables that bracket a
    continuous gesture exactly the way MovingMap.event() would off a
    real QPinchGesture (MP1 gating) -- calling the widget's own
    ``_gesture_phase`` is the same entry point event() uses, without
    constructing a fake QGesture object."""
    from PyQt6.QtCore import Qt
    GS = Qt.GestureState
    return (lambda: w._gesture_phase(GS.GestureStarted),
            lambda: w._gesture_phase(GS.GestureFinished))


# --- scenarios --------------------------------------------------------

def _scenario_pinch(app, w, lo_nm, hi_nm, zoom_in):
    """Shared pinch_out/pinch_in body: N events whose per-event factor
    geometrically walks range_nm from lo_nm/hi_nm to the other bound in
    exactly _PINCH_EVENTS steps, bracketed by the gesture phase so MP1's
    gating engages (0 renders during the gesture, 1 after settle)."""
    start, end = (lo_nm, hi_nm) if zoom_in is False else (hi_nm, lo_nm)
    w.range_nm = start
    factor = (start / end) ** (1.0 / _PINCH_EVENTS)
    started, finished = _gesture_bracket(w)
    started()
    _run_events(app, [lambda f=factor: w.zoom_by(f)
                      for _ in range(_PINCH_EVENTS)])
    finished()
    _pump(app, _PINCH_HOLD_S)
    return dict(range_from_nm=start, range_to_nm=end,
                range_actual_nm=w.range_nm, events=_PINCH_EVENTS,
                event_hz=_EVENT_HZ, hold_s=_PINCH_HOLD_S)


def scenario_pinch_out(app, w):
    return _scenario_pinch(app, w, _PINCH_RANGE_LO_NM, _PINCH_RANGE_HI_NM,
                           zoom_in=False)


def scenario_pinch_in(app, w):
    return _scenario_pinch(app, w, _PINCH_RANGE_LO_NM, _PINCH_RANGE_HI_NM,
                           zoom_in=True)


def scenario_rotate(app, w):
    started, finished = _gesture_bracket(w)
    started()
    delta = _ROTATE_SWEEP_DEG / _ROTATE_EVENTS
    _run_events(app, [lambda d=delta: w.rotate_by(d)
                      for _ in range(_ROTATE_EVENTS)])
    finished()
    app.processEvents()
    return dict(sweep_deg=_ROTATE_SWEEP_DEG, events=_ROTATE_EVENTS,
                event_hz=_EVENT_HZ, duration_s=_ROTATE_DURATION_S)


def scenario_pan(app, w):
    started, finished = _gesture_bracket(w)
    started()
    _run_events(app, [lambda: w.pan_by(_PAN_PX_PER_EVENT, 0.0)
                      for _ in range(_PAN_EVENTS)])
    finished()
    _pump(app, _PAN_HOLD_S)
    return dict(dx_px_per_event=_PAN_PX_PER_EVENT, dy_px_per_event=0.0,
                events=_PAN_EVENTS, event_hz=_EVENT_HZ,
                hold_s=_PAN_HOLD_S)


def scenario_ladder(app, w):
    ladder = w._ladder()
    w.range_nm = ladder[0]
    _pump(app, _LADDER_STEP_HOLD_S)
    for _ in ladder[1:]:
        w.range_up()
        _pump(app, _LADDER_STEP_HOLD_S)
    _pump(app, _LADDER_FINAL_HOLD_S)
    return dict(ladder=ladder, step_hold_s=_LADDER_STEP_HOLD_S,
                final_hold_s=_LADDER_FINAL_HOLD_S)


SCENARIOS = {
    "pinch_out": scenario_pinch_out,
    "pinch_in": scenario_pinch_in,
    "rotate": scenario_rotate,
    "pan": scenario_pan,
    "ladder": scenario_ladder,
}


# --- widget / run plumbing ---------------------------------------------

def build_widget(args):
    from pyefis.instruments import map as moving_map
    w = moving_map.MovingMap()
    w.resize(args.w, args.h)
    w.range_ladder = args.range_ladder
    w.range_nm = 10.0
    w.orientation = "track_up"
    w.touch_gestures = True
    w.tile_path = args.tile_path
    w.water_db_path = args.water_db
    w.water_max_vertices = args.water_max_vertices
    w.water_raster = args.water_raster
    w.highway_db_path = args.highway_db
    w.river_db_path = args.river_db
    w.nasr_db_path = args.nasr_db
    w.navaid_db_path = args.navaid_db
    # The GUI-thread responsiveness probe (brief section 4's objective
    # GIL-starvation detector) only runs while map_perf_log/overlay is
    # on; a gesture bench without it would always report zeros for the
    # one counter the brief's acceptance table (section 5) budgets on
    # directly ("GUI-thread starved time"). map_perf_log's own periodic
    # log line is harmless noise -- log.info with no handler configured
    # produces no output.
    w.map_perf_log = True
    return w


def _one_line_summary(name, snap, duration_s):
    from pyefis.instruments.map.perf import PROBE_GAP_WARN_MS
    pm = snap["paint_ms"]
    probe = snap["probe"]
    settle = snap["settle_latency_ms"]
    settle_s = ("%.0fms" % settle) if settle is not None else "n/a"
    layer_bits = "; ".join(
        "%s req=%d pub=%d superseded=%d" % (
            lid, ls["jobs_requested"], ls["jobs_published"],
            ls["jobs_superseded"])
        for lid, ls in sorted(snap["layers"].items()))
    return (
        "%s: %.2fs, %d paints (p50=%.1f p95=%.1f max=%.1f ms), "
        "settle=%s, gui gap p95=%.1fms max=%.1fms >%dms=%d%s" % (
            name, duration_s, snap["frames_painted"],
            pm["p50"], pm["p95"], pm["max"], settle_s,
            probe["p95_ms"], probe["max_ms"], int(PROBE_GAP_WARN_MS),
            probe["over_count"],
            ("; " + layer_bits) if layer_bits else ""))


def run_scenario(app, args, name, rev, host):
    w = build_widget(args)
    w.show()
    # Deterministic warm-up: build the layer set (same call paintEvent
    # would make lazily) without going through paintEvent -- the first
    # REAL paint the widget produces on its own frame-clock tick below
    # is legitimate scenario activity (a live screen paints once before
    # you can gesture on it); an extra forced paintEvent() call here
    # would not be.
    w._build_layers()
    _pump(app, 0.1)   # let the frame clock's first tick paint + settle

    t0 = time.perf_counter()
    params = SCENARIOS[name](app, w)
    duration_s = time.perf_counter() - t0

    snap = w.perf.snapshot()
    summary = _one_line_summary(name, snap, duration_s)
    return dict(
        schema_version=SCHEMA_VERSION, rev=rev, host=host, scenario=name,
        widget=dict(w=args.w, h=args.h), lat=args.lat, lon=args.lon,
        duration_s=duration_s, params=params, counters=snap,
        summary=summary)


# --- budgets -------------------------------------------------------------

def _get_path(d, path):
    cur = d
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None, False
        cur = cur[part]
    return cur, True


def check_budgets(results, budgets):
    """budgets: {scenario: [{"path": "a.b.c", "max": x} | {"min": x}, ...]}
    against dotted paths into each result's "counters" snapshot. A path
    that isn't present (e.g. a layer that never ran because no data path
    was given) is skipped with a warning, not treated as a violation --
    mirrors MP8's "warn on unknown host" tolerance for what the harness
    can't measure in a given run. Returns the list of violations."""
    violations = []
    by_scenario = {r["scenario"]: r for r in results}
    for name, checks in budgets.items():
        r = by_scenario.get(name)
        if r is None:
            continue
        for check in checks:
            path = check["path"]
            value, found = _get_path(r["counters"], path)
            if not found or value is None:
                print("bench_map_gestures: budget path %r not present in "
                      "%r counters -- skipped" % (path, name),
                      file=sys.stderr)
                continue
            if "max" in check and value > check["max"]:
                violations.append(dict(scenario=name, path=path,
                                       value=value, bound="max",
                                       limit=check["max"]))
            if "min" in check and value < check["min"]:
                violations.append(dict(scenario=name, path=path,
                                       value=value, bound="min",
                                       limit=check["min"]))
    return violations


# --- CLI -----------------------------------------------------------------

def _parse_args(argv):
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenario",
                    choices=list(SCENARIOS) + ["all"], default="all")
    ap.add_argument("--w", type=int, default=_DEFAULT_W)
    ap.add_argument("--h", type=int, default=_DEFAULT_H)
    ap.add_argument("--lat", type=float, default=_DEFAULT_LAT)
    ap.add_argument("--lon", type=float, default=_DEFAULT_LON)
    ap.add_argument("--track", type=float, default=0.0)
    ap.add_argument("--alt", type=float, default=1500.0,
                    help="ownship altitude, ft (caution-mode terrain tint)")
    ap.add_argument("--range-ladder", default="2,5,10,20,40,80,160")
    ap.add_argument("--tile-path", default="",
                    help="GLO-30/SRTM mip pyramid root (terrain layer)")
    ap.add_argument("--water-db", default="", help="water.sqlite")
    ap.add_argument("--water-max-vertices", type=int, default=512)
    ap.add_argument("--water-raster", choices=["numpy", "qt"],
                    default="numpy")
    ap.add_argument("--highway-db", default="", help="highways.sqlite")
    ap.add_argument("--river-db", default="", help="rivers.sqlite")
    ap.add_argument("--nasr-db", default="", help="airports.sqlite")
    ap.add_argument("--navaid-db", default="", help="navaids.sqlite")
    ap.add_argument("--out", default="",
                    help="write JSON here instead of stdout")
    ap.add_argument("--budget", default="",
                    help="budgets JSON; exit non-zero on any violation")
    return ap.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)
    _bootstrap_fix_db(args.lat, args.lon, args.track, args.alt)

    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])

    names = list(SCENARIOS) if args.scenario == "all" else [args.scenario]
    rev, host = _git_rev(), socket.gethostname()

    results = []
    for name in names:
        r = run_scenario(app, args, name, rev, host)
        print(r["summary"], file=sys.stderr)
        results.append(r)

    payload = json.dumps(results, indent=2)
    if args.out:
        Path(args.out).write_text(payload + "\n")
    else:
        print(payload)

    if args.budget:
        budgets = json.loads(Path(args.budget).read_text())
        violations = check_budgets(results, budgets)
        if violations:
            print("BUDGET VIOLATIONS:", file=sys.stderr)
            for v in violations:
                print("  [%s] %s = %s (%s %s)" % (
                    v["scenario"], v["path"], v["value"], v["bound"],
                    v["limit"]), file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
