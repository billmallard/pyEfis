#  SPDX-License-Identifier: GPL-2.0-or-later
"""Fly-by turn arcs on the map's leg paths (TURN3, AER-5418).

The engine publishes each slot's turn anticipation, ``FPLfTA``; the map
draws the arc from it with the engine's own construction
(fix-gateway ``engine._fly_by_arc``), split at the apex, where the engine
sequences. The golden vectors below were produced by that engine function
at fix-gateway dev e234cb8, so the port cannot drift from it unnoticed.
"""

import math

import pytest

from pyefis.flightplan import fixbridge
from pyefis.flightplan import geo
from pyefis.flightplan import leg_paths as fp_legs

# (A, B, C, d_ta, engine center, engine radius, engine exit point, turn).
ENGINE_ARCS = [
    ((34.4, -119.9), (34.5, -119.7), (34.7, -119.62), 0.62,
     (34.518520463853484, -119.72824923057209), 1.674962035582822,
     (34.50980960670878, -119.6960856114872), "L"),
    ((34.5, -119.7), (34.7, -119.62), (34.8, -119.8), 1.35,
     (34.68795890837971, -119.66294349826279), 1.7872469817821854,
     (34.71260892169184, -119.6426458599309), "L"),
    ((34.4, -119.9), (34.5, -119.7), (34.45, -119.5), 0.9,
     (34.463425750106346, -119.69441192594667), 2.0220329282917042,
     (34.495662737053784, -119.68258965635164), "R"),
]


def _slot(ident, lat, lon, pt="TF", crs=0.0):
    return fixbridge.RouteSlot(id=ident, lat=lat, lon=lon, type="fix", role="none", pt=pt, crs=crs)


def _route(*pts):
    return [_slot(chr(ord("A") + i), lat, lon) for i, (lat, lon) in enumerate(pts)]


def _near(p, q, tol_nm=1e-6):
    return geo.distance_nm(p[0], p[1], q[0], q[1]) <= tol_nm


@pytest.mark.parametrize("a, b, c, d_ta, center, radius, exit_, turn", ENGINE_ARCS)
def test_the_arc_is_the_engines(a, b, c, d_ta, center, radius, exit_, turn):
    into, out = fp_legs.flyby_arc(a, b, c, d_ta)
    # Every point is on the engine's circle, and it ends on the engine's
    # exit point.
    for p in into + out:
        assert geo.distance_nm(center[0], center[1], *p) == pytest.approx(radius, abs=1e-6)
    assert _near(out[-1], exit_)
    # It starts d_ta before the fix on the leg in, tangent to it.
    back = geo.initial_bearing(*b, *a)
    assert _near(into[0], geo.destination_point(b[0], b[1], back, d_ta))
    # It turns the coded way: the center is on that side of the leg in.
    side = geo.cross_track_nm(center[0], center[1], a[0], a[1], b[0], b[1])
    assert (side > 0) == (turn == "R")


def test_the_halves_meet_at_the_apex_on_the_bisector():
    a, b, c, d_ta = ENGINE_ARCS[0][:4]
    into, out = fp_legs.flyby_arc(a, b, c, d_ta)
    apex = into[-1]
    assert apex == out[0]
    # The apex is on the line from the fix to the arc's center: the line
    # through the fix at right angles to the mean course, which is the
    # bisector the engine sequences on (_past_turn_bisector).
    center = ENGINE_ARCS[0][4]
    assert geo.initial_bearing(*b, *apex) == pytest.approx(geo.initial_bearing(*b, *center), abs=1e-6)
    in_c = (geo.initial_bearing(*b, *a) + 180.0) % 360.0
    out_c = geo.initial_bearing(*b, *c)
    mean = in_c + ((out_c - in_c + 180.0) % 360.0 - 180.0) / 2.0
    assert abs((geo.initial_bearing(*b, *apex) - mean + 180.0) % 360.0 - 180.0) == pytest.approx(90.0, abs=1e-6)
    # and it is the arc's midpoint.
    assert len(into) == len(out)


def test_a_turn_rounds_the_corner_and_splits_the_legs_at_the_apex():
    slots = _route(*ENGINE_ARCS[0][:3])
    d_ta = ENGINE_ARCS[0][3]
    paths = fp_legs.build_leg_paths(slots)
    fp_legs.apply_flyby_turns(paths, slots, [0.0, d_ta, 0.0], act_leg=2,
                              fr=(slots[0].lat, slots[0].lon))
    into, out = fp_legs.flyby_arc(*ENGINE_ARCS[0][:4])
    assert paths[0].points == [(slots[0].lat, slots[0].lon)] + into
    assert paths[1].points == out + [(slots[2].lat, slots[2].lon)]
    # The leg out is still flown from B: the FROM the engine publishes
    # after the bisector.
    assert paths[1].origin == (slots[1].lat, slots[1].lon)
    # The fix itself is no longer on the path.
    assert all(not _near(p, (slots[1].lat, slots[1].lon), 0.01) for p in paths[0].points + paths[1].points)


def test_no_fplta_means_the_square_corner_as_before():
    slots = _route(*ENGINE_ARCS[0][:3])
    paths = fp_legs.build_leg_paths(slots)
    before = [list(p.points) for p in paths]
    assert fp_legs.apply_flyby_turns(paths, slots, [0.0, 0.0, 0.0], act_leg=2) is None
    assert [p.points for p in paths] == before


def test_a_leg_shorter_than_its_turn_stays_square():
    # B -> C is 0.5 nm: the turn at B would need 0.62 nm of it.
    a, b = ENGINE_ARCS[0][:2]
    c = geo.destination_point(b[0], b[1], 20.0, 0.5)
    slots = _route(a, b, c)
    paths = fp_legs.build_leg_paths(slots)
    before = [list(p.points) for p in paths]
    fp_legs.apply_flyby_turns(paths, slots, [0.0, 0.62, 0.0], act_leg=2)
    assert [p.points for p in paths] == before


def test_consecutive_turns_chain_and_overlapping_ones_do_not():
    # B and C both turn: the leg B -> C runs from B's apex to C's apex.
    a, b, c = ENGINE_ARCS[0][:3]
    d = (34.8, -119.8)
    slots = _route(a, b, c, d)
    paths = fp_legs.build_leg_paths(slots)
    fp_legs.apply_flyby_turns(paths, slots, [0.0, 0.62, 1.35, 0.0], act_leg=2)
    assert _near(paths[1].points[0], fp_legs.flyby_arc(a, b, c, 0.62)[1][0])
    assert _near(paths[1].points[-1], fp_legs.flyby_arc(b, c, d, 1.35)[0][-1])
    # If C's turn would start before B's ends, C stays square.
    paths = fp_legs.build_leg_paths(slots)
    leg = geo.distance_nm(*b, *c)
    fp_legs.apply_flyby_turns(paths, slots, [0.0, 0.62, leg - 0.3, 0.0], act_leg=2)
    assert _near(paths[1].points[0], fp_legs.flyby_arc(a, b, c, 0.62)[1][0])
    assert _near(paths[1].points[-1], c)


def test_the_active_fix_turns_from_the_direct_to_leg():
    # A direct-to C from a point south of it: the engine flies FROM -> C
    # and turns at C from that course, not from B -> C.
    a, b, c, d = (34.4, -119.9), (34.5, -119.7), (34.7, -119.62), (34.8, -119.8)
    slots = _route(a, b, c, d)
    fr = (34.55, -119.62)
    paths = fp_legs.build_leg_paths(slots)
    fp_legs.apply_flyby_turns(paths, slots, [0.0, 0.0, 0.5, 0.0], act_leg=3, fr=fr)
    active = paths[1]
    assert active.origin == fr and active.points[0] == fr
    into, _ = fp_legs.flyby_arc(fr, c, d, 0.5)
    assert active.points[1:] == into


def test_a_cf_leg_turns_from_its_coded_course():
    # C is a CF on 000 true: the leg in is the course line, wherever B is.
    a, b, c, d = (34.4, -119.9), (34.5, -119.7), (34.7, -119.62), (34.8, -119.8)
    slots = _route(a, b, c, d)
    slots[2] = _slot("C", *c, pt="CF", crs=0.0)
    paths = fp_legs.build_leg_paths(slots)
    fp_legs.apply_flyby_turns(paths, slots, [0.0, 0.0, 0.5, 0.0], act_leg=2)
    anchor = geo.destination_point(c[0], c[1], 180.0, 10.0)
    into, _ = fp_legs.flyby_arc(anchor, c, d, 0.5)
    assert all(_near(p, q, 1e-6) for p, q in zip(paths[1].points[-len(into):], into))


def test_plan_activated_at_slot_one_gets_a_lead_path():
    a, b, c = ENGINE_ARCS[0][:3]
    slots = _route(b, c)
    paths = fp_legs.build_leg_paths(slots)
    lead = fp_legs.apply_flyby_turns(paths, slots, [0.62, 0.0], act_leg=1, fr=a)
    into, out = fp_legs.flyby_arc(a, b, c, 0.62)
    assert lead.points == [a] + into
    assert paths[0].points == out + [c]


def test_fplta_reads_back_and_an_older_gateway_reads_as_no_arcs():
    class Item:
        def __init__(self, v):
            self.value = v

    class DB:
        def __init__(self, keys):
            self.keys = keys

        def get_item(self, key):
            return self.keys[key]

    class Fix:
        pass

    bridge = fixbridge.FixBridge.__new__(fixbridge.FixBridge)
    bridge.available = True
    bridge._fix = Fix()
    bridge._fix.db = DB({"FPL1TA": Item(0.0), "FPL2TA": Item(0.78), "FPL3TA": Item(None)})
    assert bridge.read_turn_anticipations(3) == [0.0, 0.78, 0.0]
    bridge._fix.db = DB({})
    assert bridge.read_turn_anticipations(3) == [0.0, 0.0, 0.0]
    assert math.isclose(sum(bridge.read_turn_anticipations(0)), 0.0)
