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

--moving-position (AER-679, briefs/map_gesture_perf_plan.md section 5):
    Every gesture scenario above pins LAT/LONG and only varies range/
    rotation/pan -- a regime the aircraft is never actually in. AER-677
    found that driving real LAT/LONG motion collapses the SVS frame gap
    from ~25 ms (40 fps) to ~699 ms (1.4 fps) even though SVS's own
    internal render time barely moves (frame.svs_total stayed ~6.5 ms):
    the render thread is being STARVED by the position-triggered
    collectors (water/highway/obstacle queries), not doing more drawing.
    A static bench pattern cannot see this at all.

    --moving-position drives LAT/LONG at --gs/--heading/--position-hz for
    --duration seconds (default 130 kt / 280 deg / 20 Hz -- AER-677's own
    fixgw.netfix reproduction, promoted here rather than reinvented) and
    reports frame-GAP percentiles (p50/p95/p99/max -- "a mean hides a
    lurch") for whichever --target you ask for (map, svs, or both,
    default both), plus a hit/miss tally for the SVS water/highway/
    obstacle/airport collector caches so a red result can be read as
    "renderer slow" (frame_total_ms high) vs "renderer starved"
    (frame_gap_ms high while frame_total_ms stays low, collector misses
    high) -- exactly the distinction that diagnosed AER-677. Caveat
    carried through to the output ("caveat" key): the position writer
    itself is Python load, so this measures "pyEfis under motion
    comparable to X-Plane," not a pure-pyEfis number.

    Pass threshold: svs.frame_gap_ms.p95 <= 50 ms; map.probe.p95_ms <= 50
    ms (AER-1082). Both 50 ms bounds are ``PROBE_GAP_WARN_MS`` from
    map/perf.py, the project's own existing GUI-thread-stall gate (MP6).
    SVS is gated on its own paint-to-paint gap directly. AER-1086
    re-measured the healthy baseline on current dev with this harness
    (real GL required -- offscreen QPA can't create a QOpenGLWidget
    context; run under a shared X display instead, see that issue):
    p50 33.0 / p95 34.0 / p99 34.9 / max 35.6 ms, 41 s at 130 kt/280
    deg/20 Hz, collector hit rates >99%. SVS repaints on its own
    free-running 30 fps QTimer (ai/__init__.py set_frame_rate), not on
    position change, so this tracks that timer's ~33.3 ms period rather
    than being floored by the 20 Hz drive period -- 50 ms keeps clean
    margin above it. (The bar's earlier "~25 ms (40 fps)" justification
    was a DEMO-era figure -- AER-677 retired that whole measurement
    era -- and is no longer the basis for this bound.) The map is NOT
    gated on frame_gap_ms (still reported as an observable): AER-692
    found it reads ~205-300 ms by pose-quantization arithmetic alone at
    10 NM/130 kt with every layer healthy, which would make a
    frame_gap_ms bound permanently red. The map is instead gated on
    probe.p95_ms, GuiProbe's own 10 ms-timer tick-to-tick gap -- the
    objective GIL-starvation detector, insensitive to pose quantization.
    See tools/budgets/moving_position.json for a ready-to-use --budget
    file and docs/moving_map_spec.md section 9.2 for the full
    derivation.

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

Run --moving-position (bench, real packs, AER-677 repro defaults):
    ssh pyefis@10.110.10.241
    cd ~/src/pyEfis && export QT_QPA_PLATFORM=offscreen PYTHONPATH=src
    nice -n 10 ~/pyefis-venv/bin/python tools/bench_map_gestures.py \\
        --moving-position --target both --duration 40 \\
        --tile-path /data/makerplane-data/terrain/tiles \\
        --water-db /data/makerplane-data/water/current/water.sqlite \\
        --highway-db /data/makerplane-data/highways/current/highways.sqlite \\
        --nasr-db /data/makerplane-data/navdata/current/airports.sqlite \\
        --dof-db /data/makerplane-data/obstacles/current/obstacles.sqlite \\
        --budget tools/budgets/moving_position.json
"""
import argparse
import json
import math
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


def _bootstrap_fix_db(lat, lon, track, alt_ft, gs=120.0):
    """Patch pyavtools.fix onto the same in-memory mock client/scheduler
    conftest.py uses for the unit tests, then define the FIX keys
    MovingMap and the AI/SVS widget subscribe to. Must patch
    sys.modules before pyavtools.fix is first imported anywhere in the
    process -- ``from . import client`` binds the submodule by value, so
    a patch after that import is a no-op (this is why conftest.py does
    the same patch at the top of the file, before any test collection).

    LAT/LONG/TRACKM/ALT are all MovingMap needs. The AI widget needs more
    (AER-679): PITCH/ROLL/ALAT/TAS are fetched unguarded in its
    constructor (ai/__init__.py raises KeyError if they're not already
    defined -- no graceful fallback like its LAT/LONG/ALT/GS/TRACK keys
    have), and it reads ground track from TRACK, not TRACKM (the map/HSI
    convention) -- both keys are defined here, at the same value, so one
    bootstrap serves both widgets. This mirrors the 11-key set
    tests/visual_svs_test.py uses, the only proven no-gateway reference
    for the AI/SVS widget."""
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
    # AI/SVS-only keys (harmless extras for a MovingMap-only run).
    _def("PITCH", -90.0, 90.0, "deg", 0.0)
    _def("ROLL", -180.0, 180.0, "deg", 0.0)
    _def("ALAT", -30.0, 30.0, "g", 0.0)
    _def("TAS", 0.0, 2000.0, "knots", gs)
    _def("GS", 0.0, 2000.0, "knots", gs)
    _def("TRACK", 0.0, 359.9, "deg", track)
    _def("HEAD", 0.0, 359.9, "deg", track)
    _def("VS", -30000.0, 30000.0, "ft/min", 0.0)
    return fix


def _dead_reckon_step(lat, lon, gs_kt, heading_deg, dt_s):
    """One flat-earth dead-reckoning step (AER-679) -- the exact formula
    AER-677's ad hoc ``fixgw.netfix`` reproduction script and
    tests/visual_svs_test.py's ``SVS_SIM_MOTION`` both use, promoted here
    rather than reinvented."""
    d_deg = (gs_kt * dt_s / 3600.0) / 60.0
    lat2 = lat + d_deg * math.cos(math.radians(heading_deg))
    lon2 = lon + d_deg * math.sin(math.radians(heading_deg)) \
        / math.cos(math.radians(lat))
    return lat2, lon2


def _percentiles(values):
    """p50/p95/p99/max of *values* (unordered floats, ms); None fields
    and count=0 when empty. Percentiles, not a mean (AER-679 brief: "a
    mean hides a lurch") -- same indexing convention as map/perf.py's
    module-level ``_percentiles``, extended with p99 since a
    moving-position run is long enough for the tail to matter and isn't
    bounded by that module's 256-sample ring."""
    v = sorted(values)
    n = len(v)
    if not n:
        return dict(p50=None, p95=None, p99=None, max=None, count=0)

    def pct(p):
        return v[min(n - 1, int(p * (n - 1)))]

    return dict(p50=pct(0.50), p95=pct(0.95), p99=pct(0.99), max=v[-1],
               count=n)


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


def build_svs_widget(args):
    """Build the AI widget with SVS enabled, offscreen (AER-679) --
    build_widget()'s counterpart for the AI/PFD side. Mirrors
    tests/visual_svs_test.py's construction, the only proven no-gateway
    reference for this widget; ``_bootstrap_fix_db`` must already have
    defined PITCH/ROLL/ALAT/TAS or the ``AI(...)`` constructor raises."""
    from pyefis.instruments.ai import AI
    w = AI(None, show_fpm=True)
    w.resize(args.w, args.h)
    w.set_svs_config({
        "enabled": True,
        "tile_path": args.tile_path,
        "renderer": "opengl",
        "range_nm": args.range_nm,
        "auto_range": True,
        "clearance_green_ft": 1000,
        "clearance_yellow_ft": 500,
        "nasr_db_path": args.nasr_db,
        "dof_db_path": args.dof_db,
        "water_db_path": args.water_db,
        "highway_db_path": args.highway_db,
        "svs_perf_log": True,
        "haze": True,
        "haze_distance_nm": 40.0,
        "msaa_samples": 2,
        "safe_gradient": True,
        "terrain_texture": 0.35,
        "terrain_grid": 0.35,
        "paved_only": True,
    })
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


# --- moving-position mode (AER-679) --------------------------------------
#
# ai/svs.py's own profiler (_SVSPerfLog) is log-line-only: it accumulates
# into private dicts and clears them every 2 s inside maybe_report(), with
# no public, non-self-clearing read API (unlike map/perf.py's
# MapPerfStats, which is what run_scenario() reads via .snapshot() above).
# Rather than add a new counters surface to production SVS code, the
# hooks below wrap the exact call sites _SVSPerfLog itself times/gauges
# from OUTSIDE the renderer -- same semantics, no risk to the hot path,
# nothing to keep in sync if svs.py's internals change shape later.

_MOVING_POSITION_SCENARIO = "moving_position"
#: SVS collector caches to tally hit/miss for -- the two the AER-677
#: py-spy profile actually implicated (water 652 samples, highways 389)
#: plus the two remaining collectors that share the generic async-cache
#: helper, for completeness.
_SVS_COLLECTOR_ASYNC_NAMES = ("obstacles", "airports")


def _install_svs_hooks(renderer):
    """Wrap ``SVSRenderer.draw`` and its four collector cache entry
    points on *renderer* (an ``AI`` widget's ``.svs``) to capture the same
    numbers ``frame.gap_between_svs``/``frame.svs_total`` are -- wall-
    clock gap between consecutive ``draw()`` calls, and each call's own
    duration -- plus a hit/miss tally for the water/highway/obstacle/
    airport collector caches. A cache MISS is defined as "this call
    started a new collect-worker thread" (identity-compares the relevant
    ``_..._worker``/``_async_state[name]['worker']`` attribute before and
    after the call) -- the exact, and only, event that puts new GIL-held
    work onto a background thread under this architecture; anything that
    doesn't start a new worker (an exact cache hit, or promoting an
    already-finished worker's result) is a HIT, since both cost ~0 on the
    render thread, which is the only thing this benchmark's frame-gap
    number can see stalling.

    Returns ``(samples, collectors, restore)``; call ``restore()`` when
    done to put the renderer's original methods back."""
    samples = {"gap_ms": [], "total_ms": []}
    collectors = {name: {"hit": 0, "miss": 0} for name in
                 ("water", "highways") + _SVS_COLLECTOR_ASYNC_NAMES}
    originals = {}
    state = {"last_draw_ns": None}

    orig_draw = renderer.draw

    def draw_wrapper(p, w, h, ac_lat, ac_lon, ac_alt_ft, pitch_deg,
                     roll_deg, heading_deg, pixels_per_deg,
                     device_pixel_ratio=1.0):
        now_ns = time.perf_counter_ns()
        if state["last_draw_ns"] is not None:
            samples["gap_ms"].append(
                (now_ns - state["last_draw_ns"]) / 1e6)
        state["last_draw_ns"] = now_ns
        t0 = time.perf_counter_ns()
        try:
            return orig_draw(p, w, h, ac_lat, ac_lon, ac_alt_ft, pitch_deg,
                             roll_deg, heading_deg, pixels_per_deg,
                             device_pixel_ratio)
        finally:
            samples["total_ms"].append(
                (time.perf_counter_ns() - t0) / 1e6)

    renderer.draw = draw_wrapper
    originals["draw"] = orig_draw

    def _wrap_worker_collector(attr_name, worker_attr, collector_name):
        orig = getattr(renderer, attr_name, None)
        if orig is None:
            return

        def wrapper(*args, **kwargs):
            before = getattr(renderer, worker_attr, None)
            result = orig(*args, **kwargs)
            after = getattr(renderer, worker_attr, None)
            bucket = collectors[collector_name]
            bucket["miss" if after is not before else "hit"] += 1
            return result

        setattr(renderer, attr_name, wrapper)
        originals[attr_name] = orig

    _wrap_worker_collector("_collect_water_triangles", "_water_worker",
                           "water")
    _wrap_worker_collector("_collect_highways", "_hwy_worker", "highways")

    orig_async_cache = getattr(renderer, "_async_cache", None)
    if orig_async_cache is not None:
        def async_cache_wrapper(name, key, builder):
            before = renderer._async_state.get(name, {}).get("worker")
            result = orig_async_cache(name, key, builder)
            after = renderer._async_state.get(name, {}).get("worker")
            if name in collectors:
                collectors[name]["miss" if after is not before
                                 else "hit"] += 1
            return result

        renderer._async_cache = async_cache_wrapper
        originals["_async_cache"] = orig_async_cache

    def restore():
        renderer.draw = originals["draw"]
        for attr in ("_collect_water_triangles", "_collect_highways",
                    "_async_cache"):
            if attr in originals:
                setattr(renderer, attr, originals[attr])

    return samples, collectors, restore


def _install_map_hooks(perf):
    """Capture full-run paint-to-paint wall-clock gaps for a MovingMap's
    ``MapPerfStats`` (AER-679) -- the map-side analogue of
    ``frame.gap_between_svs``. ``MapPerfStats.paint_ms`` is a 256-sample
    ring (map/perf.py RING_SIZE) meant for live monitoring, too short a
    window to give a whole-run percentile for a multi-minute
    moving-position run, so this wraps ``record_paint_ms`` (called once
    per completed paint) to log every sample for the run's full
    duration instead.

    Returns ``(samples, restore)``."""
    samples = []
    state = {"last_ns": None}
    orig = perf.record_paint_ms

    def wrapper(ms):
        now_ns = time.perf_counter_ns()
        if state["last_ns"] is not None:
            samples.append((now_ns - state["last_ns"]) / 1e6)
        state["last_ns"] = now_ns
        return orig(ms)

    perf.record_paint_ms = wrapper

    def restore():
        perf.record_paint_ms = orig

    return samples, restore


def run_moving_position(app, args, rev, host):
    """Drive LAT/LONG continuously (AER-679) instead of running a static
    gesture scenario, against whichever of {map, svs, both} --target
    asks for, and report frame-gap percentiles + collector hit/miss for
    each. See the module docstring's "--moving-position" section for the
    full rationale and the sourced pass threshold."""
    fix = _bootstrap_fix_db(args.lat, args.lon, args.heading, args.alt,
                            gs=args.gs)

    widgets = {}
    if args.target in ("map", "both"):
        w = build_widget(args)
        w.show()
        w._build_layers()
        widgets["map"] = w
    if args.target in ("svs", "both"):
        w = build_svs_widget(args)
        w.show()
        widgets["svs"] = w

    _pump(app, 0.2)   # let the first paint/resize/frame-clock tick land
    if "svs" in widgets:
        # set_svs_config() attaches the SVS scene item only if
        # self.scene already exists, which resizeEvent sets -- belt and
        # suspenders against ordering timing so draw() actually runs.
        widgets["svs"]._attach_svs_item_if_ready()

    svs_samples = svs_collectors = svs_restore = None
    if "svs" in widgets:
        svs_samples, svs_collectors, svs_restore = \
            _install_svs_hooks(widgets["svs"].svs)
    map_samples = map_restore = None
    if "map" in widgets:
        map_samples, map_restore = _install_map_hooks(widgets["map"].perf)

    lat, lon = args.lat, args.lon
    dt = 1.0 / args.position_hz
    n_steps = max(1, int(round(args.duration * args.position_hz)))
    t0 = time.perf_counter()
    try:
        for i in range(n_steps):
            target = t0 + i * dt
            remaining = target - time.perf_counter()
            if remaining > 0:
                _pump(app, remaining)
            lat, lon = _dead_reckon_step(lat, lon, args.gs, args.heading,
                                         dt)
            fix.db.set_value("LAT", lat)
            fix.db.set_value("LONG", lon)
        _pump(app, 1.0)   # drain trailing paints/worker promotions
    finally:
        duration_s = time.perf_counter() - t0
        if svs_restore:
            svs_restore()
        if map_restore:
            map_restore()

    counters = {}
    if svs_samples is not None:
        counters["svs"] = dict(
            frame_gap_ms=_percentiles(svs_samples["gap_ms"]),
            frame_total_ms=_percentiles(svs_samples["total_ms"]),
            collectors={
                name: dict(
                    hit=c["hit"], miss=c["miss"],
                    hit_rate=(c["hit"] / (c["hit"] + c["miss"])
                             if (c["hit"] + c["miss"]) else None))
                for name, c in svs_collectors.items()})
    if map_samples is not None:
        snap = widgets["map"].perf.snapshot()
        snap["frame_gap_ms"] = _percentiles(map_samples)
        counters["map"] = snap

    def _fmt_gap(g):
        if not g["count"]:
            return "n=0"
        return "p50=%.1f p95=%.1f p99=%.1f max=%.1f ms (n=%d)" % (
            g["p50"], g["p95"], g["p99"], g["max"], g["count"])

    summary_bits = []
    if "svs" in counters:
        summary_bits.append(
            "svs gap %s" % _fmt_gap(counters["svs"]["frame_gap_ms"]))
    if "map" in counters:
        summary_bits.append(
            "map gap %s" % _fmt_gap(counters["map"]["frame_gap_ms"]))
    summary = ("moving_position: %.1fs @ %.0f kt hdg %.0f, %.0f Hz -- %s"
              % (duration_s, args.gs, args.heading, args.position_hz,
                 "; ".join(summary_bits)))

    return dict(
        schema_version=SCHEMA_VERSION, rev=rev, host=host,
        scenario=_MOVING_POSITION_SCENARIO, target=args.target,
        widget=dict(w=args.w, h=args.h), lat=args.lat, lon=args.lon,
        duration_s=duration_s,
        params=dict(gs_kt=args.gs, heading_deg=args.heading,
                   position_hz=args.position_hz,
                   duration_s=args.duration),
        counters=counters, summary=summary,
        caveat=("the %.0f Hz LAT/LONG bus writer driving this run is "
               "itself Python load, comparable to X-Plane's own update "
               "rate but not present in a pure-pyEfis idle measurement "
               "-- read these numbers as \"pyEfis under motion "
               "comparable to X-Plane,\" not a pure-pyEfis figure "
               "(AER-677)." % args.position_hz))


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
    ap.add_argument("--dof-db", default="",
                    help="obstacles.sqlite (SVS obstacle layer)")
    ap.add_argument("--range-nm", type=float, default=30.0,
                    help="SVS initial range, NM "
                         "(--moving-position --target svs/both)")
    ap.add_argument("--moving-position", action="store_true",
                    help="AER-679: drive LAT/LONG continuously at "
                         "--gs/--heading/--position-hz for --duration "
                         "seconds instead of running a gesture "
                         "--scenario (which is ignored if this is set)")
    ap.add_argument("--target", choices=["map", "svs", "both"],
                    default="both",
                    help="which widget(s) --moving-position drives")
    ap.add_argument("--gs", type=float, default=130.0,
                    help="ground speed, kt (--moving-position; AER-677's "
                         "fixgw.netfix repro default)")
    ap.add_argument("--heading", type=float, default=280.0,
                    help="ground track, deg (--moving-position; "
                         "AER-677's repro default)")
    ap.add_argument("--position-hz", type=float, default=20.0,
                    help="LAT/LONG update rate, Hz (--moving-position; "
                         "AER-677 drove the FIX bus at 20 Hz)")
    ap.add_argument("--duration", type=float, default=40.0,
                    help="--moving-position run length, seconds")
    ap.add_argument("--out", default="",
                    help="write JSON here instead of stdout")
    ap.add_argument("--budget", default="",
                    help="budgets JSON; exit non-zero on any violation")
    return ap.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)

    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    rev, host = _git_rev(), socket.gethostname()

    if args.moving_position:
        r = run_moving_position(app, args, rev, host)
        print(r["summary"], file=sys.stderr)
        results = [r]
    else:
        _bootstrap_fix_db(args.lat, args.lon, args.track, args.alt)
        names = (list(SCENARIOS) if args.scenario == "all"
                else [args.scenario])
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
