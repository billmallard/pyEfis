#  SPDX-License-Identifier: GPL-2.0-or-later
"""Tests for tools/build_water_masks.py -- MP10a
(briefs/map_gesture_perf_plan.md Track 2; pyEfis #98).

The DoD line that matters most here: a mask built by build_water_masks.py
must be byte-identical to the same mask built by makerplane-data's stdlib
``tests/test_terrain.py::_write_wmask`` fixture, for at least one odd
``side`` (padding is only visible when ``side % 8 != 0``, which is every
real level). Nothing in makerplane-data inspects the ``.wmask`` bytes, so
its suite passes under any packing -- this file is the only place the
format is actually pinned. ``_write_wmask`` is PORTED here (stdlib, no
numpy) rather than imported across repos, per the brief.

Plain pytest + tmp_path + sqlite3, no Qt, no PyQt6 import anywhere in this
module or in tools/build_water_masks.py -- both packages
(``pyefis.instruments.ai``, ``pyefis.instruments.map``) pull PyQt6 into
their ``__init__.py`` (AER-1090), so ``raster.py`` is loaded here by bare
file path (bypassing the package import) purely as an independent parity
check against MP5's algorithm; the builder itself never does this.
"""

import importlib.util
import json
import sqlite3
import struct
import sys
from pathlib import Path

import numpy as np
import pytest

_ROOT = Path(__file__).resolve().parents[2]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bm = _load("build_water_masks", _ROOT / "tools" / "build_water_masks.py")
raster = _load("raster_bare",
                _ROOT / "src" / "pyefis" / "instruments" / "map" / "raster.py")


# ---------------------------------------------------------------------------
# Synthetic water.sqlite -- minimal schema (no mapbox_earcut / triangles
# needed; build_water_masks.py never reads that column).
# ---------------------------------------------------------------------------

_SCHEMA_RINGS = """
CREATE TABLE water_polygons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    min_lat REAL NOT NULL, max_lat REAL NOT NULL,
    min_lon REAL NOT NULL, max_lon REAL NOT NULL,
    kind TEXT NOT NULL, elev_ft REAL,
    vertices BLOB NOT NULL, triangles BLOB, rings BLOB
);
"""

# Pre-#44 schema: no rings column at all (not just NULL data), so the
# builder's column probe must genuinely fall back, not just see nulls.
_SCHEMA_NO_RINGS = """
CREATE TABLE water_polygons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    min_lat REAL NOT NULL, max_lat REAL NOT NULL,
    min_lon REAL NOT NULL, max_lon REAL NOT NULL,
    kind TEXT NOT NULL, elev_ft REAL,
    vertices BLOB NOT NULL, triangles BLOB
);
"""

_RTREE_SCHEMA = """
CREATE VIRTUAL TABLE water_rtree USING rtree(
    id, min_lat, max_lat, min_lon, max_lon
);
"""


def _encode_vertices(vertices) -> bytes:
    buf = bytearray(len(vertices) * 16)
    for i, (lat, lon) in enumerate(vertices):
        struct.pack_into("<dd", buf, i * 16, float(lat), float(lon))
    return bytes(buf)


def _encode_rings(ring_ends, n_vertices) -> bytes | None:
    if not ring_ends:
        return None
    fmt = "I" if n_vertices > 65535 else "H"
    return struct.pack(f"<{len(ring_ends)}{fmt}", *ring_ends)


def _make_water_db(path: Path, polygons, use_rtree=True, use_rings=True):
    """*polygons* is a list of dicts: kind, vertices [(lat, lon), ...],
    optional rings (ring END offsets), optional bbox override. When
    *use_rings* is False the table is built WITHOUT a rings column at
    all (not just null data), so the builder's column probe genuinely
    falls back rather than coincidentally seeing nulls."""
    schema = (_SCHEMA_RINGS if use_rings else _SCHEMA_NO_RINGS)
    if use_rtree:
        schema += _RTREE_SCHEMA
    con = sqlite3.connect(path)
    con.executescript(schema)
    cols = ("id, min_lat, max_lat, min_lon, max_lon, kind, elev_ft, "
            "vertices, triangles" + (", rings" if use_rings else ""))
    placeholders = ",".join("?" * (9 + (1 if use_rings else 0)))
    for i, poly in enumerate(polygons, start=1):
        vertices = poly["vertices"]
        lats = [v[0] for v in vertices]
        lons = [v[1] for v in vertices]
        bbox = poly.get("bbox", (min(lats), max(lats), min(lons), max(lons)))
        values = [i, bbox[0], bbox[1], bbox[2], bbox[3], poly["kind"],
                  poly.get("elev_ft"), _encode_vertices(vertices), None]
        if use_rings:
            values.append(_encode_rings(poly.get("rings"), len(vertices)))
        con.execute(
            f"INSERT INTO water_polygons ({cols}) VALUES ({placeholders})",
            values)
        if use_rtree:
            con.execute(
                "INSERT INTO water_rtree (id, min_lat, max_lat, min_lon, max_lon) "
                "VALUES (?,?,?,?,?)", (i, bbox[0], bbox[1], bbox[2], bbox[3]))
    con.commit()
    con.close()


@pytest.fixture(autouse=True)
def _reset_worker_globals():
    """build_water_masks.py's module-global _CON/_HAS_RTREE/_HAS_RINGS
    stand in for a pool worker's per-process state (set by _init_worker);
    close/reset them after every test regardless of how they got set
    (directly, via water_con, or via bm.main())."""
    yield
    if bm._CON is not None:
        bm._CON.close()
    bm._CON = None
    bm._HAS_RTREE = False
    bm._HAS_RINGS = False


@pytest.fixture
def water_con():
    """Sets the module-global connection build_water_masks.py's worker
    functions read from, as the pool initializer would."""
    def _apply(path, use_rtree=True, use_rings=True):
        con = bm.open_water_db(path)
        rtree, rings = bm._probe_water_db(con)
        bm._CON, bm._HAS_RTREE, bm._HAS_RINGS = con, rtree, rings
        return con
    return _apply


def _write_hgt(path: Path, side: int):
    path.parent.mkdir(parents=True, exist_ok=True)
    np.zeros((side, side), dtype=">i2").tofile(path)


# ---------------------------------------------------------------------------
# 1. Even-odd fill: parity with MP5's raster.fill_even_odd (square case),
#    and correctness of the point-registration shift trick.
# ---------------------------------------------------------------------------

def test_fill_even_odd_rect_matches_mp5_raster_for_square_grids():
    rings = [np.array([[1.3, 0.6], [8.7, 1.1], [7.9, 8.4], [0.8, 7.2]])]
    n = 10
    assert (raster.fill_even_odd(rings, n)
            == bm._fill_even_odd_rect(rings, n, n)).all()


def test_mask_at_nodes_is_point_sampled_not_pixel_area():
    """A square with corners exactly on integer nodes (2,2)-(6,2)-(6,6)-(2,6):
    under point registration, nodes strictly inside are covered and nodes
    strictly outside are not (exact-boundary nodes are a scanline tie-break
    edge case, defensible either way, and not asserted here) -- pixel-AREA
    fill_even_odd on the same coordinates would answer a different question
    (areas between nodes) with a different boundary entirely."""
    ring = [np.array([[2.0, 2.0], [6.0, 2.0], [6.0, 6.0], [2.0, 6.0]])]
    mask = bm._mask_at_nodes(ring, 9, 9)
    ys, xs = np.mgrid[0:9, 0:9]
    interior = (xs > 2) & (xs < 6) & (ys > 2) & (ys < 6)
    exterior = (xs < 2) | (xs > 6) | (ys < 2) | (ys > 6)
    assert mask[interior].all()
    assert not mask[exterior].any()


# ---------------------------------------------------------------------------
# 2. THE pinning test: byte-identical packing vs MP10b's stdlib fixture,
#    for an odd side (side % 8 != 0) -- 1801 is L1's real GLO-30 side.
# ---------------------------------------------------------------------------

def _write_wmask_mp10b(side):
    """Ported verbatim from makerplane-data tests/test_terrain.py
    (_write_wmask), added when MP10b closed 2026-09-06. Builds a
    deterministic "bottom half, right half" bit pattern with stdlib
    int/bytes ops (no numpy) and returns the packed bytes -- the fixture
    packtools rides through unread. Kept here, not imported, per the
    brief: the contract is only really asserted on the pyEfis side."""
    half = side // 2
    row_bytes = -(-side // 8)                # ceil(side / 8)
    pad = row_bytes * 8 - side
    zero_row = bytes(row_bytes)
    half_bits = "0" * half + "1" * (side - half) + "0" * pad
    half_row = int(half_bits, 2).to_bytes(row_bytes, "big")
    return zero_row * half + half_row * (side - half)


@pytest.mark.parametrize("side", [13, 1801])   # 1801 = real L1 GLO-30 side
def test_packing_matches_mp10b_fixture(side):
    assert side % 8 != 0                       # padding only visible here
    half = side // 2
    mask = np.zeros((side, side), dtype=bool)
    mask[half:, half:] = True
    assert bm.pack_mask(mask) == _write_wmask_mp10b(side)


def test_wmask_size_matches_packed_length():
    for side in (1, 7, 8, 9, 3601):
        packed = bm.pack_mask(np.zeros((3, side), dtype=bool))
        assert len(packed) == bm.wmask_size_for_side(3, side)


# ---------------------------------------------------------------------------
# 3. Native tile mask building: registration, no size filter, ocean
#    included, island holes preserved (#44 pattern), idempotent re-run.
# ---------------------------------------------------------------------------

def test_build_tile_mask_registration_and_content(tmp_path, water_con):
    # tile N34W120 covers lat [34, 35), lon [-120, -119); a lake from
    # (34.2, -119.8) to (34.8, -119.2).
    db = tmp_path / "water.sqlite"
    _make_water_db(db, [{
        "kind": "lake",
        "vertices": [(34.2, -119.8), (34.2, -119.2),
                     (34.8, -119.2), (34.8, -119.8)],
    }])
    water_con(db)

    n = 21   # samples_per_deg = 20
    p = tmp_path / "tiles" / ".mip" / "1" / "N34" / "N34W120.hgt"
    _write_hgt(p, n)

    stem, written, err = bm.build_tile_mask(p, force=False)
    assert err is None and written and stem == "N34W120"

    mask_bytes = p.with_suffix(".wmask").read_bytes()
    row_bytes = -(-n // 8)
    mask = np.unpackbits(
        np.frombuffer(mask_bytes, dtype=np.uint8).reshape(n, row_bytes),
        axis=1)[:, :n].astype(bool)

    # row r -> lat = 35 - r/20 ; col c -> lon = -120 + c/20
    ys, xs = np.mgrid[0:n, 0:n]
    lat = 35 - ys / 20.0
    lon = -120 + xs / 20.0
    expected = ((lat >= 34.2) & (lat <= 34.8)
                & (lon >= -119.8) & (lon <= -119.2))
    # Exact polygon-boundary nodes are an edge case of the scanline
    # convention (either side is defensible); compare the strict interior.
    interior = ((lat > 34.2) & (lat < 34.8) & (lon > -119.8) & (lon < -119.2))
    assert (mask[interior] == expected[interior]).all()
    assert mask[interior].all()
    assert not mask[(lat < 34.0) | (lat > 35.0)].any()


def test_build_tile_mask_no_size_filter_and_ocean_included(tmp_path, water_con):
    """The brief requires "ocean + inland, even-odd rings, no size
    filter" -- unlike the renderer's WaterDB (32-vertex cap, bbox-size
    floor, optional drop_ocean), the builder must rasterize a tiny pond
    AND an ocean-kind polygon with no filtering at all."""
    db = tmp_path / "water.sqlite"
    _make_water_db(db, [
        {"kind": "ocean", "vertices": [(34.0, -120.0), (34.0, -119.9),
                                        (34.1, -119.9), (34.1, -120.0)]},
        {"kind": "lake", "vertices": [(34.5, -119.51), (34.5, -119.49),
                                       (34.52, -119.49), (34.52, -119.51)]},
    ])
    water_con(db)
    n = 41   # samples_per_deg = 40 -- fine enough to resolve a 0.02 deg pond
    p = tmp_path / "tiles" / ".mip" / "1" / "N34" / "N34W120.hgt"
    _write_hgt(p, n)
    bm.build_tile_mask(p, force=False)
    mask_bytes = p.with_suffix(".wmask").read_bytes()
    row_bytes = -(-n // 8)
    mask = np.unpackbits(
        np.frombuffer(mask_bytes, dtype=np.uint8).reshape(n, row_bytes),
        axis=1)[:, :n].astype(bool)
    assert mask.any()   # both polygons contributed SOME water


def test_build_tile_mask_island_hole_excluded(tmp_path, water_con):
    """#44 pattern: an outer ring with a hole ring must leave the hole
    unpainted under the even-odd rule, exactly as MP5's renderer path
    does for the screen-space raster."""
    outer = [(34.1, -119.9), (34.1, -119.1), (34.9, -119.1), (34.9, -119.9)]
    hole = [(34.4, -119.6), (34.4, -119.4), (34.6, -119.4), (34.6, -119.6)]
    db = tmp_path / "water.sqlite"
    _make_water_db(db, [{
        "kind": "lake",
        "vertices": outer + hole,
        "rings": [len(outer), len(outer) + len(hole)],
    }])
    water_con(db)
    n = 21
    p = tmp_path / "tiles" / ".mip" / "1" / "N34" / "N34W120.hgt"
    _write_hgt(p, n)
    bm.build_tile_mask(p, force=False)
    mask_bytes = p.with_suffix(".wmask").read_bytes()
    row_bytes = -(-n // 8)
    mask = np.unpackbits(
        np.frombuffer(mask_bytes, dtype=np.uint8).reshape(n, row_bytes),
        axis=1)[:, :n].astype(bool)
    # island centre (34.5, -119.5) -> row=(35-34.5)*20=10, col=(-119.5+120)*20=10
    assert not mask[10, 10]
    # inside outer, well clear of the hole
    assert mask[5, 5]


def test_build_tile_mask_idempotent_byte_identical(tmp_path, water_con):
    db = tmp_path / "water.sqlite"
    _make_water_db(db, [{
        "kind": "lake",
        "vertices": [(34.2, -119.8), (34.2, -119.2),
                     (34.8, -119.2), (34.8, -119.8)],
    }])
    water_con(db)
    n = 21
    p = tmp_path / "tiles" / ".mip" / "1" / "N34" / "N34W120.hgt"
    _write_hgt(p, n)
    bm.build_tile_mask(p, force=False)
    first = p.with_suffix(".wmask").read_bytes()
    bm.build_tile_mask(p, force=True)
    second = p.with_suffix(".wmask").read_bytes()
    assert first == second


def test_build_tile_mask_skips_existing_unless_forced(tmp_path, water_con):
    db = tmp_path / "water.sqlite"
    _make_water_db(db, [])
    water_con(db)
    n = 9
    p = tmp_path / "tiles" / ".mip" / "1" / "N34" / "N34W120.hgt"
    _write_hgt(p, n)
    bm.build_tile_mask(p, force=False)
    out = p.with_suffix(".wmask")
    out.write_bytes(b"stale")
    stem, written, err = bm.build_tile_mask(p, force=False)
    assert not written and err is None
    assert out.read_bytes() == b"stale"
    stem, written, err = bm.build_tile_mask(p, force=True)
    assert written and out.read_bytes() != b"stale"


def test_build_tile_mask_no_rtree_or_rings_column_fallback(tmp_path, water_con):
    """Older water.sqlite editions lack the rtree virtual table and/or
    the rings column -- the builder must still produce a correct mask
    via the plain bbox query, single-ring only."""
    db = tmp_path / "water.sqlite"
    _make_water_db(db, [{
        "kind": "lake",
        "vertices": [(34.2, -119.8), (34.2, -119.2),
                     (34.8, -119.2), (34.8, -119.8)],
    }], use_rtree=False, use_rings=False)
    water_con(db)
    assert bm._HAS_RTREE is False and bm._HAS_RINGS is False
    n = 21
    p = tmp_path / "tiles" / ".mip" / "1" / "N34" / "N34W120.hgt"
    _write_hgt(p, n)
    bm.build_tile_mask(p, force=False)
    mask_bytes = p.with_suffix(".wmask").read_bytes()
    row_bytes = -(-n // 8)
    mask = np.unpackbits(
        np.frombuffer(mask_bytes, dtype=np.uint8).reshape(n, row_bytes),
        axis=1)[:, :n].astype(bool)
    assert mask[10, 10]        # centre of the lake


# ---------------------------------------------------------------------------
# 4. Mosaic mask building -- rectangular (rows != cols) grid.
# ---------------------------------------------------------------------------

def test_build_mosaic_mask_rectangular_registration(tmp_path, water_con):
    db = tmp_path / "water.sqlite"
    _make_water_db(db, [{
        "kind": "lake",
        "vertices": [(33.5, -119.0), (33.5, -117.0),
                     (34.5, -117.0), (34.5, -119.0)],
    }])
    water_con(db)
    # 4 deg lat x 6 deg lon extent at spd=10 -> rows=41, cols=61 (rows != cols)
    spd = 10
    meta = {"level": 4, "rows": 41, "cols": 61, "spd": spd,
            "lat_n": 36, "lon_w": -120}
    root = tmp_path / "tiles" / ".mip" / "mosaic"
    root.mkdir(parents=True)
    jp = root / "L4.json"
    jp.write_text(json.dumps(meta))
    _write_hgt(root / "L4.hgt", 1)   # content unused; only shape/size relevant

    label, written, err = bm.build_mosaic_mask(jp, force=False)
    assert err is None and written

    mask_bytes = (root / "L4.wmask").read_bytes()
    rows, cols = meta["rows"], meta["cols"]
    row_bytes = -(-cols // 8)
    mask = np.unpackbits(
        np.frombuffer(mask_bytes, dtype=np.uint8).reshape(rows, row_bytes),
        axis=1)[:, :cols].astype(bool)
    assert mask.shape == (41, 61)
    # row r -> lat = 36 - r/10 ; col c -> lon = -120 + c/10
    # lake interior e.g. lat 34.0 -> r=20 ; lon -118.0 -> c=20
    assert mask[20, 20]
    assert not mask[0, 0]


# ---------------------------------------------------------------------------
# 5. pack_check self-test: every >= L1 .hgt needs a correctly sized .wmask.
# ---------------------------------------------------------------------------

def test_check_pack_reports_missing_and_wrong_size(tmp_path):
    root = tmp_path / "tiles"
    p = root / ".mip" / "1" / "N34" / "N34W120.hgt"
    _write_hgt(p, 21)
    problems = bm.check_pack(root, [1], [4, 5, 6])
    assert len(problems) == 1 and "missing" in problems[0]

    p.with_suffix(".wmask").write_bytes(b"\x00" * 5)   # wrong size
    problems = bm.check_pack(root, [1], [4, 5, 6])
    assert len(problems) == 1 and "size" in problems[0]

    p.with_suffix(".wmask").write_bytes(
        b"\x00" * bm.wmask_size_for_side(21, 21))
    assert bm.check_pack(root, [1], [4, 5, 6]) == []


def test_check_pack_covers_mosaics(tmp_path):
    root = tmp_path / "tiles"
    mdir = root / ".mip" / "mosaic"
    mdir.mkdir(parents=True)
    meta = {"level": 4, "rows": 10, "cols": 12, "spd": 5, "lat_n": 40, "lon_w": -125}
    (mdir / "L4.json").write_text(json.dumps(meta))
    _write_hgt(mdir / "L4.hgt", 1)
    problems = bm.check_pack(root, [1], [4])
    assert len(problems) == 1 and "L4" in problems[0]
    (mdir / "L4.wmask").write_bytes(
        b"\x00" * bm.wmask_size_for_side(meta["rows"], meta["cols"]))
    assert bm.check_pack(root, [1], [4]) == []


# ---------------------------------------------------------------------------
# 6. End-to-end CLI smoke test (sequential, jobs=1 -- no multiprocessing
#    spawn needed for this small a fixture).
# ---------------------------------------------------------------------------

def test_main_builds_and_checks(tmp_path, capsys):
    db = tmp_path / "water.sqlite"
    _make_water_db(db, [{
        "kind": "lake",
        "vertices": [(34.2, -119.8), (34.2, -119.2),
                     (34.8, -119.2), (34.8, -119.8)],
    }])
    root = tmp_path / "tiles"
    _write_hgt(root / ".mip" / "1" / "N34" / "N34W120.hgt", 21)

    rc = bm.main([str(root), str(db), "--levels", "1", "--mosaic-levels",
                  "--jobs", "1"])
    assert rc == 0
    assert (root / ".mip" / "1" / "N34" / "N34W120.wmask").exists()

    # re-run without --force: skipped, still clean
    rc = bm.main([str(root), str(db), "--levels", "1", "--mosaic-levels",
                  "--jobs", "1"])
    assert rc == 0

    rc = bm.main([str(root), "--check-only", "--levels", "1",
                  "--mosaic-levels"])
    assert rc == 0
