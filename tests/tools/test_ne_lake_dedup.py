#  SPDX-License-Identifier: GPL-2.0-or-later
"""Tests for tools/build_water_db.py -- AER-4604 NE lake dedup.

The map draws overlapping water polygons as their union (AER-4594,
AER-4596), so a Natural Earth lake left on top of its OSM twin paints
wherever either outline says water, and NE's coarser edge shows past
the OSM shoreline (Mille Lacs SE shore, GSL west side). The builder
now drops an NE lake that OSM already draws and keeps one OSM does
not. These tests drive ``main()`` end to end from the text format.
"""

import importlib.util
import sqlite3
import sys
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


def _square(lat0, lon0, lat1, lon1):
    return [(lat0, lon0), (lat0, lon1), (lat1, lon1), (lat1, lon0)]


# Mille Lacs in miniature: the NE lake runs past its OSM twin on the
# south-east, which is the strip that painted after the union fix.
NE_LAKE = _square(46.10, -93.85, 46.40, -93.45)
OSM_TWIN = _square(46.16, -93.85, 46.40, -93.52)
NE_ONLY_PT = (46.12, -93.47)    # inside NE, outside OSM


def _build(tmp_path, polys, *extra):
    """Run the builder's main() on ``polys`` [(kind, ring)]; return the
    (id, kind) rows it wrote."""
    txt = tmp_path / "in.txt"
    lines = []
    for kind, ring in polys:
        lines.append(f"P {kind}")
        lines += [f"{lat} {lon}" for lat, lon in ring]
        lines.append("")
    txt.write_text("\n".join(lines) + "\n")
    out = tmp_path / "water.sqlite"
    argv = ["build_water_db.py", str(out), "--text", str(txt), *extra]
    old = sys.argv
    sys.argv = argv
    try:
        bw.main()
    finally:
        sys.argv = old
    con = sqlite3.connect(str(out))
    try:
        return con.execute(
            "SELECT id, kind FROM water_polygons ORDER BY id").fetchall()
    finally:
        con.close()


def _kinds(rows):
    return sorted(k for _, k in rows)


class TestNeLakeDedup:
    def test_ne_lake_duplicated_by_osm_is_not_emitted(self, tmp_path):
        rows = _build(tmp_path, [("lake", NE_LAKE), ("water", OSM_TWIN)])
        assert _kinds(rows) == ["water"]

    def test_opt_out_keeps_both(self, tmp_path):
        rows = _build(tmp_path, [("lake", NE_LAKE), ("water", OSM_TWIN)],
                      "--keep-ne-duplicates")
        assert _kinds(rows) == ["lake", "water"]

    def test_dropped_lake_leaves_rtree_in_step(self, tmp_path):
        _build(tmp_path, [("lake", NE_LAKE), ("water", OSM_TWIN)])
        con = sqlite3.connect(str(tmp_path / "water.sqlite"))
        lat, lon = NE_ONLY_PT
        hits = con.execute(
            "SELECT id FROM water_rtree WHERE min_lat <= ? AND max_lat >= ? "
            "AND min_lon <= ? AND max_lon >= ?",
            (lat, lat, lon, lon)).fetchall()
        assert hits == []       # nothing left to paint the NE-only strip

    def test_ne_lake_without_osm_is_kept(self, tmp_path):
        far = _square(40.0, -100.0, 40.2, -99.8)
        rows = _build(tmp_path, [("lake", NE_LAKE), ("water", far)])
        assert _kinds(rows) == ["lake", "water"]

    def test_ne_lake_osm_only_partly_maps_is_kept(self, tmp_path):
        # OSM maps one corner, a quarter of the lake (a river reservoir
        # OSM tags as riverbank leaves only scraps like this): NE is the
        # only full outline. The cover is in the partial band, so only
        # the bbox test keeps it.
        corner = _square(46.25, -93.65, 46.40, -93.45)
        rows = _build(tmp_path, [("lake", NE_LAKE), ("water", corner)],
                      "--keep-ne-duplicates")
        con = sqlite3.connect(str(tmp_path / "water.sqlite"))
        lake_id = [i for i, k in rows if k == "lake"][0]
        cover, iou = bw.ne_lake_osm_match(con, lake_id)
        con.close()
        assert bw.NE_DUP_MIN_PARTIAL_COVER <= cover < bw.NE_DUP_MIN_COVER
        assert iou < bw.NE_DUP_MIN_BBOX_IOU
        rows = _build(tmp_path, [("lake", NE_LAKE), ("water", corner)])
        assert _kinds(rows) == ["lake", "water"]

    def test_narrow_lake_coarse_ne_outline_is_dropped(self, tmp_path):
        # Lake Chelan / Lake Powell shape: OSM spans the same bbox but,
        # being a thin lake, fills well under half of NE's fat outline.
        ne = _square(47.0, -120.0, 48.0, -119.0)
        osm = [(47.0, -120.0), (47.0, -119.6), (48.0, -119.0),
               (48.0, -119.4)]
        rows = _build(tmp_path, [("lake", ne), ("water", osm)],
                      "--keep-ne-duplicates")
        con = sqlite3.connect(str(tmp_path / "water.sqlite"))
        lake_id = [i for i, k in rows if k == "lake"][0]
        cover, iou = bw.ne_lake_osm_match(con, lake_id)
        con.close()
        assert cover < bw.NE_DUP_MIN_COVER     # cover alone would keep it
        assert iou >= bw.NE_DUP_MIN_BBOX_IOU
        rows = _build(tmp_path, [("lake", ne), ("water", osm)])
        assert _kinds(rows) == ["water"]

    def test_osm_island_counts_as_mapped_lake(self, tmp_path):
        # NE fills islands; OSM cuts them out. An OSM lake whose big
        # island is a hole still draws the whole lake.
        ne = _square(50.0, -90.0, 51.0, -89.0)
        osm_outer = _square(50.0, -90.0, 51.0, -89.0)
        island = _square(50.1, -89.9, 50.9, -89.1)     # 64% of the lake
        con = sqlite3.connect(":memory:")
        con.executescript(bw.SCHEMA)
        bw.insert_polygon(con, "lake", None, ne)
        bw.insert_polygon(con, "water", None, osm_outer, holes=[island])
        lake_id = con.execute(
            "SELECT id FROM water_polygons WHERE kind = 'lake'").fetchone()[0]
        cover, _ = bw.ne_lake_osm_match(con, lake_id)
        assert cover == pytest.approx(1.0)
        assert [r[0] for r in bw.drop_covered_ne_lakes(con)] == [lake_id]

    def test_only_osm_water_counts_as_cover(self, tmp_path):
        # Ocean and other NE lakes are not OSM's outline of this lake.
        rows = _build(tmp_path, [("lake", NE_LAKE), ("ocean", NE_LAKE),
                                 ("lake", OSM_TWIN)])
        assert _kinds(rows) == ["lake", "lake", "ocean"]
