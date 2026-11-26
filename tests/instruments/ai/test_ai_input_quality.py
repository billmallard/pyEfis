"""INS5 (AER-6588): the AI's flight-path marker and SVS honour the quality of
VS, GS, TRACK, HEAD and MAGVAR.

On dev the FPM tracked fail and bad for its four required keys but not old,
so a source that stopped writing kept a green marker; the horizon heading
marks likewise ignored an old HEAD; and MAGVAR was read for its value alone,
so a bad or failed variation still turned the terrain. The rules under test:

- `VS`/`GS`/`TRACK`/`HEAD` old: the FPM draws in its degraded amber, as on bad.
- `HEAD` old: no horizon heading marks, as on bad or fail.
- `MAGVAR` bad or fail: no terrain, SVS UNAVAIL, FPM amber. `MAGVAR` old: no
  change (variation is slow, and an unwritten MAGVAR ages to old at 0.0).

Flags are driven through the FIX item, so the subscription is under test too.
"""
from unittest import mock

import pytest
from PyQt6.QtGui import QColor

from pyefis.instruments.ai import AI
from pyefis.instruments.ai.svs import make_svs_item

from tests.instruments.ai.test_svs_position_quality import (
    _ai_with_svs, _amber_pixels)

GREEN = QColor(0, 200, 0).name()
AMBER = QColor(255, 165, 0).name()
FPM_KEYS = ("VS", "GS", "TRACK", "HEAD")


def _clean(fix, keys):
    for key in keys:
        item = fix.db.get_item(key)
        item.old = item.bad = item.fail = False


def _define_magvar(fix, value=12.0):
    fix.db.define_item("MAGVAR", "Magnetic Variation", "float", -180.0, 180.0,
                       "deg", 60000, "")
    fix.db.set_value("MAGVAR", value)
    _clean(fix, ["MAGVAR"])


def _fpm_widget(fix, qtbot):
    _clean(fix, ("PITCH", "ROLL", "ALAT", "TAS") + FPM_KEYS)
    fix.db.set_value("GS", 120.0)
    fix.db.set_value("VS", -500.0)
    w = AI()
    qtbot.addWidget(w)
    w.resize(400, 300)
    w.show()
    qtbot.waitExposed(w)
    w.show_fpm = True
    return w


def _fpm_color(w):
    """The colour the FPM was drawn in, or None when it was not drawn."""
    p = mock.MagicMock()
    w._drawFPM(p, w.width(), w.height())
    if not p.drawEllipse.called:
        return None
    return p.setPen.call_args_list[-1].args[0].color().name()


def test_fpm_control_valid_inputs_draw_green(fix, qtbot):
    w = _fpm_widget(fix, qtbot)
    assert _fpm_color(w) == GREEN


@pytest.mark.parametrize("key", FPM_KEYS)
def test_old_fpm_input_draws_the_marker_amber(fix, qtbot, key):
    w = _fpm_widget(fix, qtbot)
    fix.db.get_item(key).old = True
    assert _fpm_color(w) == AMBER
    fix.db.get_item(key).old = False
    assert _fpm_color(w) == GREEN


@pytest.mark.parametrize("key", FPM_KEYS)
def test_fpm_reads_initial_old(fix, qtbot, key):
    _clean(fix, FPM_KEYS)
    fix.db.get_item(key).old = True
    w = AI()
    qtbot.addWidget(w)
    assert w._fpm_old[key] is True


def test_old_head_removes_horizon_heading_marks(fix, qtbot):
    w = _fpm_widget(fix, qtbot)
    w.horizon_heading_marks = True
    p = mock.MagicMock()
    w._draw_horizon_heading(p, w.width(), w.height())
    assert p.drawLine.called                       # control
    fix.db.get_item("HEAD").old = True
    p = mock.MagicMock()
    w._draw_horizon_heading(p, w.width(), w.height())
    assert not p.drawLine.called


@pytest.mark.parametrize("flag", ["bad", "fail"])
def test_bad_or_failed_magvar_removes_terrain_and_annunciates(fix, qtbot, flag):
    _define_magvar(fix)
    widget, renderer = _ai_with_svs(fix, qtbot)
    item = make_svs_item(renderer, widget)

    item.paint(mock.Mock(), None)
    assert renderer.draw.call_count == 1
    widget._update_land_brush()
    assert widget._land_brush_cur is widget.gblue_brush
    assert _amber_pixels(widget) == 0

    setattr(fix.db.get_item("MAGVAR"), flag, True)
    item.paint(mock.Mock(), None)
    assert renderer.draw.call_count == 1          # no terrain on a bad MAGVAR
    assert widget._land_brush_cur is widget.gbrown_brush
    assert _amber_pixels(widget) > 0              # SVS UNAVAIL

    setattr(fix.db.get_item("MAGVAR"), flag, False)
    item.paint(mock.Mock(), None)
    assert renderer.draw.call_count == 2
    assert _amber_pixels(widget) == 0


def test_old_magvar_keeps_terrain(fix, qtbot):
    """An old MAGVAR keeps its last value: no SVS UNAVAIL, terrain still drawn.
    An install with no MAGVAR writer has it old at 0.0 forever."""
    _define_magvar(fix)
    widget, renderer = _ai_with_svs(fix, qtbot)
    item = make_svs_item(renderer, widget)
    fix.db.get_item("MAGVAR").old = True
    item.paint(mock.Mock(), None)
    assert renderer.draw.call_count == 1
    assert _amber_pixels(widget) == 0


@pytest.mark.parametrize("flag", ["bad", "fail"])
def test_bad_or_failed_magvar_draws_the_fpm_amber(fix, qtbot, flag):
    _define_magvar(fix)
    w = _fpm_widget(fix, qtbot)
    assert _fpm_color(w) == GREEN
    setattr(fix.db.get_item("MAGVAR"), flag, True)
    assert _fpm_color(w) == AMBER


def test_magvar_reads_initial_flags(fix, qtbot):
    _define_magvar(fix)
    fix.db.get_item("MAGVAR").fail = True
    w = AI()
    qtbot.addWidget(w)
    assert w._magvar_valid() is False
