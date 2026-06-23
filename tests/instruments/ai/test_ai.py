from unittest import mock

import pytest
from PyQt6.QtCore import QPointF
from PyQt6.QtGui import QPaintEvent
from PyQt6.QtWidgets import QApplication, QGraphicsScene, QGraphicsView

from pyefis.instruments import ai


@pytest.fixture
def app(qtbot):
    test_app = QApplication.instance()
    if test_app is None:
        test_app = QApplication([])
    return test_app


def _reset_ai_items(fix, old=False, bad=False, fail=False):
    for key in ["PITCH", "ROLL", "ALAT", "TAS"]:
        item = fix.db.get_item(key)
        item.old = old
        item.bad = bad
        item.fail = fail


def _show_ai(qtbot, widget, width=240, height=220):
    qtbot.addWidget(widget)
    widget.resize(width, height)
    widget.show()
    qtbot.waitExposed(widget)
    return QPaintEvent(widget.viewport().rect())


def test_ai_resize_paint_and_input_events(fix, qtbot):
    _reset_ai_items(fix)
    widget = ai.AI(font_percent=0.2)
    event = _show_ai(qtbot, widget)

    assert widget.fontSize == 48
    assert widget.bankAngleRadius == pytest.approx(220 / 3)
    assert widget.getPitchAngle() == 0
    assert widget.getRollAngle() == 0
    assert widget.getAIOld() is False
    assert widget.getAIBad() is False
    assert widget.getAIFail() is False

    widget.paintEvent(event)

    widget.drawBankMarkers = False
    widget.paintEvent(event)

    widget.keyPressEvent(None)
    widget.wheelEvent(None)
    widget.showEvent(None)


def test_ai_resize_with_gray_quality_and_custom_bank_radius(fix, qtbot):
    _reset_ai_items(fix, old=True, bad=True)
    widget = ai.AI()
    widget.bankAngleRadius = 42
    _show_ai(qtbot, widget)

    assert widget.bankAngleRadius == 42
    assert widget.getAIOld() is True
    assert widget.getAIBad() is True


def test_ai_resize_can_skip_unmatched_minor_ticks(fix, qtbot):
    _reset_ai_items(fix)
    widget = ai.AI()
    widget.minorDiv = 7
    _show_ai(qtbot, widget)

    assert widget.pitchItems


def test_ai_setters_bound_values_and_skip_unchanged_or_failed(fix, qtbot):
    _reset_ai_items(fix)
    widget = ai.AI()
    _show_ai(qtbot, widget)
    widget.redraw = mock.Mock()
    widget.update = mock.Mock()

    # P4 frame clock: setters STORE state and mark the frame dirty;
    # the repaint happens on the next frame tick, not in the slot.
    widget._frame_dirty = False
    widget.rollAngle = 999
    assert widget.rollAngle == 180
    assert widget._frame_dirty is True
    widget.redraw.assert_not_called()

    widget._frame_dirty = False
    widget.rollAngle = 180          # unchanged -> not dirtied
    assert widget._frame_dirty is False

    widget.setLateralAcceleration(9)
    assert widget._latAccel == 0.3
    assert widget._frame_dirty is True

    widget._frame_dirty = False
    widget.setLateralAcceleration(0.3)
    assert widget._frame_dirty is False

    widget.setTrueAirspeed(400)
    assert widget._tas == 400
    assert widget._frame_dirty is True

    widget._frame_dirty = False
    widget.setTrueAirspeed(400)
    assert widget._frame_dirty is False

    widget.pitchAngle = -999
    assert widget.pitchAngle == -90
    assert widget._frame_dirty is True

    widget._frame_dirty = False
    widget.pitchAngle = -90
    assert widget._frame_dirty is False

    # The frame tick applies pending changes exactly once...
    widget._frame_dirty = True
    widget._frame_tick()
    widget.redraw.assert_called_once_with()
    widget.update.assert_called_once_with()
    # ...and a clean tick with nothing changed repaints nothing.
    widget._frame_tick()
    assert widget.redraw.call_count == 1

    widget.setAIFailRoll(True)
    widget.setRollAngle(0)
    widget.setPitchAngle(0)
    assert widget.rollAngle == 180
    assert widget.pitchAngle == -90


def test_ai_hidden_setters_update_without_redraw_or_repaint(fix, qtbot):
    _reset_ai_items(fix)
    widget = ai.AI()
    qtbot.addWidget(widget)
    widget.resize(240, 220)
    widget.redraw = mock.Mock()
    widget.update = mock.Mock()

    widget.setRollAngle(15)
    widget.setPitchAngle(12)
    widget.setLateralAcceleration(-9)
    widget.setTrueAirspeed(120)

    assert widget.rollAngle == 15
    assert widget.pitchAngle == 12
    assert widget._latAccel == -0.3
    assert widget._tas == 120
    widget.redraw.assert_not_called()
    widget.update.assert_not_called()


def test_ai_quality_flag_helpers_before_and_after_resize(fix, qtbot):
    _reset_ai_items(fix)
    widget = ai.AI()

    widget.setFail(True, "ROLL")
    widget.setFail(True, "ROLL")
    assert widget.getAIFail() is True

    widget.setOld(True, "PITCH")
    widget.setOld(True, "PITCH")
    assert widget.getAIOld() is True

    widget.setBad(True, "ALAT")
    widget.setBad(True, "ALAT")
    assert widget.getAIBad() is True

    _show_ai(qtbot, widget)
    widget.redraw = mock.Mock()

    widget.setAIFailRoll(False)
    assert QGraphicsView.scene(widget) == widget.scene

    widget.setAIFailPitch(True)
    assert QGraphicsView.scene(widget) == widget.fail_scene
    widget.setAIFailLAcc(True)
    widget.setAIFailTAS(True)
    assert widget.getAIFail() is True

    widget.setAIFailPitch(False)
    widget.setAIFailLAcc(False)
    widget.setAIFailTAS(False)
    assert widget.getAIFail() is False
    assert QGraphicsView.scene(widget) == widget.scene
    assert widget.redraw.called

    widget.setAIOldRoll(True)
    widget.setAIOldPitch(False)
    widget.setAIOldLAcc(False)
    widget.setAIOldTAS(False)
    assert widget.getAIOld() is True

    widget.setAIOldRoll(False)
    assert widget.getAIOld() is False

    widget.setAIBadRoll(True)
    widget.setAIBadPitch(False)
    widget.setAIBadLAcc(False)
    widget.setAIBadTAS(False)
    assert widget.getAIBad() is True

    widget.setAIBadRoll(False)
    assert widget.getAIBad() is False


def test_ai_failure_recovery_keeps_gray_when_old_or_bad_remain(fix, qtbot):
    _reset_ai_items(fix, old=True)
    widget = ai.AI()
    _show_ai(qtbot, widget)

    widget.setAIFailRoll(True)
    widget.setAIFailRoll(False)
    assert QGraphicsView.scene(widget) == widget.scene


def test_ai_failure_recovery_restores_color_when_quality_is_good(fix, qtbot):
    _reset_ai_items(fix)
    widget = ai.AI()
    _show_ai(qtbot, widget)

    widget.setAIFailRoll(True)
    widget.setAIFailRoll(False)

    assert QGraphicsView.scene(widget) == widget.scene


def test_ai_failure_recovery_before_sky_rect_exists(fix):
    _reset_ai_items(fix)
    widget = ai.AI()
    widget.fail_scene = QGraphicsScene()
    widget.scene = QGraphicsScene()
    widget.redraw = mock.Mock()

    widget.setAIFailRoll(True)
    widget.setAIFailRoll(False)

    assert QGraphicsView.scene(widget) == widget.scene
    widget.redraw.assert_called_once_with()


def test_ai_paint_caps_standard_rate_bank_marker_angle(fix, qtbot):
    _reset_ai_items(fix)
    widget = ai.AI()
    event = _show_ai(qtbot, widget)

    widget.setTrueAirspeed(10000)
    widget.paintEvent(event)

    assert widget._tas == 10000


def test_fd_target_resize_and_update(qtbot):
    center = QPointF(100, 120)
    widget = ai.FDTarget(center, pixelsPerDeg=5)
    qtbot.addWidget(widget)
    widget.resize(80, 40)
    widget.show()
    qtbot.waitExposed(widget)

    assert widget.w == 80
    assert widget.h == 40
    assert center.x() == 60
    assert center.y() == 100

    widget.update(3, 30)

    assert widget.x() == 60
    assert widget.y() == 85
    assert widget.poly.polygon().count() == 4


# --- Flight Path Marker low-speed gating (issue #70) -------------------------

def _fpm_inputs_ok(widget):
    for k in ('VS', 'GS', 'TRACK', 'HEAD'):
        widget._fpm_fail[k] = False


def test_fpm_hidden_below_min_groundspeed(fix, qtbot):
    """Stationary/taxiing, the GPS track is noise so the FPM darts around --
    hide it until groundspeed gives a real solution."""
    widget = ai.AI()
    _fpm_inputs_ok(widget)
    widget._fpm_gs = 0.0
    assert widget._fpm_solution_valid() is False          # idle on the runway
    widget._fpm_gs = widget._FPM_MIN_GS_KT - 0.5
    assert widget._fpm_solution_valid() is False          # slow taxi
    widget._fpm_gs = widget._FPM_MIN_GS_KT + 5.0
    assert widget._fpm_solution_valid() is True           # moving -> solution


def test_fpm_hidden_when_required_input_failed(fix, qtbot):
    """A failed GPS input (e.g. no TRACK) also has no solution, regardless of
    speed."""
    widget = ai.AI()
    _fpm_inputs_ok(widget)
    widget._fpm_gs = 120.0
    assert widget._fpm_solution_valid() is True
    widget._fpm_fail['TRACK'] = True
    assert widget._fpm_solution_valid() is False


def test_fpm_solution_independent_of_optional_vpath(fix, qtbot):
    """VPATH is optional (real GPS won't publish it) -- it must not gate the
    FPM."""
    widget = ai.AI()
    _fpm_inputs_ok(widget)
    widget._fpm_gs = 120.0
    widget._fpm_fail['VPATH'] = True
    assert widget._fpm_solution_valid() is True
