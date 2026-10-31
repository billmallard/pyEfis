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
from pyefis.instruments.tab_section import _MIN_TAB_LABEL_PX
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


# -- tab_section (#223) -------------------------------------------------------

_TABS = [{"label": "Engine", "layout": {"rows": 1, "columns": 1},
          "instruments": []},
         {"label": "Nav", "layout": {"rows": 1, "columns": 1},
          "instruments": []}]


def _tab(qtbot, **options):
    return _build(qtbot, "tab_section", options, tabs=_TABS)


def _label_px(tab_section):
    """The scaled label size -- an explicit pixel size on the bar's font."""
    return tab_section.tab_bar.font().pixelSize()


def test_tab_section_unset_keeps_todays_label_size(fix, qtbot):
    tab_section = _tab(qtbot)
    # Today's size is the inherited QTabBar font with the family applied.
    reference = QTabBar()
    qtbot.addWidget(reference)
    font = QFont(reference.font())
    font.setFamily("DejaVu Sans Condensed")
    assert tab_section.font_percent is None
    assert tab_section.tab_bar.font() == font


@pytest.mark.parametrize("position", ["top", "bottom", "left", "right"])
def test_tab_section_font_percent_grows_bar_and_shrinks_content(
        fix, qtbot, position):
    """150 (a whole-number percent, 1.5 after normalising) grows the labels;
    _layout_pages() reserves the bigger sizeHint() on every edge and the
    content area gives up exactly that much."""
    base = _tab(qtbot, tab_position=position)
    big = _tab(qtbot, tab_position=position, font_percent=150)

    assert big.font_percent == pytest.approx(1.5)
    assert _label_px(big) == round(base._base_label_px() * 1.5)

    side = position in ("left", "right")
    hint = (lambda t: t.tab_bar.sizeHint().width()) if side else \
        (lambda t: t.tab_bar.sizeHint().height())
    assert hint(big) > hint(base)
    for t in (base, big):
        if side:
            assert t.tab_bar.width() == hint(t)
            assert t.stack.width() == W - hint(t)
            assert t.stack.height() == H
        else:
            assert t.tab_bar.height() == hint(t)
            assert t.stack.height() == H - hint(t)
            assert t.stack.width() == W
    if side:
        assert big.stack.width() < base.stack.width()
    else:
        assert big.stack.height() < base.stack.height()


def test_tab_section_small_font_percent_stops_at_legibility_floor(fix, qtbot):
    """0.2 is what Bill's bench panel carries; 20% of the default label is
    unreadable, so it lands on the floor instead."""
    base = _tab(qtbot)
    small = _tab(qtbot, font_percent=0.2)
    assert round(base._base_label_px() * 0.2) < _MIN_TAB_LABEL_PX
    assert _label_px(small) == _MIN_TAB_LABEL_PX
    assert small.tab_bar.sizeHint().height() < base.tab_bar.sizeHint().height()


def test_tab_section_font_percent_survives_fg_color_stylesheet(fix, qtbot):
    t = _tab(qtbot, fg_color="#ffff00", font_percent=150)
    base = _tab(qtbot)
    assert _label_px(t) == round(base._base_label_px() * 1.5)


# -- button (#229) ------------------------------------------------------------

_BUTTON = {"dbkey": "TSBTN{id}0", "text": "Units"}


def test_button_font_percent_scales_label(fix, qtbot):
    base = _build(qtbot, "button", _BUTTON)
    half = _build(qtbot, "button", {**_BUTTON, "font_percent": 50})
    h = base.height()
    assert base._button.font().pixelSize() == qRound(h * 38 / 100)
    assert half._button.font().pixelSize() == qRound(h * 38 / 100 * 0.5)


def test_button_font_percent_never_grows_past_the_mask_fit(fix, qtbot):
    """With a font_mask the auto-fit is the largest label that fits, so the
    multiplier shrinks it but a value over 100% is clamped to the fit."""
    base = _build(qtbot, "button", {**_BUTTON, "font_mask": "XXXXX"})
    half = _build(qtbot, "button",
                  {**_BUTTON, "font_mask": "XXXXX", "font_percent": 0.5})
    big = _build(qtbot, "button",
                 {**_BUTTON, "font_mask": "XXXXX", "font_percent": 150})
    for b in (base, half, big):
        b.setStyle()
    fitted = base._button.font().pointSizeF()
    assert fitted > 0
    assert half._button.font().pointSizeF() == pytest.approx(fitted * 0.5)
    assert big._button.font().pointSizeF() == pytest.approx(fitted)

