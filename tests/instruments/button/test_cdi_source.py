"""The shipped cdi-source button against the HSI's NAVSRC scale (pyEfis#412).

NAVSRC is 0=NAV1, 1=NAV2, 2=GPS everywhere else: the HSI's source tab, the
HSI's source colouring and fix-gateway's compute select. The button once
coloured it on a 0=GPS/1=NAV1 scale, so NAV1 showed as GPS. These tests load
the real config file, not a fixture copy.
"""
import pytest
from unittest import mock
from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from pyefis.instruments import button
from pyefis.instruments.helpers import darken_to_contrast
import pyefis.hmi as hmi

CONFIG = "src/pyefis/config/buttons/cdi-source.yaml"

# The HSI's stock source colours (vloc_color / course_color) and the label
# tint its source tab draws on each (pyEfis#147).
NAV_FILL = QColor("#00ff00")
GPS_FILL = QColor("#ff00ff")


@pytest.fixture
def navsrc(fix):
    # As fix-gateway defines it (database/ahrs.yaml): the wrap span is
    # max - min, so max 3.0 is what makes the button a three-step cycle.
    fix.db.define_item("NAVSRC", "Selected Nav Source (0=NAV1, 1=NAV2, 2=GPS)",
                       "float", 0.0, 3.0, "", 50000, "")
    fix.db.define_item("TSBTN133", "Touch Button", "bool", None, None, "", 50000, "")
    for key, value in (("NAVSRC", 0.0), ("TSBTN133", False)):
        fix.db.set_value(key, value)
        fix.db.get_item(key).bad = False
        fix.db.get_item(key).fail = False
    return fix.db.get_item("NAVSRC")


@pytest.fixture
def widget(navsrc, qtbot):
    hmi.initialize({})
    parent = QWidget()
    parent.screenName = "TEST"
    parent.parent = mock.Mock()
    parent.parent.nodeID = 1
    w = button.Button(parent, config_file=CONFIG)
    qtbot.addWidget(parent)
    qtbot.addWidget(w)
    parent.resize(200, 200)
    parent.show()
    w.resize(100, 80)
    w.show()
    qtbot.waitExposed(w)
    return w


@pytest.mark.parametrize("value, fill", [
    (0.0, NAV_FILL),   # NAV1
    (1.0, NAV_FILL),   # NAV2
    (2.0, GPS_FILL),   # GPS
])
def test_colour_follows_hsi_source_scale(widget, navsrc, value, fill):
    navsrc.value = value
    assert widget._style["bg"].name() == fill.name()
    assert widget._style["fg"].name() == darken_to_contrast(fill).name()


def test_click_cycles_like_the_hsi_source_tab(widget, navsrc, qtbot):
    # The HSI's tab steps (cur + 1) % 3: NAV1 -> NAV2 -> GPS -> NAV1.
    seen = []
    for _ in range(4):
        qtbot.mouseClick(widget._button, Qt.MouseButton.LeftButton)
        seen.append((navsrc.value, widget._style["bg"].name()))
    nav, gps = NAV_FILL.name(), GPS_FILL.name()
    assert seen == [(1.0, nav), (2.0, gps), (0.0, nav), (1.0, nav)]
