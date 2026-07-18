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
    return (_decode_vertices(row["vertices"]),
            _decode_triangles(row["triangles"]),
            _decode_rings(row["rings"]))


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
