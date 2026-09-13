#  SPDX-License-Identifier: GPL-2.0-or-later
"""Count-based moving-map perf budgets (MP8a, briefs/
map_gesture_perf_plan.md section 5 + MP8's DoD; pyEfis #98).

MP8 in the brief is one item: a fixture cutter, two ~200 MB scene packs
cut from the real data, sha256 pinning, R2 publication, an on-demand
cache, per-host timing baselines, a pixel comparison, AND the pytest
perf budgets. This file is the half that needs none of that. The
**count-based** budgets are pipeline properties -- how many renders a
pinch causes, how many get thrown away, how many paints a sweep
produces, whether the water rasterizer constructs QPointF objects --
so they are hardware-independent hard assertions that run anywhere the
Qt ``offscreen`` platform runs, with no pack and no network fetch. The
fixture pack, the timing budgets and the pixel/IoU comparison are
MP8b.

Everything here drives the MP7 harness (``tools/bench_map_gestures.py``)
rather than re-implementing it: the same ``build_widget`` /
``_bootstrap_fix_db`` / ``_run_events`` / ``_gesture_bracket`` /
``scenario_*`` entry points the bench uses, so what CI asserts and what
the bench measures are the same code path.

What is asserted here, against section 5's table:

  =====================================  ===============================
  section 5 row                          test
  =====================================  ===============================
  terrain renders per pinch = 1          test_pinch_requests_exactly_
                                         one_terrain_render
  renders started and discarded = 0      test_pinch_discards_no_renders
  paints in a 3 s 60 Hz rotate <= 90     test_rotate_sweep_paints_are_
                                         bounded_by_the_frame_clock
                                         (see _CLOCK_ALLOWANCE -- the
                                         literal 90 does not hold; the
                                         number is challenged back to
                                         the brief, not weakened away)
  QPointF in the water path = 0          test_water_numpy_path_
                                         constructs_no_qpointf
  =====================================  ===============================

Deferred to MP8b, with the reason:

  * **water vertices rasterized at 160 NM <= 150k.** This is a budget on
    the VOLUME of real water data in a real scene at a real range. A
    synthetic lake set answers a different question -- it would pass at
    any threshold and gate nothing. Needs the Raleigh/Key West pack.
  * **every timing row** (worker render <= 0.6 s, settle latency
    <= 600 ms, paint p95 <= 15 ms, roads worker <= 0.3 s, GUI-thread
    starved time / max gap <= 50 ms). Hardware-dependent by
    construction; section 5 measures them on the Beelink and MP8's own
    DoD puts them against ``tests/perf/baselines/<hostname>.json``.
    A shared CI runner is not a baseline host.

**The vacuity trap, and what is done about it.** A counter that reads 0
because the code path never ran is not the same as a counter that reads
0 because the path ran and constructed nothing -- and every budget here
is of that shape. With no ``tile_path`` the terrain layer never builds a
TileCache, never requests a job, and never even appears in
``perf.snapshot()["layers"]`` (pinned by
``test_terrain_counters_are_absent_without_tiles``), so "<= 1 render per
pinch" would pass on a widget that renders nothing, forever. With no
water pack ``qpointf_count`` is 0 for the same empty reason. So:

  * every terrain budget runs against a **synthetic tile grid** (small
    square ``>i2`` HGTs -- ``load_tile`` infers the side from the file
    size), and asserts ``jobs_published >= 1`` alongside, so a render
    provably completed;
  * every water budget runs against a **synthetic water.sqlite** and
    asserts ``polygons_after >= 1`` and ``vertices_after > 0``
    alongside, so geometry was provably rasterized;
  * each budget has a companion test that drives the SAME counter the
    WRONG way -- the pinch without MP1's gesture bracket, a rotate
    sweep whose events bypass MP3's frame clock, the legacy
    ``water_raster: qt`` rasterizer -- and asserts the budget's own
    bound is violated. Those companions are the standing proof that
    these assertions can fail; a test that cannot fail reads as
    coverage and gates nothing.

None of the synthetic fixtures is a "pack": no file here exceeds a few
MB, nothing is downloaded, and nothing is pinned by hash. They exist to
make the code path run, not to stand in for real data -- which is
exactly why the volume budget above is deferred rather than faked.
"""

import importlib.util
import math
import os
import sqlite3
import time
from pathlib import Path

import numpy as np
import pytest

# Must be set before pytest-qt's qapp fixture builds the QApplication.
# CI installs pytest-env and pyproject sets it too; this keeps the file
# runnable on a bare `pytest tests/perf` with neither.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_ROOT = Path(__file__).resolve().parents[2]

#: Widget size for every scenario here. Not the bench's 650x1040: these
#: are COUNT budgets, and no counter asserted in this file is a function
#: of widget size (the terrain window key carries w/h, but it is
#: constant within a run). A smaller window keeps the worker renders
#: cheap enough for CI.
_W = _H = 300

#: Scene: the brief's Raleigh centre, so the synthetic tiles and lakes
#: sit where section 5's own numbers were measured.
_LAT, _LON = 35.8, -78.8

#: Water decode cap the appliance runs (the map's own default is 512;
#: the value matters to vertices_before, so it is always explicit).
_WATER_MAX_VERTICES = 1024

#: Headroom over the nominal gesture frame clock for
#: test_rotate_sweep_paints_are_bounded_by_the_frame_clock.
#:
#: Section 5 budgets "paints in a 3 s 60 Hz rotate sweep" at <= 90,
#: which is 30 Hz x 3.0 s exactly -- the MP3 gesture frame clock's
#: nominal rate times the nominal sweep length, with zero allowance for
#: timer behaviour. It does not hold: a HEALTHY dev tree paints 93 in
#: 2.984 s here (31.2 Hz measured against a 30 Hz nominal clock, four
#: runs, identical to the paint), because Qt's 33 ms QTimer fires
#: slightly fast under a 1 kHz event pump. 90 is therefore not
#: assertable anywhere, on any hardware, on a tree with no defect in it.
#:
#: This allowance is NOT a severity floor raised to make a finding go
#: away: the bound it produces (~103) still fails at 175-180, which is
#: what the same sweep paints when paints bypass the frame clock --
#: measured by the companion test below, and ~the pre-MP3 number
#: section 5 records as "today". The literal 90 is challenged back to
#: the brief as a requirement (AER-1121), not quietly widened here.
_CLOCK_ALLOWANCE = 1.15


def _load(name):
    """Load a tools/ script as a module (same helper as
    tests/tools/test_bench_map_gestures.py -- tools/ is not a package)."""
    spec = importlib.util.spec_from_file_location(
        name, _ROOT / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def bmg():
    """The MP7 harness itself. Importing it also pins QT_QPA_PLATFORM."""
    mod = _load("bench_map_gestures")
    mod._bootstrap_fix_db(_LAT, _LON, 90.0, 3000.0)
    return mod


@pytest.fixture(scope="module")
def tile_root(tmp_path_factory):
    """A synthetic GLO-30-shaped tile grid covering the scene.

    ``load_tile`` infers the tile side from the file size ("any square
    side is accepted"), so 121x121 big-endian int16 tiles are real
    tiles as far as TileCache and TerrainLayer._sample are concerned --
    ~29 kB each instead of 25 MB, and the whole grid is ~3 MB. The
    elevation pattern is arbitrary: nothing here asserts on what the
    terrain LOOKS like, only on how many times it was rendered.

    The grid spans +-4 deg of the scene, which covers the oversized
    north-up window at the pinch's top range (160 NM).
    """
    root = tmp_path_factory.mktemp("tiles")
    n = 121
    body = ((np.arange(n * n, dtype=">i2") % 500) + 100).reshape(n, n)
    for lat in range(int(_LAT) - 4, int(_LAT) + 5):
        d = root / ("N%02d" % lat)
        d.mkdir(exist_ok=True)
        for lon in range(int(abs(_LON)) - 4, int(abs(_LON)) + 5):
            body.tofile(d / ("N%02dW%03d.hgt" % (lat, lon)))
    return root


@pytest.fixture(scope="module")
def water_db(tmp_path_factory):
    """A synthetic water.sqlite with three dense circular lakes.

    Dense on purpose: each ring carries 2000 vertices so MP4's
    per-pixel decimation has something to drop and the surviving count
    is comfortably non-zero at 160 NM -- the two halves of "the water
    path ran AND constructed geometry" that make ``qpointf_count == 0``
    a real observation instead of a dead-path artifact. The schema is
    the pre-#44 single-ring form (no ``rings``/``triangles`` columns),
    which WaterDB reads directly; island holes are a rendering concern,
    not a counting one.
    """
    from pyefis.instruments.ai.water_db import encode_vertices
    path = tmp_path_factory.mktemp("water") / "water.sqlite"
    con = sqlite3.connect(str(path))
    con.execute("""
        CREATE TABLE water_polygons (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            min_lat   REAL NOT NULL,
            max_lat   REAL NOT NULL,
            min_lon   REAL NOT NULL,
            max_lon   REAL NOT NULL,
            kind      TEXT NOT NULL,
            elev_ft   REAL,
            vertices  BLOB NOT NULL
        )
    """)
    for clat, clon, radius in ((_LAT, _LON, 0.5),
                               (_LAT + 0.6, _LON + 0.6, 0.35),
                               (_LAT - 0.6, _LON - 0.6, 0.4)):
        verts = [(clat + radius * math.cos(2 * math.pi * i / 2000),
                  clon + radius * math.sin(2 * math.pi * i / 2000))
                 for i in range(2000)]
        lats = [v[0] for v in verts]
        lons = [v[1] for v in verts]
        con.execute(
            "INSERT INTO water_polygons "
            "(min_lat, max_lat, min_lon, max_lon, kind, elev_ft, vertices)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (min(lats), max(lats), min(lons), max(lons), "lake", 200.0,
             encode_vertices(verts)))
    con.commit()
    con.close()
    return path


def _make_widget(bmg, qapp, extra=(), range_nm=None):
    """A MovingMap built exactly the way the MP7 bench builds it."""
    args = bmg._parse_args(["--w", str(_W), "--h", str(_H),
                            "--lat", str(_LAT), "--lon", str(_LON),
                            *extra])
    w = bmg.build_widget(args)
    if range_nm is not None:
        w.range_nm = range_nm
    w.show()
    # Same deterministic warm-up run_scenario() does: build the layer
    # set and let the frame clock's first tick paint and settle, so
    # every counter read below is a DELTA across the scenario only.
    w._build_layers()
    bmg._pump(qapp, 0.3)
    return w


def _terrain(snap):
    """Terrain LayerStats out of a perf snapshot, zeros when the layer
    never registered (see test_terrain_counters_are_absent_without_tiles
    -- that state is exactly the vacuity trap, so it reads as zeros
    here rather than raising, and the tests that care assert on
    jobs_published)."""
    return snap["layers"].get("terrain", {"jobs_requested": 0,
                                          "jobs_started": 0,
                                          "jobs_published": 0,
                                          "jobs_superseded": 0})


def _delta(before, after, key):
    return _terrain(after)[key] - _terrain(before)[key]


# --- section 5: terrain renders per pinch -------------------------------


@pytest.fixture(scope="module")
def gated_pinch(bmg, qapp, tile_root):
    """One MP7 ``pinch_out`` (10 -> 160 NM, 90 zoom_by events at 60 Hz,
    5 s hold) against the synthetic tiles, bracketed by the gesture
    phase exactly as a real QPinchGesture would be -- i.e. with MP1's
    gating engaged. Module-scoped: the run takes ~7 s and two separate
    section 5 rows read the same counters off it.

    Returns (before_snapshot, after_snapshot, scenario_params)."""
    w = _make_widget(bmg, qapp, ["--tile-path", str(tile_root)])
    before = w.perf.snapshot()
    params = bmg.scenario_pinch_out(qapp, w)
    after = w.perf.snapshot()
    w.hide()
    qapp.processEvents()
    return before, after, params


def test_pinch_gesture_actually_swept_the_range(gated_pinch):
    """Guard on the two fixtures the budgets below depend on: the pinch
    reached the top of the range ladder (so the terrain window key
    genuinely changed -- a pinch that never moved the range would make
    "1 render" trivially true), and a terrain render provably
    COMPLETED (so the counters are not the empty-layer zeros)."""
    before, after, params = gated_pinch
    assert params["range_from_nm"] == 10.0
    assert params["range_actual_nm"] == pytest.approx(160.0, abs=1.0)
    assert _delta(before, after, "jobs_published") >= 1


def test_pinch_requests_exactly_one_terrain_render(gated_pinch):
    """Section 5: "terrain renders per pinch gesture" -- today one per
    event key (tens), after MP1-MP5 exactly 1.

    MP1 gates on MovingMap.defer_render: while the gesture is live or
    its settle timer is running, TerrainLayer.paint() skips _request()
    entirely, so the 90 zoom_by events across ~6 range buckets queue
    nothing. One render is requested after the settle timer fires."""
    before, after, _params = gated_pinch
    assert _delta(before, after, "jobs_requested") == 1


def test_pinch_discards_no_renders(gated_pinch):
    """Section 5: "renders started and discarded per pinch" -- today
    nearly all, after MP1-MP5 exactly 0.

    jobs_superseded counts a render that finished after a NEWER job had
    already replaced TerrainLayer._job -- work paid for and thrown
    away (brief section 2, root cause R2)."""
    before, after, _params = gated_pinch
    assert _delta(before, after, "jobs_superseded") == 0


def test_ungated_pinch_violates_both_terrain_budgets(bmg, qapp, tile_root):
    """The companion that makes the two assertions above real.

    Same 90-event 10 -> 160 NM sweep, same widget, same tiles -- with
    MP1's gesture bracket removed, which is what the pipeline did
    before MP1 (every repaint re-keyed the terrain window and queued a
    fresh job while the previous one was still rendering). Both budgets
    must FAIL here, or they are not measuring the gating."""
    w = _make_widget(bmg, qapp, ["--tile-path", str(tile_root)])
    before = w.perf.snapshot()
    w.range_nm = 10.0
    factor = (10.0 / 160.0) ** (1.0 / 90)
    bmg._run_events(qapp, [lambda f=factor: w.zoom_by(f)
                           for _ in range(90)])
    bmg._pump(qapp, 2.0)
    after = w.perf.snapshot()
    w.hide()
    qapp.processEvents()

    assert w.range_nm == pytest.approx(160.0, abs=1.0)
    assert _delta(before, after, "jobs_requested") > 1
    assert _delta(before, after, "jobs_superseded") > 0


def test_terrain_counters_are_absent_without_tiles(bmg, qapp):
    """Why every terrain budget above configures a tile path.

    With no tile_path TerrainLayer._cache stays None, paint() returns
    immediately, _request() is never called and the layer never
    registers with MapPerfStats at all -- so "terrain" is not even a
    key in the snapshot. Both budgets above would read 0 and pass
    forever on a widget that renders no terrain. This pins that
    failure mode in place so the synthetic tile fixture cannot be
    "simplified" away without a red test."""
    w = _make_widget(bmg, qapp)
    bmg.scenario_ladder(qapp, w)
    snap = w.perf.snapshot()
    w.hide()
    qapp.processEvents()
    assert "terrain" not in snap["layers"]
    assert snap["frames_painted"] > 0     # the widget itself did run


# --- section 5: paints in a 3 s rotate sweep ----------------------------


def _rotate_sweep(bmg, qapp, w):
    """Run the MP7 ``rotate`` scenario and return (paints, duration_s,
    bound) where bound is the frame clock's own ceiling over the
    MEASURED sweep length."""
    before = w.perf.snapshot()["frames_painted"]
    t0 = time.perf_counter()
    bmg.scenario_rotate(qapp, w)
    duration_s = time.perf_counter() - t0
    paints = w.perf.snapshot()["frames_painted"] - before
    bound = math.ceil(w.gesture_frame_rate * duration_s * _CLOCK_ALLOWANCE)
    return paints, duration_s, bound


def test_rotate_sweep_paints_are_bounded_by_the_frame_clock(bmg, qapp):
    """Section 5: "paints in a 3 s 60 Hz rotate sweep" -- today ~180,
    after MP1-MP5 <= 90.

    MP3 is what makes this hold: rotate_by() only marks the frame
    dirty, and _frame_tick (running at gesture_frame_rate, 30 Hz by
    default while a gesture is live) is the only thing that repaints.
    So 180 injected events at 60 Hz produce ~half that many paints.

    The bound is computed from the clock and the MEASURED sweep length
    rather than hard-coded at 90 -- see _CLOCK_ALLOWANCE for why 90 is
    not assertable on a healthy tree, and
    test_rotate_sweep_budget_fails_when_paints_bypass_the_frame_clock
    for the proof that this bound still catches the defect the row
    exists to catch."""
    w = _make_widget(bmg, qapp)
    paints, duration_s, bound = _rotate_sweep(bmg, qapp, w)
    w.hide()
    qapp.processEvents()

    # Companion: the sweep provably painted. A frozen widget also
    # satisfies an upper bound.
    assert paints > 0.5 * w.gesture_frame_rate * duration_s
    assert paints <= bound


def test_rotate_sweep_budget_fails_when_paints_bypass_the_frame_clock(
        bmg, qapp):
    """The companion that makes the bound above real.

    Model the pre-MP3 pipeline with the frame clock left exactly where
    it is: every rotate_by() ALSO repaints directly, the way the widget
    behaved before rotate_by was demoted to marking a dirty frame. The
    paint count must then track the 60 Hz event rate and blow the
    bound -- if it does not, the bound is not measuring MP3.

    ``repaint()``, not ``update()``. update() is COMPRESSIBLE: Qt
    coalesces several update() calls into one paint event when the loop
    is busy, so a control built on it measures Qt's compression as much
    as the budget -- 273 paints on an idle run, 255 behind the whole
    tests/instruments suite, and nothing says where that degrades to on
    a loaded CI runner. repaint() paints synchronously, once per call,
    under any load (273 in both of those runs), which is the property
    this control needs: N events, N paints, bound broken."""
    w = _make_widget(bmg, qapp)
    orig_rotate_by = w.rotate_by

    def rotate_and_repaint(deg):
        result = orig_rotate_by(deg)
        w.repaint()                     # pre-MP3: repaint per event
        return result

    w.rotate_by = rotate_and_repaint
    paints, _duration_s, bound = _rotate_sweep(bmg, qapp, w)
    w.hide()
    qapp.processEvents()

    assert paints > bound


# --- section 5: QPointF constructed in the water path -------------------


def _render_water_at_160nm(bmg, qapp, tile_root, water_db, raster):
    """Build a widget at 160 NM with water configured, let the terrain
    worker publish one window image, and return the WaterStats dict."""
    w = _make_widget(bmg, qapp, [
        "--tile-path", str(tile_root),
        "--water-db", str(water_db),
        "--water-raster", raster,
        "--water-max-vertices", str(_WATER_MAX_VERTICES)],
        range_nm=160.0)
    bmg._pump(qapp, 3.0)
    snap = w.perf.snapshot()
    w.hide()
    qapp.processEvents()
    assert _terrain(snap)["jobs_published"] >= 1
    return snap["water"]


@pytest.fixture(scope="module")
def water_numpy(bmg, qapp, tile_root, water_db):
    return _render_water_at_160nm(bmg, qapp, tile_root, water_db, "numpy")


@pytest.fixture(scope="module")
def water_qt(bmg, qapp, tile_root, water_db):
    return _render_water_at_160nm(bmg, qapp, tile_root, water_db, "qt")


def test_water_numpy_path_constructs_no_qpointf(water_numpy):
    """Section 5: "QPointF constructed in the water path @ 160 NM" --
    today ~932k, after MP5 exactly 0.

    The two companion assertions are the whole point: without them
    ``qpointf_count == 0`` passes on a scene with no water, on a
    misconfigured water db, and on a widget whose terrain worker never
    ran. Here the water path provably ran (polygons survived the range
    query) and provably built geometry (vertices survived MP4's
    decimation) -- and constructed no QPointF doing it."""
    assert water_numpy["polygons_after"] >= 1
    assert water_numpy["vertices_after"] > 0
    assert water_numpy["qpointf_count"] == 0


def test_water_qt_path_constructs_one_qpointf_per_surviving_vertex(
        water_qt, water_numpy):
    """The companion that makes the budget above real.

    ``water_raster: qt`` is the legacy per-vertex rasterizer MP5
    replaced, kept for one release of A/B. On the SAME scene it must
    report a NON-zero qpointf_count -- one per surviving vertex -- or
    the counter is dead and the 0 above means nothing.

    The two paths must also agree on the geometry they rasterized;
    otherwise MP5 bought its 0 by drawing something different."""
    assert water_qt["qpointf_count"] == water_qt["vertices_after"]
    assert water_qt["qpointf_count"] > 0
    assert water_qt["polygons_after"] == water_numpy["polygons_after"]
    assert water_qt["vertices_after"] == water_numpy["vertices_after"]


def test_water_vertices_are_decimated_before_rasterizing(water_numpy):
    """MP4's per-pixel decimation, which section 5's "water vertices
    rasterized at 160 NM <= 150k" row is a budget ON.

    That row's THRESHOLD is deferred to MP8b: 150k is a statement about
    how much real water a real scene holds at 160 NM, and a synthetic
    lake set would clear it at any threshold. What is assertable here
    without a pack is the mechanism -- vertices that round to the same
    image pixel are dropped before anything is rasterized -- so this
    asserts the reduction, not the number."""
    assert water_numpy["vertices_before"] > 0
    assert water_numpy["vertices_after"] < water_numpy["vertices_before"]
    assert water_numpy["polygons_after"] == water_numpy["polygons_before"]
