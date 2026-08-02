"""Airport DB backend selection + multi-provider merge.

Airport data is provider-based: a US FAA NASR primary plus optional
supplemental packs (e.g. Canada) auto-discovered under a provider directory and
merged at query time."""
import sqlite3
from pathlib import Path

from pyefis.instruments.ai.airport_db import (
    make_airport_db, NASRAirportDB, _MultiAirportDB)

# Current schema (post-VG1): runway_ends carries vgsi_code + visual_gpa.
SCHEMA = """
CREATE TABLE airports (site_no TEXT PRIMARY KEY, icao TEXT NOT NULL, name TEXT,
  lat REAL NOT NULL, lon REAL NOT NULL, elev_ft REAL, mag_var REAL, state TEXT, city TEXT);
CREATE TABLE runways (site_no TEXT, rwy_id TEXT, length_ft REAL, width_ft REAL,
  surface TEXT, lighting TEXT, PRIMARY KEY (site_no, rwy_id));
CREATE TABLE runway_ends (site_no TEXT, rwy_id TEXT, end_id TEXT, true_alignment_deg REAL,
  lat REAL, lon REAL, elev_ft REAL, displaced_thr_lat REAL, displaced_thr_lon REAL,
  displaced_thr_len_ft REAL, tdz_elev_ft REAL, marking_type TEXT, apch_lgt_code TEXT,
  end_lgts_flag TEXT, cntrln_lgts_flag TEXT, tdz_lgt_flag TEXT,
  vgsi_code TEXT, visual_gpa REAL,
  PRIMARY KEY (site_no, rwy_id, end_id));
"""

# Pre-VG1 schema (no vgsi_code/visual_gpa) — an older airport pack a device may
# still have installed. The reader must tolerate it (construct-never-raises).
SCHEMA_PRE_VGSI = """
CREATE TABLE airports (site_no TEXT PRIMARY KEY, icao TEXT NOT NULL, name TEXT,
  lat REAL NOT NULL, lon REAL NOT NULL, elev_ft REAL, mag_var REAL, state TEXT, city TEXT);
CREATE TABLE runways (site_no TEXT, rwy_id TEXT, length_ft REAL, width_ft REAL,
  surface TEXT, lighting TEXT, PRIMARY KEY (site_no, rwy_id));
CREATE TABLE runway_ends (site_no TEXT, rwy_id TEXT, end_id TEXT, true_alignment_deg REAL,
  lat REAL, lon REAL, elev_ft REAL, displaced_thr_lat REAL, displaced_thr_lon REAL,
  displaced_thr_len_ft REAL, tdz_elev_ft REAL, marking_type TEXT, apch_lgt_code TEXT,
  end_lgts_flag TEXT, cntrln_lgts_flag TEXT, tdz_lgt_flag TEXT,
  PRIMARY KEY (site_no, rwy_id, end_id));
"""


def _mkdb(path, rows, *, vgsi=None):
    """rows: (site_no, icao, lat, lon). Each gets one paved runway w/ 2 ends so
    airports_in_range yields it (it skips runway-less airports). ``vgsi`` maps an
    end_id ("09"/"27") to a (vgsi_code, visual_gpa) pair; ends absent from it get
    NULL."""
    vgsi = vgsi or {}
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    for site, icao, lat, lon in rows:
        con.execute("INSERT INTO airports VALUES (?,?,?,?,?,?,?,?,?)",
                    (site, icao, icao, lat, lon, 100, 0, "ST", "City"))
        con.execute("INSERT INTO runways VALUES (?,?,?,?,?,?)",
                    (site, "09/27", 5000, 100, "ASPH", "HIGH"))
        for end, dlon in (("09", -0.005), ("27", 0.005)):
            vc, gpa = vgsi.get(end, (None, None))
            con.execute("INSERT INTO runway_ends VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (site, "09/27", end, 90, lat, lon + dlon, 100,
                         None, None, 0, None, "", "", "", "", "", vc, gpa))
    con.commit()
    con.close()


def test_single_nasr_returns_plain_db(tmp_path):
    p = tmp_path / "navdata/current/airports.sqlite"
    _mkdb(p, [("1", "KABC", 42.3, -83.0)])
    db = make_airport_db({"nasr_db_path": str(p)})
    assert isinstance(db, NASRAirportDB)        # no provider dir -> single backend


def test_provider_dir_merges_us_and_canada(tmp_path):
    us = tmp_path / "navdata/current/airports.sqlite"
    _mkdb(us, [("1", "KABC", 42.30, -83.00)])
    prov = tmp_path / "airports"
    _mkdb(prov / "airports-canada/current/airports.sqlite", [("CYQG", "CYQG", 42.28, -82.96)])

    db = make_airport_db({"nasr_db_path": str(us),
                          "airport_provider_dir": str(prov)})
    assert isinstance(db, _MultiAirportDB) and db.ready
    got = {a.icao for a in db.airports_in_range(42.29, -82.98, 30)}
    assert "KABC" in got and "CYQG" in got      # US + CA merged


def test_provider_only_no_primary(tmp_path):
    """Provider packs work even with no US primary configured."""
    prov = tmp_path / "airports"
    _mkdb(prov / "airports-canada/current/airports.sqlite", [("CYQG", "CYQG", 42.28, -82.96)])
    db = make_airport_db({"airport_provider_dir": str(prov)})
    assert db.ready
    got = {a.icao for a in db.airports_in_range(42.28, -82.96, 20)}
    assert got == {"CYQG"}


def test_multi_dedups_by_icao(tmp_path):
    """An airport carried by two providers appears once (primary wins)."""
    a = tmp_path / "a/airports.sqlite"
    b = tmp_path / "b/airports.sqlite"
    _mkdb(a, [("1", "CYQG", 42.28, -82.96)])
    _mkdb(b, [("CYQG", "CYQG", 42.28, -82.96)])
    multi = _MultiAirportDB([NASRAirportDB(str(a)), NASRAirportDB(str(b))])
    got = [ap for ap in multi.airports_in_range(42.28, -82.96, 20)]
    assert len(got) == 1 and got[0].icao == "CYQG"


def test_no_data_is_empty_stub():
    db = make_airport_db({})
    assert db.ready is False
    assert list(db.airports_in_range(0, 0, 50)) == []


def test_vgsi_surfaced_on_runway_record(tmp_path):
    """VG1 tier 1: NASRAirportDB surfaces vgsi_code/visual_gpa per threshold, and
    an end with none reads back as None (not "" / 0.0)."""
    p = tmp_path / "navdata/current/airports.sqlite"
    # end "09" has a PAPI + published 3.00 GPA; end "27" has neither.
    _mkdb(p, [("1", "KABC", 42.3, -83.0)], vgsi={"09": ("P4L", 3.00)})
    db = NASRAirportDB(str(p))
    (ap,) = list(db.airports_in_range(42.3, -83.0, 20))
    (rwy,) = ap.runways
    # _runways_for sorts ends numerically, so thr1 == "09", thr2 == "27".
    assert rwy.thr1_designator == "09" and rwy.thr2_designator == "27"
    assert rwy.thr1_vgsi_type == "P4L" and rwy.thr1_visual_gpa == 3.00
    assert rwy.thr2_vgsi_type is None and rwy.thr2_visual_gpa is None


def test_old_pack_without_vgsi_columns_still_reads(tmp_path):
    """A pre-VG1 pack (runway_ends lacks vgsi_code/visual_gpa) must still read —
    construct-never-raises. The VGSI fields come back None."""
    p = tmp_path / "old/current/airports.sqlite"
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p)
    con.executescript(SCHEMA_PRE_VGSI)
    con.execute("INSERT INTO airports VALUES ('1','KOLD','KOLD',42.3,-83.0,100,0,'ST','City')")
    con.execute("INSERT INTO runways VALUES ('1','09/27',5000,100,'ASPH','HIGH')")
    for end, dlon in (("09", -0.005), ("27", 0.005)):
        con.execute("INSERT INTO runway_ends VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    ("1", "09/27", end, 90, 42.3, -83.0 + dlon, 100,
                     None, None, 0, None, "", "", "", "", ""))
    con.commit(); con.close()

    db = NASRAirportDB(str(p))
    (ap,) = list(db.airports_in_range(42.3, -83.0, 20))
    (rwy,) = ap.runways
    assert rwy.thr1_vgsi_type is None and rwy.thr1_visual_gpa is None
    assert rwy.thr2_vgsi_type is None and rwy.thr2_visual_gpa is None
