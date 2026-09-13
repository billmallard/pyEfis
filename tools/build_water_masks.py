#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Build the water-mask pyramid (briefs/map_gesture_perf_plan.md Track 2,
MP10a; pyEfis #98).

For every downsampled terrain tile ``.mip/<L>/<NSdir>/<name>.hgt`` (L =
1..6, built by ``build_terrain_mips.py``) and every whole-extent mosaic
``.mip/mosaic/L<level>.hgt`` (``build_terrain_mosaic.py``), rasterize every
polygon in ``water.sqlite`` (ocean + inland, even-odd rings, no size
filter) onto that level's exact elevation grid and write a row-packed
1-bit bitmask ``<name>.wmask`` next to it -- no header, ``np.packbits``
row padding, side implied by the sibling ``.hgt``'s file size (native
mips) or the mosaic's ``.json``. MP10c (``svs.py``
``TileCache.get_mask``/``get_mosaic_mask``) reads it as a coverage
channel co-registered with elevation, so water at wide range becomes one
numpy gather instead of a per-frame polygon rasterize.

Packing must stay byte-identical to makerplane-data's stdlib
``tests/test_terrain.py::_write_wmask`` fixture (added when MP10b
closed): packtools carries the ``.wmask`` bytes through unread, so this
side is the only place the format is actually asserted. See
``tests/tools/test_build_water_masks.py::test_packing_matches_mp10b_fixture``.

Deliberately never imports ``pyefis.instruments.ai`` or
``pyefis.instruments.map``: both packages' ``__init__.py`` pull in PyQt6
at module level (AER-1090), which would force Qt onto every worker
process and defeat cheap ``multiprocessing`` spawn for a headless build
tool. The even-odd scanline fill below is therefore a self-contained port
of MP5's ``pyefis.instruments.map.raster.fill_even_odd`` (same brief,
section 4), generalized to rectangular grids and to POINT registration
(see ``_fill_even_odd_rect`` / ``_mask_at_nodes``). The water.sqlite
reader is similarly a minimal, dependency-free reimplementation of
``ai/water_db.py``'s documented schema, with no vertex cap and no
ocean/size filtering, matching the brief's "no size filter" requirement
(the renderer's ``WaterDB`` caps and filters for screen-space speed;
none of that applies when building an offline mask once).

Usage::

    python tools/build_water_masks.py <tile_root> <water_db> \\
        [--levels 6] [--mosaic-levels 4 5 6] [--force] [--jobs 0] \\
        [--only N35W098 ...]

    python tools/build_water_masks.py <tile_root> --check-only
"""
import argparse
import json
import os
import re
import sqlite3
import struct
import time
from pathlib import Path

import numpy as np

MAX_LEVEL = 6                       # matches build_terrain_mips.py
DEFAULT_MOSAIC_LEVELS = (4, 5, 6)   # matches build_terrain_mosaic.py

_NAME = re.compile(r"([NS])(\d+)([EW])(\d+)", re.IGNORECASE)

# Set once per worker process (pool initializer) / once in the parent for
# the sequential path -- avoids reopening the sqlite connection per tile.
_CON: sqlite3.Connection | None = None
_HAS_RTREE = False
_HAS_RINGS = False


# ---------------------------------------------------------------------------
# Even-odd scanline fill -- ported from MP5's raster.fill_even_odd, but (a)
# generalized to rows != cols (mosaics are not square) and (b) POINT-sampled
# at exact grid nodes rather than pixel-AREA membership at pixel centers,
# matching the elevation mip pyramid's pixel-is-point registration.
# ---------------------------------------------------------------------------

def _fill_even_odd_rect(rings, rows: int, cols: int) -> np.ndarray:
    """Even-odd scanline fill of *rings* into a ``rows x cols`` boolean
    mask, testing pixel-CENTER membership (cell (j, i) center at
    ``(i + 0.5, j + 0.5)``) exactly as ``raster.fill_even_odd`` does for
    the square case -- see that function's docstring for the algorithm.
    *rings* is an iterable of ``(k, 2)`` float arrays of (x, y).
    """
    x0_parts, y0_parts, x1_parts, y1_parts = [], [], [], []
    for ring in rings:
        ring = np.asarray(ring, dtype=np.float64)
        if ring.shape[0] < 3:
            continue
        x = ring[:, 0]
        y = ring[:, 1]
        x0_parts.append(x)
        y0_parts.append(y)
        x1_parts.append(np.roll(x, -1))
        y1_parts.append(np.roll(y, -1))

    if not x0_parts:
        return np.zeros((rows, cols), dtype=bool)

    x0 = np.concatenate(x0_parts)
    y0 = np.concatenate(y0_parts)
    x1 = np.concatenate(x1_parts)
    y1 = np.concatenate(y1_parts)

    ymin = np.minimum(y0, y1)
    ymax = np.maximum(y0, y1)
    j_lo = np.clip(np.ceil(ymin - 0.5).astype(np.int64), 0, rows)
    j_hi = np.clip(np.ceil(ymax - 0.5).astype(np.int64), 0, rows)
    counts = j_hi - j_lo
    keep = counts > 0
    if not keep.any():
        return np.zeros((rows, cols), dtype=bool)
    x0, y0, x1, y1 = x0[keep], y0[keep], x1[keep], y1[keep]
    j_lo, counts = j_lo[keep], counts[keep]

    total = int(counts.sum())
    edge_id = np.repeat(np.arange(x0.shape[0]), counts)
    run_start = np.repeat(np.cumsum(counts) - counts, counts)
    j = j_lo[edge_id] + (np.arange(total) - run_start)
    yc = j.astype(np.float64) + 0.5

    dy = (y1 - y0)[edge_id]
    dx = (x1 - x0)[edge_id]
    x_at = x0[edge_id] + (yc - y0[edge_id]) * dx / dy
    c = np.clip(np.ceil(x_at - 0.5).astype(np.int64), 0, cols)

    flat = j * (cols + 1) + c
    acc = np.bincount(flat, minlength=rows * (cols + 1)).reshape(rows, cols + 1)
    return (np.cumsum(acc, axis=1)[:, :cols] & 1).astype(bool)


def _mask_at_nodes(rings, rows: int, cols: int) -> np.ndarray:
    """Even-odd fill, POINT-sampled at exact grid nodes (row r, col c) --
    matching the pixel-is-point registration ``elevation_at``/``_sample``
    use for the elevation mip pyramid, rather than pixel-AREA membership.

    Shifting every ring vertex by +0.5 in both axes turns the
    node-membership test at the integer point ``(c, r)`` into exactly the
    pixel-center test ``_fill_even_odd_rect`` already performs at
    ``(c + 0.5, r + 0.5)`` -- so the identical scanline algorithm answers
    a different question with no other change.
    """
    shifted = [np.asarray(ring, dtype=np.float64) + 0.5 for ring in rings]
    return _fill_even_odd_rect(shifted, rows, cols)


def pack_mask(mask: np.ndarray) -> bytes:
    """Row-packed 1-bit-per-pixel bytes for *mask* -- no header, MSB
    first, trailing zero bits padding each row to a byte boundary
    (``ceil(cols/8)`` bytes/row). Must stay byte-identical to
    makerplane-data's stdlib ``_write_wmask`` fixture for any *mask*, not
    just the ones this tool happens to produce -- that is the whole DoD."""
    return np.packbits(mask, axis=1).tobytes()


# ---------------------------------------------------------------------------
# Minimal, dependency-free water.sqlite reader (schema per ai/water_db.py).
# Deliberately does not import that module -- see the module docstring.
# ---------------------------------------------------------------------------

def _decode_vertices(blob: bytes) -> np.ndarray:
    """Unpack a struct-packed ``<dd...`` blob into an ``(n, 2)`` float64
    (lat, lon) array. No vertex cap -- the brief requires rasterizing
    every polygon at full resolution ("no size filter")."""
    if not blob:
        return np.empty((0, 2), dtype=np.float64)
    return np.frombuffer(blob, dtype="<f8").reshape(-1, 2)


def _decode_rings(blob, n_vertices: int):
    """Unpack a little-endian ring-END-offset blob (earcut convention:
    outer ring first, then holes). uint16 for <= 65535 vertices, uint32
    beyond -- same rule ``ai/water_db.py`` uses on both build and read
    sides. Returns None for single-ring rows."""
    if not blob:
        return None
    if n_vertices > 65535:
        n = len(blob) // 4
        return list(struct.unpack(f"<{n}I", blob))
    n = len(blob) // 2
    return list(struct.unpack(f"<{n}H", blob))


def _probe_water_db(con: sqlite3.Connection):
    has_rtree = False
    has_rings = False
    try:
        con.execute("SELECT id FROM water_rtree LIMIT 0")
        has_rtree = True
    except sqlite3.OperationalError:
        pass
    try:
        con.execute("SELECT rings FROM water_polygons LIMIT 0")
        has_rings = True
    except sqlite3.OperationalError:
        pass
    return has_rtree, has_rings


def open_water_db(path) -> sqlite3.Connection:
    """Open *path* read-only. Raises if missing/unreadable -- unlike the
    renderer's construct-never-raises WaterDB, a build tool with no data
    to build from is an error, not a degraded runtime mode."""
    uri = f"file:{Path(path).resolve()}?mode=ro"
    con = sqlite3.connect(uri, uri=True, check_same_thread=False)
    con.execute("SELECT id FROM water_polygons LIMIT 0")
    return con


def polygons_in_bbox(con: sqlite3.Connection, has_rtree: bool, has_rings: bool,
                      lat_lo: float, lat_hi: float, lon_lo: float, lon_hi: float):
    """Yield ``(vertices, rings)`` for every polygon whose bbox overlaps
    the query bbox -- ocean and inland alike, undecimated, no size
    floor (brief: "no size filter"). Mirrors the bbox-overlap query
    ``WaterDB.polygons_in_range`` uses, minus the screen-space filters
    that don't apply to an offline full-resolution build."""
    if has_rtree:
        rings_expr = "p.rings" if has_rings else "NULL AS rings"
        sql = (
            f"SELECT p.vertices, {rings_expr} "
            "FROM water_polygons p "
            "JOIN water_rtree r ON r.id = p.id "
            "WHERE r.min_lat <= ? AND r.max_lat >= ? "
            "  AND r.min_lon <= ? AND r.max_lon >= ?")
        params = (lat_hi, lat_lo, lon_hi, lon_lo)
    else:
        rings_expr = "rings" if has_rings else "NULL AS rings"
        sql = (
            f"SELECT vertices, {rings_expr} "
            "FROM water_polygons "
            "WHERE max_lat > ? AND min_lat < ? "
            "  AND max_lon > ? AND min_lon < ?")
        params = (lat_lo, lat_hi, lon_lo, lon_hi)
    for row in con.execute(sql, params):
        vertices = _decode_vertices(row[0])
        rings = _decode_rings(row[1], vertices.shape[0])
        yield vertices, rings


def _rings_as_xy(vertices: np.ndarray, rings, lat0_n: float, lon0_w: float,
                  samples_per_deg: float):
    """Split a polygon's (lat, lon) vertex array into per-ring (x, y)
    pixel-space arrays, projected onto a grid whose row 0 = ``lat0_n``
    and col 0 = ``lon0_w`` (north/west corner), at ``samples_per_deg``
    nodes per degree -- the same convention ``elevation_at``/the mosaic
    reader use (row increases southward, col increases eastward)."""
    if vertices.shape[0] == 0:
        return
    xs = (vertices[:, 1] - lon0_w) * samples_per_deg
    ys = (lat0_n - vertices[:, 0]) * samples_per_deg
    ends = rings if rings else [vertices.shape[0]]
    start = 0
    for end in ends:
        if end - start >= 3:
            yield np.stack((xs[start:end], ys[start:end]), axis=1)
        start = end


def _collect_rings(lat_lo, lat_hi, lon_lo, lon_hi, lat0_n, lon0_w, samples_per_deg):
    rings = []
    for vertices, poly_rings in polygons_in_bbox(
            _CON, _HAS_RTREE, _HAS_RINGS, lat_lo, lat_hi, lon_lo, lon_hi):
        rings.extend(_rings_as_xy(vertices, poly_rings, lat0_n, lon0_w,
                                   samples_per_deg))
    return rings


# ---------------------------------------------------------------------------
# Tile / mosaic discovery and mask building
# ---------------------------------------------------------------------------

def _tile_coord(stem: str):
    m = _NAME.match(stem)
    if not m:
        return None
    lat = int(m.group(2)) * (1 if m.group(1).upper() == "N" else -1)
    lon = int(m.group(4)) * (1 if m.group(3).upper() == "E" else -1)
    return lat, lon


def _side_from_file(path: Path) -> int | None:
    size = path.stat().st_size
    n = int(round((size / 2) ** 0.5))
    return n if n * n * 2 == size else None


def wmask_size_for_side(rows: int, cols: int) -> int:
    return -(-cols // 8) * rows          # ceil(cols / 8) * rows


def build_tile_mask(path: Path, force: bool) -> tuple[str, bool, str | None]:
    """Build the ``.wmask`` sibling for one native mip tile. Returns
    ``(stem, written, error)``."""
    stem = path.stem.upper()
    out = path.with_suffix(".wmask")
    if out.exists() and not force:
        return stem, False, None
    coord = _tile_coord(stem)
    if coord is None:
        return stem, False, f"unrecognized tile name {stem!r}"
    tile_lat, tile_lon = coord
    n = _side_from_file(path)
    if n is None:
        return stem, False, f"not a square >i2 tile ({path.stat().st_size} bytes)"
    samples_per_deg = n - 1
    lat0_n = tile_lat + 1
    lon0_w = tile_lon
    rings = _collect_rings(tile_lat, tile_lat + 1, tile_lon, tile_lon + 1,
                            lat0_n, lon0_w, samples_per_deg)
    mask = _mask_at_nodes(rings, n, n)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(pack_mask(mask))
    return stem, True, None


def build_mosaic_mask(json_path: Path, force: bool) -> tuple[str, bool, str | None]:
    """Build the ``.wmask`` sibling for one whole-extent mosaic level."""
    hgt_path = json_path.with_suffix(".hgt")
    label = json_path.stem
    out = hgt_path.with_suffix(".wmask")
    if out.exists() and not force:
        return label, False, None
    if not hgt_path.exists():
        return label, False, f"missing sibling {hgt_path.name}"
    meta = json.loads(json_path.read_text())
    rows, cols = meta["rows"], meta["cols"]
    spd = meta["spd"]
    lat_n = meta["lat_n"]
    lon_w = meta["lon_w"]
    lat_s = lat_n - rows / spd
    lon_e = lon_w + cols / spd
    rings = _collect_rings(lat_s, lat_n, lon_w, lon_e, lat_n, lon_w, spd)
    mask = _mask_at_nodes(rings, rows, cols)
    out.write_bytes(pack_mask(mask))
    return label, True, None


def _iter_mip_tiles(root: Path, levels, only):
    for level in levels:
        for p in sorted((root / ".mip" / str(level)).glob("[NS]*/*.hgt")):
            stem = p.stem.upper()
            if only and stem not in only:
                continue
            yield level, p


def _iter_mosaics(root: Path, mosaic_levels):
    mdir = root / ".mip" / "mosaic"
    for level in mosaic_levels:
        jp = mdir / f"L{level}.json"
        if jp.exists():
            yield level, jp


# ---------------------------------------------------------------------------
# pack_check-style self-test: every >= L1 .hgt in a pack has a correctly
# sized .wmask sibling. Needs no water.sqlite -- it only checks what is
# already on disk, so it doubles as a post-download pack sanity check.
# ---------------------------------------------------------------------------

def check_pack(root: Path, levels, mosaic_levels) -> list[str]:
    """Return a list of human-readable problems; empty means clean."""
    problems = []
    for _level, path in _iter_mip_tiles(root, levels, None):
        n = _side_from_file(path)
        wmask = path.with_suffix(".wmask")
        if not wmask.exists():
            problems.append(f"{path}: missing {wmask.name}")
            continue
        if n is None:
            problems.append(f"{path}: cannot infer side from file size")
            continue
        expected = wmask_size_for_side(n, n)
        actual = wmask.stat().st_size
        if actual != expected:
            problems.append(f"{wmask}: size {actual} != expected {expected} "
                             f"(side {n})")
    for _level, jp in _iter_mosaics(root, mosaic_levels):
        meta = json.loads(jp.read_text())
        wmask = jp.with_suffix(".wmask")
        if not wmask.exists():
            problems.append(f"{jp.with_suffix('.hgt')}: missing {wmask.name}")
            continue
        expected = wmask_size_for_side(meta["rows"], meta["cols"])
        actual = wmask.stat().st_size
        if actual != expected:
            problems.append(f"{wmask}: size {actual} != expected {expected} "
                             f"(rows {meta['rows']} cols {meta['cols']})")
    return problems


# ---------------------------------------------------------------------------
# Parallel driver -- mirrors build_terrain_mips.py's pool structure.
# ---------------------------------------------------------------------------

def _init_worker(water_db_path: str):
    global _CON, _HAS_RTREE, _HAS_RINGS
    if _CON is not None:               # sequential path across repeat main() calls
        _CON.close()
    _CON = open_water_db(water_db_path)
    _HAS_RTREE, _HAS_RINGS = _probe_water_db(_CON)


def _worker(job):
    kind = job[0]
    try:
        if kind == "tile":
            _, path, force = job
            stem, written, err = build_tile_mask(path, force)
            return stem, written, err
        _, json_path, force = job
        label, written, err = build_mosaic_mask(json_path, force)
        return label, written, err
    except Exception as exc:                 # noqa: BLE001 -- one bad job != abort
        return job[1], False, repr(exc)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build the water-mask pyramid.")
    ap.add_argument("tile_root", help="terrain tile tree (holds .mip/...)")
    ap.add_argument("water_db", nargs="?", default=None,
                    help="water.sqlite (required unless --check-only)")
    ap.add_argument("--levels", type=int, nargs="*",
                    default=list(range(1, MAX_LEVEL + 1)),
                    help="mip levels to build masks for (default 1..6)")
    ap.add_argument("--mosaic-levels", type=int, nargs="*",
                    default=list(DEFAULT_MOSAIC_LEVELS),
                    help=f"mosaic levels (default {list(DEFAULT_MOSAIC_LEVELS)})")
    ap.add_argument("--force", action="store_true",
                    help="rebuild masks that already exist")
    ap.add_argument("-j", "--jobs", type=int, default=0,
                    help="worker processes (0 = all CPUs; 1 = sequential)")
    ap.add_argument("--only", nargs="*", default=None,
                    help="only these native tiles (e.g. N35W098)")
    ap.add_argument("--check-only", action="store_true",
                    help="skip building; only run the pack_check self-test "
                         "against what is already on disk")
    args = ap.parse_args(argv)

    root = Path(args.tile_root)
    only = {s.upper() for s in args.only} if args.only else None

    if not args.check_only:
        if not args.water_db:
            ap.error("water_db is required unless --check-only")
        tile_jobs = [("tile", p, args.force)
                     for _, p in _iter_mip_tiles(root, args.levels, only)]
        mosaic_jobs = [("mosaic", jp, args.force)
                       for _, jp in _iter_mosaics(root, args.mosaic_levels)]
        jobs = tile_jobs + mosaic_jobs
        jobs_n = max(1, min(args.jobs if args.jobs > 0 else (os.cpu_count() or 1),
                             len(jobs) or 1))
        print(f"root={root}  tiles={len(tile_jobs)}  mosaics={len(mosaic_jobs)}  "
              f"jobs={jobs_n}")
        t0 = time.perf_counter()
        written = 0
        errors = []

        if jobs_n == 1:
            _init_worker(args.water_db)
            for i, job in enumerate(jobs):
                label, ok, err = _worker(job)
                written += int(ok)
                if err:
                    errors.append((label, err))
        else:
            import multiprocessing as mp
            with mp.Pool(jobs_n, initializer=_init_worker,
                         initargs=(args.water_db,)) as pool:
                for label, ok, err in pool.imap_unordered(_worker, jobs,
                                                          chunksize=1):
                    written += int(ok)
                    if err:
                        errors.append((label, err))

        footprint = sum(p.stat().st_size for p in root.rglob("*.wmask"))
        dt = time.perf_counter() - t0
        print(f"done: {len(jobs)} jobs -> {written} masks written, "
              f"footprint {footprint / 1e3:.1f} KB, {dt:.1f}s")
        if errors:
            print(f"WARNING: {len(errors)} job(s) errored:")
            for label, err in errors[:20]:
                print(f"  {label}: {err}")
            if len(errors) > 20:
                print(f"  ... and {len(errors) - 20} more")
            return 1

    problems = check_pack(root, args.levels, args.mosaic_levels)
    if problems:
        print(f"pack_check: {len(problems)} problem(s):")
        for p in problems[:50]:
            print(f"  {p}")
        return 1
    print("pack_check: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
