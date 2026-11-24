#  SPDX-License-Identifier: GPL-2.0-or-later
"""AER-6420 (FPA3) evidence: the moving map after banner Insert on a route
the engine refused. Run under pytest (it needs the in-memory FIX database
from the root conftest); see README.md. Writes $AER6420_OUT."""

import os

from pyefis.flightplan import fixbridge
from pyefis.flightplan import model as fp_model
from tests.instruments.test_map_flight_plan_layer import _define, _define_all_fp1_keys
from tests.instruments.test_map_graphical_edit import (LAT0, LON0, _map, _paint,
                                                       _tap, _three_leg_plan)


def test_render_insert_on_refused_route(fix, qtbot):
    _define_all_fp1_keys(fix)
    bridge = fixbridge.FixBridge(fix)
    bridge.publish(_three_leg_plan())
    _define(fix, "FPLLDSEQ", "int", fix.db.get_item("FPLSEQ").value)
    # A second commit the engine refuses: FPLLDSEQ stays at the flown seq.
    bridge.publish(fp_model.FlightPlan(name="R", waypoints=[
        fp_model.Waypoint(id=f"R{i}", type="fix", lat=LAT0, lon=LON0 + 0.2 * i)
        for i in range(4)]))
    m = _map(qtbot, 800, 480)
    m.range_nm = 40.0
    x = m._transform()
    c = x.to_screen(LAT0 + 0.03, LON0 + 0.3)
    _tap(m, c.x(), c.y())
    m.banner_insert()
    _paint(m).save(os.environ["AER6420_OUT"])
