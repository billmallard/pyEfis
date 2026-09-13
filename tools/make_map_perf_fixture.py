#!/usr/bin/env python3
#  SPDX-License-Identifier: GPL-2.0-or-later
"""Cut a small geographic-window perf fixture pack out of the real
moving-map data packs (MP8b, briefs/map_gesture_perf_plan.md's MP8 item;
pyEfis #98, AER-1133).

MP8a (AER-1121, pyEfis #207) landed the count-based moving-map perf
budgets in ``tests/perf/test_map_gestures.py`` -- pipeline properties
(renders per pinch, paints per sweep, QPointF count) that need no real
data and run in CI with the Qt ``offscreen`` platform. What that file
explicitly deferred is a **volume** budget: how much real water/terrain/
road geometry a real scene holds at 160 NM. A synthetic fixture answers
a different question and would pass at any threshold -- MP8b's job is
the fixture that makes that budget meaningful.

This tool cuts a window out of the FULL real packs (terrain mip pyramid,
terrain mosaic, ``water.sqlite``, a highway db, a navaid db) that the
data-manager pipeline builds and pyEfis reads at runtime -- it does not
build those packs itself (see ``tools/build_terrain_mips.py``,
``build_terrain_mosaic.py``, ``build_water_db.py``, ``build_highway_db.py``,
``build_navaid_db.py`` for that). Output is a directory with the exact
on-disk layout the runtime readers expect (``TileCache.get_mip``/
``get_mosaic`` in ``src/pyefis/instruments/ai/svs.py``, ``WaterDB`` in
``water_db.py``, ``HighwayDB`` in ``highway_db.py``, the navaid layers in
``src/pyefis/instruments/map/layers/navaids.py``), verified against those
same reader classes in ``tests/tools/test_make_map_perf_fixture.py`` --
not merely produced by inspection of their schemas.

Two scenes (brief's Track 4 MP8 item), both dense, both real perf traps:

    raleigh    35.8, -78.8    the brief's own reference scene
    key_west   24.55, -81.78  dense multi-ring coastline (the 08-13
                               stutter scene; the #44 island-hole case)

Usage, cutting from a real pack tree on a workstation that holds it
(never on the EFIS device -- same rule as the builder tools)::

    python tools/make_map_perf_fixture.py cut --scene raleigh \\
        --tile-root /data/makerplane-data/terrain/tiles \\
        --water-db  /data/makerplane-data/water/current/water.sqlite \\
        --highway-db /data/makerplane-data/highways/current/highway.sqlite \\
        --navaid-db  /data/makerplane-data/navaids/current/navaids.sqlite \\
        --out dist/perf-fixtures/raleigh

Add ``--publish`` to additionally push the packaged tarball to R2 under
``test-fixtures/<scene>/`` (mirrors the existing wrangler convention in
``.github/workflows/editor-assets.yml``: it skips cleanly with a warning,
exit 0, when ``CLOUDFLARE_API_TOKEN``/``CLOUDFLARE_ACCOUNT_ID`` are unset
rather than failing a CI run that has no secrets). A successful publish
also rewrites this scene's entry in ``tools/perf_fixtures.json`` -- the
checked-in, sha256-pinned manifest ``fetch_fixture`` reads.

On-demand fetch side (what a perf test in ``tests/perf/`` calls)::

    from tools.make_map_perf_fixture import fetch_fixture
    path = fetch_fixture("raleigh")   # None if PYEFIS_PERF_FIXTURE unset

``fetch_fixture`` never touches the network unless ``PYEFIS_PERF_FIXTURE``
is truthy (CI sets it; a bare local ``pytest`` run must skip cleanly, not
fail) and never adds a runtime dependency -- download/verify/extract are
stdlib (``urllib``, ``hashlib``, ``tarfile``).

**Honest limitation, current as of this tool's introduction:** the
``sha256``/``url`` fields in ``tools/perf_fixtures.json`` start ``null``
for both scenes. Producing the real packs requires (a) access to the
full production terrain/water/highway/navaid packs, which live in the
data-manager pipeline's storage, not in a pyEfis checkout, and (b) R2
write credentials. Whoever runs ``cut --publish`` against the real packs
fills the manifest in; until then ``fetch_fixture`` raises a clear,
actionable ``PerfFixtureUnavailable`` rather than silently returning
nothing or fabricating a pin.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import sqlite3
import sys
import tarfile
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_TOOLS_DIR = _ROOT / "tools"
MANIFEST_PATH = _TOOLS_DIR / "perf_fixtures.json"

#: The brief's Track 4 MP8 scenes. lat/lon is the window centre; a real
#: full-pack tile root/water/highway/navaid db must be supplied on the
#: command line -- this dict only pins scene identity and pose, the way
#: ``export_svs_preview_patch.py``'s ``SCENES`` pins configurator poses.
SCENES = {
    "raleigh": {"lat": 35.8, "lon": -78.8},
    "key_west": {"lat": 24.55, "lon": -81.78},
}

#: "2x2 deg window" per the issue. Centred on the scene lat/lon; the
#: terrain tile grid this expands to is whole-degree aligned and may be
#: very slightly larger (see _cell_range) -- water/highway/navaid cuts
#: reuse that same, larger bbox so every data type in the pack shares
#: exactly one footprint definition. Over-inclusion costs a little size;
#: under-inclusion would silently gate nothing (see module docstring of
#: tests/perf/test_map_gestures.py, "the vacuity trap").
WINDOW_DEG = 2.0

MIP_LEVELS = (1, 2, 3, 4, 5, 6)          # matches build_terrain_mips.MAX_LEVEL
MOSAIC_LEVELS = (4, 5, 6)                # matches build_terrain_mosaic default

#: Traces to CI fetch time, not to physics (issue text) -- a scene over
#: this is a real problem to escalate, not a window to quietly shrink.
MAX_PACK_BYTES = 200 * 1024 * 1024

SRTM3_VOID = -32768

#: Verbatim from tools/build_water_db.py's SCHEMA (not imported: that
#: module pulls in mapbox_earcut at top level for tessellation, a
#: build-time-only dependency this cutter has no use for and should not
#: force onto whoever just wants to cut a fixture). Keep in sync by hand.
WATER_SCHEMA = """
CREATE TABLE IF NOT EXISTS water_polygons (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    min_lat   REAL NOT NULL,
    max_lat   REAL NOT NULL,
    min_lon   REAL NOT NULL,
    max_lon   REAL NOT NULL,
    kind      TEXT NOT NULL,
    elev_ft   REAL,
    vertices  BLOB NOT NULL,
    triangles BLOB,
    rings     BLOB
);
CREATE INDEX IF NOT EXISTS idx_bbox
    ON water_polygons(min_lat, max_lat, min_lon, max_lon);
CREATE INDEX IF NOT EXISTS idx_kind ON water_polygons(kind);
CREATE VIRTUAL TABLE IF NOT EXISTS water_rtree USING rtree(
    id,
    min_lat, max_lat,
    min_lon, max_lon
);
CREATE TABLE IF NOT EXISTS waterway_lines (
    id INTEGER PRIMARY KEY,
    fclass TEXT NOT NULL,
    min_lat REAL, max_lat REAL, min_lon REAL, max_lon REAL,
    verts BLOB NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS waterway_rtree USING rtree(
    id, min_lat, max_lat, min_lon, max_lon
);
"""

#: Verbatim from tools/build_highway_db.py's SCHEMA. Loaded as a literal
#: for the same reason as WATER_SCHEMA above -- consistency, and this
#: one in particular has no problematic top-level import today, but a
#: cutter tool should not be coupled to a builder's import graph at all.
HIGHWAY_SCHEMA = """
CREATE TABLE IF NOT EXISTS highway_lines (
    id INTEGER PRIMARY KEY,
    fclass TEXT NOT NULL,
    min_lat REAL, max_lat REAL, min_lon REAL, max_lon REAL,
    verts BLOB NOT NULL,
    flags INTEGER NOT NULL DEFAULT 0,
    ref TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS highway_rtree USING rtree(
    id, min_lat, max_lat, min_lon, max_lon
);
"""


class PerfFixtureError(RuntimeError):
    """Cutting/packaging failed in a way the operator must act on."""


class PerfFixtureUnavailable(RuntimeError):
    """fetch_fixture was asked for a scene with no usable pinned manifest
    entry -- distinct from "PYEFIS_PERF_FIXTURE unset" (which is a clean
    ``None`` return, not an error)."""


# ---------------------------------------------------------------------------
# Loading sibling tools/*.py modules (tools/ is not a package -- same
# pattern tests/tools/test_bench_map_gestures.py and
# tests/perf/test_map_gestures.py already use).
# ---------------------------------------------------------------------------

def _load_tool(name: str):
    spec = importlib.util.spec_from_file_location(
        name, _TOOLS_DIR / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# HGT tile naming -- mirrors src/pyefis/instruments/ai/svs.py tile_name /
# _hgt_path exactly (duplicated, not imported: svs.py imports PyQt6 at
# module scope, and this tool must stay usable with no Qt installed, the
# same reason tools/build_terrain_mips.py never imports svs.py for this).
# ---------------------------------------------------------------------------

def tile_name(lat: int, lon: int) -> str:
    ns = "N" if lat >= 0 else "S"
    ew = "E" if lon >= 0 else "W"
    return f"{ns}{abs(lat):02d}{ew}{abs(lon):03d}"


def _ns_dir(lat: int) -> str:
    return f"{'N' if lat >= 0 else 'S'}{abs(lat):02d}"


def _hgt_path(tile_root: Path, lat: int, lon: int) -> Path | None:
    name = tile_name(lat, lon)
    for p in (tile_root / _ns_dir(lat) / f"{name}.hgt",
              tile_root / f"{name}.hgt",
              tile_root / f"{name}.HGT"):
        if p.exists():
            return p
    return None


def _cell_range(lo: float, hi: float) -> range:
    """Integer SW-corner degree cells whose [c, c+1) span overlaps
    [lo, hi). May include one extra cell when ``hi`` lands exactly on an
    integer -- harmless over-inclusion, never a missed cell."""
    return range(math.floor(lo), math.floor(hi) + 1)


def window_bbox(lat: float, lon: float, window_deg: float = WINDOW_DEG):
    """Return (lat_lo, lat_hi, lon_lo, lon_hi, lat_cells, lon_cells) for a
    scene centre -- the single footprint every data type in the pack is
    cut against."""
    half = window_deg / 2.0
    lat_lo, lat_hi = lat - half, lat + half
    lon_lo, lon_hi = lon - half, lon + half
    lat_cells = _cell_range(lat_lo, lat_hi)
    lon_cells = _cell_range(lon_lo, lon_hi)
    # Widen the query bbox to the whole-degree tile grid so terrain and
    # the vector layers agree on one footprint (module docstring).
    return (float(lat_cells.start), float(lat_cells.stop),
            float(lon_cells.start), float(lon_cells.stop),
            lat_cells, lon_cells)


# ---------------------------------------------------------------------------
# Terrain: native tiles, mip pyramid, mosaic
# ---------------------------------------------------------------------------

def cut_terrain(src_root: Path, dst_root: Path, lat_cells: range,
                 lon_cells: range, mip_levels=MIP_LEVELS,
                 mosaic_levels=MOSAIC_LEVELS) -> dict:
    """Copy native + mip tiles for every cell in the window, then
    regenerate the mosaic from the CUT mip tiles via the real
    ``build_terrain_mosaic.build_level`` -- not by slicing the source
    mosaic and hand-adjusting its JSON. Reusing the shipped builder is
    what guarantees the cut mosaic's (rows, cols, spd, lat_n, lon_w) is
    self-consistent with its own .hgt file, which is TileCache.get_mosaic's
    hard requirement (a shape/JSON mismatch makes the mosaic silently
    unavailable, not wrong -- but "silently unavailable" is still not
    what a fixture claiming to hold a mosaic should ship)."""
    native_copied = 0
    native_bytes = 0
    mip_copied = {level: 0 for level in mip_levels}
    mip_bytes = 0
    for la in lat_cells:
        for lo in lon_cells:
            src = _hgt_path(src_root, la, lo)
            if src is not None:
                dst = dst_root / _ns_dir(la) / f"{tile_name(la, lo)}.hgt"
                dst.parent.mkdir(parents=True, exist_ok=True)
                data = src.read_bytes()
                dst.write_bytes(data)
                native_copied += 1
                native_bytes += len(data)
            for level in mip_levels:
                msrc = _hgt_path(src_root / ".mip" / str(level), la, lo)
                if msrc is None:
                    continue
                mdst = (dst_root / ".mip" / str(level) / _ns_dir(la)
                        / f"{tile_name(la, lo)}.hgt")
                mdst.parent.mkdir(parents=True, exist_ok=True)
                data = msrc.read_bytes()
                mdst.write_bytes(data)
                mip_copied[level] += 1
                mip_bytes += len(data)

    build_terrain_mosaic = _load_tool("build_terrain_mosaic")
    mosaic_meta = {}
    for level in mosaic_levels:
        if mip_copied.get(level, 0) == 0:
            continue     # no mip tiles at this level in the window -> nothing to stitch
        meta = build_terrain_mosaic.build_level(dst_root, level)
        if meta is not None:
            mosaic_meta[level] = meta

    return {
        "native_tiles": native_copied,
        "native_bytes": native_bytes,
        "mip_tiles": mip_copied,
        "mip_bytes": mip_bytes,
        "mosaic_levels": mosaic_meta,
    }


# ---------------------------------------------------------------------------
# water.sqlite
# ---------------------------------------------------------------------------

def cut_water(src_path: Path, dst_path: Path, bbox) -> dict:
    """Bbox-overlap copy of water_polygons/waterway_lines, rtree rebuilt
    from the copied rows -- see WaterDB.polygons_in_range's plain-B-tree
    predicate (water_db.py) for why this exact inequality shape (and not
    a stricter "fully contained" test) is the right cut: a polygon whose
    bbox only partially overlaps the window must still be kept WHOLE, not
    clipped, matching what a real renderer positioned inside the window
    would fetch for it."""
    lat_lo, lat_hi, lon_lo, lon_hi = bbox
    if dst_path.exists():
        dst_path.unlink()
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(dst_path))
    try:
        con.executescript(WATER_SCHEMA)
        con.execute("ATTACH DATABASE ? AS src", (str(src_path),))
        stats = {}
        for table, rtree in (("water_polygons", "water_rtree"),
                              ("waterway_lines", "waterway_rtree")):
            cur = con.execute(
                f"INSERT INTO {table} SELECT * FROM src.{table} "
                "WHERE max_lat > ? AND min_lat < ? "
                "AND max_lon > ? AND min_lon < ?",
                (lat_lo, lat_hi, lon_lo, lon_hi))
            con.execute(
                f"INSERT INTO {rtree} (id, min_lat, max_lat, min_lon, max_lon) "
                f"SELECT id, min_lat, max_lat, min_lon, max_lon FROM {table}")
            stats[table] = cur.rowcount
        stats["vertex_bytes"] = con.execute(
            "SELECT COALESCE(SUM(LENGTH(vertices)), 0) FROM water_polygons"
        ).fetchone()[0]
        stats["vertices"] = stats["vertex_bytes"] // 16
        con.commit()
        con.execute("DETACH DATABASE src")
    finally:
        con.close()
    _vacuum(dst_path)
    return stats


# ---------------------------------------------------------------------------
# highway db
# ---------------------------------------------------------------------------

def cut_highway(src_path: Path, dst_path: Path, bbox) -> dict:
    lat_lo, lat_hi, lon_lo, lon_hi = bbox
    if dst_path.exists():
        dst_path.unlink()
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(dst_path))
    try:
        con.executescript(HIGHWAY_SCHEMA)
        con.execute("ATTACH DATABASE ? AS src", (str(src_path),))
        cur = con.execute(
            "INSERT INTO highway_lines SELECT * FROM src.highway_lines "
            "WHERE max_lat >= ? AND min_lat <= ? "
            "AND max_lon >= ? AND min_lon <= ?",
            (lat_lo, lat_hi, lon_lo, lon_hi))
        n = cur.rowcount
        con.execute(
            "INSERT INTO highway_rtree (id, min_lat, max_lat, min_lon, max_lon) "
            "SELECT id, min_lat, max_lat, min_lon, max_lon FROM highway_lines")
        vertex_bytes = con.execute(
            "SELECT COALESCE(SUM(LENGTH(verts)), 0) FROM highway_lines"
        ).fetchone()[0]
        con.commit()
        con.execute("DETACH DATABASE src")
    finally:
        con.close()
    _vacuum(dst_path)
    return {"highway_lines": n, "vertex_bytes": vertex_bytes,
            "vertices": vertex_bytes // 8}


# ---------------------------------------------------------------------------
# navaid db -- flat lat/lon tables, no rtree (build_navaid_db.py's own
# inline schema; there is no importable SCHEMA constant there to reuse,
# so this mirrors it literally -- keep the two in sync by hand).
# ---------------------------------------------------------------------------

NAVAID_SCHEMA = """
CREATE TABLE navaids (id TEXT, type TEXT, name TEXT, freq TEXT,
                      elev_ft REAL, lat REAL, lon REAL);
CREATE TABLE fixes (id TEXT, use_code TEXT, lat REAL, lon REAL);
CREATE TABLE awy_segments (awy_id TEXT, seq INTEGER,
                           p1 TEXT, lat1 REAL, lon1 REAL,
                           p2 TEXT, lat2 REAL, lon2 REAL);
"""

NAVAID_INDEXES = """
CREATE INDEX idx_nav_ll ON navaids(lat, lon);
CREATE INDEX idx_fix_ll ON fixes(lat, lon);
CREATE INDEX idx_seg_ll ON awy_segments(lat1, lon1);
"""


def cut_navaid(src_path: Path, dst_path: Path, bbox) -> dict:
    """navaids/fixes: plain lat/lon-in-range copy. awy_segments: kept if
    EITHER endpoint falls in the window (mirrors AirwaysLayer's own
    OR-of-two-BETWEENs query, src/pyefis/instruments/map/layers/
    navaids.py) -- an airway that only clips the window's edge must
    still render its segment across it, the same reason water/highway
    rows are kept whole rather than clipped."""
    lat_lo, lat_hi, lon_lo, lon_hi = bbox
    if dst_path.exists():
        dst_path.unlink()
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(dst_path))
    try:
        con.executescript(NAVAID_SCHEMA)
        con.execute("ATTACH DATABASE ? AS src", (str(src_path),))
        stats = {}
        for table in ("navaids", "fixes"):
            cur = con.execute(
                f"INSERT INTO {table} SELECT * FROM src.{table} "
                "WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?",
                (lat_lo, lat_hi, lon_lo, lon_hi))
            stats[table] = cur.rowcount
        cur = con.execute(
            "INSERT INTO awy_segments SELECT * FROM src.awy_segments "
            "WHERE (lat1 BETWEEN ? AND ? AND lon1 BETWEEN ? AND ?) "
            "   OR (lat2 BETWEEN ? AND ? AND lon2 BETWEEN ? AND ?)",
            (lat_lo, lat_hi, lon_lo, lon_hi, lat_lo, lat_hi, lon_lo, lon_hi))
        stats["awy_segments"] = cur.rowcount
        con.commit()
        con.execute("DETACH DATABASE src")
        con.executescript(NAVAID_INDEXES)
        con.commit()
    finally:
        con.close()
    _vacuum(dst_path)
    return stats


def _vacuum(path: Path):
    con = sqlite3.connect(str(path))
    try:
        con.execute("VACUUM")
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Packaging
# ---------------------------------------------------------------------------

def _dir_size(root: Path) -> int:
    return sum(p.stat().st_size for p in root.rglob("*") if p.is_file())


def package(out_dir: Path, dest_tarball: Path) -> tuple[int, str]:
    """tar.gz ``out_dir`` and return (size_bytes, sha256_hex) of the
    archive. Byte-for-byte deterministic given the same file CONTENTS
    (sorted member order; mtime/uid/gid/mode/gzip-header-mtime all
    zeroed) -- so re-cutting from the same source packs reproduces the
    same sha256, which is the whole point of pinning one (AER-1133:
    "reproducible from the real packs with the exact command
    recorded")."""
    import gzip
    dest_tarball.parent.mkdir(parents=True, exist_ok=True)
    members = sorted(p for p in out_dir.rglob("*") if p.is_file())
    with open(dest_tarball, "wb") as raw:
        # filename="" suppresses gzip's embedded original-filename header
        # field (FNAME) -- without it, two tarballs with byte-identical
        # CONTENT still differ because gzip records the destination
        # path's basename, and package() is called with a different
        # dest_tarball name per scene.
        with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0,
                            filename="") as gz:
            with tarfile.open(fileobj=gz, mode="w") as tar:
                for m in members:
                    info = tar.gettarinfo(
                        m, arcname=str(m.relative_to(out_dir)))
                    info.mtime = 0
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    info.mode = 0o644
                    with open(m, "rb") as f:
                        tar.addfile(info, f)
    digest = hashlib.sha256()
    with open(dest_tarball, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    size = dest_tarball.stat().st_size
    return size, digest.hexdigest()


# ---------------------------------------------------------------------------
# cut: one scene, end to end
# ---------------------------------------------------------------------------

def cut_scene(scene: str, tile_root: Path, water_db: Path, highway_db: Path,
              navaid_db: Path, out_dir: Path,
              window_deg: float = WINDOW_DEG,
              max_bytes: int = MAX_PACK_BYTES) -> dict:
    if scene not in SCENES:
        raise PerfFixtureError(
            f"unknown scene {scene!r}; known scenes: {sorted(SCENES)}")
    lat, lon = SCENES[scene]["lat"], SCENES[scene]["lon"]
    lat_lo, lat_hi, lon_lo, lon_hi, lat_cells, lon_cells = window_bbox(
        lat, lon, window_deg)
    bbox = (lat_lo, lat_hi, lon_lo, lon_hi)

    out_dir = Path(out_dir)
    if out_dir.exists() and any(out_dir.iterdir()):
        raise PerfFixtureError(
            f"{out_dir} already has content; remove it first "
            "(refusing to merge into a stale cut)")
    out_dir.mkdir(parents=True, exist_ok=True)

    stats = {"scene": scene, "lat": lat, "lon": lon, "bbox": bbox,
             "window_deg": window_deg}

    stats["terrain"] = cut_terrain(Path(tile_root), out_dir, lat_cells,
                                    lon_cells)
    center_tile = _hgt_path(out_dir, math.floor(lat), math.floor(lon))
    if center_tile is None:
        raise PerfFixtureError(
            f"scene {scene}: the native tile under the scene centre "
            f"({lat}, {lon}) is missing from {tile_root} -- the 2-5 NM "
            "case this pack exists to cover would have no terrain at all. "
            "Check --tile-root, not the window size.")

    stats["water"] = cut_water(Path(water_db), out_dir / "water.sqlite", bbox)
    stats["highway"] = cut_highway(Path(highway_db),
                                    out_dir / "highway.sqlite", bbox)
    stats["navaid"] = cut_navaid(Path(navaid_db), out_dir / "navaids.sqlite",
                                  bbox)

    stats["raw_bytes"] = _dir_size(out_dir)
    if stats["raw_bytes"] > max_bytes:
        raise PerfFixtureError(
            f"scene {scene}: cut pack is {stats['raw_bytes'] / 1e6:.0f} MB, "
            f"over the {max_bytes / 1e6:.0f} MB budget BEFORE tar.gz. "
            "This is a real finding, not a knob to turn: shrinking the "
            "window would slice out the geometry the volume budget is "
            "supposed to gate on. Report the breakdown above and get a "
            "ruling on the number before packaging (issue AER-1133: "
            "'the 200 MB traces to CI fetch time, not to physics').")
    return stats


# ---------------------------------------------------------------------------
# Manifest + fetch
# ---------------------------------------------------------------------------

def _load_manifest(path: Path = MANIFEST_PATH) -> dict:
    if not path.is_file():
        raise PerfFixtureError(f"manifest not found: {path}")
    return json.loads(path.read_text())


def _save_manifest(manifest: dict, path: Path = MANIFEST_PATH):
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def _truthy(value: str | None) -> bool:
    return bool(value) and value.strip().lower() not in ("", "0", "false",
                                                          "no", "off")


def fetch_fixture(scene: str, cache_dir: Path | None = None,
                   manifest_path: Path = MANIFEST_PATH) -> Path | None:
    """Return the extracted fixture directory for ``scene``, or ``None``
    without touching the network when ``PYEFIS_PERF_FIXTURE`` is not
    set -- the "a local run without it must skip cleanly" contract
    (AER-1133). Raises ``PerfFixtureUnavailable`` (not a silent None) if
    the flag IS set but no usable pin exists for this scene, so CI fails
    loudly on a real misconfiguration rather than quietly skipping a
    budget it was told to run."""
    if not _truthy(os.environ.get("PYEFIS_PERF_FIXTURE")):
        return None

    manifest = _load_manifest(manifest_path)
    entry = manifest.get("scenes", {}).get(scene)
    if not entry or not entry.get("sha256") or not entry.get("url"):
        raise PerfFixtureUnavailable(
            f"PYEFIS_PERF_FIXTURE is set but scene {scene!r} has no "
            f"published pin in {manifest_path} yet. Run "
            "`make_map_perf_fixture.py cut --scene "
            f"{scene} --publish` against the real data packs with R2 "
            "credentials, then re-check in the updated manifest.")

    cache_dir = Path(cache_dir or os.environ.get("PYEFIS_FIXTURE_CACHE")
                     or (Path.home() / ".cache" / "pyefis-fixtures"))
    cache_dir.mkdir(parents=True, exist_ok=True)
    tarball = cache_dir / f"{scene}.tar.gz"
    extracted = cache_dir / scene
    sha_marker = cache_dir / f"{scene}.sha256"

    if (extracted.is_dir() and sha_marker.is_file()
            and sha_marker.read_text().strip() == entry["sha256"]):
        return extracted     # already fetched + verified this exact pin

    _download(entry["url"], tarball)
    digest = hashlib.sha256()
    with open(tarball, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    got = digest.hexdigest()
    if got != entry["sha256"]:
        tarball.unlink(missing_ok=True)
        raise PerfFixtureUnavailable(
            f"scene {scene!r}: downloaded tarball sha256 {got} does not "
            f"match the pinned {entry['sha256']} in {manifest_path} -- "
            "not extracting a fixture that does not match its pin.")

    if extracted.is_dir():
        import shutil
        shutil.rmtree(extracted)
    extracted.mkdir(parents=True)
    with tarfile.open(tarball, "r:gz") as tar:
        tar.extractall(extracted, filter="data")
    sha_marker.write_text(entry["sha256"])
    return extracted


def _download(url: str, dest: Path):
    with urllib.request.urlopen(url) as resp, open(dest, "wb") as out:
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cmd_cut(args) -> int:
    stats = cut_scene(args.scene, args.tile_root, args.water_db,
                       args.highway_db, args.navaid_db, args.out,
                       window_deg=args.window_deg, max_bytes=args.max_bytes)
    print(json.dumps(stats, indent=2, default=str))

    tarball = Path(args.out).with_suffix(".tar.gz")
    size, sha256 = package(Path(args.out), tarball)
    print(f"packaged {tarball} : {size / 1e6:.1f} MB  sha256={sha256}")
    if size > args.max_bytes:
        raise PerfFixtureError(
            f"packaged tarball {size / 1e6:.0f} MB exceeds the "
            f"{args.max_bytes / 1e6:.0f} MB budget even though the raw "
            f"directory ({stats['raw_bytes'] / 1e6:.0f} MB) did not -- "
            "unusual (gzip should shrink, not grow); investigate before "
            "publishing.")

    if args.publish:
        _publish(args.scene, tarball, size, sha256)
    else:
        print("(not publishing -- pass --publish to push to R2 and pin "
              "the manifest)")
    return 0


def _publish(scene: str, tarball: Path, size: int, sha256: str) -> bool:
    """Push ``tarball`` to R2 under test-fixtures/<scene>/, mirroring the
    existing wrangler convention in .github/workflows/editor-assets.yml:
    skip cleanly (return False, exit 0) with a warning when credentials
    are absent -- this is a CI-safe no-op, not a failure, on a fork or a
    dev box with no secrets. On success, rewrite this scene's manifest
    entry so fetch_fixture can find it."""
    token = os.environ.get("CLOUDFLARE_API_TOKEN")
    account = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
    if not token or not account:
        print("WARNING: CLOUDFLARE_API_TOKEN/CLOUDFLARE_ACCOUNT_ID not set "
              "-- skipping publish (the pack was still cut and packaged "
              f"locally at {tarball}).")
        return False

    import shutil
    import subprocess
    if shutil.which("npx") is None:
        print("WARNING: npx not found -- skipping publish.")
        return False

    key = f"test-fixtures/{scene}/{scene}.tar.gz"
    cmd = ["npx", "--yes", "wrangler@4", "r2", "object", "put",
           f"makerplane-configs/{key}", "--file", str(tarball),
           "--content-type", "application/gzip", "--remote"]
    print(f"publishing: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)

    url = f"https://makerplane-configs.r2.dev/{key}"
    manifest = (_load_manifest() if MANIFEST_PATH.is_file()
                else {"scenes": {}})
    manifest.setdefault("scenes", {})[scene] = {
        "lat": SCENES[scene]["lat"], "lon": SCENES[scene]["lon"],
        "sha256": sha256, "url": url, "bytes": size,
    }
    _save_manifest(manifest)
    print(f"manifest updated: {MANIFEST_PATH}")
    return True


def _cmd_fetch(args) -> int:
    os.environ.setdefault("PYEFIS_PERF_FIXTURE", "1")
    path = fetch_fixture(args.scene, cache_dir=args.cache_dir)
    if path is None:
        print("PYEFIS_PERF_FIXTURE is unset even after --fetch forced it "
              "on; this should not happen", file=sys.stderr)
        return 1
    print(path)
    return 0


def _parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="command", required=True)

    cut = sub.add_parser("cut", help="cut + package one scene from real packs")
    cut.add_argument("--scene", required=True, choices=sorted(SCENES))
    cut.add_argument("--tile-root", required=True,
                     help="terrain tile tree root (holds <NSdir>/*.hgt "
                          "and .mip/)")
    cut.add_argument("--water-db", required=True)
    cut.add_argument("--highway-db", required=True)
    cut.add_argument("--navaid-db", required=True)
    cut.add_argument("--out", required=True, help="output directory")
    cut.add_argument("--window-deg", type=float, default=WINDOW_DEG)
    cut.add_argument("--max-bytes", type=int, default=MAX_PACK_BYTES)
    cut.add_argument("--publish", action="store_true",
                     help="push the packaged tarball to R2 and pin the "
                          "manifest (skips cleanly with no credentials)")
    cut.set_defaults(func=_cmd_cut)

    fetch = sub.add_parser("fetch", help="fetch + verify a published scene")
    fetch.add_argument("--scene", required=True, choices=sorted(SCENES))
    fetch.add_argument("--cache-dir", default=None)
    fetch.set_defaults(func=_cmd_fetch)

    return ap.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv)
    try:
        return args.func(args)
    except (PerfFixtureError, PerfFixtureUnavailable) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
