#  SPDX-License-Identifier: GPL-2.0-or-later
"""Ground paths of procedure legs (PA8, billmallard/pyEfis#239,
``pyefis.flightplan.leg_paths``), pinned against real published procedures.

Data sources, none typed by hand here:

- KSSF RNAV (GPS) 28 and the KABQ/KFNT holds: the route blocks
  fix-gateway's encoder (``fixgw/sim/fplroute.py``) builds from FAA CIFP
  cycle 2611, committed as ``fixtures/fplroute_blocks.json`` and checked
  against fix-gateway by ``test_fplroute_conformance.py``.
- KABQ RNAV (GPS) Y RWY 21 (RF), 09J VOR-A (AF, PI): the constants
  fix-gateway's ``tests/plugins/flightplan/test_engine_golden_procedures.py``
  decodes from its ``tests/fixtures/cifp/FAACIFP18`` excerpt, where
  ``test_leg_constants_match_the_committed_golden_fixture_file`` re-decodes
  the file and asserts every one of them.
"""

import math

import pytest

from pyefis.flightplan import fixbridge, geo
from pyefis.flightplan import leg_paths as L
from tests.flightplan.test_fplroute_conformance import FIXTURE, _route_block


def _profile(name):
    prof = FIXTURE["profiles"][name]
    return _route_block([tuple(w) for w in prof["writes"]]), prof["magvar_deg"]


def _slot(id, lat, lon, pt="TF", **kw):
    return fixbridge.RouteSlot(id=id, lat=lat, lon=lon, type="fix", role="none", pt=pt, **kw)


def _xtk(p, a, course):
    """Signed cross-track (NM, right positive) of *p* from the line through
    *a* on true *course*."""
    b = geo.destination_point(a[0], a[1], course, 10.0)
    return geo.cross_track_nm(p[0], p[1], a[0], a[1], b[0], b[1])


# ---------------------------------------------------------------------------
# DF: the coded turn direction (QA1 F3, AER-4541; Elon on AER-1607).
# KSSF RNAV 28 missed approach: climb on 279.6 M (CA), then DF GANLE coded
# RIGHT. GANLE lies about 130 deg LEFT of the climb-out, so the short way
# is left and the procedure says right.
# ---------------------------------------------------------------------------
def _kssf_df():
    route, magvar = _profile("qa1-missed-coded-turn-kssf-r28")
    slots = route.waypoints
    k = next(i for i, s in enumerate(slots) if s.pt == "DF")
    assert slots[k].id == "GANLE" and slots[k].turn == "R"
    assert slots[k - 1].pt == "CA"
    paths = L.build_leg_paths(slots, magvar)
    df = next(p for p in paths if p.to_slot == k + 1)
    climb_true = (slots[k - 1].crs - magvar) % 360.0
    return slots, k, df, climb_true


def test_kssf_df_short_way_is_left():
    """The premise: from the end of the climb-out, GANLE is well to the left,
    so a short-way (great-circle) DF would turn left."""
    slots, k, df, climb = _kssf_df()
    start = df.points[0]
    rel = (geo.initial_bearing(*start, slots[k].lat, slots[k].lon) - climb + 180.0) % 360.0 - 180.0
    assert -140.0 < rel < -110.0


def test_kssf_df_coded_right_is_drawn_turning_right():
    """DoD (Elon, AER-1607): the drawn turn side for a coded-RIGHT DF. Every
    vertex of the turn lies right of the climb-out course (the turn circle
    sits entirely on that side), and the turn sweeps the long way round,
    well past 180 deg, before it rolls out for GANLE."""
    slots, k, df, climb = _kssf_df()
    start = df.points[0]
    turn = df.points[1:-2]          # the arc; then roll-out point, then GANLE
    assert len(turn) > 30
    assert all(_xtk(p, start, climb) > 0.0 for p in turn)
    # Heading at the roll-out: the course of the straight run to GANLE.
    a, b = df.points[-2], df.points[-1]
    rollout = geo.initial_bearing(*a, *b)
    swept = (rollout - climb) % 360.0           # measured clockwise
    assert 200.0 < swept < 260.0
    assert df.points[-1] == (slots[k].lat, slots[k].lon)


def test_df_turn_left_mirrors_it():
    """The same DF coded LEFT turns the short way here: every vertex left of
    the climb-out. The pin above fails if the code ignores FPLfTURN."""
    slots, k, _df, climb = _kssf_df()
    slots[k].turn = "L"
    paths = L.build_leg_paths(slots, -3.0)
    df = next(p for p in paths if p.to_slot == k + 1)
    assert all(_xtk(p, df.points[0], climb) < 0.0 for p in df.points[1:-2])
    a, b = df.points[-2], df.points[-1]
    assert (climb - geo.initial_bearing(*a, *b)) % 360.0 < 180.0


def test_df_without_a_coded_turn_is_the_straight_leg():
    slots, k, _df, _climb = _kssf_df()
    slots[k].turn = ""
    df = next(p for p in L.build_leg_paths(slots, -3.0) if p.to_slot == k + 1)
    assert len(df.points) == 2


def test_df_with_the_fix_inside_the_turn_circle_is_straight():
    start = (34.0, -119.0)
    fix = geo.destination_point(*start, 90.0, 0.3)     # inside a 0.64 NM circle
    slots = [_slot("A", *geo.destination_point(*start, 0.0, -5.0)), _slot("B", *start),
             _slot("C", *fix, pt="DF", turn="R")]
    df = L.build_leg_paths(slots)[-1]
    assert df.points == [start, fix]


# ---------------------------------------------------------------------------
# RF: KABQ RNAV (GPS) Y RWY 21, FOXRR transition -- two chained real arcs
# around one centre fix, CFDXH, both coded turn R.
# ---------------------------------------------------------------------------
KABQ_BGEYE = (35.12695833, -106.65031667)
KABQ_CFDXH = (35.08599722, -106.62291667)
KABQ_KEIFR = (35.125675, -106.59285556)
KABQ_KAGNE = (35.09366667, -106.56681944)


def test_kabq_rf_arcs_follow_the_circle_clockwise():
    r1 = geo.distance_nm(*KABQ_CFDXH, *KABQ_KEIFR)
    r2 = geo.distance_nm(*KABQ_CFDXH, *KABQ_KAGNE)
    slots = [_slot("BGEYE", *KABQ_BGEYE),
             _slot("KEIFR", *KABQ_KEIFR, pt="RF", turn="R", dst=r1,
                   ctr_lat=KABQ_CFDXH[0], ctr_lon=KABQ_CFDXH[1]),
             _slot("KAGNE", *KABQ_KAGNE, pt="RF", turn="R", dst=r2,
                   ctr_lat=KABQ_CFDXH[0], ctr_lon=KABQ_CFDXH[1])]
    paths = L.build_leg_paths(slots)
    arc = paths[1]                       # KEIFR -> KAGNE, the arc-to-arc join
    assert arc.points[0] == KABQ_KEIFR and arc.points[-1] == KABQ_KAGNE
    assert len(arc.points) > 3           # tessellated, not a chord
    for p in arc.points:
        assert geo.distance_nm(*KABQ_CFDXH, *p) == pytest.approx(r2, abs=0.02)
    radials = [geo.initial_bearing(*KABQ_CFDXH, *p) for p in arc.points]
    steps = [(b - a) % 360.0 for a, b in zip(radials, radials[1:])]
    assert all(0.0 < s <= L.ARC_STEP_DEG + 1e-6 for s in steps)    # clockwise


# ---------------------------------------------------------------------------
# AF: 09J VOR-A, TOMDY (turn R) and WIGID (turn L) transitions, both onto
# the 7 NM arc around the SSI VOR at SAUSE.
# ---------------------------------------------------------------------------
NINEJ_SSI = (31.05051389, -81.44596389)
NINEJ_TOMDY = (30.93517778, -81.42359167)
NINEJ_SAUSE = (30.95256944, -81.52011111)
NINEJ_WIGID = (31.10594444, -81.565575)


@pytest.mark.parametrize("start, turn, sign", [(NINEJ_TOMDY, "R", 1.0), (NINEJ_WIGID, "L", -1.0)])
def test_09j_dme_arc_in_the_coded_direction(start, turn, sign):
    radius = geo.distance_nm(*NINEJ_SSI, *NINEJ_SAUSE)
    slots = [_slot("IF", *start, pt="IF"),
             _slot("SAUSE", *NINEJ_SAUSE, pt="AF", turn=turn, dst=7.0,
                   ctr_lat=NINEJ_SSI[0], ctr_lon=NINEJ_SSI[1])]
    arc = L.build_leg_paths(slots)[0]
    assert arc.points[-1] == NINEJ_SAUSE
    for p in arc.points[1:-1]:
        assert geo.distance_nm(*NINEJ_SSI, *p) == pytest.approx(7.0, abs=0.01)
    radials = [geo.initial_bearing(*NINEJ_SSI, *p) for p in arc.points]
    for a, b in zip(radials, radials[1:]):
        assert sign * ((b - a + 180.0) % 360.0 - 180.0) > 0.0
    assert radius == pytest.approx(7.0, abs=0.05)


# ---------------------------------------------------------------------------
# Holds: the racetrack the engine flies, drawn to the coded inbound course,
# turn direction and leg length. KSSF GANLE (R, 4.0 NM) and KBVY (L).
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("profile", ["qa1-missed-coded-turn-kssf-r28",
                                     "qa1-hold-direct-left-kbvy-r09"])
def test_hold_racetrack_on_the_coded_side_and_length(profile):
    route, magvar = _profile(profile)
    slots = route.waypoints
    k = next(i for i, s in enumerate(slots) if s.pt == "HM")
    hm = slots[k]
    path = next(p for p in L.build_leg_paths(slots, magvar) if p.to_slot == k + 1)
    fix = (hm.lat, hm.lon)
    inbound = (hm.crs - magvar) % 360.0
    track = path.pattern
    assert track[0] == fix and track[-1] == fix
    sign = 1.0 if hm.turn == "R" else -1.0
    # The holding side: right of the inbound course for a right-hand hold.
    lateral = [sign * _xtk(p, fix, inbound) for p in track]
    assert min(lateral) > -0.01
    assert max(lateral) == pytest.approx(2.0 * L.TURN_RADIUS_NM, abs=0.02)
    # Outbound ends hm.dst along-track from the fix; the turn in adds a radius.
    outbound = inbound + 180.0
    reach = max(geo.distance_nm(*fix, *p) * math.cos(math.radians(
        geo.initial_bearing(*fix, *p) - outbound)) for p in track[1:-1])
    assert hm.dst <= reach <= hm.dst + L.TURN_RADIUS_NM + 0.02


def test_procedure_turn_reaches_the_engines_outbound_point():
    """09J VOR-A SSI transition: a lone PI at the IAF, inbound 172.1, 10 NM.
    The drawn shape goes out to the point the engine flies the outbound leg
    to (reciprocal + 45 deg for a right turn, 10 NM), reverses, and comes
    back onto the inbound course."""
    fix = NINEJ_SSI
    slots = [_slot("A", *geo.destination_point(*fix, 0.0, 15.0)),
             _slot("SSI", *fix, pt="PI", crs=172.1, dst=10.0, turn="R")]
    pat = L.build_leg_paths(slots)[0].pattern
    out_pt = geo.destination_point(*fix, (172.1 + 180.0 + 45.0) % 360.0, 10.0)
    assert pat[0] == fix and pat[-1] == fix
    assert geo.distance_nm(*pat[1], *out_pt) < 0.01
    # The intercept point, just before the fix, sits on the inbound course.
    assert abs(_xtk(pat[-2], fix, 172.1)) < 0.01


# ---------------------------------------------------------------------------
# Course, altitude-terminated and vector legs.
# ---------------------------------------------------------------------------
def test_ca_runs_along_its_coded_course():
    slots, k, _df, climb = _kssf_df()
    ca = next(p for p in L.build_leg_paths(slots, -3.0) if p.to_slot == k)
    a, b = ca.points
    assert geo.initial_bearing(*a, *b) == pytest.approx(climb, abs=0.1)
    assert not ca.vector


@pytest.mark.parametrize("pt", ["VA", "VM", "VI"])
def test_vector_legs_are_a_stub_on_the_coded_heading(pt):
    start = (34.0, -119.0)
    slots = [_slot("A", *start), _slot("", 0.0, 0.0, pt=pt, crs=250.0)]
    leg = L.build_leg_paths(slots, magvar=10.0)[0]
    assert leg.vector
    a, b = leg.points
    assert a == start
    assert geo.initial_bearing(*a, *b) == pytest.approx(240.0, abs=0.1)
    assert geo.distance_nm(*a, *b) == pytest.approx(L.VECTOR_STUB_NM, abs=0.01)


def test_plain_route_is_the_great_circle_legs_it_always_was():
    slots = [_slot(f"W{i}", 34.0 + 0.1 * i, -119.0 - 0.1 * i) for i in range(4)]
    paths = L.build_leg_paths(slots)
    assert [p.points for p in paths] == [
        [(s.lat, s.lon), (t.lat, t.lon)] for s, t in zip(slots, slots[1:])]
    assert [p.to_slot for p in paths] == [2, 3, 4]
    assert not any(p.pattern or p.vector for p in paths)


def test_turn_radius_is_standard_rate_at_the_nominal_speed():
    # 3 deg/s: a full circle in 120 s, so the circumference is 2 minutes'
    # travel.
    assert 2.0 * math.pi * L.TURN_RADIUS_NM == pytest.approx(L.NOMINAL_GS_KT / 30.0)
