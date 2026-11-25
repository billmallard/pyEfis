#  SPDX-License-Identifier: GPL-2.0-or-later
"""Tests for pyefis.flightplan.route_string -- RTE1 (AER-6454).

The packs are real: ``fixtures/route_string_packs.json`` holds unedited
cycle-2611 rows from the bench's airports, navaids and procedures packs
(``fixtures/make_route_string_packs.py`` regenerates it). Where a test adds
a row of its own, it says so.

Bill's two bench plans are ForeFlight exports of KSBA-KPHX and KSBA-KPMD
(fix-gateway ``tests/plugins/fpl_exchange/data/foreflight/``, AER-6321).
Their waypoints and coordinates are copied below, and the route strings
here must expand to exactly those points from the panel's own navdata.
"""

import json
import sqlite3
from pathlib import Path

import pytest

from pyefis.flightplan import geo
from pyefis.flightplan import route_string as rs
from pyefis.flightplan.airways import AirwayGraph
from pyefis.flightplan.procedures import ProcedureIndex
from pyefis.flightplan.waypoints import WaypointIndex

FIXTURE = Path(__file__).parent / "fixtures" / "route_string_packs.json"

# (ident, Garmin type, lat, lon), from ksba_kphx.fpl in fix-gateway.
KSBA_KPHX_FPL = [
    ("KSBA", "AIRPORT", 34.426192, -119.841493),
    ("FLOUT", "INT", 34.257589, -119.953203),
    ("VTU", "VOR", 34.115064, -119.0495),
    ("HENER", "INT", 34.331064, -119.227689),
    ("OHIGH", "INT", 34.431353, -119.310819),
    ("TTE", "VOR", 35.91305, -119.020808),
    ("WRING", "INT", 35.513156, -118.874961),
    ("AMONT", "INT", 35.183811, -118.755381),
    ("LOPES", "INT", 35.031814, -118.701403),
    ("PAIDD", "INT", 34.843322, -118.634233),
    ("JEFFY", "INT", 34.748139, -118.600106),
    ("LHS", "VOR", 34.682972, -118.576939),
    ("WAYVE", "INT", 34.572875, -118.512353),
    ("DARTS", "INT", 34.156047, -118.269594),
    ("MOVVE", "INT", 34.108067, -118.341983),
    ("MIPTE", "INT", 34.058486, -118.400789),
    ("KPHX", "AIRPORT", 33.434278, -112.011583),
]
# ksba_kpmd.fpl: the same route to LHS, then KPMD.
KSBA_KPMD_FPL = KSBA_KPHX_FPL[:12] + [("KPMD", "AIRPORT", 34.629391, -118.084537)]

# The route strings a pilot would write for them. PAIDD is not on V459 in
# cycle 2611 (V459 runs LOPES JEFFY), so the plans leave the airway for it.
KSBA_KPMD = "KSBA FLOUT VTU V485 OHIGH TTE V459 LOPES PAIDD JEFFY V459 LHS KPMD"
KSBA_KPHX = ("KSBA FLOUT VTU V485 OHIGH TTE V459 LOPES PAIDD JEFFY V459 LHS "
             "WAYVE DARTS MOVVE MIPTE KPHX")

_GARMIN_TYPE = {"AIRPORT": "airport", "VOR": "vor", "INT": "fix"}


def _build(path, pack):
    con = sqlite3.connect(str(path))
    for sql in pack["schema"]:
        con.execute(sql)
    for table, rows in pack.items():
        if table == "schema" or not rows:
            continue
        con.executemany(f"INSERT INTO {table} VALUES ({','.join('?' * len(rows[0]))})", rows)
    con.commit()
    con.close()
    return path


def _build_all(directory):
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return {name: _build(directory / f"{name}.sqlite", data[name]) for name in data}


@pytest.fixture(scope="module")
def shared_packs(tmp_path_factory):
    return _build_all(tmp_path_factory.mktemp("route_string_packs"))


@pytest.fixture
def packs(tmp_path):
    """A copy of its own, for a test that adds rows."""
    return _build_all(tmp_path)


def _sources(tmp_path, packs, extra_navaids=(), extra_fixes=()):
    if extra_navaids or extra_fixes:
        con = sqlite3.connect(str(packs["navaids"]))
        con.executemany("INSERT INTO navaids VALUES (?,?,?,?,?,?,?)", extra_navaids)
        con.executemany("INSERT INTO fixes VALUES (?,?,?,?)", extra_fixes)
        con.commit()
        con.close()
    index = WaypointIndex(str(packs["airports"]), str(packs["navaids"]),
                          user_file=str(tmp_path / "user.json"),
                          recent_file=str(tmp_path / "recent.json"))
    assert index.wait_ready(timeout=5)
    graph = AirwayGraph(packs["procedures"])
    procs = ProcedureIndex(packs["procedures"])
    return index, graph, procs


@pytest.fixture
def sources(tmp_path, shared_packs):
    index, graph, procs = _sources(tmp_path, shared_packs)
    yield index, graph, procs
    graph.close()


def _expand(sources, text, **kw):
    return rs.expand(text, *sources, **kw)


def _ids(plan):
    return [w.id for w in plan.waypoints]


def _refusal(sources, text, **kw):
    with pytest.raises(rs.RouteStringError) as e:
        _expand(sources, text, **kw)
    return e.value


# ---------------------------------------------------------------------------
# Bill's bench plans
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text, fpl", [(KSBA_KPMD, KSBA_KPMD_FPL), (KSBA_KPHX, KSBA_KPHX_FPL)],
                         ids=["KSBA-KPMD", "KSBA-KPHX"])
def test_bench_plan_expands_to_the_foreflight_points(sources, text, fpl):
    plan = _expand(sources, text)
    assert _ids(plan) == [ident for ident, *_ in fpl]
    for wp, (ident, gtype, lat, lon) in zip(plan.waypoints, fpl):
        assert wp.type == _GARMIN_TYPE[gtype], ident
        # NASR and CIFP code a fix a few feet from where ForeFlight has it.
        assert geo.distance_nm(wp.lat, wp.lon, lat, lon) < 0.05, ident


def test_bench_plan_keeps_its_airways_as_segments(sources):
    plan = _expand(sources, KSBA_KPMD)
    airways = [(s.ident, s.entry, s.exit) for s in plan.segments if s.kind == "airway"]
    assert airways == [("V485", "VTU", "OHIGH"), ("V459", "TTE", "LOPES"),
                       ("V459", "JEFFY", "LHS")]
    assert all(s.cycle == "2611" for s in plan.segments if s.kind == "airway")


def test_bench_plan_carries_the_airway_meas(sources):
    plan = _expand(sources, KSBA_KPMD)
    alts = {w.id: w.alt for w in plan.waypoints}
    assert alts["VTU"] == ""        # the leg into the entry fix is not on V485
    assert alts["HENER"].startswith("+")
    assert alts["FLOUT"] == ""


def test_bench_plan_is_named_and_marked(sources):
    plan = _expand(sources, KSBA_KPMD.lower())
    assert plan.name == "KSBA-KPMD"
    assert plan.source == "route"
    assert plan.comment == KSBA_KPMD


def test_route_round_trips_through_the_route_file(sources):
    from pyefis.flightplan import model
    plan = _expand(sources, KSBA_KPHX)
    assert model.FlightPlan.from_json(plan.to_json()) == plan


# ---------------------------------------------------------------------------
# Unknown and ambiguous idents: named, never guessed
# ---------------------------------------------------------------------------
def test_unknown_idents_are_all_named(sources):
    e = _refusal(sources, "KSBA XYZZY VTU QQQQQ KPMD")
    assert e.unknown == ("XYZZY", "QQQQQ")
    assert str(e) == "NOT FOUND: XYZZY, QQQQQ"


def test_ident_with_two_places_is_refused_with_both(sources):
    # AA is two real NDBs, Kenie (Minnesota) and Cedar (Georgia).
    e = _refusal(sources, "KSBA AA KPMD")
    assert str(e) == "TWO PLACES NAMED: AA"
    assert sorted(w.name for w in e.ambiguous["AA"]) == ["Cedar", "Kenie"]


def test_unknown_and_ambiguous_are_named_in_one_refusal(sources):
    e = _refusal(sources, "KSBA AA XYZZY KPMD")
    assert str(e) == "NOT FOUND: XYZZY; TWO PLACES NAMED: AA"


def test_vor_test_facility_does_not_make_a_vor_ambiguous(sources):
    plan = _expand(sources, "KABQ ABQ KSAF")
    assert [(w.id, w.type) for w in plan.waypoints] == [
        ("KABQ", "airport"), ("ABQ", "vor"), ("KSAF", "airport")]


def test_two_records_of_one_place_are_one_place(sources):
    # MAZ: an NDB and a VOR/DME 0.18 nm apart at Mayaguez -- one place, and
    # the VOR is the record kept.
    plan = _expand(sources, "KSBA MAZ KPMD")
    assert plan.waypoints[1].type == "vor"


def test_an_adjacent_airway_pins_which_place_is_meant(tmp_path, packs):
    # Test-made row: a second HENER, in Maine. V485 passes through only one.
    index, graph, procs = _sources(tmp_path, packs,
                                   extra_fixes=[("HENER", "RP", 44.5, -69.5)])
    try:
        plan = rs.expand("KSBA HENER V485 OHIGH KPMD", index, graph, procs)
        assert plan.waypoints[1].lon == pytest.approx(-119.23, abs=0.01)
        with pytest.raises(rs.RouteStringError, match="TWO PLACES NAMED: HENER"):
            rs.expand("KSBA HENER KPMD", index, graph, procs)
    finally:
        graph.close()


def test_airport_is_preferred_at_the_ends_and_a_navaid_between(sources):
    # PMD is the Palmdale airport (by its FAA ident) and the Palmdale VORTAC,
    # 1.0 nm apart.
    plan = _expand(sources, "SBA PMD PHX")
    assert [(w.id, w.type) for w in plan.waypoints] == [
        ("KSBA", "airport"), ("PMD", "vor"), ("KPHX", "airport")]
    plan = _expand(sources, "KSBA PMD")
    assert [(w.id, w.type) for w in plan.waypoints][-1] == ("KPMD", "airport")


def test_vot_sharing_an_airport_ident_leaves_the_airport(sources):
    # PHX in the navaids pack is the Phoenix VOT, not a VOR (that is PXR).
    plan = _expand(sources, "KSBA PHX KPMD")
    assert [(w.id, w.type) for w in plan.waypoints][1] == ("KPHX", "airport")


def test_an_airport_ident_that_is_also_a_navaid_is_ambiguous_between(tmp_path, packs):
    # Test-made row: a VOR named KPHX, so the airport's own ident is no
    # longer one place.
    index, graph, procs = _sources(tmp_path, packs, extra_navaids=[
        ("KPHX", "VOR", "Test", "110.0", 0.0, 40.0, -100.0)])
    try:
        with pytest.raises(rs.RouteStringError, match="TWO PLACES NAMED: KPHX"):
            rs.expand("KSBA KPHX KPMD", index, graph, procs)
    finally:
        graph.close()


# ---------------------------------------------------------------------------
# Airways
# ---------------------------------------------------------------------------
def test_airway_needs_an_exit_fix(sources):
    assert str(_refusal(sources, "KSBA VTU V27 DCT GVO KSMX")) == "V27 NEEDS AN EXIT FIX"


def test_two_airways_need_their_junction(sources):
    assert str(_refusal(sources, "KSBA VTU V27 V485 OHIGH KPMD")) == "V27 NEEDS AN EXIT FIX"


def test_entry_fix_must_be_on_the_airway(sources):
    assert str(_refusal(sources, "KSBA V27 GVO KSMX")) == "'KSBA' IS NOT ON AIRWAY V27"


def test_airway_without_a_procedures_pack_is_unknown(tmp_path, packs):
    index, _graph, _procs = _sources(tmp_path, packs)
    _graph.close()
    with pytest.raises(rs.RouteStringError) as e:
        rs.expand("KSBA VTU V27 GVO KSMX", index)
    assert e.value.unknown == ("V27",)


def test_dct_is_direct(sources):
    assert _ids(_expand(sources, "KSBA DCT VTU DCT KPMD")) == ["KSBA", "VTU", "KPMD"]


# ---------------------------------------------------------------------------
# SID and STAR
# ---------------------------------------------------------------------------
def test_sid_needing_a_runway_says_which(sources):
    with pytest.raises(rs.RunwayNeededError) as e:
        _expand(sources, "KSBA FLOUT5 VTU V27 GVO KSMX")
    assert (e.value.airport, e.value.procedure) == ("KSBA", "FLOUT5")
    assert e.value.choices == ("RW07", "RW15B", "RW25")
    assert str(e.value) == "FLOUT5 NEEDS A RUNWAY: RW07, RW15B, RW25"


def test_sid_transition_from_the_next_point_chains_into_the_airway(sources):
    plan = _expand(sources, "KSBA FLOUT5 VTU V27 GVO KSMX", runways={"KSBA": "25"})
    kinds = [(s.kind, s.ident) for s in plan.segments]
    assert kinds == [("waypoint", ""), ("departure", "FLOUT5.RW25.VTU"), ("airway", "V27"),
                     ("waypoint", "")]
    ids = _ids(plan)
    assert ids.count("VTU") == 1
    assert ids[ids.index("VTU") + 1] == "HENER"


def test_sid_transition_written_with_a_dot_is_the_same_route(sources):
    implicit = _expand(sources, "KSBA FLOUT5 VTU V27 GVO KSMX", runways={"KSBA": "RW25"})
    dotted = _expand(sources, "KSBA FLOUT5.VTU V27 GVO KSMX", runways={"KSBA": "RW25"})
    stated = _expand(sources, "KSBA FLOUT5.VTU VTU V27 GVO KSMX", runways={"KSBA": "RW25"})
    assert _ids(implicit) == _ids(dotted) == _ids(stated)


def test_sid_with_an_unknown_transition_is_refused(sources):
    e = _refusal(sources, "KSBA FLOUT5.XYZ KSMX", runways={"KSBA": "RW25"})
    assert str(e) == "XYZ IS NOT A TRANSITION OF FLOUT5"


def test_star_transition_from_the_point_before_it(sources):
    for text in ("KLAX HEC PITBL2 KSBA", "KLAX HEC.PITBL2 KSBA"):
        plan = _expand(sources, text, runways={"KSBA": "RW25"})
        assert [(s.kind, s.ident) for s in plan.segments if s.kind != "waypoint"] == [
            ("arrival", "PITBL2.HEC.RW25")]
        ids = _ids(plan)
        assert ids[:2] == ["KLAX", "HEC"] and ids.count("HEC") == 1
        assert ids[-1] == "KSBA"


def test_procedure_name_away_from_its_airport_is_refused(sources):
    e = _refusal(sources, "KSBA VTU FLOUT5 KSMX")
    assert e.unknown == ("FLOUT5",)


# ---------------------------------------------------------------------------
# Lat/lon and what is left out
# ---------------------------------------------------------------------------
def test_lat_lon_points(sources):
    plan = _expand(sources, "KSBA 3407N11901W 34N119W KPMD")
    a, b = plan.waypoints[1], plan.waypoints[2]
    assert (a.id, a.type) == ("3407N11901W", "user")
    assert (a.lat, a.lon) == pytest.approx((34 + 7 / 60, -(119 + 1 / 60)))
    assert (b.lat, b.lon) == (34.0, -119.0)


def test_lat_lon_with_bad_minutes_is_not_a_point(sources):
    assert _refusal(sources, "KSBA 3460N11901W KPMD").unknown == ("3460N11901W",)


@pytest.mark.parametrize("token, message", [
    ("VTU090025", "RADIAL-DISTANCE NOT SUPPORTED: VTU090025"),
    ("N0140A080", "SPEED/LEVEL NOT SUPPORTED: N0140A080"),
    ("VTU/N0140A080", "SPEED/LEVEL NOT SUPPORTED: VTU/N0140A080"),
    ("VTU.V27", "NOT A PROCEDURE HERE: VTU.V27"),
])
def test_left_out_forms_are_named(sources, token, message):
    assert str(_refusal(sources, f"KSBA LHS {token} KPMD")) == message


def test_empty_and_single_point_routes(sources):
    assert str(_refusal(sources, "  ")) == "ENTER A ROUTE"
    assert str(_refusal(sources, "KSBA")) == "A ROUTE NEEDS TWO POINTS"
