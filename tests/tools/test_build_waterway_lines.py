#  SPDX-License-Identifier: GPL-2.0-or-later
"""Tests for tools/build_water_db.py --waterway -- issue #39 rivers as lines.

Winding rivers cannot survive as filled polygons (decimation cuts
chords across the meanders and balloons the channel into a lake-blob),
so the polygon ingest DROPS riverbank shapes and rivers were absent
from the SVS. The builder now imports OSM waterway CENTERLINES
(Geofabrik gis_osm_waterways_free_1) into a waterway_lines polyline
table that mirrors the highway store (highway_db.py): float32 (lat,
lon) verts, per-part rows, fclass filter, R-tree bbox index. These
tests drive synthetic OSM polyline shapefiles through the importer and
assert the stored polylines. Renderer wiring is a follow-up; the only
consumers exercised here are the schema and the highway-format decode.

Plain pytest + tmp_path. mapbox_earcut is imported at module scope by
build_water_db (build-time-only dep), and pyshp writes the synthetic
inputs; the module skips without either.
"""

import importlib.util
import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("mapbox_earcut",
                    reason="build-time tessellation dependency")
shapefile = pytest.importorskip(
    "shapefile", reason="pyshp is a build-time-only dependency")

_ROOT = Path(__file__).resolve().parents[2]


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, _ROOT / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bw = _load("build_water_db")

TOL_DEG = 40.0 / bw._M_PER_DEG          # the CLI default, in degrees

# A synthetic meandering river in (lat, lon), spacing well above the
# 40 m decimation tolerance so every vertex survives the import.
RIVER = [(35.00, -81.00), (35.01, -81.02), (35.02, -81.01),
         (35.03, -81.03), (35.04, -81.02)]


def _write_lines(tmp_path, shapes, stem="waterways", fields=("fclass",)):
    """Write a synthetic OSM-style polyline shapefile. ``shapes`` is a
    list of (fclass, [part, ...]) with each part a (lat, lon) list."""
    shp = tmp_path / stem
    w = shapefile.Writer(str(shp), shapeType=shapefile.POLYLINE)
    for f in fields:
        w.field(f, "C")
    for fclass, parts in shapes:
        # pyshp wants (lon, lat) points.
        w.line([[(lon, lat) for lat, lon in part] for part in parts])
        w.record(*([fclass] * len(fields)))
    w.close()
    return str(shp) + ".shp"


def _open_db(tmp_path):
    path = tmp_path / "water.sqlite"
    con = sqlite3.connect(str(path))
    con.executescript(bw.SCHEMA)
    return path, con


def _fetch_lines(path):
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT id, fclass, min_lat, max_lat, min_lon, max_lon, verts "
        "FROM waterway_lines ORDER BY id").fetchall()
    con.close()
    return rows


def _decode(row):
    # The contract under test: waterway verts decode with the HIGHWAY
    # reader's format (little-endian float32 pairs), so the future
    # renderer query can reuse the proven highway path.
    from pyefis.instruments.ai.highway_db import decode_vertices
    return decode_vertices(row["verts"])


class TestWaterwayImport:
    def test_river_imported_as_polyline(self, tmp_path):
        shp = _write_lines(tmp_path, [("river", [RIVER])])
        path, con = _open_db(tmp_path)
        n = bw.import_waterways(con, shp, TOL_DEG, bw.WATERWAY_CLASSES)
        con.commit()
        con.close()
        assert n == 1
        rows = _fetch_lines(path)
        assert len(rows) == 1
        row = rows[0]
        assert row["fclass"] == "river"
        verts = _decode(row)
        # float32 storage: 8 bytes per (lat, lon) vertex, values within
        # float32 rounding of the source line, order preserved.
        assert len(row["verts"]) == len(RIVER) * 8
        assert verts.shape == (len(RIVER), 2)
        for (lat, lon), (vlat, vlon) in zip(RIVER, verts):
            assert abs(lat - vlat) < 1e-5
            assert abs(lon - vlon) < 1e-5
        assert row["min_lat"] == pytest.approx(35.00, abs=1e-5)
        assert row["max_lat"] == pytest.approx(35.04, abs=1e-5)
        assert row["min_lon"] == pytest.approx(-81.03, abs=1e-5)
        assert row["max_lon"] == pytest.approx(-81.00, abs=1e-5)

    def test_default_classes_keep_river_canal_stream(self, tmp_path):
        shifted = [[(lat + k * 0.1, lon) for lat, lon in RIVER]
                   for k in range(5)]
        shp = _write_lines(tmp_path, [("river", [shifted[0]]),
                                      ("canal", [shifted[1]]),
                                      ("stream", [shifted[2]]),
                                      ("drain", [shifted[3]]),
                                      ("ditch", [shifted[4]])])
        path, con = _open_db(tmp_path)
        n = bw.import_waterways(con, shp, TOL_DEG, bw.WATERWAY_CLASSES)
        con.commit()
        con.close()
        assert n == 3
        assert sorted(r["fclass"] for r in _fetch_lines(path)) == \
            ["canal", "river", "stream"]

    def test_class_override(self, tmp_path):
        shp = _write_lines(tmp_path, [
            ("river", [RIVER]),
            ("drain", [[(lat + 0.1, lon) for lat, lon in RIVER]])])
        path, con = _open_db(tmp_path)
        n = bw.import_waterways(con, shp, TOL_DEG, ("drain",))
        con.commit()
        con.close()
        assert n == 1
        assert [r["fclass"] for r in _fetch_lines(path)] == ["drain"]

    def test_multipart_shape_splits_into_rows(self, tmp_path):
        part2 = [(lat + 0.5, lon) for lat, lon in RIVER]
        shp = _write_lines(tmp_path, [("river", [RIVER, part2])])
        path, con = _open_db(tmp_path)
        n = bw.import_waterways(con, shp, TOL_DEG, bw.WATERWAY_CLASSES)
        con.commit()
        con.close()
        assert n == 2
        rows = _fetch_lines(path)
        assert len(rows) == 2
        assert {r["fclass"] for r in rows} == {"river"}
        lats = sorted(float(_decode(r)[0][0]) for r in rows)
        assert lats[0] == pytest.approx(RIVER[0][0], abs=1e-5)
        assert lats[1] == pytest.approx(part2[0][0], abs=1e-5)

    def test_decimation_drops_jitter_keeps_bends(self, tmp_path):
        # Two straight legs with a right-angle bend, oversampled every
        # ~0.001 deg (~110 m spacing but collinear): Douglas-Peucker at
        # 40 m must collapse each leg to its endpoints while the bend
        # survives -- the shape-preserving property that makes lines
        # safe where polygon fills blobbed.
        leg1 = [(35.0, -81.0 + k * 0.001) for k in range(101)]
        leg2 = [(35.0 + k * 0.001, -80.9) for k in range(1, 101)]
        dense = leg1 + leg2
        shp = _write_lines(tmp_path, [("river", [dense])])
        path, con = _open_db(tmp_path)
        n = bw.import_waterways(con, shp, TOL_DEG, bw.WATERWAY_CLASSES)
        con.commit()
        con.close()
        assert n == 1
        verts = _decode(_fetch_lines(path)[0])
        assert len(verts) == 3                     # ends + the bend
        assert verts[0][0] == pytest.approx(35.0, abs=1e-5)
        assert verts[0][1] == pytest.approx(-81.0, abs=1e-5)
        assert verts[1][0] == pytest.approx(35.0, abs=1e-5)
        assert verts[1][1] == pytest.approx(-80.9, abs=1e-5)
        assert verts[2][0] == pytest.approx(35.1, abs=1e-5)
        assert verts[2][1] == pytest.approx(-80.9, abs=1e-5)

    def test_missing_fclass_fails_loudly(self, tmp_path):
        shp = _write_lines(tmp_path, [("1", [RIVER])], fields=("osm_id",))
        path, con = _open_db(tmp_path)
        with pytest.raises(SystemExit):
            bw.import_waterways(con, shp, TOL_DEG, bw.WATERWAY_CLASSES)
        con.close()


class TestSchemaAndQuery:
    def test_fresh_db_has_empty_waterway_tables(self, tmp_path):
        # The tables exist in every new build (even without --waterway)
        # so a reader can probe by content, and adding them never
        # disturbs the polygon store old readers know.
        path, con = _open_db(tmp_path)
        con.close()
        con = sqlite3.connect(str(path))
        assert con.execute(
            "SELECT count(*) FROM waterway_lines").fetchone()[0] == 0
        assert con.execute(
            "SELECT count(*) FROM waterway_rtree").fetchone()[0] == 0
        assert con.execute(
            "SELECT count(*) FROM water_polygons").fetchone()[0] == 0
        con.close()

    def test_rtree_range_query_pattern(self, tmp_path):
        # The exact JOIN the future reader will run (the
        # HighwayDB.polylines_in_range pattern): in range near the
        # river finds it, far away finds nothing.
        shp = _write_lines(tmp_path, [("river", [RIVER])])
        path, con = _open_db(tmp_path)
        bw.import_waterways(con, shp, TOL_DEG, bw.WATERWAY_CLASSES)
        con.commit()
        con.close()

        sql = ("SELECT l.fclass, l.verts FROM waterway_lines l "
               "JOIN waterway_rtree r ON r.id = l.id "
               "WHERE r.max_lat >= ? AND r.min_lat <= ? "
               "  AND r.max_lon >= ? AND r.min_lon <= ?")
        con = sqlite3.connect(str(path))
        d = 10.0 / 60.0                             # 10 nm box
        near = con.execute(sql, (35.02 - d, 35.02 + d,
                                 -81.02 - d, -81.02 + d)).fetchall()
        far = con.execute(sql, (44.0 - d, 44.0 + d,
                                -71.0 - d, -71.0 + d)).fetchall()
        con.close()
        assert len(near) == 1
        assert near[0][0] == "river"
        assert not far

    def test_polygons_and_waterways_coexist(self, tmp_path):
        # One build can carry both stores; neither disturbs the other.
        outer = [(24.0, -82.5), (25.0, -82.5), (25.0, -81.0),
                 (24.0, -81.0)]
        shp = _write_lines(tmp_path, [("river", [RIVER])])
        path, con = _open_db(tmp_path)
        assert bw.insert_polygon(con, "ocean", None, outer,
                                 max_vertices=32)
        assert bw.import_waterways(con, shp, TOL_DEG,
                                   bw.WATERWAY_CLASSES) == 1
        con.commit()
        con.close()
        con = sqlite3.connect(str(path))
        assert con.execute(
            "SELECT count(*) FROM water_polygons").fetchone()[0] == 1
        assert con.execute(
            "SELECT count(*) FROM waterway_lines").fetchone()[0] == 1
        con.close()


class TestCli:
    def test_waterway_flag_end_to_end(self, tmp_path, monkeypatch,
                                      capsys):
        shp = _write_lines(tmp_path, [("river", [RIVER]),
                                      ("drain", [[(lat + 0.1, lon)
                                                  for lat, lon in RIVER]])])
        out = tmp_path / "water.sqlite"
        monkeypatch.setattr("sys.argv", [
            "build_water_db.py", str(out), "--waterway", shp])
        bw.main()
        captured = capsys.readouterr()
        assert "1 waterway line" in captured.out
        rows = _fetch_lines(out)
        assert len(rows) == 1
        assert rows[0]["fclass"] == "river"

    def test_waterway_classes_flag(self, tmp_path, monkeypatch):
        shp = _write_lines(tmp_path, [("river", [RIVER]),
                                      ("drain", [[(lat + 0.1, lon)
                                                  for lat, lon in RIVER]])])
        out = tmp_path / "water.sqlite"
        monkeypatch.setattr("sys.argv", [
            "build_water_db.py", str(out), "--waterway", shp,
            "--waterway-classes", "drain"])
        bw.main()
        rows = _fetch_lines(out)
        assert [r["fclass"] for r in rows] == ["drain"]
