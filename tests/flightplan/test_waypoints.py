#  SPDX-License-Identifier: GPL-2.0-or-later
"""Tests for pyefis.flightplan.waypoints -- FP3 (billmallard/pyEfis#182).

Builds a fixture ``airports.sqlite`` / ``navaids.sqlite`` pair in-test (a
dozen airports incl. a 3-letter FAA id, a few VOR/NDB, fixes incl. a
duplicate ident shared with a VOR) and exercises every path named in the
issue's Definition of Done.
"""

import csv
import subprocess
import sqlite3
import sys
import time
from pathlib import Path

import pytest

from pyefis.flightplan import geo
from pyefis.flightplan.waypoints import (
    DuplicateIdentError,
    InvalidWaypointError,
    RecentList,
    USER_WAYPOINT_CAP,
    UserWaypointStore,
    WaypointCapacityError,
    WaypointInUseError,
    WaypointIndex,
    WaypointNotFoundError,
)

REF = (34.4275, -119.8546)  # near KSBA -- the visual-harness default position

# (site_no, icao, name, lat, lon, elev_ft, longest_runway_ft)
AIRPORTS = [
    ("1",  "SBA",  "Santa Barbara Muni",  34.42621, -119.84037, 10,   6000),  # 3-letter FAA id
    ("2",  "KSMX", "Santa Maria Pub",     34.89892, -120.45758, 257,  6304),
    ("3",  "KLAX", "Los Angeles Intl",    33.94250, -118.40810, 125,  12091),
    ("4",  "KVNY", "Van Nuys",            34.20970, -118.48980, 802,  8001),
    ("5",  "KOXR", "Oxnard",              34.20090, -119.20710, 45,   6014),
    ("6",  "KSZP", "Santa Paula",         34.35720, -119.06180, 243,  2641),
    ("7",  "KRIV", "Riverside Muni",      33.95190, -117.44500, 819,  4998),
    ("8",  "KBUR", "Bob Hope",            34.20070, -118.35900, 778,  6886),
    ("9",  "KSDM", "Brown Field",         32.57230, -116.98000, 526,  7972),
    ("10", "KJFK", "John F Kennedy Intl", 40.63990, -73.77870,  13,   14511),  # > 200 nm
    ("11", "KDEN", "Denver Intl",         39.85840, -104.66700, 5431, 16000),  # > 200 nm
    ("12", "KEYW", "Key West Intl",       24.55610, -81.75960,  3,    4801),   # > 200 nm
]

# (id, type, name, freq, elev_ft, lat, lon)
NAVAIDS = [
    ("GVO", "VOR/DME", "Gaviota", "113.90", 2125, 34.53142, -120.09106),
    ("RZS", "VOR/DME", "Reyes",   "115.40", 1500, 34.02000, -119.55000),
    ("POM", "NDB",     "Pomona",  "356",    800,  34.06000, -117.75000),
    ("ZZZ", "VOR",     "Zulu Zulu Zulu", "112.30", 900, 34.50000, -119.50000),  # dup ident w/ a fix
]

# (id, use_code, lat, lon)
FIXES = [
    ("ZUMAB", "RP", 34.60000, -120.00000),
    ("RIICH", "RP", 34.70000, -119.90000),
    ("ZZZ",   "RP", 34.51000, -119.49000),  # duplicate ident shared with the VOR above
]


def _build_fixture_dbs(tmp_path):
    airports_path = tmp_path / "airports.sqlite"
    con = sqlite3.connect(str(airports_path))
    con.executescript(
        "CREATE TABLE airports (site_no TEXT PRIMARY KEY, icao TEXT, name TEXT, "
        "  lat REAL, lon REAL, elev_ft REAL);"
        "CREATE TABLE runways (site_no TEXT, rwy_id TEXT, length_ft REAL);"
        "CREATE INDEX idx_airports_icao ON airports(icao);"
    )
    for site_no, icao, name, lat, lon, elev_ft, rwy_len in AIRPORTS:
        con.execute("INSERT INTO airports VALUES (?,?,?,?,?,?)",
                    (site_no, icao, name, lat, lon, elev_ft))
        con.execute("INSERT INTO runways VALUES (?,?,?)",
                    (site_no, "1", rwy_len))
    con.commit()
    con.close()

    navaids_path = tmp_path / "navaids.sqlite"
    con = sqlite3.connect(str(navaids_path))
    con.executescript(
        "CREATE TABLE navaids (id TEXT, type TEXT, name TEXT, freq TEXT, "
        "  elev_ft REAL, lat REAL, lon REAL);"
        "CREATE TABLE fixes (id TEXT, use_code TEXT, lat REAL, lon REAL);"
    )
    con.executemany("INSERT INTO navaids VALUES (?,?,?,?,?,?,?)", NAVAIDS)
    con.executemany("INSERT INTO fixes VALUES (?,?,?,?)", FIXES)
    con.commit()
    con.close()

    return airports_path, navaids_path


@pytest.fixture
def index(tmp_path):
    airports_path, navaids_path = _build_fixture_dbs(tmp_path)
    idx = WaypointIndex(str(airports_path), str(navaids_path),
                        user_file=str(tmp_path / "user_waypoints.json"),
                        recent_file=str(tmp_path / "recent.json"))
    assert idx.wait_ready(timeout=5) is True
    return idx


# ---------------------------------------------------------------------------
# construct-never-raises / ready
# ---------------------------------------------------------------------------
def test_missing_files_never_raises_and_not_ready(tmp_path):
    idx = WaypointIndex(str(tmp_path / "nope_airports.sqlite"),
                        str(tmp_path / "nope_navaids.sqlite"))
    assert idx.wait_ready(timeout=5) is False
    assert idx.ready is False
    assert idx.lookup("KSBA") == []


def test_construct_with_no_paths_never_raises():
    idx = WaypointIndex()
    assert idx.wait_ready(timeout=5) is False
    assert idx.ready is False


def test_index_build_budget_ms(tmp_path):
    airports_path, navaids_path = _build_fixture_dbs(tmp_path)
    t0 = time.monotonic()
    idx = WaypointIndex(str(airports_path), str(navaids_path))
    assert idx.wait_ready(timeout=5) is True
    dt_ms = (time.monotonic() - t0) * 1000
    assert dt_ms < 50, f"fixture index build took {dt_ms:.1f} ms (budget 50 ms)"


# ---------------------------------------------------------------------------
# lookup
# ---------------------------------------------------------------------------
def test_lookup_icao_and_faa_id_both_forms(index):
    by_faa = index.lookup("SBA")
    by_icao = index.lookup("KSBA")
    assert [w.id for w in by_faa] == ["KSBA"]
    assert [w.id for w in by_icao] == ["KSBA"]
    assert by_faa[0].type == "airport"
    assert by_faa[0].name == "Santa Barbara Muni"


def test_lookup_k_prefixed_alias_also_strips(index):
    # KSMX in the db already carries the K -- SMX must resolve to it too.
    got = index.lookup("SMX")
    assert [w.id for w in got] == ["KSMX"]


def test_lookup_duplicate_ident_returns_both(index):
    got = index.lookup("ZZZ")
    types = sorted(w.type for w in got)
    assert types == ["fix", "vor"]


def test_lookup_unknown_ident_returns_empty(index):
    assert index.lookup("QQQQQQ") == []


# ---------------------------------------------------------------------------
# prefix (FastFind)
# ---------------------------------------------------------------------------
def test_prefix_ordered_by_distance_from_ref(index):
    # KSBA, KSMX, KSZP all match "KS"; order changes with the reference point.
    near_sba = index.prefix("KS", *REF, types={"airport"})
    assert [w.id for w in near_sba][:1] == ["KSBA"]

    near_smx = index.prefix("KS", 34.89892, -120.45758, types={"airport"})
    assert [w.id for w in near_smx][:1] == ["KSMX"]
    assert near_sba != near_smx


def test_prefix_respects_limit_and_type_filter(index):
    got = index.prefix("K", *REF, limit=2, types={"airport"})
    assert len(got) == 2
    assert all(w.type == "airport" for w in got)


def test_prefix_includes_user_waypoints(index):
    index.user.add(lat=34.43, lon=-119.85, comment="near SBA", id="FOXY")
    got = index.prefix("FOX", *REF)
    assert [w.id for w in got] == ["FOXY"]


def test_prefix_empty_text_returns_nothing(index):
    assert index.prefix("", *REF) == []


# ---------------------------------------------------------------------------
# nearest
# ---------------------------------------------------------------------------
def test_nearest_orders_ascending_and_applies_200nm_cutoff(index):
    got = index.nearest(*REF, radius_nm=200, limit=25, types={"airport"})
    ids = [wp.id for wp, dist, brg, extra in got]
    assert ids[0] == "KSBA"
    dists = [dist for wp, dist, brg, extra in got]
    assert dists == sorted(dists)
    # far outliers (> 200 nm from REF) must be excluded
    assert "KJFK" not in ids and "KDEN" not in ids and "KEYW" not in ids
    # KSDM is ~182 nm -- inside the cut, must appear
    assert "KSDM" in ids
    assert len(got) <= 25


def test_nearest_airport_extra_is_longest_runway(index):
    got = index.nearest(*REF, radius_nm=10, types={"airport"})
    assert len(got) == 1
    wp, dist, brg, extra = got[0]
    assert wp.id == "KSBA"
    assert extra == 6000


def test_nearest_non_airport_extra_is_none(index):
    got = index.nearest(*REF, radius_nm=25, types={"fix"})
    assert got and all(extra is None for _wp, _d, _b, extra in got)


def test_nearest_bearing_true_matches_geo(index):
    got = index.nearest(*REF, radius_nm=10, types={"airport"})
    wp, dist, brg, extra = got[0]
    assert brg == pytest.approx(geo.initial_bearing(*REF, wp.lat, wp.lon), abs=1e-6)


# ---------------------------------------------------------------------------
# user waypoints
# ---------------------------------------------------------------------------
def test_user_add_default_ident_and_persists(tmp_path):
    store = UserWaypointStore(str(tmp_path / "user_waypoints.json"))
    wp = store.add(lat=34.5, lon=-119.9, comment="ridge")
    assert wp.id == "USR001"
    assert wp.type == "user"

    reloaded = UserWaypointStore(str(tmp_path / "user_waypoints.json"))
    assert [w.id for w in reloaded.list()] == ["USR001"]


def test_user_add_explicit_id_uppercased(tmp_path):
    store = UserWaypointStore(str(tmp_path / "u.json"))
    wp = store.add(lat=34.5, lon=-119.9, comment="", id="ridge1")
    assert wp.id == "RIDGE1"


def test_user_add_rejects_long_ident(tmp_path):
    store = UserWaypointStore(str(tmp_path / "u.json"))
    with pytest.raises(InvalidWaypointError):
        store.add(lat=34.5, lon=-119.9, id="TOOLONGID")


def test_user_add_rejects_long_comment(tmp_path):
    store = UserWaypointStore(str(tmp_path / "u.json"))
    with pytest.raises(InvalidWaypointError):
        store.add(lat=34.5, lon=-119.9, comment="x" * 26, id="ABC")


def test_user_add_duplicate_ident_refused(tmp_path):
    store = UserWaypointStore(str(tmp_path / "u.json"))
    store.add(lat=34.5, lon=-119.9, id="ABC")
    with pytest.raises(DuplicateIdentError):
        store.add(lat=10.0, lon=10.0, id="ABC")


def test_user_add_cap(tmp_path, monkeypatch):
    import pyefis.flightplan.waypoints as wpmod
    monkeypatch.setattr(wpmod, "USER_WAYPOINT_CAP", 2)
    store = UserWaypointStore(str(tmp_path / "u.json"))
    store.add(lat=1, lon=1, id="AAA")
    store.add(lat=2, lon=2, id="BBB")
    with pytest.raises(WaypointCapacityError):
        store.add(lat=3, lon=3, id="CCC")


def test_user_edit_updates_fields(tmp_path):
    store = UserWaypointStore(str(tmp_path / "u.json"))
    store.add(lat=34.5, lon=-119.9, comment="old", id="ABC")
    wp = store.edit("ABC", lat=1.0, lon=2.0, comment="new")
    assert (wp.lat, wp.lon, wp.comment) == (1.0, 2.0, "new")


def test_user_edit_missing_raises(tmp_path):
    store = UserWaypointStore(str(tmp_path / "u.json"))
    with pytest.raises(WaypointNotFoundError):
        store.edit("NOPE", lat=1.0)


def test_user_delete(tmp_path):
    store = UserWaypointStore(str(tmp_path / "u.json"))
    store.add(lat=34.5, lon=-119.9, id="ABC")
    store.delete("ABC")
    assert store.list() == []


def test_user_edit_and_delete_refused_while_active(tmp_path):
    store = UserWaypointStore(str(tmp_path / "u.json"))
    store.add(lat=34.5, lon=-119.9, id="ABC")
    with pytest.raises(WaypointInUseError):
        store.edit("ABC", lat=1.0, active_idents={"ABC"})
    with pytest.raises(WaypointInUseError):
        store.delete("ABC", active_idents={"abc"})  # case-insensitive
    # still there -- both refusals were no-ops
    assert [w.id for w in store.list()] == ["ABC"]


def test_user_import_csv_limits_and_dedupe(tmp_path):
    csv_path = tmp_path / "import.csv"
    with open(csv_path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "lat", "lon", "comment"])
        w.writerow(["FOX1", "34.7100", "-119.9100", "Foxtrot One"])
        w.writerow(["FOX1", "34.7200", "-119.9200", "duplicate ident"])
        w.writerow(["FOX2", "34.71005", "-119.91005", "within dedupe distance of FOX1"])
        w.writerow(["BADROW", "not-a-number", "-119.9", "invalid lat"])
        w.writerow(["TOOLONGID1", "34.8000", "-120.0000", "ident too long"])

    store = UserWaypointStore(str(tmp_path / "u.json"))
    result = store.import_csv(str(csv_path))

    assert result.added == 1
    assert result.skipped_duplicate_id == 1
    assert result.skipped_duplicate_position == 1
    assert result.skipped_invalid == 2
    assert [w.id for w in store.list()] == ["FOX1"]


# ---------------------------------------------------------------------------
# recent
# ---------------------------------------------------------------------------
def test_recent_caps_at_20_most_recent_first(tmp_path):
    recent = RecentList(str(tmp_path / "recent.json"))
    for i in range(25):
        recent.push(f"WP{i:03d}")
    got = recent.list()
    assert len(got) == 20
    assert got[0] == "WP024"  # most recently pushed is first
    assert "WP000" not in got  # the oldest fell off the cap


def test_recent_push_existing_moves_to_front(tmp_path):
    recent = RecentList(str(tmp_path / "recent.json"))
    recent.push("AAA")
    recent.push("BBB")
    recent.push("AAA")
    assert recent.list() == ["AAA", "BBB"]


def test_recent_persists_across_instances(tmp_path):
    path = str(tmp_path / "recent.json")
    RecentList(path).push("KSBA")
    assert RecentList(path).list() == ["KSBA"]


# ---------------------------------------------------------------------------
# Qt-free
# ---------------------------------------------------------------------------
def test_no_qt_import():
    src_root = str(Path(__file__).resolve().parents[2] / "src")
    code = (
        "import sys\n"
        "import pyefis.flightplan.waypoints\n"
        "assert 'PyQt6' not in sys.modules, sorted(m for m in sys.modules if 'PyQt' in m)\n"
    )
    result = subprocess.run([sys.executable, "-c", code], cwd=src_root,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
