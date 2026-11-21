#  SPDX-License-Identifier: GPL-2.0-or-later
"""A hold at any fix from the clearance ATC gives (HOLDFIX1, AER-6210):
direction and radial to inbound course, leg time to distance, the ``HM``
slot, and where it goes in the plan."""

import pytest

from pyefis.flightplan import geo
from pyefis.flightplan import hold
from pyefis.flightplan import model
from pyefis.flightplan import proc_load

# The eight directions, the radial each one names, and the inbound course
# a hold on that radial flies: the reciprocal.
EIGHT = [("N", 0.0, 180.0), ("NE", 45.0, 225.0), ("E", 90.0, 270.0), ("SE", 135.0, 315.0),
         ("S", 180.0, 0.0), ("SW", 225.0, 45.0), ("W", 270.0, 90.0), ("NW", 315.0, 135.0)]


@pytest.mark.parametrize("direction,radial,inbound", EIGHT)
def test_direction_alone_holds_on_its_own_radial(direction, radial, inbound):
    assert hold.inbound_course(direction) == pytest.approx(inbound)


@pytest.mark.parametrize("direction,radial,inbound", EIGHT)
def test_radial_gives_its_reciprocal_inbound(direction, radial, inbound):
    # Off the octant's centre by 20 deg either way: still that side.
    for off in (-20.0, 0.0, 20.0):
        got = hold.inbound_course(direction, radial=radial + off)
        assert got == pytest.approx((inbound + off) % 360.0)


@pytest.mark.parametrize("direction,radial,inbound", EIGHT)
def test_inbound_course_is_taken_as_given(direction, radial, inbound):
    for off in (-20.0, 0.0, 20.0):
        course = (inbound + off) % 360.0
        assert hold.inbound_course(direction, inbound=course) == pytest.approx(course)


@pytest.mark.parametrize("direction,radial,inbound", EIGHT)
def test_radial_on_the_other_side_is_refused(direction, radial, inbound):
    with pytest.raises(hold.HoldError, match=f"IS NOT {direction} OF THE FIX"):
        hold.inbound_course(direction, radial=radial + 180.0)
    with pytest.raises(hold.HoldError, match=f"IS NOT {direction} OF THE FIX"):
        hold.inbound_course(direction, inbound=radial)


def test_side_tolerance_edge():
    # 45 deg off is still the side; just past it is not.
    assert hold.inbound_course("N", radial=45.0) == pytest.approx(225.0)
    assert hold.inbound_course("N", radial=315.0) == pytest.approx(135.0)
    with pytest.raises(hold.HoldError):
        hold.inbound_course("N", radial=45.1)


def test_the_briefs_clearance():
    # "Hold southeast of X on the 130 radial": inbound 310.
    assert hold.inbound_course("SE", radial=130.0) == pytest.approx(310.0)


def test_nearest_direction_round_trips_every_direction():
    for direction, radial, _ in EIGHT:
        assert hold.nearest_direction(radial) == direction
        assert hold.nearest_direction(radial + 22.0) == direction
        assert hold.nearest_direction(radial - 22.0) == direction


def test_course_text_reads_north_as_360():
    assert hold.course_text(0.0) == "360°"
    assert hold.course_text(359.6) == "360°"
    assert hold.course_text(310.2) == "310°"
    assert hold.course_text(5.0) == "005°"


# -- leg time -------------------------------------------------------------

def test_default_leg_time_follows_aim_5_3_8():
    assert hold.default_leg_minutes(None) == 1.0
    assert hold.default_leg_minutes(3000.0) == 1.0
    assert hold.default_leg_minutes(14000.0) == 1.0
    assert hold.default_leg_minutes(14001.0) == 1.5
    assert hold.default_leg_minutes(18000.0) == 1.5


def test_minutes_to_distance_at_the_hold_speed():
    assert hold.minutes_to_nm(1.0, 90.0) == 1.5
    assert hold.minutes_to_nm(1.5, 90.0) == 2.25
    assert hold.minutes_to_nm(1.0, 200.0) == pytest.approx(3.33)
    assert hold.leg_nm(1.5, "MIN", 120.0) == 3.0
    assert hold.leg_nm(10, "NM", 90.0) == 10.0


@pytest.mark.parametrize("bad", [0, -1, "x", None])
def test_a_leg_of_nothing_is_refused(bad):
    with pytest.raises(hold.HoldError):
        hold.leg_nm(bad, "MIN", 90.0)


def test_proc_load_converts_a_coded_t010_with_the_same_function(monkeypatch):
    calls = []

    def spy(minutes, speed):
        calls.append((minutes, speed))
        return 4.25
    monkeypatch.setattr(hold, "minutes_to_nm", spy)
    leg = _ProcLeg(path_term="HM", fix_id="WINCH", time_min=1.0)
    wp = proc_load._waypoint(leg, None, magvar=0.0, hold_speed_kt=150.0, resolve_navaid=None)
    assert calls == [(1.0, 150.0)]
    assert wp.dst == 4.25


class _ProcLeg:
    def __init__(self, path_term, fix_id, time_min):
        self.path_term, self.fix_id, self.time_min = path_term, fix_id, time_min
        self.lat, self.lon, self.fix_type = 35.0, -120.0, "fix"
        self.course, self.turn_dir, self.dist_nm = 121.0, "L", None
        self.speed_kt, self.flags = 0, 0
        self.alt_desc, self.alt1_ft, self.alt2_ft = "", None, None


# -- the slot and the plan ------------------------------------------------

A = model.Waypoint(id="AAA", type="fix", lat=34.0, lon=-120.0)
B = model.Waypoint(id="BBB", type="vor", lat=34.0, lon=-119.0)
C = model.Waypoint(id="CCC", type="fix", lat=34.5, lon=-118.5)
D = model.Waypoint(id="DDD", type="fix", lat=35.0, lon=-118.0)


def test_hold_waypoint_is_the_fix_again_as_hm():
    fix = B.copy(role="faf", alt="+5000", flags=0x21, comment="x")
    wp = hold.hold_waypoint(fix, 310.04, "L", 1.5)
    assert (wp.id, wp.type, wp.lat, wp.lon) == (B.id, B.type, B.lat, B.lon)
    assert (wp.pt, wp.crs, wp.turn, wp.dst) == ("HM", 310.0, "L", 1.5)
    assert (wp.role, wp.alt, wp.flags, wp.comment) == ("none", "", 0, "")
    assert hold.is_pilot_hold(wp)
    assert not hold.is_pilot_hold(wp.copy(flags=0x20))


def test_arrival_course_is_measured_at_the_fix_and_magnetic():
    plan = model.FlightPlan(segments=[model.waypoint_segment(A), model.waypoint_segment(B)])
    back = geo.initial_bearing(B.lat, B.lon, A.lat, A.lon)
    assert hold.arrival_course(plan, 1, magvar=12.0) == pytest.approx((back + 180 + 12) % 360)
    # Not the course at the leg's start: a 50 nm leg east turns about 0.3 deg.
    start = geo.initial_bearing(A.lat, A.lon, B.lat, B.lon)
    assert abs(hold.arrival_course(plan, 1, magvar=0.0) - start) > 0.2


def test_arrival_course_uses_a_coded_course_and_the_aircraft_for_the_first_fix():
    plan = model.FlightPlan(segments=[model.waypoint_segment(A),
                                      model.waypoint_segment(B.copy(pt="CF", crs=95.0))])
    assert hold.arrival_course(plan, 1, magvar=12.0) == 95.0
    assert hold.arrival_course(plan, 0, magvar=0.0) is None
    north = (A.lat - 0.5, A.lon)
    assert hold.arrival_course(plan, 0, magvar=0.0, aircraft=north) == pytest.approx(0.0, abs=0.01)


def _hm(fix, crs=270.0):
    return hold.hold_waypoint(fix, crs, "R", 1.5)


def test_insert_hold_after_a_plain_waypoint_is_its_own_row():
    plan = model.FlightPlan(segments=[model.waypoint_segment(w) for w in (A, B, C)])
    before = plan.to_json()
    plan.insert_hold(1, _hm(B))
    assert [w.id for w in plan.waypoints] == ["AAA", "BBB", "BBB", "CCC"]
    assert [s.kind for s in plan.segments] == ["waypoint"] * 4
    assert plan.waypoints[2].pt == "HM"
    plan.remove_hold(2)
    assert plan.to_json() == before


@pytest.mark.parametrize("kind,ident", [("airway", "V27"), ("arrival", "SADDE8"),
                                        ("approach", "R24")])
def test_insert_hold_inside_a_segment_keeps_the_segment_whole(kind, ident):
    seg = model.Segment(kind=kind, ident=ident, legs=[A, B, C, D])
    plan = model.FlightPlan(segments=[seg])
    before = plan.to_json()
    plan.insert_hold(1, _hm(B))
    assert len(plan.segments) == 1
    assert [w.id for w in plan.segments[0].legs] == ["AAA", "BBB", "BBB", "CCC", "DDD"]
    assert (plan.segments[0].entry, plan.segments[0].exit) == ("AAA", "DDD")
    plan.remove_hold(2)
    assert plan.to_json() == before


def test_insert_hold_at_an_airways_exit_keeps_the_exit():
    plan = model.FlightPlan(segments=[model.Segment(kind="airway", ident="V27", legs=[A, B])])
    plan.insert_hold(1, _hm(B))
    assert plan.segments[0].exit == "BBB"
    assert plan.waypoints[-1].pt == "HM"


def test_a_second_hold_at_one_fix_and_a_hold_off_its_fix_are_refused():
    plan = model.FlightPlan(segments=[model.waypoint_segment(w) for w in (A, B)])
    plan.insert_hold(1, _hm(B))
    with pytest.raises(model.FlightPlanError, match="ALREADY A HOLD AT BBB"):
        plan.insert_hold(1, _hm(B))
    with pytest.raises(model.FlightPlanError, match="must follow"):
        plan.insert_hold(0, _hm(B))
    with pytest.raises(model.FlightPlanError, match="not a hold"):
        plan.insert_hold(0, A.copy())
    with pytest.raises(model.FlightPlanError, match="not a hold"):
        plan.remove_hold(0)


def test_can_hold_at():
    no_fix = model.Waypoint(id="", type="fix", lat=34.1, lon=-120.0, pt="CA", crs=90.0,
                            alt="+700")
    plan = model.FlightPlan(segments=[model.waypoint_segment(w) for w in (A, no_fix, B, C)])
    assert hold.can_hold_at(plan, 0)
    assert not hold.can_hold_at(plan, 1)   # a leg with no fix
    assert hold.can_hold_at(plan, 2)
    plan.insert_hold(2, _hm(B))
    assert not hold.can_hold_at(plan, 2)   # already followed by its hold
    assert not hold.can_hold_at(plan, 3)   # the hold itself
    assert hold.can_hold_at(plan, 4)
    assert not hold.can_hold_at(plan, 9)


def test_the_hold_survives_a_route_file_round_trip():
    plan = model.FlightPlan(segments=[model.waypoint_segment(w) for w in (A, B)])
    plan.insert_hold(1, _hm(B, crs=310.0))
    again = model.FlightPlan.from_json(plan.to_json())
    assert again == plan
    assert (again.waypoints[2].pt, again.waypoints[2].crs) == ("HM", 310.0)
