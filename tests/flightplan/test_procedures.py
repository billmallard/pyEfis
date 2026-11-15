#  SPDX-License-Identifier: GPL-2.0-or-later
"""Tests for pyefis.flightplan.procedures -- PA5 (billmallard/pyEfis#236,
AER-1604).

Builds a fixture ``procedures.pack`` sqlite in-test, matching PA1's schema
(makerplane-data ``packtools/build/procedures.py``) byte-for-byte: the
``procedures``/``transitions``/``legs`` tables plus ``idx_proc_airport``,
``idx_trans_proc``, ``idx_legs_trans``. Same approach as
``test_airways.py`` -- a small hand-built table rather than a binary
fixture shared across repos. KSBA/GVO use the real coordinates already
established in ``test_waypoints.py``/``test_airways.py``.
"""

import sqlite3

import pytest

from pyefis.flightplan.procedures import (
    Procedure,
    ProcedureIndex,
    ProcedureLeg,
    Transition,
)

_SCHEMA = """
CREATE TABLE procedures (
    id              INTEGER PRIMARY KEY,
    airport         TEXT NOT NULL,
    kind            TEXT NOT NULL,
    ident           TEXT NOT NULL,
    runway          TEXT,
    approach_type   TEXT,
    rnp             REAL,
    cycle           TEXT NOT NULL
);
CREATE TABLE transitions (
    id          INTEGER PRIMARY KEY,
    proc_id     INTEGER NOT NULL REFERENCES procedures(id),
    role        TEXT NOT NULL,
    ident       TEXT
);
CREATE TABLE legs (
    transition_id   INTEGER NOT NULL REFERENCES transitions(id),
    seq             INTEGER NOT NULL,
    path_term       TEXT NOT NULL,
    fix_id          TEXT,
    fix_lat         REAL,
    fix_lon         REAL,
    fix_type        TEXT,
    recd_navaid     TEXT,
    theta           REAL,
    rho             REAL,
    course          REAL,
    dist_nm         REAL,
    time_min        REAL,
    alt_desc        TEXT,
    alt1_ft         INTEGER,
    alt2_ft         INTEGER,
    speed_kt        INTEGER,
    turn_dir        TEXT,
    rnp             REAL,
    flags           INTEGER NOT NULL,
    centre_fix      TEXT,
    centre_lat      REAL,
    centre_lon      REAL,
    arc_radius_nm   REAL
);
CREATE INDEX idx_proc_airport ON procedures(airport, kind);
CREATE INDEX idx_trans_proc ON transitions(proc_id);
CREATE INDEX idx_legs_trans ON legs(transition_id, seq);
"""

KSBA = (34.42621, -119.84037)
GVO = (34.53142, -120.09106)

# ARINC 424 5.20 WDC bit 5 -- first leg of the missed-approach segment
# (mirrors makerplane-data packtools.arinc424.FLAG_FIRST_MISSED_LEG).
FLAG_FIRST_MISSED_LEG = 1 << 5


@pytest.fixture()
def pack_path(tmp_path):
    path = tmp_path / "procedures-conus.pack"
    con = sqlite3.connect(str(path))
    con.executescript(_SCHEMA)

    def insert_procedure(airport, kind, ident, runway, approach_type, rnp):
        cur = con.execute(
            "INSERT INTO procedures (airport, kind, ident, runway, "
            "approach_type, rnp, cycle) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (airport, kind, ident, runway, approach_type, rnp, "2609"))
        return cur.lastrowid

    def insert_transition(proc_id, role, ident):
        cur = con.execute(
            "INSERT INTO transitions (proc_id, role, ident) VALUES (?, ?, ?)",
            (proc_id, role, ident))
        return cur.lastrowid

    def insert_leg(transition_id, seq, path_term, fix_id, latlon, **kw):
        lat, lon = latlon if latlon else (None, None)
        row = dict(transition_id=transition_id, seq=seq, path_term=path_term,
                   fix_id=fix_id, fix_lat=lat, fix_lon=lon, fix_type=None,
                   recd_navaid=None, theta=None, rho=None, course=None,
                   dist_nm=None, time_min=None, alt_desc=None, alt1_ft=None,
                   alt2_ft=None, speed_kt=None, turn_dir=None, rnp=None,
                   flags=0, centre_fix=None, centre_lat=None, centre_lon=None,
                   arc_radius_nm=None)
        row.update(kw)
        cols = ", ".join(row)
        qs = ", ".join("?" for _ in row)
        con.execute(f"INSERT INTO legs ({cols}) VALUES ({qs})", list(row.values()))

    # KSBA ILS RWY 7: an enroute (GVO) transition feeding into the common
    # (final + missed) transition.
    apr = insert_procedure("KSBA", "approach", "I07", "07", "I", 0.3)
    apr_enroute = insert_transition(apr, "enroute", "GVO")
    insert_leg(apr_enroute, 10, "IF", "GVO", GVO)
    apr_common = insert_transition(apr, "common", None)
    insert_leg(apr_common, 10, "CF", "FAWSB", (34.45, -119.80), alt1_ft=2000)
    insert_leg(apr_common, 20, "RF", "RW07", KSBA, centre_fix="ARCCTR",
               centre_lat=34.40, centre_lon=-119.82, arc_radius_nm=1.2)
    insert_leg(apr_common, 30, "CF", "MISSFX", (34.50, -119.90),
               flags=FLAG_FIRST_MISSED_LEG)

    # KSBA SID with a runway-specific transition (RW07), a common transition
    # and an enroute (GVO) transition -- exercises runways_at()'s SID path.
    sid = insert_procedure("KSBA", "sid", "TEST1", None, None, None)
    sid_rw = insert_transition(sid, "runway", "RW07")
    insert_leg(sid_rw, 10, "CA", None, None, alt1_ft=1000)
    sid_common = insert_transition(sid, "common", None)
    insert_leg(sid_common, 10, "TF", "FIX1", (34.44, -119.83))
    sid_enroute = insert_transition(sid, "enroute", "GVO")
    insert_leg(sid_enroute, 10, "TF", "GVO", GVO)

    # A circling-only approach (no runway of its own) at the same airport --
    # must be excluded by a runway filter but included with none.
    insert_procedure("KSBA", "approach", "VOR-A", None, "VOR", None)

    # A different airport's approach -- must never leak into a KSBA query.
    insert_procedure("KSMX", "approach", "I12", "12", "I", 0.3)

    con.commit()
    con.close()
    return path


@pytest.fixture()
def idx(pack_path):
    return ProcedureIndex(pack_path)


# ---------------------------------------------------------------------------
# Construct-never-raises / readiness
# ---------------------------------------------------------------------------
def test_missing_pack_is_not_ready(tmp_path):
    i = ProcedureIndex(tmp_path / "does_not_exist.pack")
    assert i.ready is False


def test_none_path_is_not_ready():
    assert ProcedureIndex(None).ready is False


def test_bogus_file_is_not_ready(tmp_path):
    bogus = tmp_path / "bogus.pack"
    bogus.write_text("not a sqlite file")
    assert ProcedureIndex(bogus).ready is False


def test_not_ready_queries_answer_empty_never_raise(tmp_path):
    i = ProcedureIndex(tmp_path / "does_not_exist.pack")
    assert i.procedures_at("KSBA") == []
    assert i.find("KSBA", "approach", "I07") is None
    assert i.runways_at("KSBA") == []
    assert i.transitions_for(1) == []
    assert i.legs_for(1) == []


def test_pack_opens(idx):
    assert idx.ready is True


# ---------------------------------------------------------------------------
# procedures_at
# ---------------------------------------------------------------------------
def test_procedures_at_returns_every_kind_sorted_by_ident(idx):
    procs = idx.procedures_at("KSBA")
    assert [p.ident for p in procs] == ["I07", "TEST1", "VOR-A"]
    assert all(isinstance(p, Procedure) for p in procs)


def test_procedures_at_filters_by_kind(idx):
    procs = idx.procedures_at("KSBA", kind="approach")
    assert {p.ident for p in procs} == {"I07", "VOR-A"}


def test_procedures_at_does_not_leak_other_airports(idx):
    procs = idx.procedures_at("KSBA")
    assert all(p.airport == "KSBA" for p in procs)
    assert idx.procedures_at("KSMX")[0].ident == "I12"


def test_procedures_at_unknown_airport_is_empty(idx):
    assert idx.procedures_at("KXXX") == []


def test_procedures_at_approach_runway_filter_matches_normalised(idx):
    # "7" normalises to "07", matching the stored "07".
    procs = idx.procedures_at("KSBA", kind="approach", runway="7")
    assert [p.ident for p in procs] == ["I07"]


def test_procedures_at_runway_filter_excludes_circling(idx):
    procs = idx.procedures_at("KSBA", kind="approach", runway="07")
    assert "VOR-A" not in {p.ident for p in procs}


def test_procedures_at_sid_runway_filter_uses_runway_transition(idx):
    procs = idx.procedures_at("KSBA", kind="sid", runway="07")
    assert [p.ident for p in procs] == ["TEST1"]
    assert idx.procedures_at("KSBA", kind="sid", runway="25") == []


# ---------------------------------------------------------------------------
# find
# ---------------------------------------------------------------------------
def test_find_exact_match(idx):
    p = idx.find("KSBA", "approach", "I07")
    assert p is not None
    assert p.approach_type == "I" and p.runway == "07" and p.rnp == 0.3
    assert p.cycle == "2609"


def test_find_unknown_is_none(idx):
    assert idx.find("KSBA", "approach", "I99") is None


# ---------------------------------------------------------------------------
# runways_at
# ---------------------------------------------------------------------------
def test_runways_at_approach_default_kind(idx):
    assert idx.runways_at("KSBA") == ["07"]


def test_runways_at_sid_from_runway_transition(idx):
    assert idx.runways_at("KSBA", kind="sid") == ["07"]


def test_runways_at_star_with_no_runway_transitions_is_empty(idx):
    assert idx.runways_at("KSBA", kind="star") == []


# ---------------------------------------------------------------------------
# transitions_for
# ---------------------------------------------------------------------------
def test_transitions_for_returns_every_role(idx):
    proc = idx.find("KSBA", "sid", "TEST1")
    trans = idx.transitions_for(proc.id)
    assert {t.role for t in trans} == {"runway", "common", "enroute"}
    assert all(isinstance(t, Transition) and t.proc_id == proc.id for t in trans)


def test_transitions_for_filters_by_role(idx):
    proc = idx.find("KSBA", "sid", "TEST1")
    trans = idx.transitions_for(proc.id, role="runway")
    assert len(trans) == 1 and trans[0].ident == "RW07"


def test_transitions_for_unknown_proc_is_empty(idx):
    assert idx.transitions_for(999999) == []


# ---------------------------------------------------------------------------
# legs_for
# ---------------------------------------------------------------------------
def test_legs_for_ordered_by_seq(idx):
    proc = idx.find("KSBA", "approach", "I07")
    common = next(t for t in idx.transitions_for(proc.id) if t.role == "common")
    legs = idx.legs_for(common.id)
    assert [leg.seq for leg in legs] == [10, 20, 30]
    assert all(isinstance(leg, ProcedureLeg) for leg in legs)


def test_legs_for_carries_rf_arc_fields(idx):
    proc = idx.find("KSBA", "approach", "I07")
    common = next(t for t in idx.transitions_for(proc.id) if t.role == "common")
    legs = idx.legs_for(common.id)
    arc_leg = next(leg for leg in legs if leg.path_term == "RF")
    assert arc_leg.centre_fix == "ARCCTR"
    assert arc_leg.centre_lat == pytest.approx(34.40)
    assert arc_leg.arc_radius_nm == pytest.approx(1.2)


def test_legs_for_carries_missed_flag_opaque(idx):
    proc = idx.find("KSBA", "approach", "I07")
    common = next(t for t in idx.transitions_for(proc.id) if t.role == "common")
    legs = idx.legs_for(common.id)
    missed_leg = next(leg for leg in legs if leg.fix_id == "MISSFX")
    assert missed_leg.flags & FLAG_FIRST_MISSED_LEG


def test_legs_for_carries_position_and_altitude(idx):
    proc = idx.find("KSBA", "approach", "I07")
    enroute = next(t for t in idx.transitions_for(proc.id) if t.role == "enroute")
    leg = idx.legs_for(enroute.id)[0]
    assert leg.fix_id == "GVO"
    assert leg.lat == pytest.approx(GVO[0])
    assert leg.lon == pytest.approx(GVO[1])


def test_legs_for_unknown_transition_is_empty(idx):
    assert idx.legs_for(999999) == []
