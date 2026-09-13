#  SPDX-License-Identifier: GPL-2.0-or-later
"""Tests for tools/make_map_perf_fixture.py (MP8b, briefs/
map_gesture_perf_plan.md's MP8 item; pyEfis #98, AER-1133; reworked per
AER-1140's ruling, AER-1142).

Builds tiny SOURCE packs with the exact real on-disk schemas (native +
mip HGT tiles via the real ``build_terrain_mips``/``build_terrain_mosaic``
builders, ``water.sqlite``/``highway.sqlite`` via the real builders'
``SCHEMA`` constants, a navaid db mirroring ``build_navaid_db.py``'s
inline schema) spanning a grid wider than the cut window, then asserts
the cutter both (a) excludes geometry outside the window and (b)
produces output the REAL runtime readers (``TileCache``, ``WaterDB``,
``HighwayDB``) accept and return correct rows from -- not just files
that look right by inspection. This is deliberately not
``tests/perf/`` (MP8a's file surface; QA's, per AER-1133's "not yours")
-- it tests the cutter tool itself, the same way
``tests/tools/test_bench_map_gestures.py`` tests the MP7 harness.

AER-1140's ruling found the ORIGINAL cutter unpublishable: a uniform
3x3-degree native-tile grid busts the size cap on its own, and that same
window captured only 14% of Raleigh's water at 160 NM -- a volume budget
asserted against it would pass with a real rasterizer regression hiding
underneath. The tests below exercise the four-part rework: the tarball
(not raw directory) gate, the concentric per-mip-level cut, the
per-layer derived footprints, and (the anti-vacuity test) a check that
demonstrably fails against the OLD ``WINDOW_DEG = 2.0`` behaviour and
passes against the new derivation."""

import hashlib
import importlib.util
import json
import math
import os
import sqlite3
import struct
from pathlib import Path

import numpy as np
import pytest

_ROOT = Path(__file__).resolve().parents[2]


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, _ROOT / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def mpf():
    return _load("make_map_perf_fixture")


@pytest.fixture(scope="module")
def build_terrain_mips():
    return _load("build_terrain_mips")


@pytest.fixture(scope="module")
def build_terrain_mosaic():
    return _load("build_terrain_mosaic")


_LAT, _LON = 35.8, -78.8   # the Raleigh scene

#: A fixed literal bbox used by the water/highway/navaid CUT-MECHANICS
#: tests below (row inclusion/exclusion, rtree rebuild, whole-row-kept
#: semantics) -- those tests are about the SQL predicate shape, not about
#: how a real footprint is derived, so a plain literal is the right tool
#: here (the derivation itself gets its own tests further down).
_TEST_BBOX = (34.0, 37.0, -80.0, -77.0)

#: Deliberately NOT tests/perf/test_map_gestures.py's 121-sample tile:
#: at that pitch the native/level-0 band is so coarse relative to a
#: whole-degree cell that EVERY mip level saturates to the same
#: ladder-top-clamped footprint, and there is nothing left for
#: "each level cuts its own band" to demonstrate. 361 keeps levels 0/1
#: meaningfully distinct while staying fast to build (~1 s for the grid
#: below) -- this value is a test-speed/differentiation trade-off, not a
#: stand-in for the real GLO-30 side (3601), which the geometry tests
#: further down use directly via ``_native_m_for_side(3601)``. At this
#: coarser-than-real pitch the derived native-footprint (band radius +
#: pan-excursion margin) needs more than MAX_NATIVE_CELLS whole-degree
#: cells -- see the ``generous_native_cap`` fixture below, which is
#: exactly that trade-off made explicit rather than silently bypassed.
_NATIVE_SIDE = 361


def _native_m_for_side(side):
    return 111139.0 / (side - 1)


#: The synthetic terrain grid's own extent -- sized to fully contain the
#: Raleigh scene's level-0/1 concentric bands (and the pan-excursion-
#: expanded native footprint) at ``_NATIVE_SIDE``'s native pitch
#: (verified once, empirically, when this fixture was authored;
#: ``test_cut_terrain_mip_levels_use_their_own_band`` re-checks it
#: against the live derivation on every run rather than trusting this
#: comment to stay true).
_TERRAIN_GRID_LAT = range(33, 38)     # 33..37
_TERRAIN_GRID_LON = range(-82, -76)   # -82..-77


@pytest.fixture()
def generous_native_cap(mpf, monkeypatch):
    """MAX_NATIVE_CELLS (4) is tuned to the REAL GLO-30 native pitch
    (30.87 m/sample) -- ``test_native_footprint_raises_past_the_cell_cap``
    exercises it at that exact scale. The synthetic ``_NATIVE_SIDE``
    tile is deliberately far coarser (module comment above), which
    inflates the derived native/pan-margin radii proportionally; tests
    that cut a FULL synthetic pack raise this cap rather than pretend
    the synthetic scale is production scale."""
    monkeypatch.setattr(mpf, "MAX_NATIVE_CELLS", 64)


# --- shared synthetic SOURCE pack (module-scoped: built once) --------------

@pytest.fixture(scope="module")
def source_terrain(tmp_path_factory, build_terrain_mips, build_terrain_mosaic):
    """Native + full 1..6 mip pyramid + L4-6 mosaic over the
    ``_TERRAIN_GRID_LAT``/``_TERRAIN_GRID_LON`` grid, built by the REAL
    builder tools. Comfortably covers the Raleigh scene's concentric mip
    bands through level 2 at this fixture's synthetic native pitch (the
    levels this test module asserts precisely); levels 3-6 saturate to
    the range-ladder-top-clamped band at this pitch and happen to be a
    SUPERSET of this grid, so cutting them copies the whole grid (still
    exercised by the mosaic test), not a clipped subset of it."""
    root = tmp_path_factory.mktemp("src_terrain")
    body = ((np.arange(_NATIVE_SIDE * _NATIVE_SIDE, dtype=">i2") % 500)
            + 100).reshape(_NATIVE_SIDE, _NATIVE_SIDE)
    for la in _TERRAIN_GRID_LAT:
        d = root / ("N%02d" % la)
        d.mkdir(exist_ok=True)
        for lo in _TERRAIN_GRID_LON:
            body.tofile(d / ("N%02dW%03d.hgt" % (la, abs(lo))))
    build_terrain_mips.main([str(root), "--jobs", "1"])
    build_terrain_mosaic.main([str(root), "--levels", "4", "5", "6"])
    return root


@pytest.fixture(scope="module")
def source_water(tmp_path_factory, mpf):
    from pyefis.instruments.ai.water_db import encode_vertices
    path = tmp_path_factory.mktemp("src_water") / "water.sqlite"
    con = sqlite3.connect(str(path))
    con.executescript(mpf.WATER_SCHEMA)
    rows = [
        # (label, min_lat, max_lat, min_lon, max_lon, kind)
        ("inside", 35.7, 35.9, -78.9, -78.7, "lake"),
        ("straddles_edge", 36.9, 37.3, -78.9, -78.7, "lake"),   # crosses _TEST_BBOX's lat_hi=37.0
        ("far_outside", 20.0, 20.1, -78.9, -78.7, "ocean"),
    ]
    ids = {}
    for label, min_lat, max_lat, min_lon, max_lon, kind in rows:
        verts = [(min_lat, min_lon), (min_lat, max_lon),
                 (max_lat, max_lon), (max_lat, min_lon)]
        cur = con.execute(
            "INSERT INTO water_polygons "
            "(min_lat, max_lat, min_lon, max_lon, kind, elev_ft, vertices) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (min_lat, max_lat, min_lon, max_lon, kind, 100.0,
             encode_vertices(verts)))
        ids[label] = cur.lastrowid
    con.execute(
        "INSERT INTO water_rtree SELECT id, min_lat, max_lat, min_lon, "
        "max_lon FROM water_polygons")
    # One waterway line inside, one far outside.
    from pyefis.instruments.ai.highway_db import encode_vertices as enc4
    for label, verts in (
            ("inside", [(35.75, -78.85), (35.85, -78.75)]),
            ("far_outside", [(1.0, 1.0), (1.1, 1.1)])):
        lats = [v[0] for v in verts]
        lons = [v[1] for v in verts]
        con.execute(
            "INSERT INTO waterway_lines "
            "(fclass, min_lat, max_lat, min_lon, max_lon, verts) "
            "VALUES ('stream', ?, ?, ?, ?, ?)",
            (min(lats), max(lats), min(lons), max(lons), enc4(verts)))
    con.execute(
        "INSERT INTO waterway_rtree SELECT id, min_lat, max_lat, min_lon, "
        "max_lon FROM waterway_lines")
    con.commit()
    con.close()
    return path, ids


@pytest.fixture(scope="module")
def source_highway(tmp_path_factory, mpf):
    from pyefis.instruments.ai.highway_db import encode_vertices
    path = tmp_path_factory.mktemp("src_highway") / "highway.sqlite"
    con = sqlite3.connect(str(path))
    con.executescript(mpf.HIGHWAY_SCHEMA)
    rows = [
        ("inside", [(35.75, -78.85), (35.85, -78.75)], "motorway", 0, "I-40"),
        ("far_outside", [(1.0, 1.0), (1.1, 1.1)], "motorway", 0, None),
    ]
    for _label, verts, fclass, flags, ref in rows:
        lats = [v[0] for v in verts]
        lons = [v[1] for v in verts]
        con.execute(
            "INSERT INTO highway_lines "
            "(fclass, min_lat, max_lat, min_lon, max_lon, verts, flags, ref) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (fclass, min(lats), max(lats), min(lons), max(lons),
             encode_vertices(verts), flags, ref))
    con.execute(
        "INSERT INTO highway_rtree SELECT id, min_lat, max_lat, min_lon, "
        "max_lon FROM highway_lines")
    con.commit()
    con.close()
    return path


@pytest.fixture(scope="module")
def source_navaid(tmp_path_factory, mpf):
    path = tmp_path_factory.mktemp("src_navaid") / "navaids.sqlite"
    con = sqlite3.connect(str(path))
    con.executescript(mpf.NAVAID_SCHEMA)
    con.execute("INSERT INTO navaids VALUES ('RDU','VOR','RDU','113.3',"
                "500.0,35.8,-78.8)")
    con.execute("INSERT INTO navaids VALUES ('FAR','VOR','FAR','999.9',"
                "0.0,1.0,1.0)")
    con.execute("INSERT INTO fixes VALUES ('FIXIN','RW',35.82,-78.82)")
    con.execute("INSERT INTO fixes VALUES ('FIXOUT','RW',1.0,1.0)")
    # One endpoint inside the window, the other far outside -- must
    # survive the cut (AirwaysLayer's own OR-of-endpoints query).
    con.execute("INSERT INTO awy_segments VALUES "
                "('V1', 1, 'RDU', 35.8, -78.8, 'FAR', 1.0, 1.0)")
    # Neither endpoint inside -- must NOT survive.
    con.execute("INSERT INTO awy_segments VALUES "
                "('V2', 1, 'X', 2.0, 2.0, 'Y', 3.0, 3.0)")
    con.executescript(mpf.NAVAID_INDEXES)
    con.commit()
    con.close()
    return path


# --- tile naming -----------------------------------------------------------

def test_tile_name_matches_svs_convention(mpf):
    # Ground truth duplicated from src/pyefis/instruments/ai/svs.py --
    # a divergence here would silently cut/copy the wrong files.
    assert mpf.tile_name(35, -79) == "N35W079"
    assert mpf.tile_name(-5, 10) == "S05E010"


# --- geometry derivation (change 2/3: derive, don't transcribe) -----------

def test_terrain_render_geometry_mpp_is_linear_in_range(mpf):
    """terrain.py's own window sizing (half_diag_m, mpp) is linear in
    range_nm for a fixed widget geometry -- AER-1140's ruling leans on
    this to justify a closed per-level band. Confirmed here against the
    ACTUAL geometry function (not re-derived algebra), so a change to the
    1.25 oversize factor or the perf widget's own w/h/anchor would show
    up as a test failure, not a silent drift."""
    _, mpp10, _ = mpf._terrain_render_geometry(10.0)
    _, mpp20, _ = mpf._terrain_render_geometry(20.0)
    assert mpp20 == pytest.approx(2 * mpp10, rel=1e-9)


def test_mip_for_range_is_monotonic_nondecreasing(mpf):
    native_m = _native_m_for_side(3601)
    ranges = [0.5, 1, 2, 5, 10, 20, 40, 80, 160, 400]
    levels = [mpf._mip_for_range(r, native_m) for r in ranges]
    assert levels == sorted(levels)
    assert levels[0] == 0
    assert levels[-1] == 6


def test_band_top_nm_is_the_selector_boundary(mpf):
    """The band top for level L is the largest range at which the SAME
    selector terrain.py calls still returns L -- confirmed by calling
    _mip_for_range on either side of the computed boundary, not by
    checking the boundary against a hand-computed number."""
    native_m = _native_m_for_side(3601)
    for level in range(6):   # level 6 is clamped to the ladder top, exempt
        top = mpf._band_top_nm(level, native_m)
        assert mpf._mip_for_range(top, native_m) == level
        assert mpf._mip_for_range(top * 1.05, native_m) > level


def test_band_top_nm_level_6_clamps_to_the_range_ladder_top(mpf):
    native_m = _native_m_for_side(3601)
    assert mpf._band_top_nm(6, native_m) == mpf.RANGE_LADDER_TOP_NM


def test_terrain_level_bands_radius_grows_with_level(mpf):
    native_m = _native_m_for_side(3601)
    bands = mpf.terrain_level_bands(_LAT, _LON, native_m)
    radii = [bands[lvl]["radius_nm"] for lvl in range(7)]
    assert radii == sorted(radii)
    assert radii[0] < 10.0          # native: a couple NM, not a country
    assert radii[-1] == pytest.approx(  # level 6 reaches the ladder top
        mpf._half_diag_nm(mpf.RANGE_LADDER_TOP_NM), rel=1e-9)


def test_navaid_bbox_deg_matches_the_layer_constants(mpf):
    """Recomputes navaids.py _DbLayer._bbox's own formula independently
    (not by calling the cutter's helper against itself) as a pin against
    silent drift of either copy."""
    range_nm, lat = 160.0, 35.8
    d = range_nm * 2.2 / 60.0
    dl = d / max(0.2, math.cos(math.radians(lat)))
    got_d, got_dl = mpf._navaid_bbox_deg(range_nm, lat)
    assert got_d == pytest.approx(d)
    assert got_dl == pytest.approx(dl)


def test_native_footprint_raises_past_the_cell_cap(mpf, monkeypatch):
    """AER-1140's ruling: 'the cutter must fail loudly when a scene's
    excursion envelope needs more native cells than fit'. Raleigh's real
    footprint already needs more than 1 cell (its centre sits close to a
    whole-degree boundary in both axes) -- capping MAX_NATIVE_CELLS below
    that must raise, not silently ship a wider ring."""
    native_m = _native_m_for_side(3601)
    lat_cells, lon_cells = mpf.native_footprint(_LAT, _LON, native_m)
    real_n = len(list(lat_cells)) * len(list(lon_cells))
    assert real_n > 1
    monkeypatch.setattr(mpf, "MAX_NATIVE_CELLS", real_n - 1)
    with pytest.raises(mpf.PerfFixtureError, match="native"):
        mpf.native_footprint(_LAT, _LON, native_m)


# --- terrain: concentric mip cut -------------------------------------------

def test_cut_terrain_native_is_pan_margin_expanded_not_the_full_grid(
        tmp_path, mpf, source_terrain, generous_native_cap):
    native_m = _native_m_for_side(_NATIVE_SIDE)
    out = tmp_path / "cut"
    stats = mpf.cut_terrain(source_terrain, out, _LAT, _LON)

    lat_cells, lon_cells = mpf.native_footprint(_LAT, _LON, native_m)
    expected = len(list(lat_cells)) * len(list(lon_cells))
    assert stats["native_tiles"] == expected
    assert stats["per_level_cells"][0] == expected
    # Strictly smaller than level 6's THEORETICAL band (its true reach,
    # not however much of it happens to exist in this small synthetic
    # source grid) -- the native footprint tracks the SCENE's own
    # low-range band (widened only by the pan-excursion margin), not the
    # widest range any layer is asserted at (160 NM, the exact shape of
    # the old WINDOW_DEG=2.0 failure this rework replaces).
    level6_band = mpf.terrain_level_bands(_LAT, _LON, native_m, levels=(6,))[6]
    level6_cells = (len(list(level6_band["lat_cells"]))
                     * len(list(level6_band["lon_cells"])))
    assert expected < level6_cells
    for la in lat_cells:
        for lo in lon_cells:
            assert (out / f"N{la:02d}" / f"N{la:02d}W{abs(lo):03d}.hgt"
                    ).is_file()


def test_cut_terrain_mip_levels_use_their_own_band(
        tmp_path, mpf, source_terrain, generous_native_cap):
    """Change 2's whole point: level 0's OWN band (before the pan-margin
    widening ``native_footprint`` separately applies) is strictly
    narrower than level 1's -- each level cuts to its own reach, not a
    grid shared by every level. (Comparing terrain_level_bands' raw
    radii/cells directly, rather than the ACTUAL cut level-0 cell count
    from ``stats``, because level 0's cut cells are pan-margin-widened
    for a different reason and can legitimately coincide in size with a
    neighbouring level's own band -- that coincidence would make a
    stats-based comparison flaky, not the property this test exists to
    demonstrate.)"""
    native_m = _native_m_for_side(_NATIVE_SIDE)
    out = tmp_path / "cut"
    stats = mpf.cut_terrain(source_terrain, out, _LAT, _LON)
    bands = mpf.terrain_level_bands(_LAT, _LON, native_m)

    assert bands[0]["radius_nm"] < bands[1]["radius_nm"]
    expected_0 = len(list(bands[0]["lat_cells"])) * len(list(bands[0]["lon_cells"]))
    expected_1 = (len(list(bands[1]["lat_cells"]))
                  * len(list(bands[1]["lon_cells"])))
    assert expected_0 < expected_1
    assert stats["mip_tiles"][1] == expected_1

    # Level 1's footprint must actually be present on disk at the cells
    # the band says, not merely counted right.
    for la in bands[1]["lat_cells"]:
        for lo in bands[1]["lon_cells"]:
            assert (out / ".mip" / "1" / f"N{la:02d}"
                    / f"N{la:02d}W{abs(lo):03d}.hgt").is_file()


def test_cut_mosaic_loads_via_the_real_tile_cache(
        tmp_path, mpf, source_terrain, generous_native_cap):
    """The hard constraint from TileCache.get_mosaic: JSON rows/cols must
    exactly match the cut .hgt array's shape, and lat_n/lon_w must be the
    CUT window's own edges -- proven by loading through the real reader.

    Level 4 is used (a ``MOSAIC_LEVELS`` member) even though its own
    derived band at this fixture's synthetic native pitch reaches WELL
    past the synthetic source grid (bands 3-6 all saturate to the same
    range-ladder-top-clamped footprint at this pitch) -- because the
    grid is a strict SUBSET of that band, every grid tile is still
    copied for level 4 (nothing is clipped), so the resulting mosaic's
    bounds are exactly the grid's own extent, not a function of the
    wider band. That is asserted against ``_TERRAIN_GRID_LAT``/``_LON``
    directly (the fixture's own known extent), not against
    ``terrain_level_bands`` (whose level-4 answer is wider than what
    actually landed on disk here)."""
    from pyefis.instruments.ai.svs import TileCache

    out = tmp_path / "cut"
    stats = mpf.cut_terrain(source_terrain, out, _LAT, _LON)
    assert 4 in stats["mosaic_levels"]

    lat_cells = list(_TERRAIN_GRID_LAT)
    lon_cells = list(_TERRAIN_GRID_LON)
    expected_lat_n = max(lat_cells) + 1
    expected_lon_w = min(lon_cells)

    cache = TileCache(out)
    meta = stats["mosaic_levels"][4]
    got = cache.get_mosaic(4)
    assert got is not None, "mosaic L4 did not load"
    arr, loaded_meta = got
    assert arr.shape == (meta["rows"], meta["cols"])
    assert loaded_meta["lat_n"] == expected_lat_n
    assert loaded_meta["lon_w"] == expected_lon_w

    # An INTERIOR sample of one tile (not on a shared edge) must read the
    # same value whether fetched via the per-tile mip or via the stitched
    # mosaic -- proving the cut mosaic was built from the SAME cut tiles
    # at the SAME offset, not stale/misaligned data.
    mid_la, mid_lo = lat_cells[len(lat_cells) // 2], lon_cells[len(lon_cells) // 2]
    mip_tile = cache.get_mip(mid_la, mid_lo, 4)
    assert mip_tile is not None
    spd = meta["spd"]
    mid = mip_tile.shape[0] // 2
    r0_tile = round((meta["lat_n"] - (mid_la + 1)) * spd)
    c0_tile = round((mid_lo - meta["lon_w"]) * spd)
    assert arr[r0_tile + mid, c0_tile + mid] == mip_tile[mid, mid]


def test_cut_terrain_requires_the_centre_native_tile(tmp_path, mpf,
                                                      tmp_path_factory):
    """The whole point of "one native tile for the low-range case" -- a
    window with no coverage at the scene's own centre is a broken pack,
    not a smaller one. This check now lives IN cut_terrain (it needs the
    centre tile to derive `native` before it can compute any band), not
    bolted on afterwards in cut_scene."""
    empty_terrain = tmp_path_factory.mktemp("empty_terrain")
    with pytest.raises(mpf.PerfFixtureError, match="native tile"):
        mpf.cut_terrain(empty_terrain, tmp_path / "nocentre", _LAT, _LON)


# --- water -----------------------------------------------------------------

def test_cut_water_keeps_overlapping_rows_whole_and_rebuilds_rtree(
        tmp_path, mpf, source_water):
    from pyefis.instruments.ai.water_db import WaterDB

    src_path, ids = source_water
    dst = tmp_path / "water.sqlite"
    stats = mpf.cut_water(src_path, dst, _TEST_BBOX)

    assert stats["water_polygons"] == 2      # inside + straddles_edge
    assert stats["waterway_lines"] == 1      # inside only

    con = sqlite3.connect(str(dst))
    kept_ids = {r[0] for r in con.execute("SELECT id FROM water_polygons")}
    assert kept_ids == {ids["inside"], ids["straddles_edge"]}
    # The straddling row must be kept WHOLE (its stored bbox unchanged),
    # not clipped to the window.
    row = con.execute(
        "SELECT min_lat, max_lat FROM water_polygons WHERE id = ?",
        (ids["straddles_edge"],)).fetchone()
    assert row == (36.9, 37.3)
    rtree_ids = {r[0] for r in con.execute("SELECT id FROM water_rtree")}
    assert rtree_ids == kept_ids
    con.close()

    # Prove it via the REAL reader too: rtree probed and used, and the
    # inside polygon comes back querying the scene centre.
    db = WaterDB(dst)
    assert db.ready
    assert db._has_rtree
    got = {p.id for p in db.polygons_in_range(_LAT, _LON, 60.0)}
    assert ids["inside"] in got


def test_cut_water_excludes_far_rows(tmp_path, mpf, source_water):
    src_path, ids = source_water
    dst = tmp_path / "water.sqlite"
    mpf.cut_water(src_path, dst, _TEST_BBOX)
    con = sqlite3.connect(str(dst))
    n = con.execute("SELECT COUNT(*) FROM water_polygons WHERE id = ?",
                     (ids["far_outside"],)).fetchone()[0]
    con.close()
    assert n == 0


# --- highway -----------------------------------------------------------

def test_cut_highway_matches_real_reader(tmp_path, mpf, source_highway):
    from pyefis.instruments.ai.highway_db import HighwayDB

    dst = tmp_path / "highway.sqlite"
    stats = mpf.cut_highway(source_highway, dst, _TEST_BBOX)
    assert stats["highway_lines"] == 1

    db = HighwayDB(dst)
    assert db.ready
    lines = list(db.polylines_in_range(_LAT, _LON, 60.0))
    assert len(lines) == 1
    assert lines[0].ref == "I-40"


# --- navaid --------------------------------------------------------------

def test_cut_navaid_keeps_airway_segment_by_either_endpoint(
        tmp_path, mpf, source_navaid):
    dst = tmp_path / "navaids.sqlite"
    stats = mpf.cut_navaid(source_navaid, dst, _TEST_BBOX)
    assert stats["navaids"] == 1
    assert stats["fixes"] == 1
    assert stats["awy_segments"] == 1     # V1 kept (endpoint in window), V2 dropped

    con = sqlite3.connect(str(dst))
    kept = con.execute("SELECT awy_id FROM awy_segments").fetchall()
    con.close()
    assert kept == [("V1",)]


# --- packaging / size budget (change 1: gate the tarball) -----------------

def test_package_is_deterministic_and_sha256_matches_contents(tmp_path, mpf):
    src = tmp_path / "pack"
    src.mkdir()
    (src / "a.txt").write_text("hello")
    (src / "sub").mkdir()
    (src / "sub" / "b.txt").write_text("world")

    tb1 = tmp_path / "out1.tar.gz"
    tb2 = tmp_path / "out2.tar.gz"
    size1, sha1 = mpf.package(src, tb1)
    size2, sha2 = mpf.package(src, tb2)
    assert sha1 == sha2
    assert size1 == size2 == tb1.stat().st_size


def test_cut_scene_does_not_gate_on_raw_directory_size(
        tmp_path, mpf, source_terrain, source_water, source_highway,
        source_navaid, monkeypatch, generous_native_cap):
    """AER-1140's ruling: the raw directory is no longer where the gate
    lives -- cut_scene must succeed (and merely report raw_bytes as an
    advisory stat) even when that raw size would have failed the OLD
    check against MAX_PACK_BYTES."""
    src_water_path, _ = source_water
    monkeypatch.setitem(mpf.SCENES, "_test_scene", {"lat": _LAT, "lon": _LON})
    out = tmp_path / "scene"
    stats = mpf.cut_scene("_test_scene", source_terrain, src_water_path,
                          source_highway, source_navaid, out)
    assert stats["raw_bytes"] > 0   # recorded...
    # ...but cut_scene itself never raises on it, regardless of size.


def test_package_scene_enforces_the_tarball_budget_as_a_hard_error(
        tmp_path, mpf, source_terrain, source_water, source_highway,
        source_navaid, monkeypatch, generous_native_cap):
    src_water_path, _ = source_water
    monkeypatch.setitem(mpf.SCENES, "_test_scene", {"lat": _LAT, "lon": _LON})
    out = tmp_path / "scene"
    mpf.cut_scene("_test_scene", source_terrain, src_water_path,
                  source_highway, source_navaid, out)
    tarball = tmp_path / "scene.tar.gz"
    with pytest.raises(mpf.PerfFixtureError, match="MB"):
        mpf.package_scene(out, tarball, max_bytes=1024)


def test_package_scene_passes_when_under_budget(
        tmp_path, mpf, source_terrain, source_water, source_highway,
        source_navaid, monkeypatch, generous_native_cap):
    src_water_path, _ = source_water
    monkeypatch.setitem(mpf.SCENES, "_test_scene", {"lat": _LAT, "lon": _LON})
    out = tmp_path / "scene"
    mpf.cut_scene("_test_scene", source_terrain, src_water_path,
                  source_highway, source_navaid, out)
    tarball = tmp_path / "scene.tar.gz"
    size, sha256 = mpf.package_scene(out, tarball)
    assert 0 < size < mpf.MAX_PACK_BYTES
    assert len(sha256) == 64


def test_cut_scene_end_to_end(
        tmp_path, mpf, source_terrain, source_water, source_highway,
        source_navaid, monkeypatch, generous_native_cap):
    src_water_path, _ = source_water
    monkeypatch.setitem(mpf.SCENES, "_test_scene", {"lat": _LAT, "lon": _LON})
    out = tmp_path / "scene"
    stats = mpf.cut_scene("_test_scene", source_terrain, src_water_path,
                          source_highway, source_navaid, out)
    assert stats["terrain"]["native_tiles"] >= 1
    assert stats["water"]["water_polygons"] == 2
    assert stats["highway"]["highway_lines"] == 1
    assert stats["navaid"]["awy_segments"] == 1
    assert "footprints" in stats and "water_deg" in stats["footprints"]
    assert (out / "water.sqlite").is_file()
    assert (out / "highway.sqlite").is_file()
    assert (out / "navaids.sqlite").is_file()
    assert stats["raw_bytes"] > 0


def test_cut_scene_requires_the_centre_native_tile(
        tmp_path, mpf, source_water, source_highway, source_navaid,
        monkeypatch, tmp_path_factory):
    empty_terrain = tmp_path_factory.mktemp("empty_terrain")
    src_water_path, _ = source_water
    monkeypatch.setitem(mpf.SCENES, "_test_scene", {"lat": _LAT, "lon": _LON})
    with pytest.raises(mpf.PerfFixtureError, match="native tile"):
        mpf.cut_scene("_test_scene", empty_terrain, src_water_path,
                       source_highway, source_navaid, tmp_path / "nocentre")


def test_cut_scene_window_deg_override_applies_to_vector_layers_only(
        tmp_path, mpf, source_terrain, source_water, source_highway,
        source_navaid, monkeypatch, generous_native_cap):
    """The manual --window-deg escape hatch replaces the DERIVED
    water/highway/navaid footprints with one uniform window, but never
    touches the concentric terrain cut (which has no notion of a single
    window at all)."""
    src_water_path, _ = source_water
    monkeypatch.setitem(mpf.SCENES, "_test_scene", {"lat": _LAT, "lon": _LON})
    out = tmp_path / "scene"
    stats = mpf.cut_scene("_test_scene", source_terrain, src_water_path,
                          source_highway, source_navaid, out,
                          window_deg=2.0)
    assert stats["footprints"] == {"override_window_deg": 2.0}
    assert "bands" in stats["terrain"]   # terrain cut is unaffected


# --- the anti-vacuity test (change 4) --------------------------------------

def test_water_footprint_covers_the_asserted_range_not_a_stale_literal(mpf):
    """AER-1140's ruling, verbatim: 'derive the radii in code from the
    selector, do not transcribe the table -- the table is the instance,
    the selector is the rule'. QA measured the OLD ``WINDOW_DEG = 2.0``
    default captured only 14% of Raleigh's water vertices at 160 NM --
    this test plants a probe point at the true 160 NM water reach and
    demonstrates BOTH halves: the old literal window would have missed
    it (the exact silent-gate failure mode), and the new per-layer
    derivation includes it. If a future edit narrows the derivation back
    toward a fixed literal, this is the test that catches it -- not by
    pinning today's radius as a snapshot, but by checking coverage
    against the SAME range (RANGE_LADDER_TOP_NM) the volume budget
    actually asserts at."""
    lat, lon = _LAT, _LON

    # The ACTUAL cut_scene code path (AER-1143): water is no longer read
    # off terrain's own mip bands (a single-geometry derivation answering
    # a different question -- see terrain_level_bands' docstring) but
    # derived directly, widest-of-every-suite-widget, at the range the
    # volume budget is asserted at.
    water_radius_nm, _env = mpf._widest_half_diag_nm(mpf.RANGE_LADDER_TOP_NM)
    water_lat_deg, water_lon_deg = mpf._deg_radius(water_radius_nm, lat)
    lat_lo, lat_hi, lon_lo, lon_hi = mpf._bbox_from_radius(
        lat, lon, water_lat_deg, water_lon_deg)

    # A probe just inside the true 160 NM half-diagonal reach.
    probe_lat = lat + water_lat_deg * 0.98

    # New derivation: covers it.
    assert lat_lo <= probe_lat <= lat_hi

    # Old literal window: does NOT -- this is the failure QA measured.
    OLD_WINDOW_DEG = 2.0
    old_lo, old_hi = lat - OLD_WINDOW_DEG / 2.0, lat + OLD_WINDOW_DEG / 2.0
    assert not (old_lo <= probe_lat <= old_hi), (
        "the probe point should be OUTSIDE the old WINDOW_DEG=2.0 box -- "
        "if this fails, the test no longer demonstrates the regression "
        "it exists to catch")


def test_highway_footprint_covers_its_own_max_range_not_a_stale_literal(mpf):
    """Same shape as the water test, for roads.py's own hidden-above-80NM
    band -- imports the real threshold from roads.py rather than
    hardcoding 80.0, so a change to that band shows up here too."""
    from pyefis.instruments.map.layers.roads import RoadsLayer

    hidden_above_nm = RoadsLayer._BAND_BASE[-1][0]
    assert hidden_above_nm == mpf.HIGHWAY_MAX_RANGE_NM

    lat, lon = _LAT, _LON
    radius_nm, _env = mpf._widest_half_diag_nm(hidden_above_nm)
    lat_deg, lon_deg = mpf._deg_radius(radius_nm, lat)
    lat_lo, lat_hi, _, _ = mpf._bbox_from_radius(lat, lon, lat_deg, lon_deg)

    probe_lat = lat + lat_deg * 0.98
    assert lat_lo <= probe_lat <= lat_hi

    OLD_WINDOW_DEG = 2.0
    old_lo, old_hi = lat - OLD_WINDOW_DEG / 2.0, lat + OLD_WINDOW_DEG / 2.0
    assert not (old_lo <= probe_lat <= old_hi)


def test_navaid_footprint_covers_its_own_max_range_not_a_stale_literal(mpf):
    from pyefis.instruments.map.layers.navaids import NavaidsLayer

    assert NavaidsLayer._MAX_RANGE == mpf.NAVAID_MAX_RANGE_NM

    lat, lon = _LAT, _LON
    lat_deg, lon_deg = mpf._navaid_bbox_deg(NavaidsLayer._MAX_RANGE, lat)
    lat_lo, lat_hi, _, _ = mpf._bbox_from_radius(lat, lon, lat_deg, lon_deg)

    probe_lat = lat + lat_deg * 0.98
    assert lat_lo <= probe_lat <= lat_hi

    OLD_WINDOW_DEG = 2.0
    old_lo, old_hi = lat - OLD_WINDOW_DEG / 2.0, lat + OLD_WINDOW_DEG / 2.0
    assert not (old_lo <= probe_lat <= old_hi)


# --- widest-across-widget-geometries (AER-1143's amendment, change 5) -----

def test_widest_half_diag_nm_prefers_the_wider_of_the_known_widgets(mpf):
    """The 300x300 count-budget widget reads further than the 650x1040
    volume-budget widget at the SAME range (a square aspect ratio beats a
    portrait one here -- ``hypot(w,h)/cy`` is 2.83 vs 2.36), so it must be
    the one ``_widest_half_diag_nm`` returns -- pinned against the two
    single-geometry numbers directly, not against each other, so a
    regression in either underlying calc still shows up."""
    radius_nm, env = mpf._widest_half_diag_nm(mpf.RANGE_LADDER_TOP_NM)
    square = mpf._half_diag_nm(mpf.RANGE_LADDER_TOP_NM, w=300, h=300,
                               anchor_frac=0.5)
    portrait = mpf._half_diag_nm(mpf.RANGE_LADDER_TOP_NM, w=650, h=1040,
                                 anchor_frac=0.5)
    assert square > portrait
    assert radius_nm == pytest.approx(square)
    assert env == (300, 300, 0.5)


def test_widest_half_diag_nm_picks_up_a_new_wider_widget(mpf, monkeypatch):
    """The falsifier: if a THIRD, wider widget geometry is added to the
    suite's known list, the derivation must pick it up automatically --
    proving this is a live computation over the list, not a comment
    that happens to match today's two entries."""
    wider = (2000, 200, 0.5)   # a very flat/wide widget: huge hypot, tiny cy
    envelopes = mpf.PERF_WIDGET_ENVELOPES + (wider,)
    radius_nm, env = mpf._widest_half_diag_nm(mpf.RANGE_LADDER_TOP_NM,
                                              envelopes=envelopes)
    assert env == wider
    default_radius, _ = mpf._widest_half_diag_nm(mpf.RANGE_LADDER_TOP_NM)
    assert radius_nm > default_radius


def test_navaid_footprint_is_range_only_not_widget_dependent(mpf):
    """navaids.py's own ``_bbox`` never reads a widget size -- confirms
    the cutter's navaid derivation stays that way even though the water/
    highway derivations above are now widget-geometry-aware, so a future
    editor does not "fix" navaid into taking an envelopes argument it has
    no use for."""
    import inspect
    assert "envelopes" not in inspect.signature(mpf._navaid_bbox_deg).parameters


# --- footprint.json: the pack declares what it was cut to cover (AER-1143,
# change 6 / requirement 5) -------------------------------------------------

def test_footprint_manifest_records_bbox_and_envelope_per_layer(mpf):
    manifest = mpf.footprint_manifest(
        "raleigh", _LAT, _LON,
        water_bbox=(30.0, 40.0, -85.0, -75.0),
        highway_bbox=(34.0, 37.0, -80.0, -77.0),
        navaid_bbox=(33.0, 38.0, -82.0, -76.0),
        water_env=(300, 300, 0.5), highway_env=(300, 300, 0.5),
        navaid_range_nm=mpf.NAVAID_MAX_RANGE_NM)

    assert manifest["scene"] == "raleigh"
    assert manifest["lat"] == _LAT and manifest["lon"] == _LON
    assert [tuple(e) for e in manifest["considered_envelopes"]] == list(
        mpf.PERF_WIDGET_ENVELOPES)

    water = manifest["layers"]["water"]
    assert water["bbox"] == [30.0, 40.0, -85.0, -75.0]
    assert water["envelope"] == {"w": 300, "h": 300,
                                 "ownship_position_frac": 0.5,
                                 "range_nm": mpf.RANGE_LADDER_TOP_NM}

    highway = manifest["layers"]["highway"]
    assert highway["envelope"]["range_nm"] == mpf.HIGHWAY_MAX_RANGE_NM

    navaid = manifest["layers"]["navaid"]
    assert navaid["bbox"] == [33.0, 38.0, -82.0, -76.0]
    assert navaid["envelope"] == {"range_nm": mpf.NAVAID_MAX_RANGE_NM,
                                  "lat": _LAT}
    assert "w" not in navaid["envelope"]   # range/lat only -- no widget


def test_footprint_manifest_records_the_override_when_window_deg_is_set(mpf):
    manifest = mpf.footprint_manifest(
        "raleigh", _LAT, _LON,
        water_bbox=(34.0, 37.0, -80.0, -77.0),
        highway_bbox=(34.0, 37.0, -80.0, -77.0),
        navaid_bbox=(34.0, 37.0, -80.0, -77.0),
        window_deg=2.0)
    for layer in ("water", "highway", "navaid"):
        assert manifest["layers"][layer]["envelope"] == {
            "override_window_deg": 2.0}


def test_cut_scene_writes_footprint_json_matching_the_actual_cut_bboxes(
        tmp_path, mpf, source_terrain, source_water, source_highway,
        source_navaid, monkeypatch, generous_native_cap):
    """The producer side of "declare, don't re-derive": the file written
    into the pack must describe the SAME bbox the vector layers were
    actually cut to, not a recomputation that could drift from it."""
    src_water_path, _ = source_water
    monkeypatch.setitem(mpf.SCENES, "_test_scene", {"lat": _LAT, "lon": _LON})
    out = tmp_path / "scene"
    stats = mpf.cut_scene("_test_scene", source_terrain, src_water_path,
                          source_highway, source_navaid, out)

    manifest_path = out / mpf.FOOTPRINT_MANIFEST_NAME
    assert manifest_path.is_file()
    on_disk = json.loads(manifest_path.read_text())
    assert on_disk == stats["footprint_manifest"]

    water_bbox = on_disk["layers"]["water"]["bbox"]
    lat_lo, lat_hi, lon_lo, lon_hi = water_bbox
    water_radius_nm, _ = mpf._widest_half_diag_nm(mpf.RANGE_LADDER_TOP_NM)
    water_lat_deg, water_lon_deg = mpf._deg_radius(water_radius_nm, _LAT)
    assert lat_lo == pytest.approx(_LAT - water_lat_deg)
    assert lat_hi == pytest.approx(_LAT + water_lat_deg)
    assert lon_lo == pytest.approx(_LON - water_lon_deg)
    assert lon_hi == pytest.approx(_LON + water_lon_deg)

    # A "required subset-of declared" consumer check, demonstrated inline:
    # a render window narrower than the declared bbox must pass; one that
    # pokes outside it must not -- the comparison AER-1143 asks a
    # consumer test to make against this file instead of re-deriving the
    # cutter's own geometry a second time.
    def _covers(declared_bbox, required_bbox):
        d_lat_lo, d_lat_hi, d_lon_lo, d_lon_hi = declared_bbox
        r_lat_lo, r_lat_hi, r_lon_lo, r_lon_hi = required_bbox
        return (d_lat_lo <= r_lat_lo and d_lat_hi >= r_lat_hi
                and d_lon_lo <= r_lon_lo and d_lon_hi >= r_lon_hi)

    inside = (_LAT - 0.1, _LAT + 0.1, _LON - 0.1, _LON + 0.1)
    outside = (_LAT - 90.0, _LAT + 90.0, _LON - 0.1, _LON + 0.1)
    assert _covers(water_bbox, inside)
    assert not _covers(water_bbox, outside)


# --- fetch_fixture ---------------------------------------------------------

def test_fetch_fixture_skips_cleanly_without_the_env_flag(
        mpf, monkeypatch, tmp_path):
    monkeypatch.delenv("PYEFIS_PERF_FIXTURE", raising=False)
    assert mpf.fetch_fixture("raleigh", cache_dir=tmp_path) is None


def test_fetch_fixture_raises_when_flag_set_but_unpublished(
        mpf, monkeypatch, tmp_path):
    monkeypatch.setenv("PYEFIS_PERF_FIXTURE", "1")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"scenes": {
        "raleigh": {"sha256": None, "url": None}}}))
    with pytest.raises(mpf.PerfFixtureUnavailable, match="no published pin"):
        mpf.fetch_fixture("raleigh", cache_dir=tmp_path / "cache",
                          manifest_path=manifest)


def test_fetch_fixture_downloads_verifies_and_caches(
        mpf, monkeypatch, tmp_path):
    payload_dir = tmp_path / "payload"
    payload_dir.mkdir()
    (payload_dir / "water.sqlite").write_bytes(b"fake-water-bytes")
    tarball = tmp_path / "raleigh.tar.gz"
    size, sha256 = mpf.package(payload_dir, tarball)

    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"scenes": {
        "raleigh": {"sha256": sha256, "url": tarball.resolve().as_uri(),
                    "bytes": size}}}))

    monkeypatch.setenv("PYEFIS_PERF_FIXTURE", "1")
    cache_dir = tmp_path / "cache"
    calls = []
    orig_download = mpf._download
    def counting_download(url, dest):
        calls.append(url)
        return orig_download(url, dest)
    monkeypatch.setattr(mpf, "_download", counting_download)

    got = mpf.fetch_fixture("raleigh", cache_dir=cache_dir,
                            manifest_path=manifest)
    assert got == cache_dir / "raleigh"
    assert (got / "water.sqlite").read_bytes() == b"fake-water-bytes"
    assert len(calls) == 1

    # Second call hits the cache -- no re-download.
    got2 = mpf.fetch_fixture("raleigh", cache_dir=cache_dir,
                             manifest_path=manifest)
    assert got2 == got
    assert len(calls) == 1


def test_fetch_fixture_rejects_a_sha256_mismatch(mpf, monkeypatch, tmp_path):
    payload_dir = tmp_path / "payload"
    payload_dir.mkdir()
    (payload_dir / "x.txt").write_text("x")
    tarball = tmp_path / "raleigh.tar.gz"
    mpf.package(payload_dir, tarball)

    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"scenes": {
        "raleigh": {"sha256": "0" * 64,
                    "url": tarball.resolve().as_uri(), "bytes": 1}}}))
    monkeypatch.setenv("PYEFIS_PERF_FIXTURE", "1")
    with pytest.raises(mpf.PerfFixtureUnavailable, match="sha256"):
        mpf.fetch_fixture("raleigh", cache_dir=tmp_path / "cache",
                          manifest_path=manifest)


def test_checked_in_manifest_is_honestly_unpublished(mpf):
    """Pins the current state of tools/perf_fixtures.json so a future
    change to it (e.g. someone fabricating a sha256 without actually
    publishing) is a visible diff, not a silent drift."""
    manifest = mpf._load_manifest()
    for scene in mpf.SCENES:
        entry = manifest["scenes"][scene]
        assert entry["sha256"] is None
        assert entry["url"] is None
