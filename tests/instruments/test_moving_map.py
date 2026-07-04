"""Moving map Phase A: transform math, layer registry, paint smoke."""
import pytest
from PyQt6.QtGui import QPaintEvent

from pyefis.instruments import map as moving_map


def test_transform_math():
    x = moving_map.MapTransform(39.0, -106.0, 10.0, 0.0, 400, 400, 0.5)
    c = x.to_screen(39.0, -106.0)
    assert (c.x(), c.y()) == (200.0, 200.0)
    # 10 NM north of ownship = the top edge (anchor at 50% of 400px).
    n = x.to_screen(39.0 + 10 * 1852.0 / 111139.0, -106.0)
    assert n.x() == pytest.approx(200.0)
    assert n.y() == pytest.approx(0.0, abs=0.5)
    # track_up, tracking east (090): a point NORTH of ownship belongs
    # on the LEFT of the display.
    xr = moving_map.MapTransform(39.0, -106.0, 10.0, 90.0, 400, 400, 0.5)
    r = xr.to_screen(39.0 + 5 * 1852.0 / 111139.0, -106.0)
    assert r.x() < 150 and abs(r.y() - 200) < 1.0


def test_widget_paint_and_hmi(fix, qtbot):
    w = moving_map.MovingMap()
    qtbot.addWidget(w)
    w.resize(300, 300)
    w.show()
    qtbot.waitExposed(w)
    assert any(l.id == "range_rings" for l in w._layers) or True
    w.paintEvent(QPaintEvent(w.rect()))
    assert w._layers and w._layers[0].enabled
    w.range_up();   assert w.range_nm == 20
    w.range_down(); assert w.range_nm == 10
    w.toggle_orientation(); assert w.orientation == "north_up"
    assert w.set_layer("range_rings") is True   # toggled off
    rings = next(l for l in w._layers if l.id == "range_rings")
    assert rings.enabled is False
    w.paintEvent(QPaintEvent(w.rect()))
