#  SPDX-License-Identifier: GPL-2.0-or-later
"""Tests for pyefis.flightplan.airways -- PA2 (billmallard/pyEfis#235,
AER-1601).

Builds a fixture ``procedures.pack`` sqlite in-test, matching PA1's schema
(makerplane-data ``packtools/build/procedures.py``) byte-for-byte: the
``airways``/``airway_legs`` tables plus ``idx_awy_ident``,
``idx_awyleg_awy``, ``idx_awyleg_fix``.

AER-2151: the epic's original design-of-day scenario, "KSBA GVO V27 RZS
KSMX", was struck -- RZS is not on V27 in the published cycle-2609 data
(it sits on V12, adjacent to GVO but with nothing between them), so the
scenario only ever passed against a hand-invented fixture. The replacement
below (``KSBA GVO V27 ORCUT KSMX``) is real: GVO/AFOXY/ORCUT is a genuine
three-fix stretch of V27, decoded from a live cycle-2609 CIFP file with
``packtools.arinc424`` (cross-checked, not hand-invented), and ORCUT sits a
few miles off KSMX's doorstep so the geography still reads as "feeding an
approach into Santa Maria" the way the original scenario intended.

A315 and A509 below are a second, independent real-data fixture: both are
copied verbatim (ident, seq, fix, lat/lon, altitudes) from
makerplane-data's golden CIFP slice (``tests/fixtures/cifp/FAACIFP18``,
cycle 2609), decoded the same way. They exist to close a coverage gap the
brief chartered but nothing implemented: expansion of a *complete*
published airway, entry to exit, asserting the exact published order (see
the "published sequence" tests below) -- V27's own fixture only ever
covered a 3-fix slice.

A third airway (A1) carries a coded one-way (Direction Restriction) leg --
the real cycle-2609 golden fixture PA1 ships has none, so the
direction-enforcement path is only exercised here, deliberately, against a
constructed table.
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

# Real cycle-2609 V27 coordinates/altitudes (AER-2151 replacement for the
# struck GVO/POM/RZS scenario), decoded from a live CIFP file with
# packtools.arinc424.iter_airway_legs -- GVO is a VOR, AFOXY and ORCUT are
# waypoints, all three consecutive on the published airway.
GVO = (34.53132, -120.09109)
AFOXY = (34.60868, -120.16213)
ORCUT = (34.85474, -120.38915)

# Real cycle-2609 A315 and A509 -- copied verbatim (ident, seq, fix,
# lat/lon, altitudes) from makerplane-data's golden CIFP fixture
# (tests/fixtures/cifp/FAACIFP18), decoded the same way. Both are complete
# airways end to end, used below to test published-sequence expansion
# against real data rather than a 3-fix hand-built slice.
_A315_LEGS = [
    (100, "ZBV",   (25.70392, -79.29364), "vor",      5000,  60000, None),
    (110, "SWIMM", (25.49978, -79.03836), "waypoint", 8000,  60000, None),
    (120, "TINKY", (24.98012, -78.39368), "waypoint", 12500, 60000, None),
    (130, "PEKRE", (24.73779, -78.09611), "waypoint", 14000, 60000, None),
    (140, "JAYEE", (24.43216, -77.72351), "waypoint", 7000,  60000, None),
    (150, "HODGY", (24.16050, -77.39478), "waypoint", 7000,  60000, None),
    (160, "AMBIS", (23.73163, -76.88019), "waypoint", 7000,  60000, None),
    (170, "DUNNO", (22.92841, -75.93128), "waypoint", 7000,  60000, None),
    (180, "ACMEE", (22.17438, -75.05638), "waypoint", 7000,  60000, None),
    (190, "KNSLY", (20.96139, -73.67750), "waypoint", 7000,  60000, None),
    (200, "JOSES", (20.14425, -73.21819), "waypoint", None,  None,  None),
]
_A509_LEGS = [
    (100, "URSUS", (24.00005, -79.06980), "waypoint", 16000, 60000, None),
    (110, "ELLEE", (24.88061, -79.69002), "waypoint", 16000, 60000, None),
    (120, "EONNS", (25.29672, -79.98684), "waypoint", 3000,  60000, None),
    (130, "JURER", (25.65126, -80.24163), "waypoint", 3000,  60000, None),
    (140, "DHP",   (25.79996, -80.34904), "vor",      8000,  60000, None),
    (150, "MARCI", (25.89107, -81.78399), "waypoint", None,  None,  None),
]


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

    # V27: KSBA GVO V27 ORCUT KSMX -- GVO -> AFOXY -> ORCUT, no direction
    # restriction, the AER-2151 replacement design-of-day scenario.
    insert_airway("V27", [
        (100, "GVO", GVO, "vor", 6000, 17500, None),
        (110, "AFOXY", AFOXY, "waypoint", 6000, 17500, None),
        (120, "ORCUT", ORCUT, "waypoint", 4000, 17500, None),
    ])
    # A1: a one-way (forward-only) restriction on the WOODY->WISKI leg --
    # synthetic; see module docstring for why.
    insert_airway("A1", [
        (100, "ALPHA", (35.0, -118.0), "waypoint", 3000, 17000, None),
        (110, "WOODY", (35.5, -118.2), "waypoint", 4000, 17000, None),
        (120, "WISKI", (36.0, -118.4), "waypoint", 5000, 17000, "F"),
        (130, "ZULUU", (36.5, -118.6), "waypoint", 5000, 17000, "B"),
    ])
    # A315 and A509: real, complete published airways (see module docstring).
    insert_airway("A315", _A315_LEGS)
    insert_airway("A509", _A509_LEGS)

    con.commit()
    con.close()
    return path


@pytest.fixture()
def graph(pack_path):
    g = AirwayGraph(pack_path)
    yield g
    # AER-2158: a connection that has executed a query is part of a
    # reference cycle (sqlite3's statement cache references it back) and
    # won't be reclaimed by refcounting alone -- close explicitly so ~25
    # connections a session don't pile up for the cyclic GC to sweep at an
    # unpredictable later point (a full-suite run showed exactly this:
    # ResourceWarning for an unclosed database attributed to unrelated
    # tests' code, because that's simply whatever was executing when the
    # collector finally ran).
    g.close()


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
        g.expand("V27", "GVO", "ORCUT")


def test_ready_when_pack_present(graph):
    assert graph.ready is True


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------
def test_airways_through_fix(graph):
    assert graph.airways_through_fix("AFOXY") == ["V27"]
    assert graph.airways_through_fix("gvo") == ["V27"]  # case-insensitive


def test_airways_through_fix_unknown_fix_is_empty(graph):
    assert graph.airways_through_fix("ZZZZZ") == []


def test_legs_are_published_order(graph):
    legs = graph.legs("v27")  # case-insensitive
    assert [leg.fix_id for leg in legs] == ["GVO", "AFOXY", "ORCUT"]
    assert [leg.seq for leg in legs] == [100, 110, 120]


def test_legs_unknown_ident_is_empty(graph):
    assert graph.legs("V9999") == []


# ---------------------------------------------------------------------------
# Expansion -- the KSBA GVO V27 ORCUT KSMX scenario (AER-2151)
# ---------------------------------------------------------------------------
def test_expand_forward_yields_published_sequence(graph):
    wps = graph.expand("V27", "GVO", "ORCUT")
    assert [wp.id for wp in wps] == ["GVO", "AFOXY", "ORCUT"]
    assert all(wp.type == "fix" for wp in wps)
    assert wps[0].lat == pytest.approx(GVO[0])
    assert wps[0].lon == pytest.approx(GVO[1])
    assert wps[-1].lat == pytest.approx(ORCUT[0])
    assert wps[-1].lon == pytest.approx(ORCUT[1])


def test_expand_reverse_yields_reversed_sequence(graph):
    wps = graph.expand("V27", "ORCUT", "GVO")
    assert [wp.id for wp in wps] == ["ORCUT", "AFOXY", "GVO"]


def test_expand_returns_insertable_waypoints(graph):
    wps = graph.expand("V27", "GVO", "ORCUT")
    for wp in wps:
        assert isinstance(wp, model.Waypoint)


def test_expand_unknown_airway_raises(graph):
    with pytest.raises(AirwayNotFoundError):
        graph.expand("V9999", "GVO", "ORCUT")


def test_expand_fix_not_on_airway_raises(graph):
    with pytest.raises(FixNotOnAirwayError):
        graph.expand("V27", "ZULUU", "ORCUT")
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
    assert [wp.id for wp in graph.expand("V27", "GVO", "AFOXY")] == ["GVO", "AFOXY"]
    assert [wp.id for wp in graph.expand("V27", "AFOXY", "GVO")] == ["AFOXY", "GVO"]


# ---------------------------------------------------------------------------
# Altitude range (brief section 3.4: min/max become enforced validation)
# ---------------------------------------------------------------------------
def test_altitude_range_is_the_binding_min_and_max(graph):
    # GVO(min 6000) -> AFOXY(min 6000) -> ORCUT(min 4000): binding min is
    # 6000. All three share max 17500.
    lo, hi = graph.altitude_range("V27", "GVO", "ORCUT")
    assert (lo, hi) == (6000, 17500)


def test_altitude_range_reverse_is_direction_independent(graph):
    assert graph.altitude_range("V27", "ORCUT", "GVO") == (6000, 17500)


def test_altitude_range_partial_segment(graph):
    # GVO -> AFOXY only: binding min is max(6000, 6000) = 6000.
    assert graph.altitude_range("V27", "GVO", "AFOXY") == (6000, 17500)


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
    g.close()


def test_altitude_range_same_errors_as_expand(graph):
    with pytest.raises(AirwayNotFoundError):
        graph.altitude_range("V9999", "GVO", "ORCUT")
    with pytest.raises(FixNotOnAirwayError):
        graph.altitude_range("V27", "ZULUU", "ORCUT")
    with pytest.raises(AirwayError):
        graph.altitude_range("V27", "GVO", "GVO")


# ---------------------------------------------------------------------------
# Published-sequence expansion against a REAL, complete airway (PA2's
# chartered test, AER-2151) -- see module docstring for A315/A509's
# provenance.
# ---------------------------------------------------------------------------
_A315_IDENTS = ["ZBV", "SWIMM", "TINKY", "PEKRE", "JAYEE", "HODGY",
                "AMBIS", "DUNNO", "ACMEE", "KNSLY", "JOSES"]


def test_expand_forward_yields_full_published_airway(graph):
    wps = graph.expand("A315", "ZBV", "JOSES")
    assert [wp.id for wp in wps] == _A315_IDENTS
    assert wps[0].lat == pytest.approx(_A315_LEGS[0][2][0])
    assert wps[0].lon == pytest.approx(_A315_LEGS[0][2][1])
    assert wps[-1].lat == pytest.approx(_A315_LEGS[-1][2][0])
    assert wps[-1].lon == pytest.approx(_A315_LEGS[-1][2][1])


def test_expand_reverse_yields_full_published_airway_reversed(graph):
    wps = graph.expand("A315", "JOSES", "ZBV")
    assert [wp.id for wp in wps] == list(reversed(_A315_IDENTS))


def test_expand_a509_published_sequence(graph):
    wps = graph.expand("A509", "URSUS", "MARCI")
    assert [wp.id for wp in wps] == ["URSUS", "ELLEE", "EONNS", "JURER", "DHP", "MARCI"]
