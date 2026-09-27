#  SPDX-License-Identifier: GPL-2.0-or-later
"""MP10c reader tests (briefs/map_gesture_perf_plan.md Track 2; pyEfis #98).

Covers ``TileCache.get_mask``/``get_mosaic_mask`` (ai/svs.py), the nearest-
neighbour OR into ``TerrainLayer._sample``/``_sample_mosaic``'s water
channel, and the range/mask-presence gate on the crisp WaterDB polygon
overlay in ``_render``.

Fixtures are tiny synthetic tiles built through the REAL
``tools/build_water_masks.py`` functions (``_write_hgt`` + ``build_tile_mask``/
``build_mosaic_mask``, the same pattern ``tests/tools/test_build_water_masks.py``
uses) -- never a hand-rolled ``.wmask`` byte layout, so a packing-format
regression in the builder would break these tests too, per the issue's "wire
it rather than rewriting it" instruction for the pack self-check below.
"""
import importlib.util
import json
import math
import sqlite3
import struct
from pathlib import Path

import numpy as np
import pytest

from pyefis.instruments.ai.camera import M_PER_DEG_LAT
from pyefis.instruments.ai.svs import TileCache, load_mask
from pyefis.instruments.ai.water_db import WaterDB
from pyefis.instruments.map.layers.terrain import TerrainLayer

_ROOT = Path(__file__).resolve().parents[2]


def _load_tool(name):
    spec = importlib.util.spec_from_file_location(name, _ROOT / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bm = _load_tool("build_water_masks")


@pytest.fixture(autouse=True)
def _reset_bm_globals():
    """build_water_masks.py's module-global _CON/_HAS_RTREE/_HAS_RINGS stand
    in for a pool worker's per-process state; reset after every test."""
    yield
    if bm._CON is not None:
        bm._CON.close()
    bm._CON = None
    bm._HAS_RTREE = False
    bm._HAS_RINGS = False


def _make_water_db(path, polygons):
    """Minimal real-schema water.sqlite (matches ai/water_db.py) with an
    rtree index, so both bm.build_tile_mask and the runtime WaterDB can
    read it."""
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE water_polygons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            min_lat REAL NOT NULL, max_lat REAL NOT NULL,
            min_lon REAL NOT NULL, max_lon REAL NOT NULL,
            kind TEXT NOT NULL, elev_ft REAL,
            vertices BLOB NOT NULL, triangles BLOB, rings BLOB
        );
        CREATE VIRTUAL TABLE water_rtree USING rtree(
            id, min_lat, max_lat, min_lon, max_lon
        );
        """
    )
    for i, poly in enumerate(polygons, start=1):
        verts = poly["vertices"]
        lats = [v[0] for v in verts]
        lons = [v[1] for v in verts]
        buf = bytearray(len(verts) * 16)
        for j, (la, lo) in enumerate(verts):
            struct.pack_into("<dd", buf, j * 16, float(la), float(lo))
        con.execute(
            "INSERT INTO water_polygons (min_lat, max_lat, min_lon, max_lon, "
            "kind, elev_ft, vertices, triangles, rings) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (min(lats), max(lats), min(lons), max(lons),
             poly.get("kind", "lake"), None, bytes(buf), None, None))
        con.execute(
            "INSERT INTO water_rtree (id, min_lat, max_lat, min_lon, max_lon) "
            "VALUES (?,?,?,?,?)",
            (i, min(lats), max(lats), min(lons), max(lons)))
    con.commit()
    con.close()


def _set_bm_water(db_path):
    con = bm.open_water_db(db_path)
    has_rtree, has_rings = bm._probe_water_db(con)
    bm._CON, bm._HAS_RTREE, bm._HAS_RINGS = con, has_rtree, has_rings


def _write_hgt(path: Path, side: int, value: float = 500.0):
    path.parent.mkdir(parents=True, exist_ok=True)
    np.full((side, side), value, dtype=">i2").tofile(path)


# ---------------------------------------------------------------------------
# TileCache.get_mask / get_mosaic_mask
# ---------------------------------------------------------------------------

def test_get_mask_reads_real_builder_output(tmp_path):
    db = tmp_path / "water.sqlite"
    _make_water_db(db, [{"vertices": [
        (34.1, -119.9), (34.1, -119.1), (34.9, -119.1), (34.9, -119.9)]}])
    _set_bm_water(db)

    tile_root = tmp_path / "tiles"
    n = 21   # samples_per_deg = 20
    hgt = tile_root / ".mip" / "1" / "N34" / "N34W120.hgt"
    _write_hgt(hgt, n)
    stem, written, err = bm.build_tile_mask(hgt, force=False)
    assert err is None and written

    cache = TileCache(tile_root)
    mask = cache.get_mask(34, -120, 1)
    assert mask is not None
    assert mask.shape == (n, n)
    assert mask.dtype == bool
    assert mask.mean() > 0.3          # a real chunk of the tile is lake

    # Native (L0) tiles never carry a mask -- MP10a only builds L1..6.
    assert cache.get_mask(34, -120, 0) is None
    # No tile at all for this cell.
    assert cache.get_mask(50, 50, 1) is None

    # Cached: a second call returns the SAME array, not a re-read.
    assert cache.get_mask(34, -120, 1) is mask


def test_get_mosaic_mask_reads_real_builder_output(tmp_path):
    db = tmp_path / "water.sqlite"
    _make_water_db(db, [{"vertices": [
        (34.1, -119.9), (34.1, -119.1), (34.9, -119.1), (34.9, -119.9)]}])
    _set_bm_water(db)

    tile_root = tmp_path / "tiles"
    mdir = tile_root / ".mip" / "mosaic"
    mdir.mkdir(parents=True)
    rows, cols, spd = 21, 21, 20.0
    meta = {"rows": rows, "cols": cols, "spd": spd, "lat_n": 35.0, "lon_w": -120.0}
    jp = mdir / "L5.json"
    jp.write_text(json.dumps(meta))
    np.full((rows, cols), 500.0, dtype=">i2").tofile(mdir / "L5.hgt")

    label, written, err = bm.build_mosaic_mask(jp, force=False)
    assert err is None and written

    cache = TileCache(tile_root)
    mask = cache.get_mosaic_mask(5)
    assert mask is not None
    assert mask.shape == (rows, cols)
    assert mask.mean() > 0.3
    assert cache.get_mosaic_mask(6) is None    # no L6 built
    assert cache.get_mosaic_mask(5) is mask    # cached


def test_load_mask_handles_missing_and_corrupt_gracefully(tmp_path):
    hgt = tmp_path / "N34W120.hgt"
    _write_hgt(hgt, 21)
    assert load_mask(hgt) is None              # no .wmask sibling at all

    wmask = hgt.with_suffix(".wmask")
    wmask.write_bytes(b"\x00" * 3)             # wrong size for side=21
    assert load_mask(hgt) is None


# ---------------------------------------------------------------------------
# _sample / _sample_mosaic: nearest-neighbour OR into `water`
# ---------------------------------------------------------------------------

def test_sample_ors_mask_into_water_matches_polygon_truth(tmp_path):
    """A feature well above the mask's own node spacing should agree with
    the crisp polygon rasterization almost exactly -- the reader mechanism
    is sound; any residual gap on a REAL dense coastline at a coarse wide-
    range mip is a resolution/registration fact of that scene, not this
    mechanism (see the fixture-gated 80 NM test in
    tests/perf/test_map_pack_budgets.py for the measured real-scene number
    and its disclosed floor)."""
    db = tmp_path / "water.sqlite"
    lat_c, lon_c = 34.5, -119.5
    d = 0.3
    _make_water_db(db, [{"vertices": [
        (lat_c - d, lon_c - d), (lat_c - d, lon_c + d),
        (lat_c + d, lon_c + d), (lat_c + d, lon_c - d)]}])
    _set_bm_water(db)

    tile_root = tmp_path / "tiles"
    n = 361   # samples_per_deg = 360, ~309 m spacing -- well under the lake
    hgt = tile_root / ".mip" / "1" / "N34" / "N34W120.hgt"
    _write_hgt(hgt, n)
    bm.build_tile_mask(hgt, force=False)

    cache = TileCache(tile_root)
    water = WaterDB(str(db), max_vertices=512)
    lay = TerrainLayer()
    lay._cache = cache
    lay._water = water

    class Owner:
        pass
    lay._owner = Owner

    lat_cos = math.cos(math.radians(lat_c))
    npx = 200
    mpp = M_PER_DEG_LAT / 360.0
    idx = np.arange(npx, dtype=np.float64) - (npx - 1) / 2.0
    lats = lat_c + (-idx * mpp) / M_PER_DEG_LAT
    lons = lon_c + (idx * mpp) / (M_PER_DEG_LAT * lat_cos)

    elev_m, water_bool, mask_hit = lay._sample(lats, lons, 1)
    assert mask_hit is True

    rgbx = np.zeros((npx, npx, 4), np.uint8)
    rgbx[..., :3] = 255
    lay._draw_water_numpy(rgbx, lat_c, lon_c, mpp, npx, lat_cos, 5.0)
    poly_water = (rgbx[..., 2] > rgbx[..., 0]) & (rgbx[..., 2] > rgbx[..., 1])

    inter = int((poly_water & water_bool).sum())
    union = int((poly_water | water_bool).sum())
    iou = inter / union if union else 1.0
    assert iou >= 0.98, f"mask-vs-polygon IoU {iou:.4f} on a mask-resolvable feature"


def test_sample_mosaic_ors_mask_into_water(tmp_path):
    db = tmp_path / "water.sqlite"
    lat_c, lon_c = 34.5, -119.5
    d = 0.3
    _make_water_db(db, [{"vertices": [
        (lat_c - d, lon_c - d), (lat_c - d, lon_c + d),
        (lat_c + d, lon_c + d), (lat_c + d, lon_c - d)]}])
    _set_bm_water(db)

    tile_root = tmp_path / "tiles"
    mdir = tile_root / ".mip" / "mosaic"
    mdir.mkdir(parents=True)
    rows = cols = 361
    spd = 360.0
    meta = {"rows": rows, "cols": cols, "spd": spd, "lat_n": 35.0, "lon_w": -120.0}
    jp = mdir / "L4.json"
    jp.write_text(json.dumps(meta))
    np.full((rows, cols), 500.0, dtype=">i2").tofile(mdir / "L4.hgt")
    bm.build_mosaic_mask(jp, force=False)

    cache = TileCache(tile_root)
    water = WaterDB(str(db), max_vertices=512)
    lay = TerrainLayer()
    lay._cache = cache
    lay._water = water

    class Owner:
        pass
    lay._owner = Owner

    lat_cos = math.cos(math.radians(lat_c))
    npx = 200
    mpp = M_PER_DEG_LAT / spd
    idx = np.arange(npx, dtype=np.float64) - (npx - 1) / 2.0
    lats = lat_c + (-idx * mpp) / M_PER_DEG_LAT
    lons = lon_c + (idx * mpp) / (M_PER_DEG_LAT * lat_cos)

    elev_m, water_bool, mask_hit = lay._sample(lats, lons, 4)
    assert mask_hit is True

    rgbx = np.zeros((npx, npx, 4), np.uint8)
    rgbx[..., :3] = 255
    lay._draw_water_numpy(rgbx, lat_c, lon_c, mpp, npx, lat_cos, 5.0)
    poly_water = (rgbx[..., 2] > rgbx[..., 0]) & (rgbx[..., 2] > rgbx[..., 1])

    inter = int((poly_water & water_bool).sum())
    union = int((poly_water | water_bool).sum())
    iou = inter / union if union else 1.0
    assert iou >= 0.98, f"mosaic mask-vs-polygon IoU {iou:.4f}"


# ---------------------------------------------------------------------------
# Old pack fallback: no .wmask -> mask_hit False, water unaffected.
# ---------------------------------------------------------------------------

def test_old_pack_without_wmask_falls_back_exactly(tmp_path):
    """DoD: 'A pack with no .wmask renders exactly as before, by reader
    fallback.' -- a genuinely mask-less pack (build_water_masks.py never
    run on it), not an argument read off the branch."""
    tile_root = tmp_path / "tiles"
    hgt = tile_root / ".mip" / "1" / "N34" / "N34W120.hgt"
    _write_hgt(hgt, 21, value=500.0)     # uniform land, no .wmask sibling

    cache = TileCache(tile_root)
    assert cache.get_mask(34, -120, 1) is None

    lat_cos = math.cos(math.radians(34.5))
    npx = 50
    mpp = 100.0
    idx = np.arange(npx, dtype=np.float64) - (npx - 1) / 2.0
    lats = 34.5 + (-idx * mpp) / M_PER_DEG_LAT
    lons = -119.5 + (idx * mpp) / (M_PER_DEG_LAT * lat_cos)

    lay = TerrainLayer()
    lay._cache = cache
    elev_m, water_bool, mask_hit = lay._sample(lats, lons, 1)
    assert mask_hit is False
    assert not water_bool.any()     # 500 m land, no void, no mask: no water


# ---------------------------------------------------------------------------
# _render: the range / mask-presence gate on the polygon overlay
# ---------------------------------------------------------------------------

class _StubCache:
    """Only what _render needs when _sample itself is monkeypatched: a
    native tile for the `native` pitch estimate."""

    def get(self, la, lo):
        return np.zeros((1201, 1201), dtype=np.float32)


class _StubWaterReady:
    ready = True


def test_render_gates_polygon_draw_by_range_and_mask_presence(monkeypatch):
    """DoD: '_draw_water runs only when range_nm <= water_polygon_max_nm
    (default 20 NM) or when no mask exists at the chosen level.'"""
    state = {"mask_hit": True}

    def fake_sample(self, lats, lons, mip):
        return (np.zeros((lats.size, lons.size), np.float32),
                np.zeros((lats.size, lons.size), bool),
                state["mask_hit"])

    calls = []
    monkeypatch.setattr(TerrainLayer, "_sample", fake_sample)
    monkeypatch.setattr(TerrainLayer, "_draw_water_numpy",
                         lambda self, rgbx, lat0, lon0, mpp, n, lat_cos,
                                range_nm: calls.append(range_nm))

    lay = TerrainLayer()
    lay._cache = _StubCache()
    lay._water = _StubWaterReady()

    class Owner:
        _alt_ft = 0.0
        water_raster = "numpy"
        water_polygon_max_nm = 20.0
    lay._owner = Owner

    key = (0,)
    # Mask present, close range (<= cutover): polygons still draw.
    lay._render((key, 34.5, -119.5, 10.0, 100, 100, 50))
    assert calls == [10.0]

    # Mask present, wide range (> cutover): polygons skipped -- the mask's
    # gather (already baked into `water` by _sample) is the only source.
    calls.clear()
    lay._render((key, 34.5, -119.5, 80.0, 100, 100, 50))
    assert calls == []

    # No mask at this pack edition: polygons ALWAYS draw, any range.
    state["mask_hit"] = False
    lay._render((key, 34.5, -119.5, 80.0, 100, 100, 50))
    assert calls == [80.0]


# ---------------------------------------------------------------------------
# Pack self-check: wire tools/build_water_masks.py's check_pack, not a
# reimplementation of the .hgt/.wmask size math.
# ---------------------------------------------------------------------------

def test_pack_self_check_flags_missing_masks_and_passes_when_built(tmp_path):
    tile_root = tmp_path / "tiles"
    for name in ("N34W120", "N34W119"):
        _write_hgt(tile_root / ".mip" / "1" / "N34" / f"{name}.hgt", 21)

    problems = bm.check_pack(tile_root, [1], [])
    assert len(problems) == 2      # both tiles missing their .wmask sibling

    db = tmp_path / "water.sqlite"
    _make_water_db(db, [])
    _set_bm_water(db)
    for name in ("N34W120", "N34W119"):
        bm.build_tile_mask(tile_root / ".mip" / "1" / "N34" / f"{name}.hgt",
                            force=False)

    assert bm.check_pack(tile_root, [1], []) == []


# ---------------------------------------------------------------------------
# Schema: the new option exports through the REGISTRY (lockstep with the
# configurator twin, same convention as test_gesture_timeout_in_schema).
# ---------------------------------------------------------------------------

def test_water_polygon_max_nm_in_schema():
    from pyefis.editor import schema as sch
    opts = sch.build_schema()["instruments"]["moving_map"]["options"]
    assert "water_polygon_max_nm" in opts
    assert opts["water_polygon_max_nm"]["default"] == 20.0
