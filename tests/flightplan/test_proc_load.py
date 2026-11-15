#  SPDX-License-Identifier: GPL-2.0-or-later
"""Tests for pyefis.flightplan.proc_load -- PA7 (billmallard/pyEfis#238,
AER-1606): assembling a coded procedure into segments and placing it in a
route. The procedures are KSBA's, decoded from the golden CIFP fixture
(``ksba_procedures.py``)."""

import pytest

from pyefis.flightplan import fixbridge, geo, model
from pyefis.flightplan import proc_load as L
from pyefis.flightplan.procedures import ProcedureIndex, ProcedureLeg
from tests.flightplan import ksba_procedures
from tests.flightplan.test_fixbridge import _define, _define_all_fp1_keys


@pytest.fixture()
def idx(tmp_path):
    return ProcedureIndex(ksba_procedures.build(tmp_path / "procedures.sqlite"))


def _ksba():
    return model.Waypoint("KSBA", "airport", *ksba_procedures.KSBA)


def _ids(seg):
    return [w.id for w in seg.legs]


def _leg(**kw):
    values = dict(seq=10, path_term="TF", fix_id="FIX", lat=34.0, lon=-119.0, fix_type=None,
                  recd_navaid=None, theta=None, rho=None, course=None, dist_nm=None,
                  time_min=None, alt_desc=None, alt1_ft=None, alt2_ft=None, speed_kt=None,
                  turn_dir=None, rnp=None, flags=0, centre_fix=None, centre_lat=None,
                  centre_lon=None, arc_radius_nm=None)
    values.update(kw)
    return ProcedureLeg(**values)


# ---------------------------------------------------------------------------
# What the PROC page offers
# ---------------------------------------------------------------------------
def test_names_read_the_way_a_pilot_says_them(idx):
    apr = idx.find("KSBA", "approach", "I07")
    assert L.procedure_name(apr) == "ILS07"
    assert L.segment_ident(apr, "GOLET") == "ILS07.GOLET"
    assert L.segment_ident(apr, L.VECTORS) == "ILS07.VECTORS"
    sid = idx.find("KSBA", "sid", "FLOUT5")
    assert L.segment_ident(sid, "VTU", "RW07") == "FLOUT5.RW07.VTU"
    assert L.segment_ident(sid, L.NO_TRANSITION, "RW07") == "FLOUT5.RW07"
    star = idx.find("KSBA", "star", "PITBL2")
    assert L.segment_ident(star, "HEC", "RW25") == "PITBL2.HEC.RW25"


def test_transition_and_runway_choices_come_from_the_pack(idx):
    apr = idx.find("KSBA", "approach", "I07")
    assert L.transition_choices(idx, apr) == ["GOLET", "GVO", L.VECTORS]
    assert L.runway_choices(idx, apr) == []
    sid = idx.find("KSBA", "sid", "FLOUT5")
    assert L.transition_choices(idx, sid) == ["GVO", "RZS", "VTU", L.NO_TRANSITION]
    assert L.runway_choices(idx, sid) == ["RW07", "RW15B", "RW25"]
    star = idx.find("KSBA", "star", "PITBL2")
    assert L.transition_choices(idx, star) == ["HEC", "PORPS", L.NO_TRANSITION]
    assert L.runway_choices(idx, star) == ["RW07", "RW25"]


# ---------------------------------------------------------------------------
# Approaches
# ---------------------------------------------------------------------------
def test_vectors_to_final_loads_the_final_and_the_missed_approach(idx):
    apr = idx.find("KSBA", "approach", "I07")
    approach, missed = L.assemble(idx, apr, L.VECTORS, magvar=-12.0)
    assert (approach.kind, approach.ident, approach.cycle) == ("approach", "ILS07.VECTORS", "2609")
    assert _ids(approach) == ["HABUT", "GOYED", "NAPPS", "RW07"]
    assert [w.pt for w in approach.legs] == ["IF", "CF", "CF", "CF"]
    assert [w.alt for w in approach.legs] == ["+3500", "+2600", "+1800", "@64"]
    assert [w.crs for w in approach.legs[1:]] == [75.0, 75.0, 75.0]
    assert (missed.kind, missed.ident) == ("missed", "ILS07")
    assert [w.pt for w in missed.legs] == ["CA", "CF", "HM"]
    # Every slot came from a coded procedure.
    assert all(w.flags & L.FLAG_FROM_PROCEDURE for s in (approach, missed) for w in s.legs)


def test_approach_roles_come_from_the_data(idx):
    # The pack sets its FAF bit on HABUT too (ARINC "final approach course
    # fix", WDC 'I'); the published FAF is NAPPS ('F'), the one nearest the
    # MAP. Two FAFs would also break the model's one-FAF rule.
    apr = idx.find("KSBA", "approach", "I07")
    approach, missed = L.assemble(idx, apr, "GOLET")
    roles = {w.id or w.pt: w.role for s in (approach, missed) for w in s.legs}
    assert roles["GOLET"] == "mahp"           # the missed approach's hold fix
    assert approach.legs[0].role == "iaf"     # GOLET, the transition's IAF
    assert roles["HABUT"] == "none"
    assert roles["NAPPS"] == "faf"
    assert roles["RW07"] == "map"
    plan = model.FlightPlan(segments=[approach, missed])
    faf_i, map_i = plan.approach()
    assert (plan.waypoints[faf_i].id, plan.waypoints[map_i].id) == ("NAPPS", "RW07")


def test_the_missed_approach_climb_has_no_fix_and_sits_on_its_course(idx):
    apr = idx.find("KSBA", "approach", "I07")
    approach, missed = L.assemble(idx, apr, L.VECTORS, magvar=-12.0)
    ca, rw07 = missed.legs[0], approach.legs[-1]
    assert (ca.id, ca.pt, ca.crs, ca.alt) == ("", "CA", 74.6, "+700")
    # 2 nm on the true course (magnetic 074.6 + 12 east) from the MAP.
    assert geo.distance_nm(rw07.lat, rw07.lon, ca.lat, ca.lon) == pytest.approx(2.0, abs=1e-3)
    assert geo.initial_bearing(rw07.lat, rw07.lon, ca.lat, ca.lon) == pytest.approx(86.6, abs=0.05)
    assert L.leg_label(ca) == "075° TO +700"


def test_a_one_minute_hold_reaches_the_bus_as_a_distance_at_the_hold_speed(idx):
    apr = idx.find("KSBA", "approach", "I07")
    hm = L.assemble(idx, apr, L.VECTORS)[1].legs[-1]
    assert (hm.pt, hm.id, hm.turn, hm.crs, hm.dst) == ("HM", "GOLET", "R", 307.0, 1.5)
    hm = L.assemble(idx, apr, L.VECTORS, hold_speed_kt=120.0)[1].legs[-1]
    assert hm.dst == 2.0


def test_the_transition_joins_the_final_at_one_slot(idx):
    # The GOLET transition ends CF HABUT and the final opens IF HABUT: one
    # fix, so one slot. Two would be a zero-length leg.
    apr = idx.find("KSBA", "approach", "I07")
    approach, _ = L.assemble(idx, apr, "GOLET")
    assert _ids(approach) == ["GOLET", "LOBER", "LOBER", "HABUT", "GOYED", "NAPPS", "RW07"]
    assert [w.pt for w in approach.legs][:4] == ["IF", "TF", "FC", "CF"]


def test_a_leg_the_engine_cannot_fly_is_passed_through_never_coerced(idx):
    # Guardrail 1: the FC leg stays FC. The engine refuses the route whole;
    # this module does not drop it or turn it into a TF.
    apr = idx.find("KSBA", "approach", "I07")
    approach, _ = L.assemble(idx, apr, "GVO")
    assert "FC" in [w.pt for w in approach.legs]


def test_an_approach_needs_a_transition(idx):
    apr = idx.find("KSBA", "approach", "I07")
    with pytest.raises(L.ProcedureLoadError, match="SELECT A TRANSITION"):
        L.assemble(idx, apr, None)
    with pytest.raises(L.ProcedureLoadError, match="NOT A TRANSITION"):
        L.assemble(idx, apr, "NOSUCH")


# ---------------------------------------------------------------------------
# Departures and arrivals
# ---------------------------------------------------------------------------
def test_a_departure_flies_runway_then_en_route(idx):
    sid = idx.find("KSBA", "sid", "FLOUT5")
    (seg,) = L.assemble(idx, sid, "VTU", "RW07", magvar=-12.0, origin=_ksba())
    assert (seg.kind, seg.ident) == ("departure", "FLOUT5.RW07.VTU")
    # VA off the runway, CI, CF FLOUT; the VTU transition's IF FLOUT is the
    # same slot as the CF FLOUT before it.
    assert [(w.id, w.pt) for w in seg.legs] == [("", "VA"), ("", "CI"), ("FLOUT", "CF"),
                                                 ("VTU", "TF")]
    va = seg.legs[0]
    assert geo.distance_nm(*ksba_procedures.KSBA, va.lat, va.lon) == pytest.approx(2.0, abs=1e-3)
    assert L.leg_label(va) == "HDG 075°"
    assert seg.legs[0].alt == "+413"


def test_a_departure_with_runway_transitions_needs_a_runway(idx):
    sid = idx.find("KSBA", "sid", "FLOUT5")
    with pytest.raises(L.ProcedureLoadError, match="SELECT A RUNWAY"):
        L.assemble(idx, sid, "VTU", None, origin=_ksba())


def test_a_leg_with_no_fix_and_nothing_before_it_refuses_the_load(idx):
    sid = idx.find("KSBA", "sid", "FLOUT5")
    with pytest.raises(L.ProcedureLoadError, match="NO FIX TO START FROM"):
        L.assemble(idx, sid, "VTU", "RW07")


def test_an_arrival_flies_en_route_then_common_then_runway(idx):
    star = idx.find("KSBA", "star", "PITBL2")
    (seg,) = L.assemble(idx, star, "HEC", "RW25")
    assert (seg.kind, seg.ident) == ("arrival", "PITBL2.HEC.RW25")
    assert _ids(seg) == ["HEC", "FRIRR", "HMBOY", "PITBL", "TELLA", "STBBZ", "HHOME", "LCLRK",
                         "LCLRK"]
    assert seg.legs[-1].pt == "FM"            # vectors at the end, as coded
    assert seg.legs[-2].flags & L.FLAG_FLYOVER


# ---------------------------------------------------------------------------
# Altitude constraints
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("desc,a1,a2,expected", [
    ("+", 3500, None, "+3500"), ("-", 5000, None, "-5000"), (None, 1800, None, "@1800"),
    ("@", 1800, None, "@1800"), ("B", 4000, 2900, "B2900,4000"), ("J", 3500, 1800, "+3500"),
    ("H", 1800, 1800, "+1800"), ("G", 2000, 1900, "@2000"), ("C", None, 6000, "+6000"),
    (None, None, None, ""),
])
def test_altitude_descriptors_pack_into_the_guide_notation(desc, a1, a2, expected):
    assert L._alt_text(_leg(alt_desc=desc, alt1_ft=a1, alt2_ft=a2)) == expected


def test_an_unknown_altitude_descriptor_refuses_the_load():
    with pytest.raises(L.ProcedureLoadError, match="ALTITUDE CODE"):
        L._alt_text(_leg(alt_desc="Z", alt1_ft=3000))


def test_an_rf_takes_its_centre_and_radius_from_the_pack():
    wp = L._waypoint(_leg(path_term="RF", centre_lat=34.1, centre_lon=-119.2, arc_radius_nm=2.5,
                          turn_dir="L"), None, magvar=0.0, hold_speed_kt=90.0,
                     resolve_navaid=None)
    assert (wp.ctr_lat, wp.ctr_lon, wp.dst, wp.turn) == (34.1, -119.2, 2.5, "L")


def test_an_af_centre_is_its_navaid_or_left_empty_for_the_engine_to_refuse():
    leg = _leg(path_term="AF", recd_navaid="GVO", rho=12.0, turn_dir="R")
    wp = L._waypoint(leg, None, magvar=0.0, hold_speed_kt=90.0,
                     resolve_navaid=lambda ident, lat, lon: (34.53, -120.09))
    assert (wp.ctr_lat, wp.ctr_lon, wp.dst) == (34.53, -120.09, 12.0)
    wp = L._waypoint(leg, None, magvar=0.0, hold_speed_kt=90.0,
                     resolve_navaid=lambda ident, lat, lon: None)
    assert (wp.ctr_lat, wp.ctr_lon) == (0.0, 0.0)


# ---------------------------------------------------------------------------
# Placing a procedure in a route
# ---------------------------------------------------------------------------
def _route(*idents):
    pos = {"KSBA": ksba_procedures.KSBA, "KSMX": (34.89894, -120.45759),
           "RZS": (34.50953, -119.77099), "HEC": (34.79702, -116.46292)}
    return model.FlightPlan(waypoints=[
        model.Waypoint(i, "airport" if i.startswith("K") else "vor", *pos[i]) for i in idents])


def _layout(plan):
    return [(s.kind, s.ident or s.entry) for s in plan.segments]


def test_procedures_go_where_the_guide_puts_them(idx):
    # Departure, En route, Arrival, Approach (guide p. 3-65), whatever order
    # they are loaded in; the destination airport stays last.
    plan = _route("KSBA", "RZS", "KSBA")
    L.insert(plan, "approach", L.assemble(idx, idx.find("KSBA", "approach", "I07"), L.VECTORS),
             "KSBA")
    L.insert(plan, "arrival", L.assemble(idx, idx.find("KSBA", "star", "PITBL2"), "PORPS", "RW07"),
             "KSBA")
    L.insert(plan, "departure",
             L.assemble(idx, idx.find("KSBA", "sid", "FLOUT5"), "VTU", "RW07", origin=_ksba()),
             "KSBA")
    assert _layout(plan) == [("waypoint", "KSBA"), ("departure", "FLOUT5.RW07.VTU"),
                             ("waypoint", "RZS"), ("arrival", "PITBL2.PORPS.RW07"),
                             ("approach", "ILS07.VECTORS"), ("missed", "ILS07"),
                             ("waypoint", "KSBA")]


def test_loading_a_procedure_replaces_the_one_of_that_kind(idx):
    apr = idx.find("KSBA", "approach", "I07")
    plan = _route("RZS", "KSBA")
    L.insert(plan, "approach", L.assemble(idx, apr, L.VECTORS), "KSBA")
    L.insert(plan, "approach", L.assemble(idx, apr, "GOLET"), "KSBA")
    assert _layout(plan) == [("waypoint", "RZS"), ("approach", "ILS07.GOLET"),
                             ("missed", "ILS07"), ("waypoint", "KSBA")]


def test_removing_an_approach_removes_its_missed_approach_too(idx):
    plan = _route("RZS", "KSBA")
    before = plan.to_json()
    L.insert(plan, "approach", L.assemble(idx, idx.find("KSBA", "approach", "I07"), "GOLET"),
             "KSBA")
    assert L.remove(plan, "approach") is True
    assert plan.to_json() == before
    assert L.remove(plan, "approach") is False


def test_a_waypoint_at_the_procedure_start_is_merged_into_it(idx):
    # HEC entered by hand, then a STAR that starts IF HEC: one slot at HEC.
    plan = _route("KSMX", "HEC", "KSBA")
    notices = L.insert(plan, "arrival",
                       L.assemble(idx, idx.find("KSBA", "star", "PITBL2"), "HEC", "RW25"), "KSBA")
    assert _layout(plan) == [("waypoint", "KSMX"), ("arrival", "PITBL2.HEC.RW25"),
                             ("waypoint", "KSBA")]
    assert notices == ["HEC MERGED INTO PITBL2.HEC.RW25"]
    assert [w.id for w in plan.waypoints].count("HEC") == 1


def _star_ending_at_golet():
    """A STAR whose last fix is the approach's IAF -- the common RNAV-era
    junction. Synthetic: PITBL2's runway transition re-coded to end at
    GOLET (with its real position)."""
    procs = list(ksba_procedures.PROCEDURES)
    legs = [leg for leg in ksba_procedures.LEGS if leg[0] != 11]
    legs.append((11, 10, "IF", "TELLA", 34.37067, -119.49486, "waypoint") + (None,) * 12
                + (0, None, None, None, None))
    legs.append((11, 20, "TF", "GOLET", 34.28135, -119.864375, "waypoint") + (None,) * 6
                + ("+", 5000) + (None,) * 4 + (0, None, None, None, None))
    return procs, legs


def test_a_procedure_that_starts_where_another_ends_shares_the_fix(tmp_path):
    procs, legs = _star_ending_at_golet()
    idx = ProcedureIndex(ksba_procedures.build(tmp_path / "p.sqlite", procs,
                                               ksba_procedures.TRANSITIONS, legs))
    plan = _route("HEC", "KSBA")
    L.insert(plan, "arrival", L.assemble(idx, idx.find("KSBA", "star", "PITBL2"), "HEC", "RW25"),
             "KSBA")
    L.insert(plan, "approach", L.assemble(idx, idx.find("KSBA", "approach", "I07"), "GOLET"),
             "KSBA")
    ids = [w.id for w in plan.waypoints]
    assert ids.count("GOLET") == 3          # end of STAR, and the missed CF + HM
    arrival, approach = plan.segments[0], plan.segments[1]
    assert arrival.legs[-1].id == "GOLET" and arrival.legs[-1].role == "iaf"
    assert approach.legs[0].id == "LOBER"
    # Removing the STAR gives the approach its IF back.
    L.remove(plan, "arrival")
    approach = plan.segments[L.loaded(plan, "approach")[0]]
    assert (approach.legs[0].id, approach.legs[0].pt) == ("GOLET", "IF")


def test_a_pilot_faf_blocks_an_approach_and_leaves_the_plan_alone(idx):
    plan = _route("RZS", "KSBA")
    plan.set_role(0, "faf")
    before = plan.to_json()
    with pytest.raises(model.FlightPlanError, match="CLEAR THE FAF/MAP ON RZS"):
        L.insert(plan, "approach", L.assemble(idx, idx.find("KSBA", "approach", "I07"),
                                              L.VECTORS), "KSBA")
    assert plan.to_json() == before


def test_a_procedure_that_does_not_fit_is_not_loaded(idx):
    plan = model.FlightPlan(waypoints=[
        model.Waypoint(f"W{i:02d}", "fix", 30.0 + i * 0.01, -100.0)
        for i in range(model.MAX_WAYPOINTS - 3)])
    before = plan.to_json()
    with pytest.raises(model.FlightPlanError, match="ROUTE FULL"):
        L.insert(plan, "approach", L.assemble(idx, idx.find("KSBA", "approach", "I07"),
                                              L.VECTORS), "KSBA")
    assert plan.to_json() == before


# ---------------------------------------------------------------------------
# On the bus
# ---------------------------------------------------------------------------
def test_a_loaded_approach_crosses_the_bus_as_two_segments(fix, idx):
    _define_all_fp1_keys(fix)
    _define(fix, "MAGVAR", "float", -12.0)
    bridge = fixbridge.FixBridge(fix)
    plan = _route("RZS", "KSBA")
    L.insert(plan, "approach", L.assemble(idx, idx.find("KSBA", "approach", "I07"), L.VECTORS),
             "KSBA")
    bridge.publish(plan)
    db = fix.db
    # RZS, 4 approach legs, 3 missed legs, KSBA.
    assert db.get_item("FPLCOUNT").value == 9
    assert [db.get_item(f"FPLS{k}KIND").value for k in range(1, 5)] == [0, 4, 5, 0]
    assert [db.get_item(f"FPLS{k}ID").value for k in (2, 3)] == ["ILS07.VECTORS", "ILS07"]
    assert (db.get_item("FPLS3ENT").value, db.get_item("FPLS3EXT").value) == ("", "GOLET")
    assert db.get_item("FPLDBCYC").value == "2609"
    assert db.get_item("FPL4FLAGS").value == 0x20 | 0x04          # NAPPS, FAF
    assert db.get_item("FPL5FLAGS").value == 0x20 | 0x08 | 0x01   # RW07, MAP, fly-over
    assert (db.get_item("FPL8PT").value, db.get_item("FPL8DST").value) == ("HM", 1.5)
    assert db.get_item("FPL8FLAGS").value == 0x20 | 0x10          # GOLET hold, MAHP
    # The bus is the truth: the plan read back has the same segments.
    assert bridge.read_plan().to_json()["segments"] == plan.to_json()["segments"]
