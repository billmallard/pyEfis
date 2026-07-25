#!/usr/bin/env python3
"""
Build a water-polygon sqlite database for SVS rendering.

Reads polygons from shapefiles (Natural Earth, OSM water-polygons) or
from a simple text format and writes them to a sqlite database the
WaterDB class can query.

Usage:
    # From shapefiles (requires pyshp):
    python build_water_db.py water.sqlite \\
        --ocean  /path/to/ne_10m_ocean.shp \\
        --lake   /path/to/ne_10m_lakes.shp \\
        --osm-water /path/to/water_polygons.shp

    # From a simple text format (no dependencies — useful on the Pi
    # for hand-crafting a small test dataset):
    python build_water_db.py water.sqlite --text input.txt

    # Waterway centerlines (rivers as lines, issue #39):
    python build_water_db.py water.sqlite \\
        --waterway /path/to/gis_osm_waterways_free_1.shp

Text format:
    # Each polygon starts with a 'P kind [elev_ft]' line, followed by
    # vertex lines 'lat lon', ended with a blank line or EOF.
    P ocean
    34.4  -120.0
    34.4  -119.5
    34.0  -119.5
    34.0  -120.0

    P lake 656
    35.78 -81.30
    35.79 -81.28
    ...
"""

import argparse
import sqlite3
import sys
from pathlib import Path

# Local import; let it fail loudly if the module is wrong.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from pyefis.instruments.ai.water_db import encode_vertices
# Waterway centerlines share the highway store's float32 line format
# (issue #39) — same encoder, so the future reader can share the
# highway decode path.
from pyefis.instruments.ai.highway_db import encode_vertices as encode_line_vertices

# Tessellation library. Pure-data Python interface around the well-
# tested earcut C++ port. Used at build time only; the renderer just
# reads the pre-computed triangle indices from the sqlite BLOB.
import mapbox_earcut as _earcut
import numpy as np


def _index_dtype(n_vertices):
    """Dtype for the ``triangles`` and ``rings`` BLOBs of a row with
    ``n_vertices`` total vertices. uint16 covers indices 0..65534 and
    the final ring-end offset (== n_vertices) up to 65535; past that
    both BLOBs switch to uint32. The reader (water_db.py) applies the
    same threshold to the vertex count it already decodes, so the
    choice is recoverable from the row itself."""
    return np.uint32 if n_vertices > 65535 else np.uint16


def tessellate_polygon(vertices, ring_ends=None):
    """Triangulate a polygon via earcut. Returns a numpy array of
    indices (3 per triangle) into ``vertices``, or None if the
    input is degenerate / fails tessellation.

    ``vertices`` is a list of (lat, lon) tuples — earcut sees them
    as generic 2D points, so lat/lon vs xy doesn't matter at this
    stage. Each output index is in [0, len(vertices)).

    ``ring_ends`` is the earcut ring-end-index list for a multi-ring
    (outer + holes) polygon: ``vertices`` holds the outer ring followed
    by each hole ring, and ``ring_ends[k]`` is the end offset of ring
    k. earcut then subtracts the holes from the fill (#44 — island
    holes must not triangulate as water). None means single ring."""
    if len(vertices) < 3:
        return None
    pts = np.asarray(vertices, dtype=np.float64)
    if ring_ends is None:
        ring_ends = [len(pts)]
    rings = np.asarray(ring_ends, dtype=np.uint32)
    try:
        idx = _earcut.triangulate_float64(pts, rings)
    except Exception:
        return None
    if idx.size == 0 or (idx.size % 3) != 0:
        return None
    # Index dtype is implied by the row's vertex count: uint16 while
    # every index AND ring-end offset fits (<= 65535 vertices), uint32
    # beyond that. The reader derives the identical rule from the
    # vertices BLOB length, so dense rows need no schema flag. The old
    # builder silently DROPPED all holes past the uint16 ceiling — a
    # dense cell like the lower Florida Keys (3,322 island rings) lost
    # every island and #44 persisted there (oracle-gate residual B).
    return idx.astype(_index_dtype(len(vertices)))


SCHEMA = """
CREATE TABLE IF NOT EXISTS water_polygons (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    min_lat   REAL NOT NULL,
    max_lat   REAL NOT NULL,
    min_lon   REAL NOT NULL,
    max_lon   REAL NOT NULL,
    kind      TEXT NOT NULL,
    elev_ft   REAL,
    vertices  BLOB NOT NULL,
    -- Pre-tessellated triangle indices into the ``vertices`` array,
    -- packed little-endian (3 indices per triangle): uint16 for rows
    -- of <= 65535 vertices, uint32 beyond (dense multi-ring cells;
    -- the dtype is implied by the row's vertex count on both the
    -- build and read side). NULL only when tessellation failed at
    -- build time (logged as a warning). The GPU water renderer
    -- uploads these directly to a GL element-array buffer with one
    -- draw call per polygon.
    triangles BLOB,
    -- Ring topology for multi-ring (outer + hole) polygons, packed as
    -- little-endian ring END offsets into ``vertices`` (earcut
    -- convention: outer ring first, then each hole ring; same
    -- uint16/uint32 vertex-count rule as ``triangles``). NULL for
    -- plain single-ring polygons — the overwhelming majority. When
    -- present, ``triangles`` was tessellated hole-aware, so island
    -- holes are excluded from the fill (#44).
    rings     BLOB
);
CREATE INDEX IF NOT EXISTS idx_bbox
    ON water_polygons(min_lat, max_lat, min_lon, max_lon);
CREATE INDEX IF NOT EXISTS idx_kind ON water_polygons(kind);

-- R-Tree spatial index for the bbox query that WaterDB.polygons_in_range
-- does every frame. With the plain B-tree index above, sqlite can only
-- use one inequality predicate efficiently and the query took ~53 ms
-- against the 878k-polygon OSM dataset at KSBA. The R-Tree drops it to
-- sub-millisecond. WaterDB falls back to the B-tree query when this
-- virtual table is missing (older DBs).
CREATE VIRTUAL TABLE IF NOT EXISTS water_rtree USING rtree(
    id,
    min_lat, max_lat,
    min_lon, max_lon
);

-- Waterway centerlines (issue #39): rivers/streams/canals as LINE
-- features, not filled polygons. A winding river cannot survive as a
-- decimated polygon — simplification cuts chords across the meanders
-- and balloons the channel into a lake-blob, which is why the polygon
-- ingest drops 'riverbank' — so the builder imports OSM waterway
-- centerlines here instead. Columns and encoding mirror the highway
-- store (highway_db.py / build_highway_db.py): ``verts`` is
-- little-endian float32 (lat, lon) pairs, one row per polyline part,
-- R-tree indexed for the range query. The tables exist in every new
-- build (empty when --waterway was not given) so a reader can probe
-- by content; old readers that only know water_polygons are
-- unaffected.
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


_M_PER_DEG = 111_320.0
_BASE_TOL_DEG = 40.0 / _M_PER_DEG       # ~40 m — finer than the SVS can resolve


def _rdp(points, tol_deg):
    """Iterative Douglas-Peucker on an (N, 2) lat/lon array. Shape-preserving:
    every simplified edge stays within ``tol_deg`` of the original outline, so
    unlike stride decimation it can never cut a chord across a winding river or
    a branching reservoir and balloon it into a filled blob. (Same algorithm
    the roads build uses — see tools/build_highway_db.py.)"""
    n = len(points)
    if n < 3:
        return points
    keep = np.zeros(n, dtype=bool)
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        a, b = stack.pop()
        if b <= a + 1:
            continue
        seg = points[a:b + 1]
        d = seg[-1] - seg[0]
        L = np.hypot(d[0], d[1])
        if L < 1e-12:
            dist = np.hypot(seg[:, 0] - seg[0, 0], seg[:, 1] - seg[0, 1])
        else:
            dist = np.abs(d[0] * (seg[0, 1] - seg[:, 1])
                          - d[1] * (seg[0, 0] - seg[:, 0])) / L
        i = int(np.argmax(dist))
        if dist[i] > tol_deg:
            keep[a + i] = True
            stack.append((a, a + i))
            stack.append((a + i, b))
    return points[keep]


def _decimate(vertices, max_vertices):
    """Simplify a polygon ring to <= ``max_vertices`` with Douglas-Peucker,
    escalating the tolerance until it fits. Replaces the old stride decimation,
    which connected every Nth perimeter point and, on long/winding/branching
    water features (rivers, reservoir systems), cut chords across the feature
    and rendered a huge solid blob over dry land. The render side
    (WaterDB._decode_vertices) caps at this same 32, so a stored ring already
    <= the cap is never re-decimated (and re-blobbed) at draw time."""
    n = len(vertices)
    if max_vertices is None or n <= max_vertices:
        return vertices
    pts = np.asarray(vertices, dtype=np.float64)
    tol = _BASE_TOL_DEG
    out = pts
    for _ in range(24):                 # escalate tolerance until under the cap
        out = _rdp(pts, tol)
        if len(out) <= max_vertices:
            return [(float(p[0]), float(p[1])) for p in out]
        tol *= 1.6
    # Pathological ring (near-fractal coastline) — DP still over the cap even at
    # a large tolerance; stride the DP-simplified result as a last resort.
    step = (len(out) - 1) / (max_vertices - 1)
    return [(float(out[int(round(k * step))][0]), float(out[int(round(k * step))][1]))
            for k in range(max_vertices)]


def ring_signed_area(vertices):
    """Shoelace signed area of a (lat, lon) ring in degrees^2, computed
    in (x=lon, y=lat) plane coordinates. Shapefile winding convention:
    OUTER rings are clockwise in (x, y) => NEGATIVE signed area; HOLE
    rings (islands) are counter-clockwise => POSITIVE. The winding
    survives our ingest, so it is the outer-vs-hole discriminator."""
    n = len(vertices)
    if n < 3:
        return 0.0
    s = 0.0
    for i in range(n):
        lat1, lon1 = vertices[i]
        lat2, lon2 = vertices[(i + 1) % n]
        s += lon1 * lat2 - lon2 * lat1
    return s / 2.0


def _point_in_ring(lat, lon, ring):
    """Even-odd ray-cast point-in-polygon on a (lat, lon) ring."""
    inside = False
    n = len(ring)
    for i in range(n):
        la1, lo1 = ring[i]
        la2, lo2 = ring[(i + 1) % n]
        if (la1 > lat) != (la2 > lat):
            x = lo1 + (lat - la1) / (la2 - la1) * (lo2 - lo1)
            if x > lon:
                inside = not inside
    return inside


def _ring_interior_points(ring, max_points=3):
    """Up to ``max_points`` points strictly inside a (lat, lon) ring,
    found by even-odd scanline: cut the ring at a constant-lat line,
    sort the edge crossings, take midpoints of the odd (inside) spans.
    Works for concave and even self-intersecting rings — 'inside' is
    exactly the even-odd sense the renderer fills with."""
    lats = [v[0] for v in ring]
    lo, hi = min(lats), max(lats)
    if hi <= lo:
        return []
    pts = []
    n = len(ring)
    for frac in (0.5, 0.3, 0.7):
        lat = lo + (hi - lo) * frac
        xs = []
        for i in range(n):
            la1, lo1 = ring[i]
            la2, lo2 = ring[(i + 1) % n]
            if (la1 > lat) != (la2 > lat):
                xs.append(lo1 + (lat - la1) / (la2 - la1) * (lo2 - lo1))
        xs.sort()
        for k in range(0, len(xs) - 1, 2):
            if xs[k + 1] > xs[k]:
                pts.append((lat, 0.5 * (xs[k] + xs[k + 1])))
                if len(pts) >= max_points:
                    return pts
    return pts


def _triangle_cover_tester(vertices, tri_idx):
    """Build a covered(lat, lon) -> bool closure over a tessellation.
    Triangles are binned into latitude strips so each query tests only
    the local candidates — a dense island cell carries 10^5 triangles
    and the verification sweep visits thousands of points."""
    v = np.asarray(vertices, dtype=np.float64)
    t = np.asarray(tri_idx, dtype=np.int64).reshape(-1, 3)
    if t.size == 0:
        return lambda lat, lon: False
    a, b, c = v[t[:, 0]], v[t[:, 1]], v[t[:, 2]]
    lat_min = np.minimum(np.minimum(a[:, 0], b[:, 0]), c[:, 0])
    lat_max = np.maximum(np.maximum(a[:, 0], b[:, 0]), c[:, 0])
    lon_min = np.minimum(np.minimum(a[:, 1], b[:, 1]), c[:, 1])
    lon_max = np.maximum(np.maximum(a[:, 1], b[:, 1]), c[:, 1])
    strips = min(64, max(1, len(t) // 64))
    lo = float(lat_min.min())
    span = max(float(lat_max.max()) - lo, 1e-12)
    s_lo = np.clip(((lat_min - lo) / span * strips).astype(int),
                   0, strips - 1)
    s_hi = np.clip(((lat_max - lo) / span * strips).astype(int),
                   0, strips - 1)
    bins = [[] for _ in range(strips)]
    for i in range(len(t)):
        for s in range(s_lo[i], s_hi[i] + 1):
            bins[s].append(i)
    bins = [np.asarray(bn, dtype=np.int64) for bn in bins]

    def covered(lat, lon):
        s = int(np.clip((lat - lo) / span * strips, 0, strips - 1))
        cand = bins[s]
        if cand.size == 0:
            return False
        m = ((lat_min[cand] <= lat) & (lat_max[cand] >= lat)
             & (lon_min[cand] <= lon) & (lon_max[cand] >= lon))
        cand = cand[m]
        if cand.size == 0:
            return False
        aa, bb, cc = a[cand], b[cand], c[cand]
        d1 = ((lon - bb[:, 1]) * (aa[:, 0] - bb[:, 0])
              - (aa[:, 1] - bb[:, 1]) * (lat - bb[:, 0]))
        d2 = ((lon - cc[:, 1]) * (bb[:, 0] - cc[:, 0])
              - (bb[:, 1] - cc[:, 1]) * (lat - cc[:, 0]))
        d3 = ((lon - aa[:, 1]) * (cc[:, 0] - aa[:, 0])
              - (cc[:, 1] - aa[:, 1]) * (lat - aa[:, 0]))
        neg = (d1 < 0) | (d2 < 0) | (d3 < 0)
        pos = (d1 > 0) | (d2 > 0) | (d3 > 0)
        return bool((~(neg & pos)).any())

    return covered


def _covered_hole_indices(all_verts, ring_ends, tri_idx):
    """Indices (into the hole list) of hole rings whose interior is
    covered by the row's fill triangles — the residual-A defect class
    of #44: decimation can hand earcut a self-intersecting or outer-
    crossing hole, and earcut then fills it instead of subtracting
    it. Judged on the STORED rings and triangles, i.e. exactly what
    the renderer will draw."""
    if len(ring_ends) <= 1:
        return []
    covered = _triangle_cover_tester(all_verts, tri_idx)
    bad = []
    for k in range(1, len(ring_ends)):
        ring = all_verts[ring_ends[k - 1]:ring_ends[k]]
        if any(covered(lat, lon)
               for lat, lon in _ring_interior_points(ring)):
            bad.append(k - 1)
    return bad


def _strip_hole_triangles(all_verts, ring_ends, tri_idx):
    """Last-resort repair when even the raw source rings tessellate
    with covered holes: drop fill triangles whose centroid lies inside
    any hole ring (even-odd). Biased toward land — for an EFIS,
    painting an island as water is the dangerous direction (#44)."""
    v = np.asarray(all_verts, dtype=np.float64)
    t = np.asarray(tri_idx, dtype=np.int64).reshape(-1, 3)
    clat = (v[t[:, 0], 0] + v[t[:, 1], 0] + v[t[:, 2], 0]) / 3.0
    clon = (v[t[:, 0], 1] + v[t[:, 1], 1] + v[t[:, 2], 1]) / 3.0
    keep = np.ones(len(t), dtype=bool)
    for k in range(1, len(ring_ends)):
        ring = all_verts[ring_ends[k - 1]:ring_ends[k]]
        rlats = [p[0] for p in ring]
        rlons = [p[1] for p in ring]
        m = ((clat >= min(rlats)) & (clat <= max(rlats))
             & (clon >= min(rlons)) & (clon <= max(rlons)) & keep)
        for i in np.nonzero(m)[0]:
            if _point_in_ring(clat[i], clon[i], ring):
                keep[i] = False
    return t[keep].reshape(-1)


def group_rings(rings):
    """Group a shape's rings into (outer, [holes]) pairs by winding +
    containment, so holes (islands) can be subtracted from their outer
    ring's fill instead of being emitted as filled water (#44).

    - A single-ring shape is always an outer, regardless of winding —
      preserves every existing single-ring source (Natural Earth lakes,
      the text format) that may not follow shapefile winding.
    - Multi-ring: negative signed area (CW) = outer, positive = hole.
      Each hole is assigned to the smallest outer whose bbox and even-odd
      interior contain the hole's first vertex — smallest-first handles
      nesting (lake on an island in a lake).
    - Anomalies fall back to the pre-#44 fill-everything behavior:
      a shape with no CW ring treats all rings as outers (reversed-
      winding source); a hole with no containing outer is DROPPED
      (never filled — filling holes is exactly the #44 bug).

    Returns (groups, orphan_holes) where groups is a list of
    (outer_ring, [hole_rings]) and orphan_holes counts dropped holes."""
    rings = [r for r in rings if len(r) >= 3]
    if not rings:
        return [], 0
    if len(rings) == 1:
        return [(rings[0], [])], 0
    areas = [ring_signed_area(r) for r in rings]
    outers = [(r, abs(a)) for r, a in zip(rings, areas) if a < 0]
    holes = [r for r, a in zip(rings, areas) if a >= 0]
    if not outers:
        # Reversed-winding (or degenerate) source — fill every ring,
        # exactly what the pre-#44 ingest did.
        return [(r, []) for r in rings], 0
    outers.sort(key=lambda t: t[1])          # smallest first
    groups = {id(r): (r, []) for r, _ in outers}
    orphans = 0
    for hole in holes:
        hlat, hlon = hole[0]
        placed = False
        for outer, _ in outers:
            lats = [v[0] for v in outer]
            lons = [v[1] for v in outer]
            if not (min(lats) <= hlat <= max(lats)
                    and min(lons) <= hlon <= max(lons)):
                continue
            if _point_in_ring(hlat, hlon, outer):
                groups[id(outer)][1].append(hole)
                placed = True
                break
        if not placed:
            orphans += 1
    return list(groups.values()), orphans


# Escalation bound for the per-ring decimation cap when hole
# verification fails: the cap doubles up to this value, then the raw
# source rings are used. Bounded so a pathological shape cannot loop.
_MAX_ESCALATED_CAP = 512


def insert_polygon(con, kind, elev_ft, vertices, max_vertices=None,
                   holes=None, stats=None):
    """Insert one water polygon: ``vertices`` is the OUTER ring,
    ``holes`` an optional list of interior (island) rings subtracted
    from the fill. Returns False if the outer ring is degenerate.

    Multi-ring rows are VERIFIED after tessellation: every hole ring
    must keep its interior clear of the row's fill triangles. The
    per-ring decimation runs before earcut sees the rings, and an
    aggressively simplified ring can self-intersect or cross its outer
    ring — earcut then fills the hole instead of subtracting it
    (oracle-gate residual A of #44: 54/770 hole interiors covered in
    a Keys probe build). On a failed verification the decimation cap
    escalates (doubling up to _MAX_ESCALATED_CAP, then the raw source
    rings); if the raw rings still fail, fill triangles whose centroid
    lands in a hole are stripped as a last resort — biased toward
    land, since painting an island as water is the dangerous direction
    for an EFIS. ``stats`` (a dict, optional) accumulates 'escalated'
    / 'stripped' / 'unresolved' row counts for the caller's summary."""
    if len(vertices) < 3:
        return False
    src_holes = [h for h in (holes or []) if len(h) >= 3]
    cap = max_vertices
    escalated = stripped = unresolved = False
    while True:
        # Decimate at build time so the BLOBs stored on disk are small.
        # Reading a 50-100 KB BLOB per polygon at query time was the
        # dominant cost in the perf log; with a 32-vertex cap each BLOB
        # is ~512 bytes and the query is bound by index scanning rather
        # than disk I/O. Multi-ring: the cap applies PER RING (outer and
        # each hole) — the reader skips its own decimation for multi-ring
        # rows, so the build-time cap is the only bound.
        out_ring = _decimate(vertices, cap)
        dec_holes = [h for h in (_decimate(h, cap) for h in src_holes)
                     if len(h) >= 3]
        all_verts = list(out_ring)
        ring_ends = [len(out_ring)]
        for h in dec_holes:
            all_verts.extend(h)
            ring_ends.append(len(all_verts))
        # Pre-tessellate. The renderer reads these indices directly
        # into a GL element-array buffer at draw time — keeps per-frame
        # Python work down to a buffer upload + glDrawElements call.
        # Hole-aware: earcut subtracts the hole rings so islands are
        # not filled (#44). Rows past 65535 vertices store uint32
        # indices instead of losing their holes (the old drop-the-holes
        # fallback re-created #44 in exactly the densest island cells).
        tri_idx = tessellate_polygon(all_verts,
                                     ring_ends if dec_holes else None)
        if not src_holes:
            break               # single-ring rows: nothing to verify
        if (tri_idx is not None
                and not _covered_hole_indices(all_verts, ring_ends,
                                              tri_idx)):
            break               # verified: every hole interior is dry
        if cap is not None:
            cap = cap * 2 if cap * 2 <= _MAX_ESCALATED_CAP else None
            escalated = True
            continue
        # Raw source rings and the fill still covers a hole (or earcut
        # refused the ring set outright).
        if tri_idx is None:
            # Store the outer ring alone rather than a multi-ring
            # vertex blob without triangles, which would draw garbage
            # through the renderer's fan fallback.
            all_verts = list(out_ring)
            ring_ends = [len(out_ring)]
            dec_holes = []
            tri_idx = tessellate_polygon(all_verts)
            unresolved = True
        else:
            tri_idx = _strip_hole_triangles(all_verts, ring_ends,
                                            tri_idx)
            stripped = True
            if _covered_hole_indices(all_verts, ring_ends, tri_idx):
                unresolved = True
        break
    if stats is not None and src_holes:
        for flag, key in ((escalated, "escalated"),
                          (stripped, "stripped"),
                          (unresolved, "unresolved")):
            if flag:
                stats[key] = stats.get(key, 0) + 1
    if unresolved:
        print("  WARNING: hole verification unresolved for a "
              f"{len(src_holes)}-hole polygon near "
              f"({vertices[0][0]:.3f}, {vertices[0][1]:.3f}) — "
              "some island interior may render as water",
              file=sys.stderr)
    # The bbox is the outer ring's — holes lie inside it by definition.
    lats = [v[0] for v in out_ring]
    lons = [v[1] for v in out_ring]
    min_lat, max_lat = min(lats), max(lats)
    min_lon, max_lon = min(lons), max(lons)
    idx_dtype = _index_dtype(len(all_verts))
    tri_blob = (np.asarray(tri_idx, dtype=idx_dtype).tobytes()
                if tri_idx is not None else None)
    rings_blob = (np.asarray(ring_ends, dtype=idx_dtype).tobytes()
                  if dec_holes else None)
    cur = con.execute(
        "INSERT INTO water_polygons "
        "(min_lat, max_lat, min_lon, max_lon, kind, elev_ft, "
        " vertices, triangles, rings) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (min_lat, max_lat, min_lon, max_lon,
         kind, elev_ft, encode_vertices(all_verts), tri_blob, rings_blob))
    con.execute(
        "INSERT INTO water_rtree (id, min_lat, max_lat, min_lon, max_lon) "
        "VALUES (?, ?, ?, ?, ?)",
        (cur.lastrowid, min_lat, max_lat, min_lon, max_lon))
    return True


def ring_area_km2(vertices):
    """Approximate area (km^2) of a (lat, lon) ring via the shoelace formula,
    scaled to km at the ring's mean latitude. Good enough to size-filter."""
    import math
    n = len(vertices)
    if n < 3:
        return 0.0
    lat0 = sum(v[0] for v in vertices) / n
    s = 0.0
    for i in range(n):
        lat1, lon1 = vertices[i]
        lat2, lon2 = vertices[(i + 1) % n]
        s += lon1 * lat2 - lon2 * lat1
    area_deg2 = abs(s) / 2.0
    return area_deg2 * 110.574 * (111.320 * math.cos(math.radians(lat0)))


def import_shapefile(con, path, kind, max_vertices, elev_ft=None,
                     min_area_km2=0.0, keep_fclass=None):
    """Import every polygon from a shapefile into the water_polygons
    table. Multi-ring shapes are grouped by winding + containment
    (``group_rings``): one row per OUTER ring, with its interior (hole)
    rings stored alongside and subtracted from the tessellated fill —
    a hole ring is never emitted as its own filled polygon (#44).
    Outer rings smaller than ``min_area_km2`` are skipped (declutters
    tiny ponds; 0 disables; holes are never size-filtered — dropping a
    hole fills its island).

    ``keep_fclass`` (a set of OSM feature classes) keeps only those classes
    when the shapefile has an ``fclass`` field — used to keep still open water
    (``water``, ``reservoir``) and drop ``riverbank`` (rivers render as filled
    lake-blobs, not rivers) and ``wetland*``. Shapefiles without an ``fclass``
    field (the ocean coastline) are never filtered."""
    try:
        import shapefile  # pyshp
    except ImportError:
        print("ERROR: shapefile import requires pyshp (`pip install pyshp`)",
              file=sys.stderr)
        sys.exit(2)

    sf = shapefile.Reader(str(path))
    fields = [f[0] for f in sf.fields[1:]]
    fclass_idx = fields.index("fclass") if "fclass" in fields else None
    use_fclass = bool(keep_fclass) and fclass_idx is not None
    n = 0
    dropped = 0
    fc_dropped = 0
    holes_kept = 0
    orphan_holes = 0
    hole_stats = {}
    records = sf.iterShapeRecords() if use_fclass else (
        (shape, None) for shape in sf.shapes())
    for item in records:
        shape = item.shape if use_fclass else item[0]
        if use_fclass and item.record[fclass_idx] not in keep_fclass:
            fc_dropped += 1
            continue
        if not shape.points:
            continue
        # shape.parts marks the start of each ring; split ring by ring,
        # then group outer rings with their holes by winding (#44).
        parts = list(shape.parts) + [len(shape.points)]
        rings = []
        for k in range(len(parts) - 1):
            ring = shape.points[parts[k]:parts[k + 1]]
            # Shapefile stores (lon, lat); we want (lat, lon).
            rings.append([(p[1], p[0]) for p in ring])
        groups, orphans = group_rings(rings)
        orphan_holes += orphans
        for outer, holes in groups:
            if min_area_km2 > 0 and ring_area_km2(outer) < min_area_km2:
                dropped += 1
                continue
            if insert_polygon(con, kind, elev_ft, outer, max_vertices,
                              holes=holes, stats=hole_stats):
                n += 1
                holes_kept += len(holes)
    notes = []
    if dropped:
        notes.append(f"{dropped} below {min_area_km2} km^2")
    if fc_dropped:
        notes.append(f"{fc_dropped} off-class")
    if orphan_holes:
        notes.append(f"{orphan_holes} orphan hole(s)")
    extra = f" ({', '.join(notes)} dropped)" if notes else ""
    holes_note = f" (+{holes_kept} island hole(s))" if holes_kept else ""
    verify_bits = [f"{hole_stats[k]} {label}" for k, label in
                   (("escalated", "row(s) escalated past the cap"),
                    ("stripped", "row(s) strip-repaired"),
                    ("unresolved", "row(s) UNRESOLVED"))
                   if hole_stats.get(k)]
    vnote = f" [hole verify: {', '.join(verify_bits)}]" if verify_bits else ""
    print(f"  {Path(path).name}: imported {n} polygon(s) as "
          f"kind={kind}{holes_note}{extra}{vnote}")
    return n


# Default OSM waterway classes kept by --waterway. Matches issue #39
# (waterway=river/stream/canal) and the moving map's rivers preset
# (tools/build_highway_db.py PRESETS["rivers"]); drain/ditch are noise
# at EFIS scale. Override with --waterway-classes.
WATERWAY_CLASSES = ("river", "canal", "stream")


def import_waterways(con, path, tol_deg, keep_classes):
    """Import OSM waterway CENTERLINES from a polyline shapefile
    (Geofabrik ``gis_osm_waterways_free_1``) into the waterway_lines
    table — rivers as lines, not polygons (#39).

    Douglas-Peucker on a polyline is shape-preserving (no fill to
    corrupt), so the meander-blob failure that makes river POLYGONS
    undrawable does not apply here. Multi-part shapes split into one
    row per part, mirroring the highway build. Renderer wiring is
    deliberately not part of this importer."""
    try:
        import shapefile  # pyshp
    except ImportError:
        print("ERROR: shapefile import requires pyshp (`pip install pyshp`)",
              file=sys.stderr)
        sys.exit(2)

    sf = shapefile.Reader(str(path))
    fields = [f[0] for f in sf.fields[1:]]
    if "fclass" not in fields:
        print(f"ERROR: {Path(path).name} has no 'fclass' field — expected "
              "an OSM waterways layer (gis_osm_waterways_free_1)",
              file=sys.stderr)
        sys.exit(2)
    fclass_idx = fields.index("fclass")
    keep = set(keep_classes)
    next_id = con.execute(
        "SELECT COALESCE(MAX(id), 0) FROM waterway_lines").fetchone()[0] + 1
    n = 0
    fc_dropped = 0
    for sr in sf.iterShapeRecords():
        fclass = sr.record[fclass_idx]
        if fclass not in keep:
            fc_dropped += 1
            continue
        if not sr.shape.points:
            continue
        pts = np.asarray(sr.shape.points, dtype=np.float64)
        parts = list(sr.shape.parts) + [len(pts)]
        for a, b in zip(parts[:-1], parts[1:]):
            seg = pts[a:b]
            if len(seg) < 2:
                continue
            # Shapefile stores (lon, lat); we store (lat, lon).
            latlon = np.column_stack([seg[:, 1], seg[:, 0]])
            latlon = _rdp(latlon, tol_deg)
            min_lat = float(latlon[:, 0].min())
            max_lat = float(latlon[:, 0].max())
            min_lon = float(latlon[:, 1].min())
            max_lon = float(latlon[:, 1].max())
            con.execute(
                "INSERT INTO waterway_lines "
                "(id, fclass, min_lat, max_lat, min_lon, max_lon, verts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (next_id, fclass, min_lat, max_lat, min_lon, max_lon,
                 encode_line_vertices(latlon)))
            con.execute(
                "INSERT INTO waterway_rtree "
                "(id, min_lat, max_lat, min_lon, max_lon) "
                "VALUES (?, ?, ?, ?, ?)",
                (next_id, min_lat, max_lat, min_lon, max_lon))
            next_id += 1
            n += 1
    extra = f" ({fc_dropped} off-class dropped)" if fc_dropped else ""
    print(f"  {Path(path).name}: imported {n} waterway line(s){extra}")
    return n


def import_text(con, path, max_vertices):
    """Import polygons from the documented text format."""
    cur_kind = None
    cur_elev = None
    cur_verts: list = []
    n = 0

    def flush():
        nonlocal cur_verts, n
        if cur_kind and len(cur_verts) >= 3:
            if insert_polygon(con, cur_kind, cur_elev, cur_verts, max_vertices):
                n += 1
        cur_verts = []

    with open(path, "r") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                if line == "":
                    flush()
                continue
            if line.startswith("P "):
                flush()
                parts = line.split()
                cur_kind = parts[1].lower()
                cur_elev = float(parts[2]) if len(parts) >= 3 else None
            else:
                lat_s, lon_s = line.split()
                cur_verts.append((float(lat_s), float(lon_s)))
    flush()
    print(f"  {Path(path).name}: imported {n} polygon(s)")
    return n


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("output", help="sqlite output path")
    p.add_argument("--ocean", action="append", default=[],
                   help="ocean shapefile (no surface elev; SRTM may be 0/void)")
    p.add_argument("--lake", action="append", default=[],
                   help="lake shapefile; elev sampled from SRTM at render time")
    p.add_argument("--river", action="append", default=[],
                   help="river polygon shapefile")
    p.add_argument("--osm-water", action="append", default=[],
                   help="generic OSM water shapefile (kind='water')")
    p.add_argument("--text", action="append", default=[],
                   help="text-format polygon file (see module docstring)")
    p.add_argument("--waterway", action="append", default=[],
                   help="OSM waterway LINE shapefile (Geofabrik "
                        "gis_osm_waterways_free_1); imports river/canal/"
                        "stream centerlines into the waterway_lines "
                        "polyline table (#39) instead of the polygon store")
    p.add_argument("--waterway-classes", nargs="*", default=None,
                   help="waterway fclass values to keep (default: "
                        + " ".join(WATERWAY_CLASSES) + ")")
    p.add_argument("--waterway-tolerance-m", type=float, default=40.0,
                   help="Douglas-Peucker tolerance (metres) for waterway "
                        "centerlines; matches the highway build default. "
                        "Polyline decimation is shape-preserving, so this "
                        "only drops sub-resolution jitter")
    p.add_argument("--max-vertices", type=int, default=32,
                   help="cap polygons to this many vertices via stride "
                        "decimation; on-disk BLOBs shrink ~150x for OSM "
                        "coastlines and per-frame water.query goes from "
                        "~50ms to under 1ms. Default 32 (matches "
                        "WaterDB.DEFAULT_MAX_VERTICES). Pass 0 to disable.")
    p.add_argument("--min-area-km2", type=float, default=0.0,
                   help="drop inland-water rings smaller than this area "
                        "(km^2) to declutter tiny ponds. Applies to "
                        "--lake/--river/--osm-water only; the ocean layer "
                        "is never filtered (coastline integrity). Default "
                        "0 disables filtering.")
    p.add_argument("--keep-fclass", nargs="*", default=None,
                   help="for OSM shapefiles with an 'fclass' field, keep only "
                        "these classes (e.g. water reservoir). Drops 'riverbank' "
                        "(rivers fill as lake-blobs) and 'wetland*'. The ocean "
                        "layer (no fclass) is unaffected. Omit to keep all.")
    p.add_argument("--ocean-max-vertices", type=int, default=None,
                   help="vertex cap for the --ocean (coastline) layer; defaults "
                        "to --max-vertices, which is the recommendation -- ocean "
                        "should match inland. Coastlines DO need the detail: a low "
                        "cap smooths coastal bays/inlets into land (at cap 32 the "
                        "Baie de Gaspe rendered as land). Only ~1 in 100 ocean "
                        "polygons are complex enough to use the cap; open ocean "
                        "simplifies to a few verts regardless, so matching the "
                        "inland cap is nearly free (~+10pct).")
    args = p.parse_args()
    max_verts = args.max_vertices if args.max_vertices > 0 else None
    ov = args.ocean_max_vertices if args.ocean_max_vertices is not None else args.max_vertices
    ocean_verts = ov if ov > 0 else None
    min_area = args.min_area_km2
    keep_fclass = set(args.keep_fclass) if args.keep_fclass else None

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    con = sqlite3.connect(str(out))
    con.executescript(SCHEMA)

    total = 0
    for path in args.ocean:
        total += import_shapefile(con, path, "ocean", ocean_verts)
    for path in args.lake:
        total += import_shapefile(con, path, "lake", max_verts,
                                  min_area_km2=min_area, keep_fclass=keep_fclass)
    for path in args.river:
        total += import_shapefile(con, path, "river", max_verts,
                                  min_area_km2=min_area, keep_fclass=keep_fclass)
    for path in args.osm_water:
        total += import_shapefile(con, path, "water", max_verts,
                                  min_area_km2=min_area, keep_fclass=keep_fclass)
    for path in args.text:
        total += import_text(con, path, max_verts)
    waterway_classes = (args.waterway_classes if args.waterway_classes
                        else WATERWAY_CLASSES)
    lines = 0
    for path in args.waterway:
        lines += import_waterways(con, path,
                                  args.waterway_tolerance_m / _M_PER_DEG,
                                  waterway_classes)
    con.commit()
    con.close()
    filt = f", min-area={min_area} km^2" if min_area > 0 else ""
    ocn = f", ocean cap={ocean_verts}" if ocean_verts != max_verts else ""
    wline = f", {lines} waterway lines" if args.waterway else ""
    print(f"-> {out} ({total} polygons{wline}, "
          f"vertex cap={max_verts}{ocn}{filt})")


if __name__ == "__main__":
    main()
