#  SPDX-License-Identifier: GPL-2.0-or-later
"""Tests for pyefis.flightplan.airways -- PA2 (billmallard/pyEfis#235,
AER-1601).

Builds a fixture ``procedures.pack`` sqlite in-test, matching PA1's schema
(makerplane-data ``packtools/build/procedures.py``) byte-for-byte: the
``airways``/``airway_legs`` tables plus ``idx_awy_ident``,
``idx_awyleg_awy``, ``idx_awyleg_fix``. V27 uses the real GVO/RZS
coordinates already established in ``test_waypoints.py`` so this exercises
the exact "KSBA GVO V27 RZS KSMX" scenario the epic targets. A second
airway (A1) carries a coded one-way (Direction Restriction) leg -- the real
cycle-2609 golden fixture PA1 ships has none, so the direction-enforcement
path is only exercised here, deliberately, against a constructed table.
"""

import sqlite3

import pytest

from pyefis.flightplan import model
from pyefis.flightplan.airways import (
    AirwayDirectionError,
    AirwayError,
    AirwayGraph,
    AirwayNotFoundError,
    FixNotOnAirwayError,
)

_SCHEMA = """
CREATE TABLE airways (
    id      INTEGER PRIMARY KEY,
    ident   TEXT NOT NULL,
    cycle   TEXT NOT NULL
);
CREATE TABLE airway_legs (
    airway_id   INTEGER NOT NULL REFERENCES airways(id),
    seq         INTEGER NOT NULL,
    fix_id      TEXT NOT NULL,
    fix_lat     REAL,
    fix_lon     REAL,
    fix_type    TEXT,
    min_alt_ft  INTEGER,
    max_alt_ft  INTEGER,
    direction   TEXT
);
CREATE INDEX idx_awy_ident ON airways(ident);
CREATE INDEX idx_awyleg_awy ON airway_legs(airway_id, seq);
CREATE INDEX idx_awyleg_fix ON airway_legs(fix_id);
"""

# Real navaid coordinates, matching test_waypoints.py's NAVAIDS table.
GVO = (34.53142, -120.09106)
RZS = (34.02000, -119.55000)
POM = (34.06000, -117.75000)


@pytest.fixture()
def pack_path(tmp_path):
    path = tmp_path / "procedures-conus.pack"
    con = sqlite3.connect(str(path))
    con.executescript(_SCHEMA)

    def insert_airway(ident, legs):
        cur = con.execute("INSERT INTO airways (ident, cycle) VALUES (?, ?)",
                           (ident, "2609"))
        airway_id = cur.lastrowid
        for seq, fix_id, (lat, lon), fix_type, min_alt, max_alt, direction in legs:
            con.execute(
                "INSERT INTO airway_legs (airway_id, seq, fix_id, fix_lat, fix_lon, "
                "fix_type, min_alt_ft, max_alt_ft, direction) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (airway_id, seq, fix_id, lat, lon, fix_type, min_alt, max_alt, direction))

    # V27: GVO -> POM -> RZS, no direction restriction (the common case).
    insert_airway("V27", [
        (100, "GVO", GVO, "vor", 5000, 18000, None),
        (110, "POM", POM, "ndb", 6000, 18000, None),
        (120, "RZS", RZS, "vor", 4000, 18000, None),
    ])
    # A1: a one-way (forward-only) restriction on the WOODY->WISKI leg.
    insert_airway("A1", [
        (100, "ALPHA", (35.0, -118.0), "waypoint", 3000, 17000, None),
        (110, "WOODY", (35.5, -118.2), "waypoint", 4000, 17000, None),
        (120, "WISKI", (36.0, -118.4), "waypoint", 5000, 17000, "F"),
        (130, "ZULUU", (36.5, -118.6), "waypoint", 5000, 17000, "B"),
    ])

    con.commit()
    con.close()
    return path


@pytest.fixture()
def graph(pack_path):
    return AirwayGraph(pack_path)


# ---------------------------------------------------------------------------
# Construct-never-raises / readiness
# ---------------------------------------------------------------------------
def test_missing_pack_is_not_ready(tmp_path):
    g = AirwayGraph(tmp_path / "does_not_exist.pack")
    assert g.ready is False


def test_no_path_is_not_ready():
    assert AirwayGraph(None).ready is False


def test_unreadable_file_is_not_ready(tmp_path):
    bogus = tmp_path / "bogus.pack"
    bogus.write_text("not a sqlite file")
    assert AirwayGraph(bogus).ready is False


def test_missing_pack_queries_answer_empty_or_raise(tmp_path):
    g = AirwayGraph(tmp_path / "does_not_exist.pack")
    assert g.airways_through_fix("GVO") == []
    assert g.legs("V27") == []
    with pytest.raises(AirwayNotFoundError):
        g.expand("V27", "GVO", "RZS")


def test_ready_when_pack_present(graph):
    assert graph.ready is True


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------
def test_airways_through_fix(graph):
    assert graph.airways_through_fix("POM") == ["V27"]
    assert graph.airways_through_fix("gvo") == ["V27"]  # case-insensitive


def test_airways_through_fix_unknown_fix_is_empty(graph):
    assert graph.airways_through_fix("ZZZZZ") == []


def test_legs_are_published_order(graph):
    legs = graph.legs("v27")  # case-insensitive
    assert [leg.fix_id for leg in legs] == ["GVO", "POM", "RZS"]
    assert [leg.seq for leg in legs] == [100, 110, 120]


def test_legs_unknown_ident_is_empty(graph):
    assert graph.legs("V9999") == []


# ---------------------------------------------------------------------------
# Expansion -- the KSBA GVO V27 RZS KSMX scenario
# ---------------------------------------------------------------------------
def test_expand_forward_yields_published_sequence(graph):
    wps = graph.expand("V27", "GVO", "RZS")
    assert [wp.id for wp in wps] == ["GVO", "POM", "RZS"]
    assert all(wp.type == "fix" for wp in wps)
    assert wps[0].lat == pytest.approx(GVO[0])
    assert wps[0].lon == pytest.approx(GVO[1])
    assert wps[-1].lat == pytest.approx(RZS[0])
    assert wps[-1].lon == pytest.approx(RZS[1])


def test_expand_reverse_yields_reversed_sequence(graph):
    wps = graph.expand("V27", "RZS", "GVO")
    assert [wp.id for wp in wps] == ["RZS", "POM", "GVO"]


def test_expand_returns_insertable_waypoints(graph):
    wps = graph.expand("V27", "GVO", "RZS")
    for wp in wps:
        assert isinstance(wp, model.Waypoint)


def test_expand_unknown_airway_raises(graph):
    with pytest.raises(AirwayNotFoundError):
        graph.expand("V9999", "GVO", "RZS")


def test_expand_fix_not_on_airway_raises(graph):
    with pytest.raises(FixNotOnAirwayError):
        graph.expand("V27", "ZULUU", "RZS")
    with pytest.raises(FixNotOnAirwayError):
        graph.expand("V27", "GVO", "ZULUU")


def test_expand_same_entry_and_exit_raises(graph):
    with pytest.raises(AirwayError):
        graph.expand("V27", "GVO", "GVO")


# ---------------------------------------------------------------------------
# Direction restriction enforcement (brief section 3.4 decision 3)
# ---------------------------------------------------------------------------
def test_expand_forward_only_leg_permits_forward_travel(graph):
    wps = graph.expand("A1", "WOODY", "WISKI")
    assert [wp.id for wp in wps] == ["WOODY", "WISKI"]


def test_expand_forward_only_leg_rejects_backward_travel(graph):
    with pytest.raises(AirwayDirectionError):
        graph.expand("A1", "WISKI", "WOODY")


def test_expand_backward_only_leg_permits_backward_travel(graph):
    wps = graph.expand("A1", "ZULUU", "WISKI")
    assert [wp.id for wp in wps] == ["ZULUU", "WISKI"]


def test_expand_backward_only_leg_rejects_forward_travel(graph):
    with pytest.raises(AirwayDirectionError):
        graph.expand("A1", "WISKI", "ZULUU")


def test_expand_spanning_both_restrictions_rejects_either_direction(graph):
    # ALPHA -> ZULUU forward crosses both the F leg (fine) and the B leg
    # (forbidden going forward) -- must reject.
    with pytest.raises(AirwayDirectionError):
        graph.expand("A1", "ALPHA", "ZULUU")
    with pytest.raises(AirwayDirectionError):
        graph.expand("A1", "ZULUU", "ALPHA")


def test_unrestricted_leg_permits_both_directions(graph):
    assert [wp.id for wp in graph.expand("V27", "GVO", "POM")] == ["GVO", "POM"]
    assert [wp.id for wp in graph.expand("V27", "POM", "GVO")] == ["POM", "GVO"]


# ---------------------------------------------------------------------------
# Altitude range (brief section 3.4: min/max become enforced validation)
# ---------------------------------------------------------------------------
def test_altitude_range_is_the_binding_min_and_max(graph):
    # GVO(min 5000) -> POM(min 6000) -> RZS(min 4000): binding min is 6000.
    # All three share max 18000.
    lo, hi = graph.altitude_range("V27", "GVO", "RZS")
    assert (lo, hi) == (6000, 18000)


def test_altitude_range_reverse_is_direction_independent(graph):
    assert graph.altitude_range("V27", "RZS", "GVO") == (6000, 18000)


def test_altitude_range_partial_segment(graph):
    # GVO -> POM only: binding min is max(5000, 6000) = 6000.
    assert graph.altitude_range("V27", "GVO", "POM") == (6000, 18000)


def test_altitude_range_missing_data_is_none(tmp_path):
    path = tmp_path / "no_alt.pack"
    con = sqlite3.connect(str(path))
    con.executescript(_SCHEMA)
    cur = con.execute("INSERT INTO airways (ident, cycle) VALUES (?, ?)", ("B1", "2609"))
    awy_id = cur.lastrowid
    con.execute("INSERT INTO airway_legs (airway_id, seq, fix_id, fix_lat, fix_lon, "
                "fix_type, min_alt_ft, max_alt_ft, direction) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (awy_id, 100, "FOO", 35.0, -118.0, "waypoint", None, None, None))
    con.execute("INSERT INTO airway_legs (airway_id, seq, fix_id, fix_lat, fix_lon, "
                "fix_type, min_alt_ft, max_alt_ft, direction) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (awy_id, 110, "BAR", 35.5, -118.5, "waypoint", None, None, None))
    con.commit()
    con.close()
    g = AirwayGraph(path)
    assert g.altitude_range("B1", "FOO", "BAR") == (None, None)


def test_altitude_range_same_errors_as_expand(graph):
    with pytest.raises(AirwayNotFoundError):
        graph.altitude_range("V9999", "GVO", "RZS")
    with pytest.raises(FixNotOnAirwayError):
        graph.altitude_range("V27", "ZULUU", "RZS")
    with pytest.raises(AirwayError):
        graph.altitude_range("V27", "GVO", "GVO")
