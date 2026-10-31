"""The common Font size option reaches six widgets that used to drop it
(pyEfis #223, #229-#233): tab_section, button, listbox, data_status,
data_annunciation and checklist.

Every case builds the instrument through the real Screen path -- YAML
``options.font_percent`` -> screenbuilder_preferences.apply_preferences ->
screenbuilder_factory.build_*() -> apply_options -- so a builder that drops the
value again fails here. Font size is a multiplier on each widget's own built-in
text size (the #219 flight_plan shape), so leaving it unset must keep today's
size exactly.
"""
import math
import re

import pytest
from PyQt6.QtCore import qRound
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QTabBar

import pyefis.hmi as hmi
from pyefis.instruments.helpers import font_scale
from pyefis.screens.screenbuilder import Screen
from tests.screens.test_screenbuilder import (
    _TestParent, _config_with_instruments)

W, H = 800, 480


@pytest.fixture(autouse=True)
def hmi_actions(qtbot):
    """Real HMI signal object (button and checklist subscribe on build);
    qtbot first so a QApplication exists."""
    hmi.initialize({})
    yield


def _build(qtbot, inst_type, options=None, tabs=None, config_path=""):
    inst = {
        "type": inst_type, "row": 0, "column": 0,
        "span": {"rows": 10, "columns": 10},
        "options": dict(options or {}),
    }
    if tabs is not None:
        inst["tabs"] = tabs
    parent = _TestParent(_config_with_instruments([inst]),
                         config_path=config_path)
    screen = Screen(parent)
    screen.screenName = "TEST"      # set by gui.Main in the app; button reads it
    qtbot.addWidget(screen)
    screen.resize(W, H)
    screen.init_screen()
    # Showing delivers the instruments' resizeEvents, where most of them
    # derive their fonts; an unshown widget only gets them lazily.
    qtbot.addWidget(parent)
    parent.resize(W, H)
    parent.show()
    qtbot.waitExposed(parent)
    return screen.instruments[0]


# -- the shared multiplier ----------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    (None, 1.0), (0, 1.0), (-0.5, 1.0), (float("nan"), 1.0),
    (float("inf"), 1.0), ("big", 1.0),
    (0.5, 0.5), (1.0, 1.0),
    # Already normalised upstream: 1.5 is 150%, not 1.5%.
    (1.5, 1.5),
])
def test_font_scale(value, expected):
    assert font_scale(value) == expected

