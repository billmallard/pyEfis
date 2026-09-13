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
  * The **volume** row is hardware-independent -- a function of the
    pack, the scene, the range, the widget size and the decimation
    algorithm, nothing else -- so it is a hard assertion wherever a pack
    exists, including CI once the manifest is published. It is a
    function of the widget GEOMETRY too, more sharply than the brief
    suggests: see "the wide-water cliff" below.
  * The **pixel comparison** is hardware-independent in the same sense,
    but only half of it holds today. "The numpy fill invents no water"
    gates; "the numpy fill covers everything the Qt path calls solid
    water" does not, and is carried as a strict ``xfail`` with its
    measurement rather than widened into a pass. Key West cannot carry
    the comparison at all and says so.
  * Everything in the ``--- falsifiers ---`` sections runs everywhere,
    always.
"""

import importlib.util
import json
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

#: The range that row is asserted at, owned by THIS suite because the
#: brief owns it. Deliberately not
#: ``make_map_perf_fixture.RANGE_LADDER_TOP_NM``, which is the cutter's
#: input and happens to hold the same value today: a coverage check that
#: takes both the cut AND the window it must contain from the same
#: constant moves with it and asserts nothing. That is the failure
#: AER-1156 is fixing, and it is easy to write again by accident -- the
#: first draft of ``test_the_cutter_declares_a_footprint_that_covers_
#: the_volume_row`` did exactly that and survived the cutter's ladder
#: top being narrowed 160 -> 100 NM.
VOLUME_ROW_RANGE_NM = 160.0

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
    root, tiles, water, _hw = _scene_pack("raleigh")
    _require_footprint("raleigh", water, 160.0, pack_root=root)
    out = M.measure_water_volume(bench, qapp, "raleigh", tiles, water)
    if out is None:
        pytest.skip("raleigh 160 NM render never published")
    return out


def _require_footprint(scene, water_db, range_nm, pack_root=None):
    """Skip unless the pack is big enough for the question. See
    ``measure.pack_coverage`` -- this is the guard that stops a
    truncated pack reporting a comfortable pass.

    AER-1156: *pack_root* is what makes this read the pack's own
    ``footprint.json`` rather than inferring the cut from the data
    extent. Callers should always pass it (``_scene_pack``'s first
    return value); it is optional only so the no-pack falsifiers below
    can exercise the fallback path deliberately."""
    s = M.SCENES[scene]
    cov = M.pack_coverage(pack_root, water_db, s["lat"], s["lon"], range_nm)
    if not cov["covers"]:
        area = cov["pack_area_vs_window"]
        need = cov["need_span_deg"]
        pytest.skip(
            f"{scene} pack does not cover the {range_nm:.0f} NM render "
            f"window, so a volume budget measured against it is not "
            f"evidence: {cov['reason']}."
            + (f" Covered area fraction {area}." if area is not None else "")
            + (f" Re-cut with a window at least {need[0]:.1f} x "
               f"{need[1]:.1f} deg." if need is not None else "")
            + " (tools/make_map_perf_fixture.py cut)")


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
    root, tiles, water, _hw = _scene_pack("raleigh")
    _require_footprint("raleigh", water, 160.0, pack_root=root)
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

def test_a_160nm_render_reads_far_more_than_160_nm_of_pack():
    """The arithmetic behind ``_require_footprint``, pinned.

    A nominal 160 NM render at 650x1040 does not read a 160 NM circle.
    It reads a window of **7.85 deg lat x 9.68 deg lon** at Raleigh --
    76 square degrees -- for two compounding reasons, both easy to
    under-count:

      * the widget's ``range_nm`` is measured anchor-to-top-edge, and
        the ownship anchor defaults to mid-screen, so the window's
        half-height is already 2x the range;
      * ``_render`` covers the ROTATED viewport -- the widget's
        half-DIAGONAL, oversized a further 1.25x.

    Together a nominal 160 NM render queries the water pack over a
    235.6 NM box.

    Why it matters, measured on the real pack rather than argued:
    Raleigh at 160 NM rasterizes 102,034 vertices against the full North
    America pack and 14,259 against a 3x3 deg cut of that same pack --
    14% of the truth, and a 10.5x margin under a 150k budget instead of
    1.47x. That budget would still catch MP4 being deleted outright, and
    would not catch decimation becoming 7x less effective.

    AER-1156: this test used to close by comparing the window against a
    literal ``9.0`` square degrees, described as what the cutter emits
    -- ``WINDOW_DEG = 2.0`` snapped to 3x3 whole-degree cells. AER-1142
    (#209) deleted ``WINDOW_DEG`` outright and derives each vector
    layer's footprint per layer instead, so both the symbol and the
    number named a thing that no longer exists. The test still passed,
    because it was arithmetic over its own literals -- which is exactly
    the drift its last paragraph claimed to be guarding against. The
    anchoring assertion now lives in
    ``test_the_cutter_declares_a_footprint_that_covers_the_volume_row``,
    where it is asked of the tool rather than of a constant copied out
    of it."""
    lat_span, lon_span = M.render_window_span_deg(160.0,
                                                  M.SCENES["raleigh"]["lat"])
    assert M.effective_range_nm(160.0) == pytest.approx(235.6, abs=0.5)
    assert lat_span == pytest.approx(7.85, abs=0.05)
    assert lon_span == pytest.approx(9.68, abs=0.05)
    # The claim in the name: the window is far wider than the nominal
    # range makes it sound. 160 NM is 2.67 deg of latitude; the window
    # is 7.85, so the pack must reach ~2.9x further than "160 NM".
    assert lat_span / (2.0 * 160.0 / 60.0) == pytest.approx(1.47, abs=0.02)


def test_the_cutter_declares_a_footprint_that_covers_the_volume_row():
    """The anchor: the cutter's own derived water footprint must contain
    the window the volume row is asserted over.

    This is the guard AER-1156 exists to install, and the one whose
    absence let AER-1142 (#209) rework the cut geometry with nothing
    noticing. It re-derives nothing -- it asks
    ``make_map_perf_fixture`` what it would cut, using the tool's own
    functions and its own published constants, and requires the answer
    to contain the window ``measure.render_window_span_deg`` says a
    160 NM render reads.

    The two sides come from different owners on purpose, which is the
    whole of why it can fail: the cut is derived with the CUTTER's
    constants, the window it must contain is ``VOLUME_ROW_RANGE_NM``,
    owned by this suite. So it goes red in both directions that matter,
    on every CI run, with no pack:

      * the cutter is narrowed, or its range/envelope inputs change, so
        a published pack would no longer cover the volume row's window
        (verified: ``RANGE_LADDER_TOP_NM`` 160 -> 100 fails this);
      * the RENDER window grows -- a wider default widget, a different
        ownship anchor, a bigger oversize factor -- past a cut that used
        to contain it (verified: the ``_render`` oversize 1.25 -> 1.6
        fails this).

    Measured today at Raleigh: the cutter derives a 282.8 NM radius from
    the widest of ``PERF_WIDGET_ENVELOPES`` at its 160 NM ladder top,
    giving a 9.43 x 11.62 deg box against a 7.85 x 9.68 deg window."""
    for scene in ("raleigh", "key_west"):
        s = M.SCENES[scene]
        lat, lon = s["lat"], s["lon"]

        radius_nm, _env = fixture_tool._widest_half_diag_nm(
            fixture_tool.RANGE_LADDER_TOP_NM)
        d_lat, d_lon = fixture_tool._deg_radius(radius_nm, lat)
        declared = fixture_tool._bbox_from_radius(lat, lon, d_lat, d_lon)

        cov = M.footprint_covers_window(declared, lat, lon,
                                        VOLUME_ROW_RANGE_NM,
                                        source="declared")
        assert cov["covers"], (
            f"the cutter's derived {scene} water footprint no longer covers "
            f"the window the volume row is asserted over. {cov['reason']}. "
            "Either the cut narrowed or the render window grew; a pack cut "
            "by this tool would make the volume row a measurement of a "
            "truncated scene.")


def test_the_manifest_name_still_matches_the_cutter():
    """``measure.FOOTPRINT_MANIFEST_NAME`` is a duplicate of the
    cutter's, for the same reason everything else in ``measure`` is a
    duplicate. If the cutter renames the file and the mirror does not
    follow, ``pack_coverage`` silently stops finding any declaration and
    falls back to the data extent on every pack -- which still passes,
    and quietly reinstates the failure mode AER-1156 removed."""
    assert (M.FOOTPRINT_MANIFEST_NAME
            == fixture_tool.FOOTPRINT_MANIFEST_NAME)


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
    """Both boxes below are HYPOTHETICAL undersized cuts, not a claim
    about what any tool emits.

    AER-1156: the first used to be commented "what the cutter emits
    today" -- ``WINDOW_DEG = 2.0`` snapped to 3x3 whole-degree cells --
    and AER-1142 (#209) deleted ``WINDOW_DEG`` and widened the
    derivation past both of them. The comparison is still worth pinning,
    because it is the guard's own arithmetic; what was false was the
    provenance claimed for the numbers. What the cutter actually emits
    is asserted, against the tool, in
    ``test_the_cutter_declares_a_footprint_that_covers_the_volume_row``."""
    lat, lon = M.SCENES["raleigh"]["lat"], M.SCENES["raleigh"]["lon"]
    cov = M.footprint_covers_window((34.0, 37.0, -80.0, -77.0), lat, lon,
                                    160.0)
    assert cov["covers"] is False
    assert cov["pack_area_vs_window"] < 0.15
    assert "160 NM render" in cov["reason"]

    # An 8x8 deg cut is still short -- recorded so nobody widens a cut
    # a little and assumes the row became evidence.
    wide = M.footprint_covers_window((32.0, 40.0, -83.0, -75.0),
                                     lat, lon, 160.0)
    assert wide["covers"] is False


def test_the_data_extent_can_report_coverage_a_cut_does_not_have():
    """Why ``pack_coverage`` decides on the declaration and not on
    ``water_coverage_bbox``. Measured, not argued.

    ``cut_water`` selects polygons by bbox OVERLAP and keeps each one
    WHOLE -- correctly, since a renderer inside the window needs the
    whole polygon. So MIN/MAX over what a cut pack contains reaches PAST
    the box it was cut to, and it reaches past it in the direction that
    reads as more coverage.

    Both boxes below are MEASURED, on the published North America water
    pack (water-na, 2026q2r6), by running ``cut_water``'s own overlap
    predicate at Raleigh over a 7.60 x 11.00 deg cut -- 8,106 polygons,
    0.127 deg short of the 160 NM window at both the top and the bottom
    in latitude:

      * the cut box does NOT contain the window -- the truth;
      * the resulting data extent DOES -- what the old guard said.

    A pack cut that way would have had its volume row treated as
    evidence with the scene truncated top and bottom.

    On the honest size of it: 0.127 deg is 7.6 NM, and this test does
    not claim that much truncation moves the vertex count enough to
    matter -- that would need a render, and it was not run. What it
    pins is that the proxy answers "covered" for a cut that is not, and
    that nothing bounds by how much. The over-report happens to stop at
    ~0.13 deg here only because this pack's ocean polygons are clipped
    to whole-degree tiles; the largest single polygon in it spans 5.46
    deg of latitude and 7.99 of longitude, which is the scale the error
    can reach on a pack built differently."""
    lat, lon = M.SCENES["raleigh"]["lat"], M.SCENES["raleigh"]["lon"]
    cut = (32.0000, 39.6000, -84.3000, -73.3000)
    data_extent = (30.9995, 40.0005, -84.8616, -72.9994)

    truth = M.footprint_covers_window(cut, lat, lon, 160.0,
                                      source="declared")
    proxy = M.footprint_covers_window(data_extent, lat, lon, 160.0,
                                      source="data-extent")
    assert truth["covers"] is False, (
        "the measured undersized cut now reads as covering; the window "
        "arithmetic moved and this recorded measurement no longer "
        "demonstrates anything.")
    assert proxy["covers"] is True, (
        "the measured data extent no longer reads as covering; re-measure "
        "before treating the data extent as a safe fallback.")


def test_pack_coverage_prefers_the_declaration_over_the_data_extent(tmp_path):
    """The precedence rule, end to end, on a pack built to make the two
    sources disagree.

    A ``footprint.json`` declaring an undersized cut must win over a
    water table whose contents sprawl past it -- that is the false pass
    above, refused. With no declaration the data extent is still used,
    because a pre-AER-1142 pack guarded loosely beats one not guarded at
    all, and ``source`` says which answered either way."""
    lat, lon = M.SCENES["raleigh"]["lat"], M.SCENES["raleigh"]["lon"]
    water = tmp_path / "water.sqlite"
    con = sqlite3.connect(str(water))
    try:
        con.executescript(fixture_tool.WATER_SCHEMA)
        # One edge polygon sprawling past the cut, exactly as the real
        # pack's do -- the measured extent from the test above.
        con.execute(
            "INSERT INTO water_polygons (min_lat, max_lat, min_lon, max_lon, "
            "kind, vertices) VALUES (?, ?, ?, ?, 'ocean', X'00')",
            (30.9995, 40.0005, -84.8616, -72.9994))
        con.commit()
    finally:
        con.close()

    # No declaration: the data extent answers, and says covered.
    fallback = M.pack_coverage(tmp_path, str(water), lat, lon, 160.0)
    assert fallback["source"] == "data-extent"
    assert fallback["covers"] is True
    assert fallback["declared_bbox"] is None

    # Same pack, now declaring the undersized cut it was really made
    # from: the declaration wins and the row is refused.
    (tmp_path / M.FOOTPRINT_MANIFEST_NAME).write_text(json.dumps({
        "scene": "raleigh", "lat": lat, "lon": lon,
        "layers": {"water": {"bbox": [32.0000, 39.6000,
                                      -84.3000, -73.3000]}},
    }))
    decided = M.pack_coverage(tmp_path, str(water), lat, lon, 160.0)
    assert decided["source"] == "declared"
    assert decided["covers"] is False
    assert decided["centre_matches"] is True
    assert decided["data_extent_bbox"] is not None
    assert "declared" in decided["reason"]


def test_pack_coverage_refuses_a_manifest_from_another_scene(tmp_path):
    """Truth-blindness, refused rather than measured around.

    A ``footprint.json`` that declares a different centre is not a
    declaration about this pack. Falling back to the data extent there
    would be worse than useless: it would answer confidently for a pack
    whose provenance is unknown. The centre check is exact (float noise
    only) because the two ``SCENES`` tables carry the same literals --
    any real difference is a different scene."""
    lat, lon = M.SCENES["raleigh"]["lat"], M.SCENES["raleigh"]["lon"]
    kw = M.SCENES["key_west"]
    (tmp_path / M.FOOTPRINT_MANIFEST_NAME).write_text(json.dumps({
        "scene": "key_west", "lat": kw["lat"], "lon": kw["lon"],
        "layers": {"water": {"bbox": [kw["lat"] - 6, kw["lat"] + 6,
                                      kw["lon"] - 6, kw["lon"] + 6]}},
    }))
    cov = M.pack_coverage(tmp_path, "", lat, lon, 160.0)
    assert cov["covers"] is False
    assert cov["centre_matches"] is False
    assert "does not describe this pack" in cov["reason"]


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


def test_the_guard_skips_rather_than_crashes_on_an_empty_pack(tmp_path):
    """Found while fixing AER-1156, and separate from it.

    ``footprint_covers_window``'s no-coverage branch returned a dict
    without ``pack_area_vs_window`` or ``need_span_deg``, and
    ``_require_footprint`` formats both into its skip message -- so an
    empty water pack raised ``KeyError`` out of the guard instead of
    skipping. The test above never saw it because it calls the
    comparison directly and never goes through the guard. This one goes
    through the guard, which is the only place the bug lived."""
    water = tmp_path / "water.sqlite"
    con = sqlite3.connect(str(water))
    try:
        con.executescript(fixture_tool.WATER_SCHEMA)
        con.commit()
    finally:
        con.close()
    # pytest.skip raises off BaseException, so catching Exception here
    # would let the skip escape and mark THIS test skipped -- which is
    # indistinguishable from it passing, the failure mode this file
    # spends most of its length avoiding.
    with pytest.raises(pytest.skip.Exception) as exc:
        _require_footprint("raleigh", str(water), 160.0, pack_root=tmp_path)
    assert "no water polygons" in str(exc.value)


# ---------------------------------------------------------------------------
# the wide-water cliff: which side of it the volume row is measured on
# ---------------------------------------------------------------------------
#
# ``TerrainLayer`` draws the full water overlay -- ocean coastline plus
# every lake down to a 3-pixel floor -- only while the WINDOW range is
# at or below ``_WATER_FULL_MAX_NM`` (300 NM). Above it the ocean is
# dropped entirely and lakes are filtered by bbox diagonal. The drawn
# set therefore changes DISCONTINUOUSLY at that boundary, and the
# boundary is crossed as a function of widget geometry, not of the range
# the pilot selected.
#
# Measured on the published North America pack (water-na, 2026q2r6),
# cap 1024, one nominal 160 NM render per row:
#
#   scene     widget     window NM   mode     vertices rasterized
#   raleigh   650x1040       235.6   full                 102,034
#   raleigh   800x480        388.4   wide                  54,019
#   key_west  650x1040       235.6   full                  75,313
#   key_west  800x480        388.4   wide                   2,593
#
# Key West loses 29x of its water at the same nominal range, because
# dropping the ocean drops essentially the whole scene. A budget written
# as "at 160 NM" is therefore two different budgets wearing one number,
# and which one you measured is decided by the widget's aspect ratio.
# Raised back to the brief as a requirement question (AER-1135); pinned
# here so the volume row at least states which of the two it is.

def test_the_wide_water_cliff_constant_still_matches_the_renderer():
    """``measure.WATER_FULL_OVERLAY_MAX_NM`` mirrors a private constant
    in the layer. If the layer moves and the mirror does not, every
    cliff-side claim below becomes a statement about a threshold that no
    longer exists -- so import the real one and require agreement."""
    from pyefis.instruments.map.layers.terrain import TerrainLayer
    assert (M.WATER_FULL_OVERLAY_MAX_NM
            == TerrainLayer._WATER_FULL_MAX_NM), (
        "the wide-water threshold moved in TerrainLayer "
        f"({TerrainLayer._WATER_FULL_MAX_NM}) but measure.py still "
        f"mirrors {M.WATER_FULL_OVERLAY_MAX_NM}.")


def test_volume_row_is_measured_with_the_full_water_overlay():
    """The volume row's scene must sit on the FULL-overlay side, and
    this states by how much.

    Section 5's 150k is a budget on MP4's decimation of a dense real
    scene. Measured in wide mode it would be a budget on the size filter
    instead -- a different mechanism, a much smaller number, and a pass
    that means nothing. 650x1040 at 160 NM reads a 235.6 NM window, 21%
    clear of the 300 NM threshold.

    This fails, rather than silently changing the number, if the scene
    geometry or the oversize factor drifts across the boundary."""
    c = M.cliff_margin(160.0)
    assert c["wide"] is False, (
        f"the 160 NM volume row is being measured in WIDE water mode "
        f"(window {c['effective_nm']} NM > {c['threshold_nm']} NM): the "
        "ocean is dropped and lakes are size-filtered, so 150k is no "
        "longer a budget on MP4's decimation.")
    assert c["effective_nm"] == pytest.approx(235.6, abs=0.5)
    assert c["fraction"] < -0.15


def test_the_300nm_timing_row_is_measured_in_wide_mode():
    """The companion, and the reason the two timing rows are not
    comparable as "the same scene, further out".

    A nominal 300 NM render at 650x1040 reads a 441.8 NM window, which
    is 47% PAST the threshold: the ocean is gone and only lakes with a
    bbox diagonal over 0.44 deg survive. Section 5 budgets both 160 and
    300 NM at the same 0.6 s, and this is the note that they are timing
    two different drawn sets. Pinned so that is a recorded fact rather
    than something a later reader has to re-derive."""
    c = M.cliff_margin(300.0)
    assert c["wide"] is True
    assert c["effective_nm"] == pytest.approx(441.8, abs=0.5)


def test_the_count_budget_geometry_is_below_the_cliff_but_only_just():
    """MP8a's landed count budgets (``test_map_gestures.py``) run at
    300x300, and its pinch tops out at 160 NM. That lands at a 282.3 NM
    window -- inside the full overlay, but with **5.9%** of headroom,
    and the pinch would cross the boundary at a top range of 170 NM.

    Nothing in MP8a asserts a water COUNT that the mode change would
    move (its synthetic lakes are 1.0-1.4 deg across and survive the
    wide-mode size floor either way), so this is not a live defect in
    that file. It is a tripwire: if the pinch's top range, the ownship
    anchor or the 1.25 oversize is edited, the MP8a water counters
    change mode, and this says so by name instead of leaving a changed
    number to be explained."""
    c = M.cliff_margin(160.0, w=300, h=300)
    assert c["wide"] is False
    assert c["effective_nm"] == pytest.approx(282.3, abs=0.5)
    assert -0.10 < c["fraction"] < 0.0, (
        f"MP8a's 300x300 geometry now sits {c['fraction']:+.1%} from the "
        "wide-water cliff; its water counters may have changed mode.")
    assert c["nominal_at_cliff_nm"] == pytest.approx(170.0, abs=1.0)


def test_a_landscape_widget_crosses_the_cliff_at_the_same_nominal_range():
    """The falsifier for the guard above: prove it can say True.

    If ``wide_water_mode`` answered False everywhere it would be a
    decoration on the volume row rather than a check. A 800x480 widget
    -- an ordinary landscape map geometry -- reads a 388.4 NM window at
    the same nominal 160 NM and is already wide.

    It also states the finding in its assertable form: the nominal range
    at which the crisp coastline disappears is 203.7 NM on the portrait
    scene and 123.6 NM on this one. Same code, same pilot-selected
    range, different picture."""
    c = M.cliff_margin(160.0, w=800, h=480)
    assert c["wide"] is True
    assert c["effective_nm"] == pytest.approx(388.4, abs=0.5)
    assert c["nominal_at_cliff_nm"] == pytest.approx(123.6, abs=1.0)
    assert (M.full_overlay_max_nominal_nm(800, 480)
            < M.full_overlay_max_nominal_nm(650, 1040))


@pytest.fixture(scope="module")
def synthetic_water(tmp_path_factory):
    """Three dense circular lakes around the Raleigh centre, so a render
    has something to query for.

    Nothing is asserted about the CONTENT -- this exists only so
    ``polygons_in_range`` is called and its arguments can be observed.
    The lakes are 0.7-1.0 deg across on purpose: big enough to survive
    the wide-mode size floor at either geometry, so whether the call
    returns anything never depends on the flag under test."""
    from pyefis.instruments.ai.water_db import encode_vertices
    lat, lon = M.SCENES["raleigh"]["lat"], M.SCENES["raleigh"]["lon"]
    path = tmp_path_factory.mktemp("water_plumbing") / "water.sqlite"
    con = sqlite3.connect(str(path))
    con.execute(
        "CREATE TABLE water_polygons ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " min_lat REAL NOT NULL, max_lat REAL NOT NULL,"
        " min_lon REAL NOT NULL, max_lon REAL NOT NULL,"
        " kind TEXT NOT NULL, elev_ft REAL, vertices BLOB NOT NULL)")
    for clat, clon, radius in ((lat, lon, 0.5), (lat + 0.6, lon + 0.6, 0.35),
                               (lat - 0.6, lon - 0.6, 0.4)):
        verts = [(clat + radius * math.cos(2 * math.pi * i / 2000),
                  clon + radius * math.sin(2 * math.pi * i / 2000))
                 for i in range(2000)]
        lats = [v[0] for v in verts]
        lons = [v[1] for v in verts]
        con.execute(
            "INSERT INTO water_polygons (min_lat, max_lat, min_lon, max_lon,"
            " kind, elev_ft, vertices) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (min(lats), max(lats), min(lons), max(lons), "lake", 200.0,
             encode_vertices(verts)))
    con.commit()
    con.close()
    return str(path)


def test_cliff_prediction_matches_the_renderer(bench, qapp, synthetic_tiles,
                                               synthetic_water):
    """The arithmetic above is a reimplementation of production sizing,
    and a reimplementation is a claim. This runs a real render at each
    geometry and requires ``wide_water_mode``'s prediction to match the
    ``drop_ocean`` the layer actually passed the water DB.

    Needs no pack: the flag is decided by geometry before a single
    polygon is read, so a three-lake synthetic set is enough to observe
    the call. This is the same lesson as
    ``test_render_window_matches_the_water_query_box`` -- the anchor
    fraction was wrong on the first pass there and no amount of
    pure-arithmetic testing could see it."""
    tiles, water = synthetic_tiles, synthetic_water
    from pyefis.instruments.ai import water_db as wdb
    for (w_px, h_px, nominal) in ((650, 1040, 160.0), (800, 480, 160.0),
                                  (300, 300, 160.0), (650, 1040, 300.0)):
        seen = []
        orig = wdb.WaterDB.polygons_in_range

        def spy(self, lat, lon, range_nm, min_bbox_diag_deg=0.0,
                drop_ocean=False, _o=orig, _s=seen, **kw):
            _s.append((range_nm, drop_ocean))
            return _o(self, lat, lon, range_nm,
                      min_bbox_diag_deg=min_bbox_diag_deg,
                      drop_ocean=drop_ocean, **kw)

        wdb.WaterDB.polygons_in_range = spy
        try:
            M.measure_water_volume(bench, qapp, "raleigh", tiles, water,
                                   range_nm=nominal, w=w_px, h=h_px)
        finally:
            wdb.WaterDB.polygons_in_range = orig
        if not seen:
            pytest.skip(f"{w_px}x{h_px} @ {nominal} NM never queried water")
        actual_range, actual_wide = seen[0]
        assert actual_range == pytest.approx(
            M.effective_range_nm(nominal, w_px, h_px), rel=0.01), (
            f"{w_px}x{h_px} @ {nominal} NM: predicted window "
            f"{M.effective_range_nm(nominal, w_px, h_px):.1f} NM, the "
            f"renderer used {actual_range:.1f} NM.")
        assert actual_wide is M.wide_water_mode(nominal, w_px, h_px), (
            f"{w_px}x{h_px} @ {nominal} NM: predicted wide="
            f"{M.wide_water_mode(nominal, w_px, h_px)}, the renderer "
            f"passed drop_ocean={actual_wide}.")


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


#: A base pixel must be this far (squared RGB distance) from the water
#: colour before the blend above can be inverted at all -- see
#: ``_coverage_measurable``. 400 is an RGB distance of 20, comfortably
#: above hillshade dither and far below any real land colour.
_COVERAGE_DEN_FLOOR = 400.0

#: Below this measurable fraction of the window the comparison is not
#: evidence and the row SKIPS with its numbers rather than passing. The
#: value is not tuned to make a scene pass: Raleigh measures 0.57 here
#: and Key West 0.03, so anything between them behaves identically.
_COVERAGE_MIN_MEASURABLE_FRAC = 0.25


def _coverage_measurable(base):
    """Which pixels can carry a coverage measurement at all.

    **The blind spot this exists to declare.** ``TerrainLayer`` paints
    its own elevation-derived water -- void tiles and the ocean
    backstop -- in exactly the overlay's RGB (``terrain.py:326`` writes
    ``60, 110, 160``; ``:404`` writes the same triple for the pack's
    polygons). Where the base render is already that colour, ``d`` is
    zero, the blend below is not invertible, and NO rasterizer
    difference is observable in the final image however large it is.

    Measured today against the published pack (water-na, 2026q2r6) at
    40 NM, offscreen:

      * **Key West, real GLO-30 Keys tiles: 0.0% measurable** at this
        floor (96.9% of the window is exactly the water RGB, and the
        remaining 3.1% is within 20 RGB of it). Total recovered
        coverage is 0.0 px: the comparison cannot distinguish the two
        paths anywhere in the scene.
      * **Raleigh: 57.2% measurable**, 11.0k px change under the numpy
        path and 17.9k under the Qt path, so the row has something to
        compare.

    This is a property of the oracle, not a defect in either
    rasterizer. Stating it as a mask -- and skipping on it -- is what
    keeps "could not be measured" from being recorded as "the two paths
    agree"."""
    d = _WATER_RGB - base
    return (d * d).sum(axis=2) > _COVERAGE_DEN_FLOOR


def _water_coverage(painted, base):
    """Per-pixel water coverage in 0..1, recovered from the blend
    ``base*(1-f) + WATER*f``, and zero wherever
    ``_coverage_measurable`` says the blend cannot be inverted.

    NOT a hard colour match, and that distinction is the second finding
    here. The legacy Qt rasterizer draws antialiased, so its boundary
    pixels are partial blends; MP5's numpy scanline fill writes whole
    pixels. A hard mask therefore scores the two as disagreeing along
    every coastline -- see
    ``test_coverage_metric_is_not_fooled_by_antialiasing``, which
    reproduces the artifact synthetically rather than resting on a
    scene number."""
    d = _WATER_RGB - base
    den = (d * d).sum(axis=2)
    num = ((painted - base) * d).sum(axis=2)
    ok = den > _COVERAGE_DEN_FLOOR
    return np.clip(np.where(ok, num / np.maximum(den, 1e-6), 0.0), 0.0, 1.0)


def _raster_ab(bench, qapp, scene):
    """The three renders MP5's comparison needs -- no water, numpy
    water, Qt water -- plus the recovered coverage fields.

    Skips (never passes) when the scene cannot carry the measurement:
    no pack, no published render, or a window the terrain backstop has
    already painted the overlay's own colour."""
    _root, tiles, water, _hw = _scene_pack(scene)
    base, _ = _window_rgb(bench, qapp, scene, tiles, "", "numpy", 40.0)
    np_img, np_snap = _window_rgb(bench, qapp, scene, tiles, water,
                                  "numpy", 40.0)
    qt_img, qt_snap = _window_rgb(bench, qapp, scene, tiles, water,
                                  "qt", 40.0)
    if base is None or np_img is None or qt_img is None:
        pytest.skip(f"{scene} 40 NM render never published")
    frac = float(_coverage_measurable(base).mean())
    if frac < _COVERAGE_MIN_MEASURABLE_FRAC:
        pytest.skip(
            f"{scene} 40 NM: only {frac * 100:.1f}% of the window can carry "
            "a coverage measurement -- the terrain layer's own water "
            "(terrain.py:326) already paints the rest in the overlay's "
            "exact RGB, so no difference between the two rasterizers is "
            "observable there. Not a pass: the paths were not compared.")
    fn = _water_coverage(np_img, base)
    fq = _water_coverage(qt_img, base)
    if fn.sum() <= 0 and fq.sum() <= 0:
        pytest.skip(
            f"neither path drew any water over the {frac * 100:.1f}% of "
            f"the {scene} window that is measurable")
    return {"scene": scene, "fn": fn, "fq": fq, "measurable_frac": frac,
            "np_snap": np_snap, "qt_snap": qt_snap}


@pytest.mark.parametrize("scene", ["raleigh", "key_west"])
def test_water_raster_paths_draw_the_same_geometry(bench, qapp, scene):
    """MP5's DoD pixel comparison, in the direction that holds and is
    the one that matters: **the numpy fill invents no water.**

    Measured at Raleigh 40 NM against the published pack (water-na,
    2026q2r6): both paths decode the same 574 polygons and the same
    29,285 post-decimation vertices, and over the 57% of the window that
    is measurable the numpy fill lights **10 pixels** that the Qt
    rasterizer calls solid land -- 1e-5 of it. Water painted where there
    is none is the failure with a cockpit consequence; this is the
    assertion that gates it, and it is hard.

    The opposite direction does NOT hold and is recorded separately in
    ``test_numpy_fill_covers_the_qt_rasterizers_solid_water``. It is
    split out rather than folded in here so that this row keeps gating
    on every host with a pack instead of being dragged red by an open
    question."""
    ab = _raster_ab(bench, qapp, scene)
    np_snap, qt_snap = ab["np_snap"], ab["qt_snap"]
    assert np_snap["water"]["polygons_after"] == \
        qt_snap["water"]["polygons_after"]
    assert np_snap["water"]["vertices_after"] == \
        qt_snap["water"]["vertices_after"]
    assert np_snap["water"]["qpointf_count"] == 0
    assert qt_snap["water"]["qpointf_count"] > 0

    fn, fq = ab["fn"], ab["fq"]
    solid_land = fq <= 0.1
    spurious = int((solid_land & (fn > 0.5)).sum())
    assert spurious <= 0.001 * max(1, int(solid_land.sum())), (
        f"MP5's numpy fill paints water on {spurious} pixels the Qt "
        f"rasterizer renders as solid land ({ab['scene']} 40 NM). Water "
        "drawn where the pack has none is the direction with a cockpit "
        "consequence.")


@pytest.mark.xfail(strict=True, reason=(
    "MP5's numpy fill is a strict SUBSET of the Qt rasterizer's water and "
    "misses 11.5% of the pixels Qt renders as solid water. Measured, not "
    "assumed -- see the docstring. Open question for the brief; strict so "
    "this fails loudly the moment the numbers move in either direction."))
@pytest.mark.parametrize("scene", ["raleigh"])
def test_numpy_fill_covers_the_qt_rasterizers_solid_water(bench, qapp, scene):
    """The half of MP5's DoD that does not hold today, recorded as a
    measurement rather than absorbed into a tolerance.

    Raleigh, 40 NM, published pack (water-na, 2026q2r6), 1024x1024
    window, both paths decoding an identical 574 polygons / 29,285
    vertices:

      ===========================================  ==============
      numpy-only water (px Qt calls solid land)            10 px
      Qt-only water (px numpy leaves dry)               6,698 px
      ...of which isolated single-pixel specks          1,059 px
      Qt solid water (coverage >= 0.9)                  9,764 px
      ...missed entirely by the numpy fill              1,124 px
      total coverage area, numpy vs Qt            10,731 / 12,423
      ===========================================  ==============

    So the numpy water is a strict subset: it never disagrees about
    WHERE water is, only about how much of the thin end of it survives.
    Part of the gap is unavoidable -- a whole-pixel scanline fill cannot
    reproduce an antialiased fringe, and the fringe here is 57% of the
    solid-water area because the scene is hundreds of small lakes. But
    **1,124 px of Qt-SOLID water going dry is not a fringe effect**, and
    that is the part this records as open.

    Why it is not fixed here and not tuned away: which of the two
    pictures is correct is a requirement question about MP5's DoD -- the
    numpy fill drops sub-pixel and hairline features that the Qt path
    renders as faint blue, and a moving map may well prefer either.
    Widening ``COVERAGE_AREA_TOLERANCE`` past 13.6% would make the row
    green while deleting the only evidence that the two pictures differ,
    which is the one thing this row exists to say.

    Raleigh only: Key West cannot carry the measurement at all
    (``_coverage_measurable``)."""
    ab = _raster_ab(bench, qapp, scene)
    fn, fq = ab["fn"], ab["fq"]
    solid_water = fq >= 0.9
    missed = int((solid_water & (fn < 0.5)).sum())
    assert missed <= 0.01 * max(1, int(solid_water.sum())), (
        f"MP5's numpy fill leaves {missed} of {int(solid_water.sum())} "
        "Qt-solid water pixels dry")
    area_n, area_q = float(fn.sum()), float(fq.sum())
    rel = abs(area_n - area_q) / max(area_n, area_q)
    assert rel <= COVERAGE_AREA_TOLERANCE, (
        f"MP5's numpy fill covers {area_n:.0f} px of water, the legacy Qt "
        f"rasterizer {area_q:.0f} px -- {rel * 100:.1f}% apart, over the "
        f"{COVERAGE_AREA_TOLERANCE * 100:.0f}% tolerance.")


def test_coverage_metric_is_not_fooled_by_antialiasing():
    """The falsifier for the oracle above, and the record of why it is
    not an IoU.

    Two synthetic renders of the SAME shape are built against a known
    background: one hard-edged (a solid 6x6 block, 36 px) and one that
    spreads the identical 36 px of coverage over a wider, partially
    covered fringe, the way an antialiased rasterizer does. Their AREAS
    are equal by construction. A hard 0.5-threshold mask nonetheless
    scores them at IoU 0.44, because it keeps only the fringe's
    fully-covered interior -- exactly the artifact a hard mask produces
    along every antialiased coastline in a real scene.

    Synthetic on purpose, and deliberately no longer resting on a scene
    number: an earlier revision of this docstring cited an exact-colour
    IoU of 0.27 against a 3.6% area agreement at Key West, and that pair
    does not reproduce against the published pack. Key West's window is
    96.9% ocean-backstop blue before the pack is read, so neither
    statistic is recoverable there at all (``_coverage_measurable``).
    The trap is real; that measurement of it was not, so it is
    demonstrated here by construction instead.

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


def test_coverage_is_blind_where_the_base_is_already_water():
    """The falsifier for ``_coverage_measurable``, and the proof that
    the skip above is a real guard rather than a comment.

    A base that is already the overlay's exact RGB is what
    ``TerrainLayer`` produces over ocean and void tiles. Paint water on
    top of it and the image does not change, so the recovered coverage
    is 0 -- **identical to the reading for "no water was drawn"**. If
    those two cases were not separated, an ocean scene would report the
    two rasterizers as agreeing perfectly while nothing had been
    compared.

    Half the frame is land and half is backstop-blue: the guard must
    call exactly the land half measurable, and the recovered coverage
    must find only the water drawn there."""
    land = np.tile(np.array([80.0, 114.0, 71.0]), (8, 8, 1))
    frame = np.concatenate([land, np.tile(_WATER_RGB, (8, 8, 1))], axis=1)

    painted = frame.copy()
    painted[:, :, :] = _WATER_RGB            # flood the WHOLE frame

    meas = _coverage_measurable(frame)
    assert meas[:, :8].all(), "land is not measurable"
    assert not meas[:, 8:].any(), (
        "pixels already painted the overlay's own colour are being "
        "treated as measurable -- the blend there is not invertible")
    assert meas.mean() == pytest.approx(0.5)

    f = _water_coverage(painted, frame)
    assert f[:, :8].sum() == pytest.approx(64.0)
    assert f[:, 8:].sum() == 0.0, (
        "coverage is being credited on pixels that could not change; "
        "an ocean scene would read as a perfect agreement")

    # And the degenerate case the Key West scene actually hits.
    all_water = np.tile(_WATER_RGB, (8, 8, 1))
    assert not _coverage_measurable(all_water).any()
    assert _water_coverage(all_water.copy(), all_water).sum() == 0.0


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
