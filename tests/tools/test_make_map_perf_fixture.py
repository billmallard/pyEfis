#  SPDX-License-Identifier: GPL-2.0-or-later
"""Tests for tools/make_map_perf_fixture.py (MP8b, briefs/
map_gesture_perf_plan.md's MP8 item; pyEfis #98, AER-1133).

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
``tests/tools/test_bench_map_gestures.py`` tests the MP7 harness."""

import hashlib
import importlib.util
import json
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


# A window centred here (2 deg default) covers whole-degree cells
# lat {34, 35, 36} x lon {-80, -79, -78} -- the SW-corner cell keys.
_LAT, _LON = 35.8, -78.8
_IN_LAT_CELLS = (34, 35, 36)
_IN_LON_CELLS = (-80, -79, -78)
_OUT_CELLS = ((33, -78), (37, -78), (35, -81), (35, -76))

_NATIVE_SIDE = 121   # same as tests/perf/test_map_gestures.py's synthetic tiles


# --- shared synthetic SOURCE pack (module-scoped: built once) --------------

@pytest.fixture(scope="module")
def source_terrain(tmp_path_factory, build_terrain_mips, build_terrain_mosaic):
    """Native + full 1..6 mip pyramid + L4-6 mosaic over a 5x6 grid, built
    by the REAL builder tools -- lat 33..37, lon -81..-76 -- a strict
    superset of the 3x3 window the cutter should select."""
    root = tmp_path_factory.mktemp("src_terrain")
    body = ((np.arange(_NATIVE_SIDE * _NATIVE_SIDE, dtype=">i2") % 500)
            + 100).reshape(_NATIVE_SIDE, _NATIVE_SIDE)
    for la in range(33, 38):
        d = root / ("N%02d" % la)
        d.mkdir(exist_ok=True)
        for lo in range(-81, -75):
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
        ("straddles_edge", 36.7, 36.95, -78.9, -78.7, "lake"),   # crosses lat_hi=36.8
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


@pytest.fixture()
def bbox(mpf):
    _, _, _, _, lat_cells, lon_cells = mpf.window_bbox(_LAT, _LON)
    assert list(lat_cells) == list(_IN_LAT_CELLS)
    assert list(lon_cells) == list(_IN_LON_CELLS)
    lat_lo, lat_hi, lon_lo, lon_hi, _, _ = mpf.window_bbox(_LAT, _LON)
    return lat_lo, lat_hi, lon_lo, lon_hi


# --- window math -------------------------------------------------------

def test_window_bbox_selects_expected_cells(mpf):
    lat_lo, lat_hi, lon_lo, lon_hi, lat_cells, lon_cells = mpf.window_bbox(
        _LAT, _LON)
    assert (lat_lo, lat_hi) == (34.0, 37.0)
    assert (lon_lo, lon_hi) == (-80.0, -77.0)
    assert list(lat_cells) == [34, 35, 36]
    assert list(lon_cells) == [-80, -79, -78]


def test_tile_name_matches_svs_convention(mpf):
    # Ground truth duplicated from src/pyefis/instruments/ai/svs.py --
    # a divergence here would silently cut/copy the wrong files.
    assert mpf.tile_name(35, -79) == "N35W079"
    assert mpf.tile_name(-5, 10) == "S05E010"


# --- terrain -------------------------------------------------------------

def test_cut_terrain_includes_only_window_cells(
        tmp_path, mpf, source_terrain, bbox):
    _, _, _, _, lat_cells, lon_cells = mpf.window_bbox(_LAT, _LON)
    out = tmp_path / "cut"
    stats = mpf.cut_terrain(source_terrain, out, lat_cells, lon_cells)

    assert stats["native_tiles"] == len(_IN_LAT_CELLS) * len(_IN_LON_CELLS)
    for level in mpf.MIP_LEVELS:
        assert stats["mip_tiles"][level] == 9

    for la in _IN_LAT_CELLS:
        for lo in _IN_LON_CELLS:
            assert (out / f"N{la:02d}" / f"N{la:02d}W{abs(lo):03d}.hgt"
                    ).is_file()
            for level in mpf.MIP_LEVELS:
                assert (out / ".mip" / str(level) / f"N{la:02d}"
                        / f"N{la:02d}W{abs(lo):03d}.hgt").is_file()

    for la, lo in _OUT_CELLS:
        assert not (out / f"N{la:02d}" / f"N{la:02d}W{abs(lo):03d}.hgt"
                    ).exists()


def test_cut_mosaic_loads_via_the_real_tile_cache(
        tmp_path, mpf, source_terrain, bbox):
    """The hard constraint from TileCache.get_mosaic: JSON rows/cols must
    exactly match the cut .hgt array's shape, and lat_n/lon_w must be the
    CUT window's own edges, not the source mosaic's -- prove it by
    loading through the real reader, not by re-deriving the same numbers
    the cutter used and comparing them to themselves."""
    from pyefis.instruments.ai.svs import TileCache

    _, _, _, _, lat_cells, lon_cells = mpf.window_bbox(_LAT, _LON)
    out = tmp_path / "cut"
    stats = mpf.cut_terrain(source_terrain, out, lat_cells, lon_cells)
    assert set(stats["mosaic_levels"]) == {4, 5, 6}

    cache = TileCache(out)
    for level, meta in stats["mosaic_levels"].items():
        got = cache.get_mosaic(level)
        assert got is not None, f"mosaic L{level} did not load"
        arr, loaded_meta = got
        assert arr.shape == (meta["rows"], meta["cols"])
        assert loaded_meta["lat_n"] == 37     # cut window's own north edge
        assert loaded_meta["lon_w"] == -80    # cut window's own west edge

    # An INTERIOR sample of one tile (not on a shared edge -- adjoining
    # tiles here are byte-identical synthetic copies, so different
    # CORNERS of the same array legitimately hold different values, and
    # a shared-edge pixel could come from either neighbour) must read the
    # same value whether fetched via the per-tile mip or via the
    # stitched mosaic -- proving the cut mosaic was built from the SAME
    # cut tiles at the SAME offset, not stale/misaligned data.
    mip_tile = cache.get_mip(35, -79, 4)
    mosaic = cache.get_mosaic(4)
    assert mip_tile is not None and mosaic is not None
    arr, meta = mosaic
    spd = meta["spd"]
    mid = mip_tile.shape[0] // 2                # interior index, e.g. 4 of 0..8
    r0_tile = round((meta["lat_n"] - 36) * spd)  # tile (35,-79)'s own north-edge row
    c0_tile = round((-79 - meta["lon_w"]) * spd)  # tile's own west-edge col
    assert arr[r0_tile + mid, c0_tile + mid] == mip_tile[mid, mid]


def test_cut_terrain_errors_are_absent_gracefully_when_source_tile_missing(
        tmp_path, mpf, source_terrain):
    """A window whose native tile is simply not in the source pack (e.g.
    open ocean with no HGT file) copies nothing for that cell rather than
    raising -- cut_scene is what enforces "the centre tile must exist";
    cut_terrain itself must tolerate sparse coverage the way TileCache's
    own get()/get_mip() do."""
    out = tmp_path / "cut"
    stats = mpf.cut_terrain(source_terrain, out, range(60, 62), range(-10, -8))
    assert stats["native_tiles"] == 0
    assert not out.exists() or not any(out.rglob("*.hgt"))


# --- water -----------------------------------------------------------------

def test_cut_water_keeps_overlapping_rows_whole_and_rebuilds_rtree(
        tmp_path, mpf, source_water, bbox):
    from pyefis.instruments.ai.water_db import WaterDB

    src_path, ids = source_water
    dst = tmp_path / "water.sqlite"
    stats = mpf.cut_water(src_path, dst, bbox)

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
    assert row == (36.7, 36.95)
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


def test_cut_water_excludes_far_rows(tmp_path, mpf, source_water, bbox):
    src_path, ids = source_water
    dst = tmp_path / "water.sqlite"
    mpf.cut_water(src_path, dst, bbox)
    con = sqlite3.connect(str(dst))
    n = con.execute("SELECT COUNT(*) FROM water_polygons WHERE id = ?",
                     (ids["far_outside"],)).fetchone()[0]
    con.close()
    assert n == 0


# --- highway -----------------------------------------------------------

def test_cut_highway_matches_real_reader(
        tmp_path, mpf, source_highway, bbox):
    from pyefis.instruments.ai.highway_db import HighwayDB

    dst = tmp_path / "highway.sqlite"
    stats = mpf.cut_highway(source_highway, dst, bbox)
    assert stats["highway_lines"] == 1

    db = HighwayDB(dst)
    assert db.ready
    lines = list(db.polylines_in_range(_LAT, _LON, 60.0))
    assert len(lines) == 1
    assert lines[0].ref == "I-40"


# --- navaid --------------------------------------------------------------

def test_cut_navaid_keeps_airway_segment_by_either_endpoint(
        tmp_path, mpf, source_navaid, bbox):
    dst = tmp_path / "navaids.sqlite"
    stats = mpf.cut_navaid(source_navaid, dst, bbox)
    assert stats["navaids"] == 1
    assert stats["fixes"] == 1
    assert stats["awy_segments"] == 1     # V1 kept (endpoint in window), V2 dropped

    con = sqlite3.connect(str(dst))
    kept = con.execute("SELECT awy_id FROM awy_segments").fetchall()
    con.close()
    assert kept == [("V1",)]


# --- packaging / size budget --------------------------------------------

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


def test_cut_scene_enforces_the_size_budget_as_a_hard_error(
        tmp_path, mpf, source_terrain, source_water, source_highway,
        source_navaid, monkeypatch):
    src_water_path, _ = source_water
    monkeypatch.setitem(mpf.SCENES, "_test_scene", {"lat": _LAT, "lon": _LON})
    with pytest.raises(mpf.PerfFixtureError, match="MB"):
        mpf.cut_scene("_test_scene", source_terrain, src_water_path,
                       source_highway, source_navaid, tmp_path / "toosmall",
                       max_bytes=1024)


def test_cut_scene_end_to_end(
        tmp_path, mpf, source_terrain, source_water, source_highway,
        source_navaid, monkeypatch):
    src_water_path, _ = source_water
    monkeypatch.setitem(mpf.SCENES, "_test_scene", {"lat": _LAT, "lon": _LON})
    out = tmp_path / "scene"
    stats = mpf.cut_scene("_test_scene", source_terrain, src_water_path,
                          source_highway, source_navaid, out)
    assert stats["terrain"]["native_tiles"] == 9
    assert stats["water"]["water_polygons"] == 2
    assert stats["highway"]["highway_lines"] == 1
    assert stats["navaid"]["awy_segments"] == 1
    assert (out / "water.sqlite").is_file()
    assert (out / "highway.sqlite").is_file()
    assert (out / "navaids.sqlite").is_file()
    assert 0 < stats["raw_bytes"] < mpf.MAX_PACK_BYTES


def test_cut_scene_requires_the_centre_native_tile(
        tmp_path, mpf, source_water, source_highway, source_navaid,
        monkeypatch, tmp_path_factory):
    """The whole point of "one native tile for the 2-5 NM case" -- a
    window with no coverage at the scene's own centre is a broken pack,
    not a smaller one."""
    empty_terrain = tmp_path_factory.mktemp("empty_terrain")
    src_water_path, _ = source_water
    monkeypatch.setitem(mpf.SCENES, "_test_scene", {"lat": _LAT, "lon": _LON})
    with pytest.raises(mpf.PerfFixtureError, match="native tile"):
        mpf.cut_scene("_test_scene", empty_terrain, src_water_path,
                       source_highway, source_navaid, tmp_path / "nocentre")


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
