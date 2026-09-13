#  SPDX-License-Identifier: GPL-2.0-or-later
"""Pack-dependent moving-map perf budgets (MP8b-2, briefs/
map_gesture_perf_plan.md section 5; pyEfis #98, AER-1135).

The other half of MP8. ``test_map_gestures.py`` (MP8a, AER-1121) landed
the count-based rows -- renders per pinch, superseded renders, paints per
sweep, QPointF count -- as hard assertions that run anywhere, with no
pack. This file is what it deferred, and every row here needs something
that a bare ``pytest`` does not have:

  =========================================  =========================
  section 5 row                              needs
  =========================================  =========================
  water vertices rasterized @ 160 NM <=150k  a real scene pack
  terrain+water worker render @ 160/300 NM   a pack AND a host baseline
  settle latency, pinch 10 -> 160 NM         a pack AND a host baseline
  map paint p95 @ 40 NM                      a pack AND a host baseline
  roads worker render @ 80 NM                a highway pack + baseline
  GUI-thread max gap during the pinch        a pack AND a host baseline
  MP5 pixel comparison (MP5 DoD)             a real scene pack
  =========================================  =========================

so every one of them can be skipped, and a skipped budget that reads as
a pass is the failure mode this file is most exposed to. Three rules are
applied throughout:

1. **A missing pack skips; it never passes.** ``_scene_pack`` raises
   ``pytest.skip`` with the reason. It never substitutes synthetic data:
   a synthetic lake set clears any volume threshold, which is precisely
   why MP8a deferred the row instead of faking it.
2. **A pack too small for the question skips too.** New here, and the
   main finding of this item -- see ``test_fixture_footprint``.
3. **Every budget has a falsifier that runs with NO pack**, so the proof
   that these assertions can fail is exercised on every CI run rather
   than only on the machine that had the data. A timing budget cannot be
   falsified by a source mutant (the mutant that breaks it is a bad
   BASELINE, not bad code), so its falsifiers are of two kinds: the
   comparator is driven with synthetic numbers either side of the bound,
   and the measurement is driven with a deliberate stall injected into
   the real render path. Between them they pin "the bound rejects a
   regression" and "the number is actually read off the code under
   test".

**What is genuinely gated, and where.** Stated plainly because a green
suite here would otherwise overstate itself:

  * On a host with **no baseline** -- which includes every GitHub-hosted
    runner, because their hostnames are per-job random strings -- every
    TIMING row warns and gates nothing. That is the DoD's own
    instruction ("on an unknown host they warn") and it is not a defect,
    but it does mean the timing rows are a bench/workstation gate, not a
    CI gate. ``tools/map_perf_baseline.host_id`` and
    ``tests/perf/baselines/README.md`` explain how a host opts in.
  * The **volume** row and the **pixel comparison** are
    hardware-independent -- they are functions of the pack, the scene,
    the range, the widget size and the decimation algorithm, nothing
    else -- so they are hard assertions wherever a pack exists,
    including CI once the manifest is published.
  * Everything in the ``--- falsifiers ---`` sections runs everywhere,
    always.
"""

import importlib.util
import math
import os
import sqlite3
import threading
import time
import warnings
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_ROOT = Path(__file__).resolve().parents[2]

from . import measure as M                                       # noqa: E402


def _load_tool(name):
    spec = importlib.util.spec_from_file_location(
        name, _ROOT / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


baseline_tool = _load_tool("map_perf_baseline")
fixture_tool = _load_tool("make_map_perf_fixture")

#: Section 5: "water vertices rasterized at 160 NM <= 150k after MP4".
WATER_VERTEX_BUDGET_160NM = 150_000

#: MP5's DoD pixel comparison. NOT an IoU threshold -- see
#: test_water_raster_paths_agree_on_coverage for why a hard-mask IoU is
#: the wrong oracle for an antialiased-vs-hard-edged pair.
COVERAGE_AREA_TOLERANCE = 0.10


# ---------------------------------------------------------------------------
# Pack resolution
# ---------------------------------------------------------------------------

def _fixture_root(scene):
    """The extracted fixture directory for ``scene``, or ``None``.

    Two ways in, both explicit:

    * ``PYEFIS_PERF_FIXTURE_DIR`` -- a directory holding ``<scene>/``
      subdirectories, for a workstation, the bench or the QA container
      that already holds real packs (or a local
      ``make_map_perf_fixture.py cut`` output). No network.
    * ``PYEFIS_PERF_FIXTURE`` -- the published, sha256-pinned pack,
      downloaded and verified by ``fetch_fixture`` (AER-1133).

    ``fetch_fixture`` raising ``PerfFixtureUnavailable`` is deliberately
    NOT caught: that means the flag was set but the manifest has no pin,
    which is a misconfiguration CI must fail on, not skip past."""
    local = os.environ.get("PYEFIS_PERF_FIXTURE_DIR", "").strip()
    if local:
        p = Path(local) / scene
        return p if p.is_dir() else None
    return fixture_tool.fetch_fixture(scene)


def _scene_pack(scene):
    """(root, tile_path, water_db, highway_db) or ``pytest.skip``."""
    root = _fixture_root(scene)
    if root is None:
        pytest.skip(
            f"no {scene} perf pack: set PYEFIS_PERF_FIXTURE=1 to fetch the "
            "published pin, or PYEFIS_PERF_FIXTURE_DIR=<dir> to point at "
            "locally cut packs (tools/make_map_perf_fixture.py cut). "
            "Refusing to substitute synthetic data -- a synthetic lake set "
            "clears any volume threshold and would gate nothing.")
    water = root / "water.sqlite"
    if not water.is_file():
        pytest.skip(f"{root} has no water.sqlite")
    highway = root / "highway.sqlite"
    return (root, str(root), str(water),
            str(highway) if highway.is_file() else "")


@pytest.fixture(scope="module")
def bench():
    mod = M.load_bench()
    mod._bootstrap_fix_db(M.SCENES["raleigh"]["lat"],
                          M.SCENES["raleigh"]["lon"], 90.0, 3000.0)
    return mod


@pytest.fixture(scope="module")
def baseline():
    """This host's timing baseline, or ``None``. Loaded once: the file
    is the same for every test and re-reading it per test would let two
    rows in one run compare against two different files."""
    return baseline_tool.load_baseline()


@pytest.fixture(scope="module")
def calibration_ms():
    """One calibration reading per session, taken once so every timing
    row in a run is judged against the same statement about how fast
    this machine currently is."""
    return baseline_tool._calibrate()


def _assert_timing(metric, measured_ms, baseline, calibration_ms):
    """Apply one timing row's budget, or warn.

    The DoD's "on an unknown host they warn" is implemented as a real
    ``UserWarning`` rather than a bare ``pytest.skip`` so the run's
    warnings summary carries a line per ungated budget -- a skipped
    timing test and a passing one look identical in ``-q`` output, and
    that is exactly how a suite comes to measure nothing without anybody
    noticing."""
    if measured_ms is None:
        pytest.skip(f"{metric}: not measured (render never published "
                    f"within {M.RENDER_TIMEOUT_S:.0f} s)")
    v = baseline_tool.check(metric, measured_ms, baseline,
                            calibration_ms=calibration_ms)
    if not v.gated:
        warnings.warn(
            f"perf budget {metric} NOT GATED on host "
            f"{baseline_tool.host_id()!r}: {v.reason}. Measured "
            f"{measured_ms:.1f} ms (section 5 reference: "
            f"{baseline_tool.METRICS[metric]['section5_reference_ms']:.0f} "
            "ms on the Beelink). See tests/perf/baselines/README.md.",
            UserWarning, stacklevel=2)
        return v
    assert v.ok, (
        f"{metric}: {measured_ms:.1f} ms exceeds "
        f"{v.bound:.1f} ms = {baseline_tool.TOLERANCE}x this host's "
        f"baseline of {v.baseline:.1f} ms "
        f"({baseline_tool.baseline_path()}).")
    return v


# ---------------------------------------------------------------------------
# section 5: water vertices rasterized at 160 NM <= 150k
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def raleigh_volume(bench, qapp):
    """One 160 NM render of the Raleigh scene, the configuration section
    5's whole table is measured in ("Beelink, Raleigh scene, 650x1040,
    warm")."""
    _root, tiles, water, _hw = _scene_pack("raleigh")
    _require_footprint("raleigh", water, 160.0)
    out = M.measure_water_volume(bench, qapp, "raleigh", tiles, water)
    if out is None:
        pytest.skip("raleigh 160 NM render never published")
    return out


def _require_footprint(scene, water_db, range_nm):
    """Skip unless the pack is big enough for the question. See
    ``measure.footprint_covers_window`` -- this is the guard that stops
    a truncated pack reporting a comfortable pass."""
    s = M.SCENES[scene]
    cov = M.footprint_covers_window(
        M.water_coverage_bbox(water_db), s["lat"], s["lon"], range_nm)
    if not cov["covers"]:
        pytest.skip(
            f"{scene} pack does not cover the {range_nm:.0f} NM render "
            f"window, so a volume budget measured against it is not "
            f"evidence: {cov['reason']}. Covered area fraction "
            f"{cov['pack_area_vs_window']}. Re-cut with a window at least "
            f"{cov['need_span_deg'][0]:.1f} x {cov['need_span_deg'][1]:.1f} "
            "deg (tools/make_map_perf_fixture.py --window-deg).")


def test_water_vertices_at_160nm_within_budget(raleigh_volume):
    """Section 5: "water vertices rasterized at 160 NM <= 150k after
    MP4" -- the row MP8a deferred because a synthetic lake set clears
    any threshold.

    The two companions are what make the number an observation rather
    than an artifact of an empty scene: the water path provably ran
    (polygons survived the range query) and MP4 provably reduced
    something (after < before). Without them a pack with no water in it
    passes at 0 vertices, forever.

    Measured on the published North America water pack (water-na,
    cycle 2026q2r6) at 650x1040 with the appliance's 1024-vertex decode
    cap: 102,034 vertices, a 1.47x margin. Key West on the same pack
    reads 75,313. Both hold; neither holds comfortably enough to call
    the budget generous."""
    assert raleigh_volume["terrain_jobs_published"] >= 1
    assert raleigh_volume["polygons_after"] >= 1
    assert raleigh_volume["vertices_after"] > 0
    assert raleigh_volume["vertices_after"] < raleigh_volume["vertices_before"]
    assert raleigh_volume["vertices_after"] <= WATER_VERTEX_BUDGET_160NM, (
        f"{raleigh_volume['vertices_after']} water vertices rasterized at "
        f"160 NM, over the {WATER_VERTEX_BUDGET_160NM} budget "
        f"(section 5). vertices_before="
        f"{raleigh_volume['vertices_before']}, polygons "
        f"{raleigh_volume['polygons_before']} -> "
        f"{raleigh_volume['polygons_after']}.")


def test_water_volume_budget_fails_without_mp4_decimation(bench, qapp):
    """The falsifier for the row above, and the reason it is worth
    asserting at all.

    MP4 is the per-pixel decimation. With it disabled the SAME scene
    rasterizes every decoded vertex, which on the real Raleigh pack is
    3,362,433 -- 22x the budget. If this passes, the budget is not
    measuring MP4."""
    _root, tiles, water, _hw = _scene_pack("raleigh")
    _require_footprint("raleigh", water, 160.0)
    from pyefis.instruments.map.layers import terrain as terrain_mod
    orig = terrain_mod._decimate_to_pixel_grid

    def no_decimation(xs, ys, ring_ends):
        return xs, ys, ring_ends

    terrain_mod._decimate_to_pixel_grid = no_decimation
    try:
        out = M.measure_water_volume(bench, qapp, "raleigh", tiles, water)
    finally:
        terrain_mod._decimate_to_pixel_grid = orig
    if out is None:
        pytest.skip("raleigh 160 NM render never published")
    assert out["vertices_after"] > WATER_VERTEX_BUDGET_160NM, (
        "the 150k budget did not catch MP4 being disabled "
        f"({out['vertices_after']} vertices) -- it is not gating the "
        "decimation it exists to gate.")


# --- falsifiers for the footprint guard (no pack needed) ----------------

def test_render_window_at_160nm_is_wider_than_a_2x2_degree_cut():
    """The arithmetic behind ``_require_footprint``, pinned.

    ``make_map_perf_fixture.WINDOW_DEG`` is 2.0, widened to whole-degree
    tile cells, so a Raleigh cut spans 3 deg x 3 deg = 9 square degrees.
    A nominal 160 NM render at 650x1040 reads a window of **7.85 deg lat
    x 9.68 deg lon** -- 76 square degrees, so the pack is about **12% of
    the window by area**.

    Two compounding reasons it is so much wider than "160 NM", both
    easy to under-count:

      * the widget's ``range_nm`` is measured anchor-to-top-edge, and
        the ownship anchor defaults to mid-screen, so the window's
        half-height is already 2x the range;
      * ``_render`` covers the ROTATED viewport -- the widget's
        half-DIAGONAL, oversized a further 1.25x.

    Together a nominal 160 NM render queries the water pack over a
    235.6 NM box.

    Consequence, measured on the real pack rather than argued: Raleigh
    at 160 NM rasterizes 102,034 vertices against the full North America
    pack and 14,259 against a 3x3 deg cut of that same pack -- 14% of
    the truth, and a 10.5x margin under a 150k budget instead of 1.47x.
    That budget would still catch MP4 being deleted outright, and would
    not catch decimation becoming 7x less effective. Even
    ``--window-deg 7`` (an 8x8 deg cut) still recovers only 90,707.

    This test is here so that raising ``WINDOW_DEG`` to cover the window
    (or deciding not to, and accepting a warn-only volume row) is a
    deliberate edit against a stated number, not a silent default."""
    lat_span, lon_span = M.render_window_span_deg(160.0,
                                                  M.SCENES["raleigh"]["lat"])
    assert M.effective_range_nm(160.0) == pytest.approx(235.6, abs=0.5)
    assert lat_span == pytest.approx(7.85, abs=0.05)
    assert lon_span == pytest.approx(9.68, abs=0.05)
    # 3x3 deg cut vs a 7.85 x 9.68 deg window
    assert (9.0 / (lat_span * lon_span)) < 0.15


def test_render_window_matches_the_water_query_box(bench, qapp):
    """The cross-check that keeps the arithmetic above honest, and the
    reason it is not left as arithmetic.

    ``render_window_span_deg`` reimplements two pieces of production
    sizing -- ``TerrainLayer._render``'s window and
    ``WaterDB.polygons_in_range``'s degree box -- and a reimplementation
    is a claim, not a fact. The first version of it here assumed the
    ownship anchor was 25% of screen height; it is 50%, and the window
    came out 1.5x too small. Nothing in the pure-arithmetic tests could
    see that.

    This asserts the predicted box against what the renderer ACTUALLY
    pulled out of the pack: run one render, then count the polygons the
    predicted box selects from the same database with the same size
    floor, and require the two to agree. If they diverge, the guard is
    measuring the wrong window and every skip/pass decision it makes is
    unsound."""
    _root, tiles, water, _hw = _scene_pack("raleigh")
    out = M.measure_water_volume(bench, qapp, "raleigh", tiles, water)
    if out is None:
        pytest.skip("raleigh 160 NM render never published")

    s = M.SCENES["raleigh"]
    lat_span, lon_span = M.render_window_span_deg(160.0, s["lat"])
    lo, hi = s["lat"] - lat_span / 2, s["lat"] + lat_span / 2
    wlo, whi = s["lon"] - lon_span / 2, s["lon"] + lon_span / 2
    # The layer's own sub-pixel floor: 3 image px, in degrees of latitude.
    mpp = (M.effective_range_nm(160.0) * 1852.0) / 511.5
    min_d = 3.0 * mpp / 111320.0
    con = sqlite3.connect(f"file:{water}?mode=ro", uri=True)
    try:
        predicted = con.execute(
            "SELECT COUNT(*) FROM water_polygons "
            "WHERE max_lat > ? AND min_lat < ? AND max_lon > ? "
            "AND min_lon < ? AND (kind = 'ocean' OR "
            "((max_lat-min_lat)*(max_lat-min_lat) + "
            " (max_lon-min_lon)*(max_lon-min_lon)) >= ?)",
            (lo, hi, wlo, whi, min_d * min_d)).fetchone()[0]
    finally:
        con.close()
    actual = out["polygons_before"]
    assert actual > 0
    assert abs(predicted - actual) <= max(5, 0.02 * actual), (
        f"the footprint guard predicts {predicted} polygons in the "
        f"160 NM window but the renderer pulled {actual}. "
        "render_window_span_deg is not reproducing the real query box, "
        "so every footprint skip/pass decision it makes is unsound.")


def test_footprint_guard_rejects_a_pack_smaller_than_the_window():
    lat, lon = M.SCENES["raleigh"]["lat"], M.SCENES["raleigh"]["lon"]
    cut = (34.0, 37.0, -80.0, -77.0)        # what the cutter emits today
    cov = M.footprint_covers_window(cut, lat, lon, 160.0)
    assert cov["covers"] is False
    assert cov["pack_area_vs_window"] < 0.15
    assert "160 NM render" in cov["reason"]

    # Even a 7 deg cut window (8x8 deg after whole-degree snapping) is
    # short -- recorded so nobody widens WINDOW_DEG a little and assumes
    # the row became evidence.
    wide = M.footprint_covers_window((32.0, 40.0, -83.0, -75.0),
                                     lat, lon, 160.0)
    assert wide["covers"] is False


def test_footprint_guard_accepts_a_pack_that_covers_the_window():
    lat, lon = M.SCENES["raleigh"]["lat"], M.SCENES["raleigh"]["lon"]
    cov = M.footprint_covers_window((30.0, 42.0, -86.0, -71.0),
                                    lat, lon, 160.0)
    assert cov["covers"] is True
    assert cov["reason"] == ""


def test_footprint_guard_rejects_an_empty_pack():
    cov = M.footprint_covers_window(None, 35.8, -78.8, 160.0)
    assert cov["covers"] is False
    assert "no water polygons" in cov["reason"]


# ---------------------------------------------------------------------------
# section 5: the timing rows
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def raleigh_timings(bench, qapp):
    """Every timing row from the Raleigh pack, measured once.

    One fixture rather than one per row: each render is seconds long,
    and -- more importantly -- a baseline pairs these numbers, so
    measuring them in separate sessions would let a settle from a quiet
    moment be judged against a gap from a busy one."""
    _root, tiles, water, highway = _scene_pack("raleigh")
    out = {}
    out["terrain_render_ms_160nm"] = M.measure_terrain_render_ms(
        bench, qapp, "raleigh", tiles, water, 160.0)
    out["terrain_render_ms_300nm"] = M.measure_terrain_render_ms(
        bench, qapp, "raleigh", tiles, water, 300.0)
    out.update(M.measure_pinch_out(bench, qapp, "raleigh", tiles, water))
    out.update(M.measure_paint_p95(bench, qapp, "raleigh", tiles, water))
    out["roads_render_ms_80nm"] = M.measure_roads_render_ms(
        bench, qapp, "raleigh", tiles, highway)
    return out


@pytest.mark.parametrize("metric", [
    "terrain_render_ms_160nm",
    "terrain_render_ms_300nm",
    "settle_latency_ms_pinch_out",
    "paint_ms_p95_40nm",
    "probe_max_gap_ms_pinch",
    "roads_render_ms_80nm",
])
def test_timing_row_within_host_baseline(metric, raleigh_timings, baseline,
                                          calibration_ms):
    """Section 5's timing rows against ``tests/perf/baselines/
    <host>.json`` with the DoD's 1.5x tolerance, warning on an unknown
    host.

    Per-host and not against section 5's absolute numbers, because those
    were measured on one machine: 0.6 s for a 160 NM render is a
    statement about a Beelink N150, and asserting it on arbitrary
    hardware would fail on a slow box with no defect present and pass on
    a fast box hiding a 3x regression. What makes the per-host form
    trustworthy is not the tolerance but the minting guards -- see
    ``tools/map_perf_baseline`` and the falsifiers below."""
    measured = raleigh_timings.get(metric)
    if measured is None:
        pytest.skip(f"{metric}: not measured with this pack "
                    "(no highway pack, or the render never published)")
    _assert_timing(metric, measured, baseline, calibration_ms)


# --- falsifiers for the comparator (no pack, no baseline needed) --------

def _fake_baseline(**metrics):
    return {
        "schema_version": baseline_tool.SCHEMA_VERSION,
        "host_id": "test", "calibration_ms": 100.0,
        "metrics": {k: {"ms": v} for k, v in metrics.items()},
    }


def test_comparator_passes_inside_the_tolerance_and_fails_outside():
    """The bound rejects a regression. 1.4x of the baseline is inside
    the 1.5x tolerance; 1.6x is not."""
    b = _fake_baseline(terrain_render_ms_160nm=400.0)
    inside = baseline_tool.check("terrain_render_ms_160nm", 560.0, b)
    outside = baseline_tool.check("terrain_render_ms_160nm", 640.0, b)
    assert inside.gated and inside.ok
    assert outside.gated and not outside.ok
    assert outside.bound == pytest.approx(600.0)


def test_comparator_does_not_report_a_pass_without_a_baseline():
    """"No baseline" must be distinguishable from "passed".

    ``ok`` is left ``None`` and ``gated`` is False, so a caller that
    writes ``assert v.ok`` gets an error rather than a silent green --
    the single most likely way this whole tier degrades into
    decoration."""
    v = baseline_tool.check("paint_ms_p95_40nm", 9999.0, None)
    assert v.gated is False
    assert v.ok is None
    assert "no baseline" in v.reason


def test_comparator_does_not_gate_a_metric_missing_from_the_baseline():
    v = baseline_tool.check("roads_render_ms_80nm", 9999.0,
                            _fake_baseline(paint_ms_p95_40nm=8.0))
    assert v.gated is False and v.ok is None


def test_comparator_stops_gating_when_the_host_has_drifted():
    """A baseline is a claim about a machine. If the calibration probe
    says the machine is now 2x slower (throttled, loaded, or a different
    box behind the same name), the claim no longer holds and the row
    warns instead of failing -- and, symmetrically, a baseline minted on
    a loaded box stops silently passing a real regression once the box
    is quiet again."""
    b = _fake_baseline(terrain_render_ms_160nm=400.0)     # cal 100 ms
    ok = baseline_tool.check("terrain_render_ms_160nm", 500.0, b,
                             calibration_ms=110.0)
    drifted = baseline_tool.check("terrain_render_ms_160nm", 500.0, b,
                                  calibration_ms=200.0)
    assert ok.gated is True
    assert drifted.gated is False
    assert "drifted" in drifted.reason


def test_comparator_rejects_an_unknown_metric():
    with pytest.raises(baseline_tool.BaselineError):
        baseline_tool.check("wall_clock_of_the_universe", 1.0,
                            _fake_baseline())


# --- falsifiers for the minting guards (no pack needed) -----------------

_GOOD = [{"terrain_render_ms_160nm": 400.0},
         {"terrain_render_ms_160nm": 410.0},
         {"terrain_render_ms_160nm": 405.0}]


def test_mint_refuses_when_the_count_budgets_did_not_pass():
    """The guard with no override, and the reason this module exists.

    A timing baseline captured over a pipeline defect records the defect
    as normal and passes it forever at 1.5x. The MP8a count budgets are
    hardware-independent, so they can tell "this tree is broken" from
    "this box is slow" -- which no clock can."""
    with pytest.raises(baseline_tool.BaselineError, match="count-based"):
        baseline_tool.build_baseline(_GOOD, count_budgets_passed=False,
                                     allow_dirty=True)


def test_mint_refuses_a_box_too_noisy_to_support_the_tolerance():
    noisy = [{"terrain_render_ms_160nm": 400.0},
             {"terrain_render_ms_160nm": 900.0},
             {"terrain_render_ms_160nm": 500.0}]
    with pytest.raises(baseline_tool.BaselineError, match="spread"):
        baseline_tool.build_baseline(noisy, count_budgets_passed=True,
                                     allow_dirty=True)


def test_mint_refuses_an_empty_baseline():
    with pytest.raises(baseline_tool.BaselineError, match="empty baseline"):
        baseline_tool.build_baseline([{"something_else_ms": 1.0}],
                                     count_budgets_passed=True,
                                     allow_dirty=True)


def test_mint_records_the_median_not_the_best_sample():
    """A baseline built from the fastest run is a baseline nothing can
    ever meet again; one built from the slowest hides a regression the
    size of the noise. The median is recorded, and every sample is kept
    in the file so the choice can be re-checked."""
    b = baseline_tool.build_baseline(_GOOD, count_budgets_passed=True,
                                     allow_dirty=True)
    row = b["metrics"]["terrain_render_ms_160nm"]
    assert row["ms"] == pytest.approx(405.0)
    assert row["samples"] == [400.0, 410.0, 405.0]
    assert row["spread"] == pytest.approx(1.025, abs=0.001)


def test_mint_records_provenance_that_can_be_rechecked():
    b = baseline_tool.build_baseline(_GOOD, count_budgets_passed=True,
                                     allow_dirty=True)
    for key in ("git_sha", "calibration_ms", "environment", "tolerance",
                "count_budgets_passed", "schema_version"):
        assert key in b, f"baseline lost its {key} provenance field"
    assert b["environment"]["host_id"] == baseline_tool.host_id()


def test_baseline_loader_rejects_a_stale_schema(tmp_path):
    (tmp_path / "somehost.json").write_text(
        '{"schema_version": 0, "metrics": {}}')
    with pytest.raises(baseline_tool.BaselineError, match="schema_version"):
        baseline_tool.load_baseline("somehost", directory=tmp_path)


def test_host_id_prefers_an_explicit_name(monkeypatch):
    """The change from the brief's ``<hostname>.json``: a GitHub-hosted
    runner's hostname is a per-job random string and a container's is
    the container id, so keying on it means no baseline is ever found on
    the hosts CI actually runs on -- every timing row warns forever,
    which is a tier that gates nothing. An operator names a machine they
    intend to keep."""
    monkeypatch.setenv("PYEFIS_PERF_HOST", "beelink")
    assert baseline_tool.host_id() == "beelink"
    monkeypatch.delenv("PYEFIS_PERF_HOST")
    assert baseline_tool.host_id()          # falls back, never empty


# --- falsifier for the measurement plumbing (tiles, but no pack) --------

@pytest.fixture(scope="module")
def synthetic_tiles(tmp_path_factory):
    """A small synthetic tile grid, purely so a render can be provoked
    without a pack.

    Same trick as ``test_map_gestures.tile_root``: ``load_tile`` infers
    the tile side from the file size, so 121x121 big-endian int16 tiles
    are real tiles to TileCache. Duplicated rather than shared because
    it exists here for a different reason -- MP8a needs it to make a
    COUNT non-vacuous, this file needs it only to make the clock tick on
    something -- and no budget in this file is asserted against it."""
    root = tmp_path_factory.mktemp("tiles_plumbing")
    n = 121
    body = ((np.arange(n * n, dtype=">i2") % 500) + 100).reshape(n, n)
    lat, lon = M.SCENES["raleigh"]["lat"], M.SCENES["raleigh"]["lon"]
    for la in range(int(lat) - 4, int(lat) + 5):
        d = root / ("N%02d" % la)
        d.mkdir(exist_ok=True)
        for lo in range(int(abs(lon)) - 4, int(abs(lon)) + 5):
            body.tofile(d / ("N%02dW%03d.hgt" % (la, lo)))
    return str(root)


def test_render_measurement_observes_a_stall_injected_into_the_worker(
        bench, qapp, synthetic_tiles):
    """The falsifier a timing budget cannot get from a source mutant.

    Everything above pins that the COMPARATOR rejects a number over the
    bound. This pins the other half -- that the number is genuinely read
    off the terrain worker, and not off a stale counter, a warm cache or
    a code path that stopped running. A 400 ms stall is injected into
    the real render and must show up, near enough in full, in the metric
    the budget reads.

    Without this, deleting the terrain layer's render entirely would
    make every timing row faster and greener."""
    from pyefis.instruments.map.layers.terrain import TerrainLayer
    stall_s = 0.4
    clean = M.measure_terrain_render_ms(bench, qapp, "raleigh",
                                        synthetic_tiles, "", 160.0)
    if clean is None:
        pytest.skip("baseline render never published")

    orig = TerrainLayer._render

    def stalled(self, job):
        time.sleep(stall_s)
        return orig(self, job)

    TerrainLayer._render = stalled
    try:
        slowed = M.measure_terrain_render_ms(bench, qapp, "raleigh",
                                             synthetic_tiles, "", 160.0)
    finally:
        TerrainLayer._render = orig
    assert slowed is not None
    assert slowed >= clean + stall_s * 1000.0 * 0.8, (
        f"a {stall_s * 1000:.0f} ms stall injected into TerrainLayer._render "
        f"moved the measured render time only {slowed - clean:.1f} ms "
        f"({clean:.1f} -> {slowed:.1f}); the timing budgets are not reading "
        "the render they claim to read.")


def test_gui_probe_reports_gaps_when_the_gil_is_held(bench, qapp,
                                                     synthetic_tiles):
    """The falsifier for the "GUI-thread starved / max gap <= 50 ms"
    row, and MP6's own DoD ("probe reports > 50 ms gaps when a test
    thread deliberately holds the GIL").

    The probe is a 10 ms QTimer on the GUI thread measuring its own
    tick-to-tick drift; a worker holding the GIL is invisible to every
    other counter here and is the entire stutter mechanism the brief's
    section 1.3 identified. If this passes with no gaps recorded, a
    green max-gap row means only that nothing was watching."""
    from pyefis.instruments.map.perf import PROBE_GAP_WARN_MS
    widget = M.build(bench, qapp, "raleigh", tile_path=synthetic_tiles,
                     range_nm=40.0)
    widget.perf.probe.reset()
    stop = threading.Event()

    def hog():
        # A pure-Python loop holds the GIL in 100-bytecode slices; the
        # GUI thread cannot run its timer while this is scheduled.
        while not stop.is_set():
            n = 0
            for _ in range(400000):
                n += 1

    t = threading.Thread(target=hog, daemon=True)
    t.start()
    try:
        bench._pump(qapp, 2.0)
    finally:
        stop.set()
        t.join(timeout=5.0)
    stats = widget.perf.snapshot()["probe"]
    widget.hide()
    qapp.processEvents()
    assert stats["count"] > 0, "the GUI probe never ticked at all"
    assert stats["max_ms"] > PROBE_GAP_WARN_MS, (
        f"a GIL-holding worker produced a max GUI-thread gap of only "
        f"{stats['max_ms']:.1f} ms; the probe cannot see starvation, so a "
        "green max-gap budget means nothing.")


# ---------------------------------------------------------------------------
# MP5's DoD: the pixel comparison
# ---------------------------------------------------------------------------

_WATER_RGB = np.array([60.0, 110.0, 160.0])


def _window_rgb(bench, app, scene, tiles, water, raster, range_nm):
    """The terrain layer's published window image as an (h, w, 3) float
    array. ``Format_RGBX8888``, so byte order really is R, G, B."""
    widget = M.build(bench, app, scene, tile_path=tiles, water_db=water,
                     range_nm=range_nm, water_raster=raster)
    snap = M._await_publish(bench, app, widget)
    if snap is None:
        widget.hide()
        app.processEvents()
        return None, None
    layer = [l for l in widget._layers
             if type(l).__name__ == "TerrainLayer"][0]
    img = layer._img[0]
    ptr = img.constBits()
    ptr.setsize(img.sizeInBytes())
    arr = np.frombuffer(ptr, np.uint8).reshape(
        img.height(), img.bytesPerLine() // 4, 4)[:, :img.width(), :3]
    out = arr.copy().astype(float)
    widget.hide()
    app.processEvents()
    return out, snap


def _water_coverage(painted, base):
    """Per-pixel water coverage in 0..1, recovered from the blend
    ``base*(1-f) + WATER*f``.

    NOT a hard colour match, and that distinction is the finding here.
    The legacy Qt rasterizer draws antialiased, so its boundary pixels
    are partial blends; MP5's numpy scanline fill writes whole pixels.
    A hard mask therefore scores the two as disagreeing along every
    coastline: measured at Key West 40 NM, an exact-colour IoU reads
    0.27 while the two paths cover the same total area to within 3.6%.
    The disagreement was entirely the oracle's."""
    d = _WATER_RGB - base
    den = (d * d).sum(axis=2)
    num = ((painted - base) * d).sum(axis=2)
    return np.clip(np.where(den > 1e-6, num / np.maximum(den, 1e-6), 0.0),
                   0.0, 1.0)


def test_water_raster_paths_agree_on_coverage(bench, qapp):
    """MP5's DoD pixel comparison: the numpy scanline fill must draw the
    same water as the per-vertex Qt rasterizer it replaced.

    Compared as total antialiasing-weighted coverage AREA, plus a soft
    (coverage-weighted) IoU, rather than as a hard-mask IoU -- see
    ``_water_coverage``. The counters are asserted equal alongside, so
    "same area" cannot be reached by drawing different geometry that
    happens to cover the same number of pixels."""
    _root, tiles, water, _hw = _scene_pack("key_west")
    base, _ = _window_rgb(bench, qapp, "key_west", tiles, "", "numpy", 40.0)
    np_img, np_snap = _window_rgb(bench, qapp, "key_west", tiles, water,
                                  "numpy", 40.0)
    qt_img, qt_snap = _window_rgb(bench, qapp, "key_west", tiles, water,
                                  "qt", 40.0)
    if base is None or np_img is None or qt_img is None:
        pytest.skip("key_west 40 NM render never published")

    assert np_snap["water"]["polygons_after"] == \
        qt_snap["water"]["polygons_after"]
    assert np_snap["water"]["vertices_after"] == \
        qt_snap["water"]["vertices_after"]
    assert np_snap["water"]["qpointf_count"] == 0
    assert qt_snap["water"]["qpointf_count"] > 0

    fn = _water_coverage(np_img, base)
    fq = _water_coverage(qt_img, base)
    area_n, area_q = float(fn.sum()), float(fq.sum())
    assert area_n > 0 and area_q > 0, "neither path drew any water"
    rel = abs(area_n - area_q) / max(area_n, area_q)
    assert rel <= COVERAGE_AREA_TOLERANCE, (
        f"MP5's numpy fill covers {area_n:.0f} px of water, the legacy Qt "
        f"rasterizer {area_q:.0f} px -- {rel * 100:.1f}% apart, over the "
        f"{COVERAGE_AREA_TOLERANCE * 100:.0f}% tolerance. MP5 bought its "
        "zero QPointF count by drawing something different.")


def test_coverage_metric_is_not_fooled_by_antialiasing():
    """The falsifier for the oracle above, and the record of why it is
    not an IoU.

    Two synthetic renders of the SAME shape are built against a known
    background: one hard-edged (a solid 6x6 block, 36 px) and one that
    spreads the identical 36 px of coverage over a wider, partially
    covered fringe, the way an antialiased rasterizer does. Their AREAS
    are equal by construction. A hard 0.5-threshold mask nonetheless
    scores them at IoU 0.44, because it keeps only the fringe's
    fully-covered interior -- which is exactly the artifact that made an
    exact-colour IoU read 0.27 on the real Key West scene while the two
    rasterizers agreed on area to within 3.6%.

    If the IoU assertion ever fails, this test has stopped demonstrating
    the trap. If the area assertion fails, ``_water_coverage`` has
    stopped recovering the blend and the comparison above is measuring
    antialiasing rather than geometry."""
    land = np.tile(np.array([80.0, 114.0, 71.0]), (12, 12, 1))

    hard_f = np.zeros((12, 12))
    hard_f[3:9, 3:9] = 1.0                       # 36 px, hard edge

    soft_f = np.zeros((12, 12))
    soft_f[4:8, 4:8] = 1.0                       # 16 px fully covered
    inner = np.zeros((12, 12), bool)
    inner[3:9, 3:9] = True
    inner[4:8, 4:8] = False                      # 20 px ring
    outer = np.zeros((12, 12), bool)
    outer[2:10, 2:10] = True
    outer[3:9, 3:9] = False                      # 28 px ring
    soft_f[inner] = 0.45                         # just under the 0.5 mask
    # Balance the outer fringe so the TOTAL coverage matches exactly.
    soft_f[outer] = (hard_f.sum() - soft_f.sum()) / outer.sum()

    def blend(f):
        return land * (1.0 - f[..., None]) + _WATER_RGB * f[..., None]

    fh = _water_coverage(blend(hard_f), land)
    fs = _water_coverage(blend(soft_f), land)

    hard_mask, soft_mask = fh >= 0.5, fs >= 0.5
    iou = (hard_mask & soft_mask).sum() / max((hard_mask | soft_mask).sum(), 1)
    assert iou < 0.6, (
        f"the hard-mask IoU reads {iou:.2f} on two shapes of identical "
        "area that differ only in antialiasing -- it no longer penalises "
        "antialiasing, so this test is not demonstrating the trap")
    assert abs(fh.sum() - fs.sum()) / fh.sum() < 0.02, (
        "the coverage metric is not recovering the antialiased blend; "
        "test_water_raster_paths_agree_on_coverage is measuring "
        "antialiasing, not geometry")


# ---------------------------------------------------------------------------
# Pack integrity -- an oracle whose ground truth follows a data pack
# ---------------------------------------------------------------------------

def test_pack_identity_is_recorded_when_a_pack_is_used():
    """Every budget in this file is a statement about a specific data
    pack, so which pack must be recoverable from the run.

    A volume budget measured against a pack nobody can identify is a
    measurement of nothing: the next cycle moves the number for reasons
    that have nothing to do with the code, and there is no way to tell
    that from a regression."""
    _root, _tiles, water, _hw = _scene_pack("raleigh")
    ident = baseline_tool.water_pack_identity(water)
    assert ident, (
        f"{water} has no pack_meta table -- this pack cannot be "
        "identified, so no budget measured against it is attributable. "
        "Re-cut from a versioned pack (build_water_db writes pack_meta).")
    assert ident.get("id") and ident.get("cycle")
