#  SPDX-License-Identifier: GPL-2.0-or-later
"""The moving map draws each fly-by turn as its arc (TURN3, AER-5418).

A 90 deg left turn at B, 0.78 nm of anticipation (120 kt, 15 deg bank):
the arc is what is painted, not the corner at B, and the magenta part moves
from the leg into B to the leg out of it at the arc's apex, where the
engine moves ``FPLACTLEG`` on (brief section 3.3.1, row 2).
"""

import pytest
from PyQt6.QtGui import QColor, QImage, QPainter

from pyefis.flightplan import fixbridge
from pyefis.flightplan import geo
from pyefis.flightplan import leg_paths as fp_legs
from pyefis.flightplan import model as fp_model
from pyefis.instruments import map as moving_map
from pyefis.instruments.map.layers import flight_plan as fp_layer
from tests.instruments.test_map_flight_plan_layer import _define, _define_all_fp1_keys, _owner

A = (34.5, -119.9)
B = (34.5, -119.7)
C = geo.destination_point(B[0], B[1], 0.0, 10.0)
D_TA = 0.78
BLACK = QColor(0, 0, 0)


def _setup(fix, qtbot, ta=D_TA, act_leg=2):
    _define_all_fp1_keys(fix)
    for n in range(1, fixbridge.MAX_SLOTS + 1):
        _define(fix, f"FPL{n}TA", "float", 0.0)
    bridge = fixbridge.FixBridge(fix)
    bridge.publish(fp_model.FlightPlan(name="T", waypoints=[
        fp_model.Waypoint(id=ident, type="fix", lat=p[0], lon=p[1])
        for ident, p in (("A", A), ("B", B), ("C", C))]))
    layer = fp_layer.FlightPlanLayer()
    layer.configure(_owner(qtbot))
    _fly(fix, layer, ta, act_leg)
    return layer


def _fly(fix, layer, ta, act_leg):
    fr, to = (A, B) if act_leg == 2 else (B, C)
    for key, value in (("FPL2TA", ta), ("FPLSTATE", 1), ("FPLACTLEG", act_leg),
                       ("FPLFRLAT", fr[0]), ("FPLFRLON", fr[1]),
                       ("WPLAT", to[0]), ("WPLON", to[1])):
        fix.db.set_value(key, value)
    layer.collect(None)


def _render(layer, size=500):
    # 2 nm range about B, north up.
    x = moving_map.MapTransform(B[0], B[1], 2.0, 0.0, size, size, 0.5)
    img = QImage(size, size, QImage.Format.Format_RGB32)
    img.fill(0)
    p = QPainter(img)
    layer.paint(p, x)
    p.end()
    return img, x


def _color_at(img, x, pt, rad=2):
    """The colours painted within *rad* px of *pt*, black excluded."""
    c = x.to_screen(*pt)
    out = set()
    for dx in range(-rad, rad + 1):
        for dy in range(-rad, rad + 1):
            col = img.pixelColor(int(round(c.x())) + dx, int(round(c.y())) + dy)
            if col != BLACK:
                out.add(col.name())
    return out


def _arc():
    into, out = fp_legs.flyby_arc(A, B, C, D_TA)
    return into, out


def test_the_arc_is_painted_and_the_corner_is_not(fix, qtbot):
    # 0.25 nm before B on A -> B is on the old square corner and 0.18 nm
    # outside the arc: inked without FPLfTA, bare with it.
    corner = geo.destination_point(B[0], B[1], 270.0, 0.25)
    into, out = _arc()
    square = _setup(fix, qtbot, ta=0.0)
    img, x = _render(square)
    assert _color_at(img, x, corner)
    assert not _color_at(img, x, into[-1])
    _fly(fix, square, D_TA, 2)
    img, x = _render(square)
    assert not _color_at(img, x, corner)
    assert _color_at(img, x, into[-1])


def test_magenta_moves_on_at_the_apex(fix, qtbot):
    into, out = _arc()
    first, second = into[len(into) // 2], out[len(out) // 2]
    magenta, white = fp_layer.ACTIVE.name(), fp_layer.FUTURE.name()
    layer = _setup(fix, qtbot)
    img, x = _render(layer)
    assert _color_at(img, x, first, 1) == {magenta}
    assert _color_at(img, x, second, 1) == {white}
    # Past the bisector: FPLACTLEG = 3, FROM = B, and the engine keeps B's
    # arc (FPLfTA) until its end.
    _fly(fix, layer, D_TA, 3)
    img, x = _render(layer)
    assert magenta not in _color_at(img, x, first, 1)
    assert _color_at(img, x, second, 1) == {magenta}


def test_an_older_gateway_without_fplta_draws_the_corner(fix, qtbot):
    _define_all_fp1_keys(fix)
    bridge = fixbridge.FixBridge(fix)
    bridge.publish(fp_model.FlightPlan(name="T", waypoints=[
        fp_model.Waypoint(id=ident, type="fix", lat=p[0], lon=p[1])
        for ident, p in (("A", A), ("B", B), ("C", C))]))
    layer = fp_layer.FlightPlanLayer()
    layer.configure(_owner(qtbot))
    for key, value in (("FPLSTATE", 1), ("FPLACTLEG", 2), ("FPLFRLAT", A[0]), ("FPLFRLON", A[1]),
                       ("WPLAT", B[0]), ("WPLON", B[1])):
        fix.db.set_value(key, value)
    layer.collect(None)
    img, x = _render(layer)
    assert _color_at(img, x, geo.destination_point(B[0], B[1], 270.0, 0.25))


@pytest.mark.parametrize("act_leg", [2, 3])
def test_the_magenta_path_is_continuous_through_the_turn(fix, qtbot, act_leg):
    # No gap at the apex: the two legs share it, whichever is active.
    layer = _setup(fix, qtbot, act_leg=act_leg)
    into, out = _arc()
    img, x = _render(layer)
    assert _color_at(img, x, into[-1], 1)
    snap = layer._snapshot
    assert snap.draw_paths[0].points[-1] == snap.draw_paths[1].points[0] == into[-1]


def test_moving_the_turns_never_rebuilds_the_route(fix, qtbot, monkeypatch):
    # The arcs follow FPLfTA, FPLACTLEG and the FROM point, which change in
    # flight: they are re-applied to a copy of the route's paths, never by
    # rebuilding the route, and the route's own paths are left square.
    layer = _setup(fix, qtbot)
    snap = layer._snapshot
    base = [list(leg.points) for leg in snap.paths]

    def boom(*_a, **_k):
        raise AssertionError("route geometry rebuilt for a turn change")

    monkeypatch.setattr(fp_legs, "build_leg_paths", boom)
    _fly(fix, layer, D_TA, 3)
    _fly(fix, layer, 0.9, 3)
    assert layer._snapshot is snap
    assert [leg.points for leg in snap.paths] == base
    assert snap.draw_paths[1].points[0] == fp_legs.flyby_arc(A, B, C, 0.9)[1][0]
