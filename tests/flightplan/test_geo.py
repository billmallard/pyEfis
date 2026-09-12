#  SPDX-License-Identifier: GPL-2.0-or-later
"""Reference-fixture table for pyefis.flightplan.geo -- the same table
fix-gateway FP2 asserts against its own bearing/distance/xte math
(makerplane/briefs/flight_plan_plan.md, FP4 scope), so the two
implementations cannot drift apart even though FP3 lands first."""

import pytest

from pyefis.flightplan import geo

BEARING_DIST_CASES = [
    # (lat1, lon1, lat2, lon2, dist_nm, bearing_true_deg)
    (0.0, 0.0, 0.0, 1.0, 60.040, 90.00),
    (34.42621, -119.84037, 34.89892, -120.45758, 41.648, 313.13),  # KSBA->KSMX
    (33.94250, -118.40810, 40.63990, -73.77870, 2145.908, 65.87),  # KLAX->KJFK
    (45.0, -100.0, 46.0, -100.0, 60.040, 0.00),
    (20.0, 179.5, 20.0, -179.5, 56.419, 89.83),  # antimeridian crossing
]

# Cross-track of a probe point from the KSBA->KSMX track (positive = right).
XTE_CASES = [
    (34.60, -120.10, -1.146),
    (34.70, -120.10, 3.246),
    (34.55, -120.25, -8.396),
]

# Same probe points, along-track distance from KSBA (FP4 -- shares the table
# fix-gateway FP2's engine asserts, brief section 3.3).
ATD_CASES = [
    (34.60, -120.10, 16.509),
    (34.70, -120.10, 20.603),
    (34.55, -120.25, 19.892),
]
KSBA = (34.42621, -119.84037)
KSMX = (34.89892, -120.45758)


@pytest.mark.parametrize("lat1,lon1,lat2,lon2,dist_nm,bearing_deg", BEARING_DIST_CASES)
def test_distance_nm(lat1, lon1, lat2, lon2, dist_nm, bearing_deg):
    assert geo.distance_nm(lat1, lon1, lat2, lon2) == pytest.approx(dist_nm, abs=1e-3)


@pytest.mark.parametrize("lat1,lon1,lat2,lon2,dist_nm,bearing_deg", BEARING_DIST_CASES)
def test_initial_bearing(lat1, lon1, lat2, lon2, dist_nm, bearing_deg):
    assert geo.initial_bearing(lat1, lon1, lat2, lon2) == pytest.approx(bearing_deg, abs=0.01)


@pytest.mark.parametrize("lat,lon,xte_nm", XTE_CASES)
def test_cross_track_nm(lat, lon, xte_nm):
    got = geo.cross_track_nm(lat, lon, KSBA[0], KSBA[1], KSMX[0], KSMX[1])
    assert got == pytest.approx(xte_nm, abs=1e-3)


def test_cross_track_nm_zero_on_track():
    got = geo.cross_track_nm(KSBA[0], KSBA[1], KSBA[0], KSBA[1], KSMX[0], KSMX[1])
    assert got == pytest.approx(0.0, abs=1e-9)


@pytest.mark.parametrize("lat,lon,atd_nm", ATD_CASES)
def test_along_track_distance_nm(lat, lon, atd_nm):
    got = geo.along_track_distance_nm(lat, lon, KSBA[0], KSBA[1], KSMX[0], KSMX[1])
    assert got == pytest.approx(atd_nm, abs=1e-3)


def test_along_track_distance_nm_zero_at_start():
    got = geo.along_track_distance_nm(KSBA[0], KSBA[1], KSBA[0], KSBA[1], KSMX[0], KSMX[1])
    assert got == pytest.approx(0.0, abs=1e-6)


def test_along_track_distance_nm_full_leg_at_end():
    got = geo.along_track_distance_nm(KSMX[0], KSMX[1], KSBA[0], KSBA[1], KSMX[0], KSMX[1])
    assert got == pytest.approx(geo.distance_nm(*KSBA, *KSMX), abs=1e-3)


def test_initial_bearing_wraps_into_0_360():
    # Southbound leg -- bearing must stay in [0, 360), never negative.
    brg = geo.initial_bearing(46.0, -100.0, 45.0, -100.0)
    assert 0.0 <= brg < 360.0
    assert brg == pytest.approx(180.0, abs=0.01)


# ---------------------------------------------------------------------------
# destination_point (FP6: the map layer's extended-final-course projection)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("lat1,lon1,lat2,lon2,dist_nm,bearing_deg", BEARING_DIST_CASES)
def test_destination_point_round_trips_bearing_dist(lat1, lon1, lat2, lon2, dist_nm, bearing_deg):
    got_lat, got_lon = geo.destination_point(lat1, lon1, bearing_deg, dist_nm)
    assert got_lat == pytest.approx(lat2, abs=1e-3)
    assert got_lon == pytest.approx(lon2, abs=1e-3)


def test_destination_point_zero_distance_is_identity():
    lat, lon = geo.destination_point(34.5, -119.0, 47.0, 0.0)
    assert lat == pytest.approx(34.5, abs=1e-9)
    assert lon == pytest.approx(-119.0, abs=1e-9)


def test_destination_point_longitude_stays_in_range():
    lat, lon = geo.destination_point(20.0, 179.9, 90.0, 30.0)
    assert -180.0 <= lon < 180.0
