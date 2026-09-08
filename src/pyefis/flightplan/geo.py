#  SPDX-License-Identifier: GPL-2.0-or-later
"""Great-circle geodesy for the flight-plan data layer.

Spherical-earth bearing / distance / cross-track, matching the formulas
fix-gateway's ``fixgw.plugins.compute`` uses for ``xteFunction`` (same
``_initial_bearing_rad`` / ``_great_circle_distance_rad`` math). The two
implementations are asserted against the same reference-fixture table
(``makerplane/briefs/flight_plan_plan.md`` FP4 scope) so they cannot drift
apart. FP3 lands first and owns this file's first version; FP4 (route model)
extends it with along-track distance.
"""

from __future__ import annotations

import math

EARTH_RADIUS_NM = 3440.065


def _rad(deg: float) -> float:
    return math.radians(deg)


def initial_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """True initial bearing in degrees [0, 360) from point 1 to point 2."""
    p1, l1, p2, l2 = _rad(lat1), _rad(lon1), _rad(lat2), _rad(lon2)
    dlon = l2 - l1
    y = math.sin(dlon) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dlon)
    return math.degrees(math.atan2(y, x)) % 360.0


def distance_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in nautical miles between two points."""
    p1, l1, p2, l2 = _rad(lat1), _rad(lon1), _rad(lat2), _rad(lon2)
    dlat = p2 - p1
    dlon = l2 - l1
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return EARTH_RADIUS_NM * c


def cross_track_nm(lat: float, lon: float,
                    lat1: float, lon1: float,
                    lat2: float, lon2: float) -> float:
    """Signed cross-track distance in nm of (lat, lon) from the great-circle
    track running from point 1 to point 2. Positive = right of track."""
    dtk = _rad(initial_bearing(lat1, lon1, lat2, lon2))
    theta13 = _rad(initial_bearing(lat1, lon1, lat, lon))
    delta13 = distance_nm(lat1, lon1, lat, lon) / EARTH_RADIUS_NM
    xte_rad = math.asin(math.sin(delta13) * math.sin(theta13 - dtk))
    return xte_rad * EARTH_RADIUS_NM
