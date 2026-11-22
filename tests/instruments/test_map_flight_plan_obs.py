#  SPDX-License-Identifier: GPL-2.0-or-later
"""The moving map's GPS OBS course line (OBS3, AER-6086).

While the engine is in OBS (FPLSTATE = 4) the flight_plan layer draws the OBS
course -- FPLCRS, magnetic, converted with the variation -- through the TO
waypoint (WPLAT/WPLON), as the G1000 and G3X do. The plan's leg into that
waypoint is no longer the path being steered, so it is not magenta.
"""

import pytest

from pyefis.flightplan import fixbridge
from pyefis.flightplan import geo as fp_geo
from pyefis.flightplan import leg_paths as fp_legs
from pyefis.instruments.map.layers import flight_plan as fp_layer

from .test_map_flight_plan_layer import _engine, _route

# TONIE-like geometry: a fix at 35N 106W, the OBS course 270 magnetic.
WP = (35.0, -106.0)


def _obs_engine(**overrides):
    base = dict(FPLSTATE=4, FPLACTLEG=2, FPLFRLAT=34.9, FPLFRLON=-106.4,
                WPLAT=WP[0], WPLON=WP[1], FPLCRS=270.0, FPLPHASE="ENR")
    base.update(overrides)
    return _engine(**base)


def test_line_passes_through_the_to_waypoint_on_the_obs_course():
    a, b = fp_layer.build_obs_course(_obs_engine(), magvar=0.0)
    assert abs(fp_geo.cross_track_nm(WP[0], WP[1], a[0], a[1], b[0], b[1])) < 1e-6
    # Inbound end first: the line is flown a -> WP -> b on the OBS course.
    assert fp_geo.initial_bearing(WP[0], WP[1], b[0], b[1]) == pytest.approx(270.0, abs=1e-6)
    assert fp_geo.distance_nm(*a, *WP) == pytest.approx(fp_layer._OBS_LINE_NM, rel=1e-6)
    assert fp_geo.distance_nm(*WP, *b) == pytest.approx(fp_layer._OBS_LINE_NM, rel=1e-6)


def test_magnetic_course_is_drawn_true():
    """FPLCRS is magnetic and is converted the way the extension past the
    MAP converts it (true = FPLCRS - MAGVAR): 270 M at MAGVAR -10 is 280 T."""
    _a, b = fp_layer.build_obs_course(_obs_engine(), magvar=-10.0)
    assert fp_geo.initial_bearing(WP[0], WP[1], b[0], b[1]) == pytest.approx(280.0, abs=1e-6)


def test_length_is_the_callers():
    a, _b = fp_layer.build_obs_course(_obs_engine(), magvar=0.0, length_nm=120.0)
    assert fp_geo.distance_nm(*a, *WP) == pytest.approx(120.0, rel=1e-6)


@pytest.mark.parametrize("state", [0, 1, 2, 3])
def test_no_line_outside_obs(state):
    assert fp_layer.build_obs_course(_obs_engine(FPLSTATE=state), magvar=0.0) is None


@pytest.mark.parametrize("key,flag", [("FPLCRS", "fail"), ("FPLCRS", "bad"),
                                      ("WPLAT", "fail")])
def test_no_line_without_a_valid_course_or_waypoint(key, flag):
    engine = _obs_engine()
    engine[key] = fixbridge.ItemValue(value=engine[key].value, old=False,
                                      bad=flag == "bad", fail=flag == "fail")
    assert fp_layer.build_obs_course(engine, magvar=0.0) is None


def test_fplcrs_is_part_of_the_draw_signature_in_obs():
    """A turn of the OBS course must repaint the map: FPLCRS joins the
    signature in OBS, as it does for the extension past the MAP."""
    assert fp_layer._extension_drawn(4, 0) is True
    assert fp_layer._extension_drawn(1, 0) is False


def test_the_active_leg_is_not_magenta_in_obs():
    route = _route(4)
    paths = fp_legs.build_leg_paths(route.waypoints)
    leg = fp_layer.build_leg_draws(route, _engine(FPLSTATE=1, FPLACTLEG=3, FPLFRLAT=1.0,
                                                  FPLFRLON=1.0, WPLAT=2.0, WPLON=2.0), paths)
    assert [c for c, *_ in leg].count(fp_layer.ACTIVE) == 1
    obs = fp_layer.build_leg_draws(route, _engine(FPLSTATE=4, FPLACTLEG=3, FPLFRLAT=1.0,
                                                  FPLFRLON=1.0, WPLAT=2.0, WPLON=2.0), paths)
    assert fp_layer.ACTIVE not in [c for c, *_ in obs]
    # The leg into the TO waypoint draws as a leg still ahead.
    assert [c for c, *_ in obs] == [c if c != fp_layer.ACTIVE else fp_layer.FUTURE
                                    for c, *_ in leg]


def test_an_unloaded_route_draws_no_from_to_leg_in_obs():
    assert fp_layer.FlightPlanLayer._unloaded_draws(_obs_engine()) == []
    assert fp_layer.FlightPlanLayer._unloaded_draws(_obs_engine(FPLSTATE=1)) != []
