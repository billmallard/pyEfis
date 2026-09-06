#  SPDX-License-Identifier: GPL-2.0-or-later
"""Tests for tools/build_highway_db.py builder guards -- makerplane-data#17.

Two silent-failure footguns were found bringing up the highways-conus pack:

  1. Append footgun: the builder continues from ``MAX(id)+1``, so building
     into an EXISTING sqlite appends -- the June rebuild doubled every state
     (1.76M rows, 856k duplicates). ``prepare_dest`` now refuses an existing
     ``--dest`` unless ``--overwrite`` is given (then it starts fresh).

  2. Empty-extract footgun: California's Geofabrik shapefile bundle was
     discontinued, its extract dir ended up EMPTY, and the state silently
     vanished from the pack -- invisible until someone flew that area.
     ``validate_shapefiles`` fails loudly when an input ``.shp`` is missing or
     carries zero shapes (the empty extract arriving at the builder).

Plain pytest + tmp_path. pyshp writes the synthetic inputs; the module skips
without it (build-time-only dependency, like the sibling water-builder tests).
"""

import importlib.util
import sqlite3
from pathlib import Path

import pytest

shapefile = pytest.importorskip(
    "shapefile", reason="pyshp is a build-time-only dependency")

_ROOT = Path(__file__).resolve().parents[2]


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, _ROOT / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bh = _load("build_highway_db")

# A synthetic motorway in (lat, lon), spacing above the 40 m decimation
# tolerance so both vertices survive; "motorway" is in the default road preset.
ROAD = [(35.00, -81.00), (35.02, -81.02), (35.04, -81.01)]


def _write_roads(tmp_path, shapes, stem="roads", fields=("fclass",)):
    """Write a synthetic Geofabrik-style roads polyline shapefile. ``shapes``
    is a list of (fclass, [part, ...]) with each part a (lat, lon) list."""
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


def _write_roads_with_attrs(tmp_path, rows, stem="roads"):
    """Write a synthetic Geofabrik-style roads shapefile carrying the
    ``tunnel``/``bridge``/``ref`` fields the real ``gis_osm_roads_free_1``
    layer has (RD3a, AER-640). ``rows`` is a list of dicts with keys
    ``fclass``, ``parts`` (a list of (lat, lon) lists), and optionally
    ``tunnel``/``bridge`` (Geofabrik ``"T"``/``"F"`` strings) and ``ref``."""
    shp = tmp_path / stem
    w = shapefile.Writer(str(shp), shapeType=shapefile.POLYLINE)
    w.field("fclass", "C")
    w.field("ref", "C")
    w.field("bridge", "C")
    w.field("tunnel", "C")
    for row in rows:
        w.line([[(lon, lat) for lat, lon in part] for part in row["parts"]])
        w.record(row["fclass"], row.get("ref", ""),
                  row.get("bridge", "F"), row.get("tunnel", "F"))
    w.close()
    return str(shp) + ".shp"


def _write_empty_roads(tmp_path, stem="empty"):
    """Write a valid but EMPTY roads shapefile (0 shapes) -- what an empty
    Geofabrik state extract looks like once it reaches the builder."""
    shp = tmp_path / stem
    w = shapefile.Writer(str(shp), shapeType=shapefile.POLYLINE)
    w.field("fclass", "C")
    w.close()
    return str(shp) + ".shp"


def _count_rows(dest):
    con = sqlite3.connect(str(dest))
    n = con.execute("SELECT count(*) FROM highway_lines").fetchone()[0]
    con.close()
    return n


def _build(tmp_path, monkeypatch, shp, dest, *extra):
    monkeypatch.setattr(
        "sys.argv", ["build_highway_db.py", "--dest", str(dest), *extra, shp])
    bh.main()


class TestDestGuard:
    def test_prepare_dest_refuses_existing(self, tmp_path):
        dest = tmp_path / "highways.sqlite"
        dest.write_bytes(b"existing")
        with pytest.raises(SystemExit):
            bh.prepare_dest(str(dest), overwrite=False)
        # refused, so the existing file is untouched
        assert dest.read_bytes() == b"existing"

    def test_prepare_dest_overwrite_removes_existing(self, tmp_path):
        dest = tmp_path / "highways.sqlite"
        dest.write_bytes(b"existing")
        bh.prepare_dest(str(dest), overwrite=True)
        assert not dest.exists()

    def test_prepare_dest_fresh_ok(self, tmp_path):
        dest = tmp_path / "highways.sqlite"
        # no file yet: neither refuse nor unlink, just returns the path
        assert bh.prepare_dest(str(dest), overwrite=False) == dest
        assert not dest.exists()

    def test_build_refuses_existing_dest(self, tmp_path, monkeypatch):
        shp = _write_roads(tmp_path, [("motorway", [ROAD])])
        dest = tmp_path / "highways.sqlite"
        _build(tmp_path, monkeypatch, shp, dest)          # first build ok
        assert _count_rows(dest) == 1
        with pytest.raises(SystemExit):                   # second refuses
            _build(tmp_path, monkeypatch, shp, dest)
        assert _count_rows(dest) == 1                     # not doubled

    def test_build_overwrite_does_not_double(self, tmp_path, monkeypatch):
        # The regression: rebuilding over an existing file used to append.
        # --overwrite must rebuild fresh, so the count stays put, never doubles.
        shp = _write_roads(tmp_path, [("motorway", [ROAD])])
        dest = tmp_path / "highways.sqlite"
        _build(tmp_path, monkeypatch, shp, dest)
        assert _count_rows(dest) == 1
        _build(tmp_path, monkeypatch, shp, dest, "--overwrite")
        assert _count_rows(dest) == 1                     # fresh, not 2


class TestEmptyExtractGuard:
    def test_validate_missing_shapefile_fails(self, tmp_path):
        with pytest.raises(SystemExit):
            bh.validate_shapefiles([str(tmp_path / "california.shp")])

    def test_validate_empty_shapefile_fails(self, tmp_path):
        shp = _write_empty_roads(tmp_path)
        with pytest.raises(SystemExit):
            bh.validate_shapefiles([shp])

    def test_validate_passes_populated_shapefile(self, tmp_path):
        shp = _write_roads(tmp_path, [("motorway", [ROAD])])
        bh.validate_shapefiles([shp])                     # no raise

    def test_build_empty_extract_fails_loudly(self, tmp_path, monkeypatch):
        empty = _write_empty_roads(tmp_path)
        dest = tmp_path / "highways.sqlite"
        with pytest.raises(SystemExit):
            _build(tmp_path, monkeypatch, empty, dest)

    def test_build_one_empty_among_many_fails(self, tmp_path, monkeypatch):
        # A single empty state must fail the whole build (the California case),
        # not get masked by the populated states beside it.
        good = _write_roads(tmp_path, [("motorway", [ROAD])], stem="texas")
        empty = _write_empty_roads(tmp_path, stem="california")
        dest = tmp_path / "highways.sqlite"
        monkeypatch.setattr("sys.argv", [
            "build_highway_db.py", "--dest", str(dest), good, empty])
        with pytest.raises(SystemExit):
            bh.main()


class TestHappyPath:
    def test_valid_build_keeps_rows(self, tmp_path, monkeypatch, capsys):
        shp = _write_roads(tmp_path, [
            ("motorway", [ROAD]),
            ("residential", [[(lat + 0.1, lon) for lat, lon in ROAD]])])
        dest = tmp_path / "highways.sqlite"
        _build(tmp_path, monkeypatch, shp, dest)
        # motorway kept, residential filtered out by the roads preset
        assert _count_rows(dest) == 1
        con = sqlite3.connect(str(dest))
        assert con.execute(
            "SELECT fclass FROM highway_lines").fetchone()[0] == "motorway"
        con.close()


class TestTunnelBridgeRef:
    """RD3a (AER-640): the builder writes a ``flags`` bitmask (bit 0
    tunnel, bit 1 bridge) and a ``ref`` column from the Geofabrik
    ``tunnel``/``bridge``/``ref`` fields."""

    def _row(self, tmp_path, monkeypatch, row, stem="roads"):
        shp = _write_roads_with_attrs(tmp_path, [row], stem=stem)
        dest = tmp_path / f"{stem}.sqlite"
        _build(tmp_path, monkeypatch, shp, dest)
        con = sqlite3.connect(str(dest))
        rec = con.execute(
            "SELECT flags, ref FROM highway_lines").fetchone()
        con.close()
        return rec

    def test_plain_way_has_no_flags_and_no_ref(self, tmp_path, monkeypatch):
        flags, ref = self._row(tmp_path, monkeypatch,
                                {"fclass": "motorway", "parts": [ROAD]})
        assert flags == 0
        assert ref is None

    def test_tunnel_sets_bit0(self, tmp_path, monkeypatch):
        flags, ref = self._row(tmp_path, monkeypatch, {
            "fclass": "motorway", "parts": [ROAD], "tunnel": "T"},
            stem="tunnel")
        assert flags == bh.FLAG_TUNNEL
        assert flags & bh.FLAG_BRIDGE == 0

    def test_bridge_sets_bit1(self, tmp_path, monkeypatch):
        flags, ref = self._row(tmp_path, monkeypatch, {
            "fclass": "motorway", "parts": [ROAD], "bridge": "T"},
            stem="bridge")
        assert flags == bh.FLAG_BRIDGE
        assert flags & bh.FLAG_TUNNEL == 0

    def test_tunnel_and_bridge_both_set(self, tmp_path, monkeypatch):
        # Doesn't occur on real data, but the bits are independent.
        flags, ref = self._row(tmp_path, monkeypatch, {
            "fclass": "motorway", "parts": [ROAD],
            "tunnel": "T", "bridge": "T"}, stem="both")
        assert flags == (bh.FLAG_TUNNEL | bh.FLAG_BRIDGE)

    def test_ref_is_carried(self, tmp_path, monkeypatch):
        flags, ref = self._row(tmp_path, monkeypatch, {
            "fclass": "motorway", "parts": [ROAD], "ref": "I-70"},
            stem="ref")
        assert ref == "I-70"

    def test_blank_ref_stored_as_null(self, tmp_path, monkeypatch):
        flags, ref = self._row(tmp_path, monkeypatch,
                                {"fclass": "motorway", "parts": [ROAD]},
                                stem="blankref")
        assert ref is None

    def test_shapefile_without_attr_fields_still_builds(
            self, tmp_path, monkeypatch):
        # A layer that never had tunnel/bridge/ref (e.g. an older
        # extract) must still build -- every row falls back to
        # flags=0, ref=NULL rather than raising.
        shp = _write_roads(tmp_path, [("motorway", [ROAD])], stem="noattrs")
        dest = tmp_path / "noattrs.sqlite"
        _build(tmp_path, monkeypatch, shp, dest)
        con = sqlite3.connect(str(dest))
        flags, ref = con.execute(
            "SELECT flags, ref FROM highway_lines").fetchone()
        con.close()
        assert flags == 0
        assert ref is None
