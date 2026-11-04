#  SPDX-License-Identifier: GPL-2.0-or-later
"""One-finger zoom rail on the moving map (billmallard/pyEfis#205, G22).

Every touch here goes through the widget's own mouse handlers (what Qt
synthesizes from a one-finger touch), not straight into the rail helpers, so
the claim-before-pan/tap ordering is what is under test. Range changes are
asserted on the bound MAPRANGE item as well as on ``range_nm``, because the
rail has to go through the single range-write path (#202) to keep a button,
a knob, pinch and the rail in agreement.
"""

import pytest
from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QColor, QImage

import pyefis.hmi.functions as functions
from pyefis.instruments import map as moving_map
from pyefis.screens import screenbuilder_factory as factory

LAT0, LON0 = 34.5, -120.0
_LADDER = [2.0, 5.0, 10.0, 20.0, 40.0, 80.0, 160.0]


class _Ev:
    def __init__(self, x, y):
        self._p = QPointF(x, y)

    def button(self):
        return Qt.MouseButton.LeftButton

    def position(self):
        return self._p

    def modifiers(self):
        return Qt.KeyboardModifier.NoModifier

    def accept(self):
        pass


def _map(qtbot, rail=True, w=400, h=480):
    m = moving_map.MovingMap()
    qtbot.addWidget(m)
    m.resize(w, h)
    m.orientation = "north_up"
    m._lat, m._lon = LAT0, LON0
    m.range_ladder = "2,5,10,20,40,80,160"
    m.range_nm = 10.0
    m.zoom_rail = rail
    m._build_layers()
    return m


def _bind_maprange(fix, m):
    fix.db.define_item("MAPRANGE", "MAPRANGE", "int", 0, 7, "", 50000, "")
    fix.db.set_value("MAPRANGE", _LADDER.index(10.0))
    item = fix.db.get_item("MAPRANGE")
    item.bad = False
    item.fail = False
    m.range_key = "MAPRANGE"
    m.init_live_bindings(m._live_binding_specs())
    return item


def _tap(m, pt):
    m.mousePressEvent(_Ev(pt.x(), pt.y()))
    m.mouseReleaseEvent(_Ev(pt.x(), pt.y()))


def _render(m):
    img = QImage(m.width(), m.height(), QImage.Format.Format_ARGB32)
    m.render(img)
    return img


def _rung_point(m, g, i):
    return QPointF(g["x"], m._rail_rung_y(g, i))


# --- a rail touch is the rail's, not the map's ------------------------------

def test_rail_tap_does_not_recenter_pan_or_place_a_pointer(fix, qtbot):
    m = _map(qtbot)
    m.pan_by(60, 0)
    assert m.is_offset
    g = m.zoom_rail_geometry()

    _tap(m, _rung_point(m, g, 3))           # the 20 NM detent
    assert m.range_nm == 20.0
    assert m.is_offset                      # still panned
    assert m.pointer is None                # no map point placed under it


def test_double_tap_on_a_cap_steps_twice_instead_of_recentring(fix, qtbot):
    """Qt sends a double tap's second press to mouseDoubleClickEvent, which
    on the map means recenter. On the rail it must be a second step."""
    m = _map(qtbot)
    m.pan_by(60, 0)
    c = m.zoom_rail_geometry()["plus"].center()
    m.mousePressEvent(_Ev(c.x(), c.y()))
    m.mouseReleaseEvent(_Ev(c.x(), c.y()))
    m.mouseDoubleClickEvent(_Ev(c.x(), c.y()))
    m.mouseReleaseEvent(_Ev(c.x(), c.y()))
    assert m.range_nm == 2.0                # 10 -> 5 -> 2
    assert m.is_offset


def test_drag_on_the_rail_does_not_pan(fix, qtbot):
    m = _map(qtbot)
    g = m.zoom_rail_geometry()
    start = _rung_point(m, g, 2)
    m.mousePressEvent(_Ev(start.x(), start.y()))
    m.mouseMoveEvent(_Ev(start.x() + 40, start.y()))
    m.mouseReleaseEvent(_Ev(start.x() + 40, start.y()))
    assert not m.is_offset


# --- detents -----------------------------------------------------------------

def test_drag_position_maps_to_the_nearest_rung(fix, qtbot):
    m = _map(qtbot)
    g = m.zoom_rail_geometry()
    step = m._rail_step(g)
    assert step > 0
    start = _rung_point(m, g, 2)            # thumb at 10 NM
    m.mousePressEvent(_Ev(start.x(), start.y()))
    assert m.range_nm == 10.0
    seen = []
    # Down the rail, finger a little off each detent: 40% past rung i still
    # reads rung i, 60% past reads rung i+1.
    for i, frac, want in ((2, 0.4, 10.0), (2, 0.6, 20.0), (4, 0.45, 40.0),
                          (5, 0.55, 160.0), (0, 0.0, 2.0)):
        y = m._rail_rung_y(g, i) + frac * step
        m.mouseMoveEvent(_Ev(g["x"], y))
        seen.append(m.range_nm)
        assert m.range_nm == want, (i, frac)
    m.mouseReleaseEvent(_Ev(g["x"], m._rail_rung_y(g, 0)))
    assert m._rail_active is None


def test_up_is_zoom_in(fix, qtbot):
    m = _map(qtbot)
    g = m.zoom_rail_geometry()
    assert g["ladder"][0] == 2.0 and g["ladder"][-1] == 160.0
    assert m._rail_rung_y(g, 0) < m._rail_rung_y(g, 6)
    assert g["plus"].center().y() < g["minus"].center().y()


def test_caps_step_one_rung_and_stop_at_the_ends(fix, qtbot):
    m = _map(qtbot)
    g = m.zoom_rail_geometry()
    plus, minus = g["plus"].center(), g["minus"].center()

    _tap(m, plus)
    assert m.range_nm == 5.0
    _tap(m, plus)
    assert m.range_nm == 2.0
    _tap(m, plus)
    assert m.range_nm == 2.0                # stops at the smallest rung

    m.range_nm = 80.0
    _tap(m, minus)
    assert m.range_nm == 160.0
    _tap(m, minus)
    assert m.range_nm == 160.0              # stops at the largest rung


def test_cap_steps_from_a_free_pinch_range_to_the_next_rung(fix, qtbot):
    """After a pinch left 13.7 NM on screen, + goes to 10 and - to 20: the
    same thing a range button does (#202's one write path)."""
    m = _map(qtbot)
    g = m.zoom_rail_geometry()
    m.range_nm = 13.7
    _tap(m, g["plus"].center())
    assert m.range_nm == 10.0
    m.range_nm = 13.7
    _tap(m, g["minus"].center())
    assert m.range_nm == 20.0


# --- the range key ------------------------------------------------------------

def test_range_key_holds_the_rung_index_after_a_rail_change(fix, qtbot):
    m = _map(qtbot)
    item = _bind_maprange(fix, m)
    g = m.zoom_rail_geometry()

    _tap(m, _rung_point(m, g, 5))           # jump to 80 NM
    assert m.range_nm == 80.0
    assert item.value == _LADDER.index(80.0)

    _tap(m, g["plus"].center())             # step in to 40 NM
    assert item.value == _LADDER.index(40.0)

    functions.changeValueWrap("MAPRANGE,1")  # then a real RNG+ button press
    assert m.range_nm == 80.0               # steps from where the rail left it


def test_external_maprange_write_moves_the_thumb(fix, qtbot):
    m = _map(qtbot)
    _bind_maprange(fix, m)
    g = m.zoom_rail_geometry()
    assert m._rail_thumb_y(g) == pytest.approx(m._rail_rung_y(g, 2))

    fix.db.set_value("MAPRANGE", _LADDER.index(40.0))   # a button or knob
    assert m.range_nm == 40.0
    assert m._rail_thumb_y(g) == pytest.approx(m._rail_rung_y(g, 4))

    # And on the glass: the thumb's centre is painted where the rung is.
    img = _render(m)
    x, y = int(round(g["x"])), int(round(m._rail_rung_y(g, 4)))
    assert QColor(img.pixel(x, y)) == m._RAIL_REST


def test_thumb_sits_between_rungs_for_a_free_range(fix, qtbot):
    m = _map(qtbot)
    g = m.zoom_rail_geometry()
    m.range_nm = (10.0 * 20.0) ** 0.5       # log midpoint of 10 and 20
    mid = (m._rail_rung_y(g, 2) + m._rail_rung_y(g, 3)) / 2.0
    assert m._rail_thumb_y(g) == pytest.approx(mid)


# --- zoom_rail: false ----------------------------------------------------------

def test_rail_off_draws_nothing_and_claims_no_touches(fix, qtbot):
    on = _map(qtbot, rail=True)
    g = on.zoom_rail_geometry()
    rung = _rung_point(on, g, 5)

    off = _map(qtbot, rail=False)
    assert off.zoom_rail_geometry() is None
    bare = _map(qtbot, rail=False)
    bare.zoom_rail_side = "right"           # side alone must draw nothing
    assert _render(off) == _render(bare)
    assert _render(on) != _render(off)      # the rail does draw when on

    # A press where the rail would be is an ordinary map press: a drag pans.
    off.mousePressEvent(_Ev(rung.x(), rung.y()))
    off.mouseMoveEvent(_Ev(rung.x() + 40, rung.y()))
    off.mouseReleaseEvent(_Ev(rung.x() + 40, rung.y()))
    assert off.range_nm == 10.0
    assert off.is_offset

    # And a tap there places a map point as it always did.
    off2 = _map(qtbot, rail=False)
    _tap(off2, rung)
    assert off2.pointer is not None
    assert off2.range_nm == 10.0


# --- geometry ---------------------------------------------------------------------

def test_touch_column_is_twenty_mm_on_the_configured_panel(fix, qtbot):
    m = _map(qtbot, w=1024, h=600)
    m._px_per_mm = lambda: 6.0              # a ~152 dpi panel
    g = m.zoom_rail_geometry()
    assert g["claim"].width() == pytest.approx(120.0)
    assert g["plus"].height() == pytest.approx(120.0)
    assert g["claim"].left() == 0.0         # at the bezel, for a bracing finger
    # One chip height below the status chip, and clear of the banner area.
    chip_h = max(9, int(1024 * 0.03)) + 6
    assert g["claim"].top() == pytest.approx(4.0 + 2 * chip_h)
    assert g["claim"].bottom() <= 600 * 0.75 + 1e-6


def test_right_side_mirrors_the_rail(fix, qtbot):
    m = _map(qtbot)
    m.zoom_rail_side = "right"
    g = m.zoom_rail_geometry()
    assert g["claim"].right() == pytest.approx(m.width())
    _tap(m, _rung_point(m, g, 4))
    assert m.range_nm == 40.0


def test_thumb_interior_is_its_own_colour_not_the_halo(fix, qtbot):
    """The thumb's halo is a ring outside the disc, never an underlay, so the
    disc interior reads exactly the ink colour at rest and while touched."""
    m = _map(qtbot)
    g = m.zoom_rail_geometry()
    x, y = int(round(g["x"])), int(round(m._rail_thumb_y(g)))
    assert QColor(_render(m).pixel(x, y)) == m._RAIL_REST
    m.mousePressEvent(_Ev(g["x"], m._rail_thumb_y(g)))
    assert QColor(_render(m).pixel(x, y)) == m._RAIL_ACTIVE
    m.mouseReleaseEvent(_Ev(g["x"], m._rail_thumb_y(g)))


def test_zoom_rail_props_registered():
    spec = factory.REGISTRY["moving_map"]
    props = {p.name: p for p in spec.properties}
    assert props["zoom_rail"].default is False
    assert props["zoom_rail_side"].enum == ["left", "right"]
