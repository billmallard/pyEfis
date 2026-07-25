#  SPDX-License-Identifier: GPL-2.0-or-later
"""Tests for tools/build_water_db.py -- issue #44 island holes.

An island is an interior (hole) ring of a water multipolygon. The old
ingest emitted EVERY ring as its own filled polygon and tessellated
single-ring only, so an island was painted as water twice over: the
outer ring's fill covered it, and its own coastline became a filled
ocean polygon (KEYW / Florida Keys, issue #44). These tests prove the
builder now preserves ring topology: winding classification, hole
grouping, hole-aware tessellation (an interior-ring point is NOT
covered by the stored triangles; a surrounding-water point IS), and
that a hole ring is never emitted as its own row.

Plain pytest + tmp_path. mapbox_earcut is a build-time-only dep (the
``watertools`` extra); the whole module skips without it.
"""

import importlib.util
import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("mapbox_earcut",
                    reason="build-time tessellation dependency")

_ROOT = Path(__file__).resolve().parents[2]


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, _ROOT / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bw = _load("build_water_db")


# Synthetic island-in-water multipolygon around the Florida Keys.
# Shapefile winding convention in (x=lon, y=lat): outer ring clockwise
# (negative shoelace signed area), hole ring counter-clockwise
# (positive). The hole is the island.
OUTER_CW = [(24.0, -82.5), (25.0, -82.5), (25.0, -81.0), (24.0, -81.0)]
HOLE_CCW = [(24.5, -81.8), (24.5, -81.7), (24.6, -81.7), (24.6, -81.8)]
ISLAND_PT = (24.55, -81.75)     # interior of the hole -- must be LAND
WATER_PT = (24.2, -82.0)        # inside outer, outside hole -- water


def _open_db(tmp_path):
    path = tmp_path / "water.sqlite"
    con = sqlite3.connect(str(path))
    con.executescript(bw.SCHEMA)
    return path, con


def _fetch_rows(path):
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT kind, vertices, triangles, rings "
        "FROM water_polygons").fetchall()
    con.close()
    return rows


def _decode(row):
    from pyefis.instruments.ai.water_db import (
        _decode_rings, _decode_triangles, _decode_vertices)
    n_verts = len(row["vertices"]) // 16
    return (_decode_vertices(row["vertices"]),
            _decode_triangles(row["triangles"], n_verts),
            _decode_rings(row["rings"], n_verts))


def _covered_points_mask(points, vertices, triangles):
    """Vectorized ``_covered_by_triangles`` for large sweeps: a boolean
    per (lat, lon) point, True when any stored fill triangle covers it.
    Per-triangle bboxes prefilter the exact sign tests so a full sweep
    of a dense cell (10^5 triangles) stays test-suite fast."""
    import numpy as np
    v = np.asarray(vertices, dtype=np.float64)
    t = np.asarray(triangles, dtype=np.int64).reshape(-1, 3)
    a, b, c = v[t[:, 0]], v[t[:, 1]], v[t[:, 2]]
    lat_min = np.minimum(np.minimum(a[:, 0], b[:, 0]), c[:, 0])
    lat_max = np.maximum(np.maximum(a[:, 0], b[:, 0]), c[:, 0])
    lon_min = np.minimum(np.minimum(a[:, 1], b[:, 1]), c[:, 1])
    lon_max = np.maximum(np.maximum(a[:, 1], b[:, 1]), c[:, 1])
    out = np.zeros(len(points), dtype=bool)
    for i, (lat, lon) in enumerate(points):
        cand = np.nonzero((lat_min <= lat) & (lat_max >= lat)
                          & (lon_min <= lon) & (lon_max >= lon))[0]
        if cand.size == 0:
            continue
        aa, bb, cc = a[cand], b[cand], c[cand]
        d1 = ((lon - bb[:, 1]) * (aa[:, 0] - bb[:, 0])
              - (aa[:, 1] - bb[:, 1]) * (lat - bb[:, 0]))
        d2 = ((lon - cc[:, 1]) * (bb[:, 0] - cc[:, 0])
              - (bb[:, 1] - cc[:, 1]) * (lat - cc[:, 0]))
        d3 = ((lon - aa[:, 1]) * (cc[:, 0] - aa[:, 0])
              - (cc[:, 1] - aa[:, 1]) * (lat - aa[:, 0]))
        neg = (d1 < 0) | (d2 < 0) | (d3 < 0)
        pos = (d1 > 0) | (d2 > 0) | (d3 > 0)
        out[i] = bool((~(neg & pos)).any())
    return out


def _covered_by_triangles(lat, lon, vertices, triangles):
    """True when (lat, lon) lies inside any stored fill triangle --
    the exact question the GPU renderer answers, since it draws the
    pre-tessellated triangles and nothing else."""
    for t in range(0, len(triangles), 3):
        (y1, x1) = vertices[triangles[t]]
        (y2, x2) = vertices[triangles[t + 1]]
        (y3, x3) = vertices[triangles[t + 2]]
        d1 = (lon - x2) * (y1 - y2) - (x1 - x2) * (lat - y2)
        d2 = (lon - x3) * (y2 - y3) - (x2 - x3) * (lat - y3)
        d3 = (lon - x1) * (y3 - y1) - (x3 - x1) * (lat - y1)
        neg = (d1 < 0) or (d2 < 0) or (d3 < 0)
        pos = (d1 > 0) or (d2 > 0) or (d3 > 0)
        if not (neg and pos):
            return True
    return False


class TestRingClassification:
    def test_shapefile_winding_signs(self):
        # Outer = CW in (lon, lat) = negative signed area; hole = CCW
        # = positive. This is the discriminator the whole fix rests on.
        assert bw.ring_signed_area(OUTER_CW) < 0
        assert bw.ring_signed_area(HOLE_CCW) > 0

    def test_hole_grouped_under_containing_outer(self):
        groups, orphans = bw.group_rings([OUTER_CW, HOLE_CCW])
        assert orphans == 0
        assert len(groups) == 1
        outer, holes = groups[0]
        assert outer == OUTER_CW
        assert holes == [HOLE_CCW]

    def test_orphan_hole_is_dropped_not_filled(self):
        # A hole outside every outer must vanish -- emitting it filled
        # is exactly the #44 bug.
        far_hole = [(30.5, -70.8), (30.5, -70.7),
                    (30.6, -70.7), (30.6, -70.8)]
        groups, orphans = bw.group_rings([OUTER_CW, far_hole])
        assert orphans == 1
        assert groups == [(OUTER_CW, [])]

    def test_single_ring_is_outer_regardless_of_winding(self):
        # Natural Earth lakes / the text format don't guarantee
        # shapefile winding; a lone ring always fills.
        groups, orphans = bw.group_rings([HOLE_CCW])
        assert orphans == 0
        assert groups == [(HOLE_CCW, [])]

    def test_all_ccw_shape_falls_back_to_fill_everything(self):
        # Reversed-winding source: no CW ring at all. Fill every ring
        # (the pre-#44 behavior) rather than dropping the shape.
        a = [(24.5, -81.8), (24.5, -81.7), (24.6, -81.7), (24.6, -81.8)]
        b = [(25.5, -80.8), (25.5, -80.7), (25.6, -80.7), (25.6, -80.8)]
        groups, orphans = bw.group_rings([a, b])
        assert orphans == 0
        assert sorted(map(id, (g[0] for g in groups))) == \
            sorted(map(id, [a, b]))
        assert all(h == [] for _, h in groups)

    def test_nested_hole_goes_to_smallest_outer(self):
        # Lake (outer) on an island (hole) in the sea (outer): the
        # island's pond-hole belongs to the small lake outer, not the
        # ocean outer that also contains it.
        lake_cw = [(24.52, -81.78), (24.58, -81.78),
                   (24.58, -81.72), (24.52, -81.72)]
        pond_hole = [(24.54, -81.76), (24.54, -81.74),
                     (24.56, -81.74), (24.56, -81.76)]
        groups, orphans = bw.group_rings([OUTER_CW, lake_cw, pond_hole])
        assert orphans == 0
        by_outer = {id(o): h for o, h in groups}
        assert by_outer[id(lake_cw)] == [pond_hole]
        assert by_outer[id(OUTER_CW)] == []


class TestIslandNotFilled:
    """The #44 acceptance test: after the build, the island interior
    is NOT covered by the stored water fill and the surrounding ring
    IS -- judged on the tessellated triangles, which are exactly what
    the GPU renderer draws."""

    def test_hole_excluded_from_fill_and_not_its_own_row(self, tmp_path):
        path, con = _open_db(tmp_path)
        assert bw.insert_polygon(con, "ocean", None, OUTER_CW,
                                 max_vertices=32, holes=[HOLE_CCW])
        con.commit()
        con.close()

        rows = _fetch_rows(path)
        # Mechanism 2 of #44: the hole must NOT appear as its own
        # filled polygon row.
        assert len(rows) == 1
        verts, tris, rings = _decode(rows[0])
        assert rings is not None and len(rings) == 2
        assert tris is not None
        # Mechanism 1 of #44: the outer fill must exclude the hole.
        assert not _covered_by_triangles(*ISLAND_PT, verts, tris)
        assert _covered_by_triangles(*WATER_PT, verts, tris)

    def test_single_ring_row_stores_no_rings_blob(self, tmp_path):
        path, con = _open_db(tmp_path)
        assert bw.insert_polygon(con, "ocean", None, OUTER_CW,
                                 max_vertices=32)
        con.commit()
        con.close()
        rows = _fetch_rows(path)
        assert len(rows) == 1
        verts, tris, rings = _decode(rows[0])
        assert rings is None
        assert _covered_by_triangles(*ISLAND_PT, verts, tris)  # no hole

    def test_per_ring_decimation_keeps_topology(self, tmp_path):
        # A many-vertex outer ring decimates to the cap; the hole ring
        # survives as a distinct ring and its interior stays dry.
        import math
        n = 240
        dense_outer = [(24.5 + 0.5 * math.sin(2 * math.pi * k / n),
                        -81.75 + 0.75 * math.cos(2 * math.pi * k / n))
                       for k in range(n)]
        if bw.ring_signed_area(dense_outer) > 0:
            dense_outer.reverse()
        path, con = _open_db(tmp_path)
        assert bw.insert_polygon(con, "ocean", None, dense_outer,
                                 max_vertices=32, holes=[HOLE_CCW])
        con.commit()
        con.close()
        verts, tris, rings = _decode(_fetch_rows(path)[0])
        assert rings is not None and len(rings) == 2
        assert rings[0] <= 32                     # outer capped per-ring
        assert rings[1] == len(verts)
        assert not _covered_by_triangles(*ISLAND_PT, verts, tris)
        assert _covered_by_triangles(*WATER_PT, verts, tris)


class TestShapefileImport:
    def test_multi_ring_shapefile_end_to_end(self, tmp_path):
        shapefile = pytest.importorskip(
            "shapefile", reason="pyshp is a build-time-only dependency")
        shp = tmp_path / "ocean"
        w = shapefile.Writer(str(shp), shapeType=shapefile.POLYGON)
        w.field("id", "N")
        # pyshp wants (lon, lat) parts; winding as stored above.
        w.poly([[(lon, lat) for lat, lon in OUTER_CW + OUTER_CW[:1]],
                [(lon, lat) for lat, lon in HOLE_CCW + HOLE_CCW[:1]]])
        w.record(1)
        w.close()

        path, con = _open_db(tmp_path)
        n = bw.import_shapefile(con, str(shp) + ".shp", "ocean", 32)
        con.commit()
        con.close()
        assert n == 1
        rows = _fetch_rows(path)
        assert len(rows) == 1                    # hole is not its own row
        verts, tris, rings = _decode(rows[0])
        assert rings is not None
        assert not _covered_by_triangles(*ISLAND_PT, verts, tris)
        assert _covered_by_triangles(*WATER_PT, verts, tris)

    def test_waterdb_reads_multi_ring_row_intact(self, tmp_path):
        from pyefis.instruments.ai.water_db import WaterDB
        path, con = _open_db(tmp_path)
        assert bw.insert_polygon(con, "ocean", None, OUTER_CW,
                                 max_vertices=32, holes=[HOLE_CCW])
        con.commit()
        con.close()

        # max_vertices below the 8 stored vertices: a legacy single-ring
        # row would be re-decimated; a multi-ring row must never be.
        db = WaterDB(path, max_vertices=6)
        assert db.ready is True
        polys = list(db.polygons_in_range(24.55, -81.75, 30.0))
        assert len(polys) == 1
        poly = polys[0]
        assert poly.rings == [4, 8]
        assert len(poly.vertices) == 8           # never re-decimated
        assert poly.outer_vertices == poly.vertices[:4]
        assert poly.triangles is not None
        assert max(poly.triangles) < len(poly.vertices)
        assert not _covered_by_triangles(*ISLAND_PT, poly.vertices,
                                         poly.triangles)


class TestHoleVerification:
    """Residual A of #44: per-ring decimation can hand earcut a self-
    intersecting or outer-crossing hole, and earcut then FILLS it
    (54/770 hole interiors covered in a Keys probe build). The builder
    now verifies every hole interior against the stored triangles,
    escalates the decimation cap on failure, and strips hole-covering
    triangles as a last resort."""

    def _bad_fan(self):
        import numpy as np
        # The outer square fan-filled with the hole ignored — covers
        # the island, exactly what a corrupted hole degenerates to.
        return np.asarray([0, 1, 2, 0, 2, 3], dtype=np.uint16)

    def test_interior_points_are_inside_their_ring(self):
        concave = [(24.50, -81.80), (24.50, -81.70), (24.60, -81.70),
                   (24.60, -81.74), (24.52, -81.74), (24.52, -81.76),
                   (24.60, -81.76), (24.60, -81.80)]
        for ring in (HOLE_CCW, OUTER_CW, concave):
            pts = bw._ring_interior_points(ring)
            assert pts
            for lat, lon in pts:
                assert bw._point_in_ring(lat, lon, ring)

    def test_detector_flags_fill_that_covers_hole(self):
        all_verts = OUTER_CW + HOLE_CCW
        assert bw._covered_hole_indices(all_verts, [4, 8],
                                        self._bad_fan()) == [0]

    def test_detector_passes_hole_aware_fill(self):
        all_verts = OUTER_CW + HOLE_CCW
        tri = bw.tessellate_polygon(all_verts, [4, 8])
        assert tri is not None
        assert bw._covered_hole_indices(all_verts, [4, 8], tri) == []

    def test_escalation_recovers_from_bad_tessellation(self, tmp_path,
                                                       monkeypatch):
        # First attempt returns the hole-covering fan; the retry (at
        # the doubled cap) delegates to the real earcut. The bad fill
        # must be detected and never stored.
        real = bw.tessellate_polygon
        calls = {"n": 0}

        def flaky(verts, ring_ends=None):
            calls["n"] += 1
            if calls["n"] == 1:
                return self._bad_fan()
            return real(verts, ring_ends)

        monkeypatch.setattr(bw, "tessellate_polygon", flaky)
        path, con = _open_db(tmp_path)
        stats = {}
        assert bw.insert_polygon(con, "ocean", None, OUTER_CW,
                                 max_vertices=32, holes=[HOLE_CCW],
                                 stats=stats)
        con.commit()
        con.close()
        assert stats.get("escalated") == 1
        assert "stripped" not in stats and "unresolved" not in stats
        verts, tris, rings = _decode(_fetch_rows(path)[0])
        assert rings is not None and len(rings) == 2
        assert not _covered_by_triangles(*ISLAND_PT, verts, tris)
        assert _covered_by_triangles(*WATER_PT, verts, tris)

    def test_strip_fallback_when_raw_rings_still_fail(self, tmp_path,
                                                      monkeypatch):
        # Every attempt (including the raw source rings) yields a
        # correct hole-aware fill PLUS one rogue triangle inside the
        # hole: the escalation ladder exhausts, then the strip repair
        # removes the rogue triangle and the row verifies clean.
        import numpy as np
        real = bw.tessellate_polygon

        def always_rogue(verts, ring_ends=None):
            good = real(verts, ring_ends)
            # Vertices 4, 5, 6 are hole vertices — the rogue triangle
            # sits inside the island.
            return np.concatenate(
                [good, np.asarray([4, 5, 6], dtype=good.dtype)])

        monkeypatch.setattr(bw, "tessellate_polygon", always_rogue)
        path, con = _open_db(tmp_path)
        stats = {}
        assert bw.insert_polygon(con, "ocean", None, OUTER_CW,
                                 max_vertices=32, holes=[HOLE_CCW],
                                 stats=stats)
        con.commit()
        con.close()
        assert stats.get("escalated") == 1    # ladder ran first
        assert stats.get("stripped") == 1
        assert "unresolved" not in stats
        verts, tris, rings = _decode(_fetch_rows(path)[0])
        assert rings is not None and len(rings) == 2
        assert len(tris) % 3 == 0
        assert not _covered_by_triangles(*ISLAND_PT, verts, tris)
        assert _covered_by_triangles(*WATER_PT, verts, tris)

    def test_strip_removes_large_cover_with_centroid_outside_hole(self):
        # The residual behind the #44/#103 "0 inland" gate slip: a large
        # fill triangle covers a small island while its OWN centroid sits
        # outside the island. The old centroid-in-hole strip left it; the
        # interior-point strip removes it. Big triangle (verts 8,9,10)
        # contains the whole HOLE_CCW island; its centroid is at ~24.67N,
        # north of the 24.5-24.6N island.
        import numpy as np
        all_verts = OUTER_CW + HOLE_CCW + [
            (24.0, -81.75), (25.0, -81.90), (25.0, -81.60)]
        ring_ends = [4, 8]
        tri = np.asarray([8, 9, 10], dtype=np.uint16)
        assert bw._covered_hole_indices(all_verts, ring_ends, tri) == [0]
        cen = ((24.0 + 25.0 + 25.0) / 3, (-81.75 - 81.90 - 81.60) / 3)
        assert not bw._point_in_ring(cen[0], cen[1], HOLE_CCW)  # centroid out
        stripped = bw._strip_hole_triangles(all_verts, ring_ends, tri)
        assert bw._covered_hole_indices(all_verts, ring_ends, stripped) == []
        assert len(stripped) == 0     # the only triangle covered the island

    def test_distinct_ring_len_ignores_dups_and_closure(self):
        assert bw._distinct_ring_len([(0, 0), (1, 1), (0, 0)]) == 2   # a line
        assert bw._distinct_ring_len(
            [(0, 0), (1, 0), (1, 1), (0, 0)]) == 3      # triangle + closure
        assert bw._distinct_ring_len(HOLE_CCW) == 4

    def test_degenerate_decimated_hole_is_dropped(self, tmp_path):
        # A hole that collapses to two distinct points (a zero-area line)
        # must not be emitted as a hole: it has no probeable interior yet
        # the pack-check oracle flags it. The row stores as single-ring.
        path, con = _open_db(tmp_path)
        degenerate = [(24.5, -81.8), (24.6, -81.7), (24.5, -81.8)]
        assert bw.insert_polygon(con, "water", None, OUTER_CW,
                                 max_vertices=32, holes=[degenerate])
        con.commit()
        con.close()
        _, _, rings = _decode(_fetch_rows(path)[0])
        assert rings is None

    def test_ring_interior_points_probes_a_tiny_triangle(self):
        # A 3-vertex island the scanline can miss must still yield an
        # interior point (the centroid), or the verifier treats it as
        # clean and ships it covered (the fail-open bug).
        tiny = [(34.0742, -118.2603), (34.0746, -118.2596),
                (34.0744, -118.2600)]
        pts = bw._ring_interior_points(tiny)
        assert pts
        assert any(bw._point_in_ring(lat, lon, tiny) for lat, lon in pts)


def _dense_multipolygon():
    """A synthetic dense cell: one outer box + a 20x15 grid of
    220-vertex circular island holes = 66,004 vertices, past the
    uint16 index ceiling (65,535 — the old builder silently DROPPED
    every hole of such a row; the real lower-Keys cell lost its
    3,322 islands that way, #44's oracle-gate residual B). Returns
    (outer, holes, hole_centers)."""
    import math
    outer = [(24.0, -82.0), (25.0, -82.0), (25.0, -81.0), (24.0, -81.0)]
    if bw.ring_signed_area(outer) > 0:
        outer.reverse()
    holes = []
    centers = []
    nv = 220
    for gy in range(15):
        for gx in range(20):
            clat = 24.0 + (gy + 0.5) / 15.0
            clon = -82.0 + (gx + 0.5) / 20.0
            ring = [(clat + 0.015 * math.sin(2 * math.pi * k / nv),
                     clon + 0.015 * math.cos(2 * math.pi * k / nv))
                    for k in range(nv)]
            if bw.ring_signed_area(ring) < 0:
                ring.reverse()      # holes must be CCW (positive area)
            holes.append(ring)
            centers.append((clat, clon))
    return outer, holes, centers


class TestDenseCellUint32:
    """Residual B of #44: a row whose total vertex count exceeds the
    uint16 index range must keep its holes via uint32 triangle/ring
    indices — not silently drop them all. The dtype is implied by the
    row's vertex count on both the build and the read side."""

    @pytest.fixture(scope="class")
    def dense_db(self, tmp_path_factory):
        tmp = tmp_path_factory.mktemp("dense_water")
        path = tmp / "water.sqlite"
        con = sqlite3.connect(str(path))
        con.executescript(bw.SCHEMA)
        outer, holes, centers = _dense_multipolygon()
        assert bw.insert_polygon(con, "ocean", None, outer,
                                 max_vertices=None, holes=holes)
        con.commit()
        con.close()
        return path, centers

    def test_row_keeps_all_holes_past_uint16(self, dense_db):
        path, centers = dense_db
        rows = _fetch_rows(path)
        assert len(rows) == 1                    # holes never become rows
        verts, tris, rings = _decode(rows[0])
        assert len(verts) == 66004               # nothing dropped
        assert len(verts) > 65535                # the case uint16 cannot hold
        assert rings is not None
        assert len(rings) == 1 + len(centers)    # outer + every hole
        assert rings[-1] == len(verts)

    def test_blobs_are_uint32_and_indices_valid(self, dense_db):
        path, _ = dense_db
        row = _fetch_rows(path)[0]
        verts, tris, rings = _decode(row)
        # 4-byte little-endian indices on disk, decoded 1:1.
        assert len(row["triangles"]) == len(tris) * 4
        assert len(row["rings"]) == len(rings) * 4
        assert len(tris) % 3 == 0
        assert max(tris) < len(verts)
        # Vertices past the uint16 range are actually referenced —
        # proof the fill really spans the whole ring set.
        assert max(tris) > 65535
        assert max(rings) > 65535

    def test_no_hole_interior_covered_full_sweep(self, dense_db):
        # The DoD sweep: every hole interior point (in-ring by
        # even-odd) must be clear of the row's fill triangles, and
        # water between the islands must still be filled.
        path, centers = dense_db
        verts, tris, rings = _decode(_fetch_rows(path)[0])
        r2 = 0.015 / 2.0
        island_pts = []
        for clat, clon in centers:
            island_pts.extend([(clat, clon),
                               (clat + r2, clon), (clat - r2, clon),
                               (clat, clon + r2), (clat, clon - r2)])
        covered = _covered_points_mask(island_pts, verts, tris)
        assert not covered.any(), (
            f"{int(covered.sum())}/{len(island_pts)} island interior "
            "points covered by water fill")
        water_pts = [(24.0 + gy / 15.0, -82.0 + gx / 20.0)
                     for gy, gx in ((1, 1), (7, 10), (14, 19),
                                    (3, 15), (11, 4))]
        assert _covered_points_mask(water_pts, verts, tris).all()

    def test_waterdb_reads_dense_row_intact(self, dense_db):
        from pyefis.instruments.ai.water_db import WaterDB
        path, centers = dense_db
        db = WaterDB(path, max_vertices=32)
        assert db.ready is True
        polys = list(db.polygons_in_range(24.5, -81.5, 30.0))
        assert len(polys) == 1
        poly = polys[0]
        assert len(poly.vertices) == 66004       # never re-decimated
        assert poly.rings is not None
        assert len(poly.rings) == 1 + len(centers)
        assert poly.triangles is not None
        assert max(poly.triangles) < len(poly.vertices)
        # Spot-check through the reader's own decode: island dry,
        # surrounding water wet.
        clat, clon = centers[0]
        mask = _covered_points_mask([(clat, clon), (24.0 + 1 / 15.0,
                                                    -82.0 + 1 / 20.0)],
                                    poly.vertices, poly.triangles)
        assert not mask[0]
        assert mask[1]
