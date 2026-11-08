#  SPDX-License-Identifier: GPL-2.0-or-later
"""G59 (billmallard/pyEfis#375): a route waypoint that is also an airport,
VOR or fix is drawn once. Bill's option A: the database layer keeps the
symbol and label; the flight-plan layer adds only the TO ring and a role
suffix there, and draws in full the points no database layer is showing.

The layers are painted in the map's z order onto one ``MapTransform``, as
``MovingMap.paintEvent`` does, through a recording painter. KSBA and GVO
are the two places Bill saw doubled on the Beelink.
"""

import math

import pytest
from PyQt6.QtCore import QPointF
from PyQt6.QtGui import QImage, QPainter

from pyefis.flightplan import fixbridge
from pyefis.flightplan import model as fp_model
from pyefis.instruments.map import MapTransform
from pyefis.instruments.map.layers import find_drawn, mark_drawn
from pyefis.instruments.map.layers import flight_plan as fp_layer
from pyefis.instruments.map.layers.airports import AirportsLayer
from pyefis.instruments.map.layers.navaids import FixesLayer, NavaidsLayer
from tests.instruments.test_map_flight_plan_layer import _define_all_fp1_keys, _owner

KSBA = (34.42619166, -119.84149277)
GVO = (34.53119, -120.09111)
JAIOH = (34.42900, -119.80000)
USER = (34.45000, -119.90000)


class _ReadyDB:
    ready = True


class _Rec(QPainter):
    """Records the glyph primitives and text the layers ask for."""

    def __init__(self, dev):
        super().__init__(dev)
        self.centres, self.texts = [], []

    def drawPolygon(self, poly, *a):
        n = poly.size()
        self.centres.append(QPointF(sum(poly[i].x() for i in range(n)) / n,
                                    sum(poly[i].y() for i in range(n)) / n))
        return super().drawPolygon(poly, *a)

    def drawEllipse(self, *a):
        if isinstance(a[0], QPointF):
            self.centres.append(QPointF(a[0]))
        return super().drawEllipse(*a)

    def drawText(self, rect, flags, text):
        self.texts.append(text)
        return super().drawText(rect, flags, text)


def _publish(fix, roles=None):
    _define_all_fp1_keys(fix)
    wps = [fp_model.Waypoint(id="KSBA", type="airport", lat=KSBA[0], lon=KSBA[1]),
           fp_model.Waypoint(id="JAIOH", type="fix", lat=JAIOH[0], lon=JAIOH[1]),
           fp_model.Waypoint(id="USR1", type="user", lat=USER[0], lon=USER[1]),
           fp_model.Waypoint(id="GVO", type="vor", lat=GVO[0], lon=GVO[1])]
    for idx, role in (roles or {}).items():
        wps[idx].role = role
    fixbridge.FixBridge(fix).publish(fp_model.FlightPlan(name="G59", waypoints=wps))


def _db_layers(x, airports=True, navaids=True, fixes=True):
    out = []
    if airports:
        a = AirportsLayer()
        a._owner = None
        a._db_all = _ReadyDB()
        a._snap = (a._key(x), [{"icao": "KSBA", "lat": KSBA[0], "lon": KSBA[1],
                                "longest": 6052.0, "hard": True, "rwys": [],
                                "runways": [], "span_nm": 0.0}])
        out.append(a)
    for on, cls, rows in ((fixes, FixesLayer, [("JAIOH",) + JAIOH]),
                          (navaids, NavaidsLayer, [("GVO", "VORTAC", "116.50") + GVO])):
        if on:
            lay = cls()
            lay._owner = None
            lay._path = "unused.sqlite"
            lay._snap = (lay._key(x), rows)
            out.append(lay)
    return out      # already in z order: airports 30, fixes 38, navaids 40


def _render(layers, x):
    img = QImage(x.w, x.h, QImage.Format.Format_RGB32)
    img.fill(0)
    p = _Rec(img)
    for lay in layers:
        p.save()
        lay.paint(p, x)
        p.restore()
    p.end()
    return p


def _at(p, x, place):
    c = x.to_screen(*place)
    return sum(1 for q in p.centres if math.hypot(q.x() - c.x(), q.y() - c.y()) < 0.5)


def _labels(p, ident):
    return [t for t in p.texts if t.split(" ")[0] == ident]


@pytest.mark.parametrize("place,ident", [(KSBA, "KSBA"), (GVO, "GVO")])
@pytest.mark.parametrize("range_nm", [2.0, 20.0])
def test_route_point_a_database_layer_draws_is_drawn_once(fix, qtbot, place, ident, range_nm):
    _publish(fix)
    fpl = fp_layer.FlightPlanLayer()
    fpl.configure(_owner(qtbot))
    x = MapTransform(place[0], place[1], range_nm, 0.0, 800, 480, 0.5)
    alone = _render(_db_layers(x), x)
    x = MapTransform(place[0], place[1], range_nm, 0.0, 800, 480, 0.5)
    both = _render(_db_layers(x) + [fpl], x)
    assert _at(alone, x, place) >= 1
    assert _at(both, x, place) == _at(alone, x, place)     # no second glyph
    assert len(_labels(both, ident)) == 1                   # no second label


def test_flight_plan_layer_draws_what_no_database_layer_shows(fix, qtbot):
    """Layers off: the route still shows every point, once, in full."""
    _publish(fix)
    fpl = fp_layer.FlightPlanLayer()
    fpl.configure(_owner(qtbot))
    x = MapTransform(KSBA[0], KSBA[1], 20.0, 0.0, 800, 480, 0.5)
    p = _render(_db_layers(x, airports=False, navaids=False, fixes=False) + [fpl], x)
    for place, ident in ((KSBA, "KSBA"), (GVO, "GVO"), (JAIOH, "JAIOH"), (USER, "USR1")):
        assert _at(p, x, place) >= 1, ident
        assert len(_labels(p, ident)) == 1, ident


def test_user_point_is_drawn_by_the_flight_plan_layer(fix, qtbot):
    _publish(fix)
    fpl = fp_layer.FlightPlanLayer()
    fpl.configure(_owner(qtbot))
    x = MapTransform(KSBA[0], KSBA[1], 20.0, 0.0, 800, 480, 0.5)
    p = _render(_db_layers(x) + [fpl], x)
    assert _at(p, x, USER) == 1
    assert _labels(p, "USR1") == ["USR1"]


def test_unlabelled_airport_symbol_takes_the_route_label_once(fix, qtbot):
    """60 NM: the airports layer draws the symbol but no ident (its labels
    stop at 40 NM); the route label (to 80 NM) is the one label."""
    _publish(fix)
    fpl = fp_layer.FlightPlanLayer()
    fpl.configure(_owner(qtbot))
    x = MapTransform(KSBA[0], KSBA[1], 60.0, 0.0, 800, 480, 0.5)
    alone = _render(_db_layers(x, navaids=False, fixes=False), x)
    x = MapTransform(KSBA[0], KSBA[1], 60.0, 0.0, 800, 480, 0.5)
    both = _render(_db_layers(x, navaids=False, fixes=False) + [fpl], x)
    assert _labels(alone, "KSBA") == []
    assert _at(both, x, KSBA) == _at(alone, x, KSBA)
    assert _labels(both, "KSBA") == ["KSBA"]


def test_role_suffix_stays_under_the_database_label(fix, qtbot):
    _publish(fix, roles={1: "faf"})
    fpl = fp_layer.FlightPlanLayer()
    fpl.configure(_owner(qtbot))
    x = MapTransform(JAIOH[0], JAIOH[1], 2.0, 0.0, 800, 480, 0.5)
    p = _render(_db_layers(x) + [fpl], x)
    assert "JAIOH FAF" not in p.texts
    assert p.texts.count("JAIOH") == 1 and p.texts.count("FAF") == 1


def test_same_ident_elsewhere_is_not_the_same_place():
    x = MapTransform(34.0, -119.0, 20.0, 0.0, 800, 480, 0.5)
    here = x.to_screen(34.0, -119.0)
    mark_drawn(x, "abc", here, 0.0, True)
    assert find_drawn(x, "ABC", here) is not None
    assert find_drawn(x, "ABC", x.to_screen(34.05, -119.0)) is None
    assert find_drawn(x, "XYZ", here) is None
    assert MapTransform(34.0, -119.0, 20.0, 0.0, 800, 480, 0.5).drawn_points == {}
