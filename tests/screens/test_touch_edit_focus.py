#  SPDX-License-Identifier: GPL-2.0-or-later
"""Touch-select + knob-edit focus (pyEfis #308, TK1).

Touching a value takes the same in-control state a knob push would: inner knob
= ``enc_changed`` (fine), outer ring = ``enc_outer_changed`` (coarse), push =
``enc_clicked``; the timeout, a press anywhere else and a screen change all
clear it, and only one value holds focus panel-wide.
"""

import time

import pytest
from PyQt6.QtCore import QPoint, QRectF, QTimer, Qt
from PyQt6.QtGui import QColor, QImage, QPainter
from PyQt6.QtWidgets import QWidget

from pyefis.instruments import edit_focus
from pyefis.instruments.gauges import numeric
from pyefis.screens.screenbuilder_encoder import EncoderController


@pytest.fixture(autouse=True)
def _clean_registry():
    edit_focus.set_at_rest_hint(False)
    yield
    owner = edit_focus.owner()
    if owner is not None:
        owner.release_focus()
    edit_focus.release(edit_focus.owner())
    edit_focus.set_at_rest_hint(False)


class _FakeScreen:
    """Just the attributes EncoderController reads."""

    def __init__(self, instruments=None, order=None, timeout=10_000):
        self.instruments = dict(instruments or {})
        self.encoder_list = [{"inst": i, "order": n}
                             for n, i in enumerate(order or [])]
        self.encoder_list_sorted = list(order or [])
        self.encoder_current_selection = 0 if order else None
        self.encoder_timeout = timeout
        self.encoder_timestamp = 0
        self.encoder_control = False
        self.encoder_timer = QTimer()
        self.encoder = None
        self.encoder_button = None
        self.visible = True
        self.encoder_controller = EncoderController(self)

    def isVisible(self):
        return self.visible

    def encoderChanged(self, value=0):
        self.encoder_controller.changed(value)


class _Value:
    """A settable value speaking the enc_* protocol; records every call."""

    touch_edit = True

    def __init__(self, select_ok=True, click_keeps=False):
        self.calls = []
        self.select_ok = select_ok
        self.click_keeps = click_keeps

    def isEnabled(self):
        return True

    def enc_selectable(self):
        return True

    def enc_highlight(self, onoff):
        self.calls.append(("highlight", onoff))

    def enc_select(self):
        self.calls.append(("select",))
        return self.select_ok

    def enc_changed(self, steps):
        self.calls.append(("fine", steps))
        return True

    def enc_outer_changed(self, steps):
        self.calls.append(("coarse", steps))
        return True

    def enc_clicked(self):
        self.calls.append(("push",))
        return self.click_keeps


def _touch(screen, inst):
    return screen.encoder_controller.touch_focus(inst)


def test_touch_focuses_without_encoder_order(qtbot):
    v = _Value()
    s = _FakeScreen({0: v})
    assert _touch(s, v) is True
    assert v.calls == [("highlight", True), ("select",)]
    assert s.encoder_control is True
    assert edit_focus.owner() is s.encoder_controller
    assert s.encoder_controller.focused_instrument() is v


def test_inner_is_fine_outer_is_coarse_push_runs_action_then_clears(qtbot):
    v = _Value()
    s = _FakeScreen({0: v})
    _touch(s, v)
    ctl = s.encoder_controller
    ctl.changed(3)
    ctl.outer_changed(-2)
    assert v.calls[-2:] == [("fine", 3), ("coarse", -2)]
    ctl.button_changed(True)
    assert v.calls[-2:] == [("push",), ("highlight", False)]
    assert s.encoder_control is False
    assert edit_focus.owner() is None
    assert ctl.focused_instrument() is None


def test_touch_lands_on_the_enrolled_instrument_in_the_knob_walk(qtbot):
    a, b = _Value(), _Value()
    s = _FakeScreen({0: a, 1: b}, order=[0, 1])
    _touch(s, b)
    assert s.encoder_current_selection == 1
    s.encoder_controller.changed(1)
    assert b.calls[-1] == ("fine", 1)
    assert ("fine", 1) not in a.calls


def test_timeout_clears_focus(qtbot):
    v = _Value()
    s = _FakeScreen({0: v}, timeout=50)
    s.encoder_controller._connect_timer()
    _touch(s, v)
    qtbot.waitUntil(lambda: s.encoder_control is False, timeout=2000)
    assert v.calls[-1] == ("highlight", False)
    assert edit_focus.owner() is None


def test_knob_activity_restarts_the_timeout(qtbot):
    v = _Value()
    s = _FakeScreen({0: v}, timeout=200)
    s.encoder_controller._connect_timer()
    _touch(s, v)
    for _ in range(4):              # 4 x 120 ms > one timeout, but never idle
        qtbot.wait(120)
        s.encoder_controller.changed(1)
    assert s.encoder_control is True


def test_only_one_focus_panel_wide_across_screens(qtbot):
    a, b = _Value(), _Value()
    sa, sb = _FakeScreen({0: a}), _FakeScreen({0: b})
    _touch(sa, a)
    _touch(sb, b)
    assert sa.encoder_control is False
    assert a.calls[-1] == ("highlight", False)
    assert sb.encoder_control is True
    assert edit_focus.owner() is sb.encoder_controller


def test_touching_another_value_on_the_same_screen_moves_focus(qtbot):
    a, b = _Value(), _Value()
    s = _FakeScreen({0: a, 1: b})
    _touch(s, a)
    _touch(s, b)
    assert a.calls[-1] == ("highlight", False)
    s.encoder_controller.changed(-1)
    assert b.calls[-1] == ("fine", -1)
    assert ("fine", -1) not in a.calls


def test_retouching_the_focused_value_keeps_focus(qtbot):
    v = _Value()
    s = _FakeScreen({0: v})
    _touch(s, v)
    _touch(s, v)
    assert v.calls == [("highlight", True), ("select",)]
    assert s.encoder_control is True


def test_select_refusal_leaves_no_focus(qtbot):
    v = _Value(select_ok=False)
    s = _FakeScreen({0: v})
    assert _touch(s, v) is False
    assert s.encoder_control is False
    assert edit_focus.owner() is None


def test_release_focus_is_what_a_screen_change_calls(qtbot):
    v = _Value()
    s = _FakeScreen({0: v})
    _touch(s, v)
    s.encoder_controller.release_focus()
    assert s.encoder_control is False
    assert v.calls[-1] == ("highlight", False)
    assert edit_focus.owner() is None


def test_hidden_screen_ignores_touch(qtbot):
    v = _Value()
    s = _FakeScreen({0: v})
    s.visible = False
    assert _touch(s, v) is False
    assert v.calls == []


def test_knob_path_entering_control_claims_the_panel_focus(qtbot):
    a, b = _Value(), _Value()
    sa = _FakeScreen({0: a})
    sb = _FakeScreen({0: b}, order=[0])
    _touch(sa, a)
    # knob walk on screen b: highlight, then push to select
    sb.encoder_controller.changed(1)
    sb.encoder_controller.button_changed(True)
    assert sb.encoder_control is True
    assert sa.encoder_control is False
    assert edit_focus.owner() is sb.encoder_controller


# --- with real widgets: touch-away and screen change ------------------------

class _Host(QWidget):
    """Stands in for a Screen: the gauge finds encoder_controller by walking up
    its parents, exactly as on a real screen."""

    def __init__(self):
        super().__init__()
        self.instruments = {}
        self.encoder_list = []
        self.encoder_list_sorted = []
        self.encoder_current_selection = None
        self.encoder_timeout = 10_000
        self.encoder_timestamp = 0
        self.encoder_control = False
        self.encoder_timer = QTimer(self)
        self.encoder = None
        self.encoder_button = None
        self.encoder_controller = EncoderController(self)

    def encoderChanged(self, value=0):
        self.encoder_controller.changed(value)

    def hideEvent(self, event):
        # Same body as Screen.hideEvent.
        self.encoder_controller.release_focus()
        super().hideEvent(event)


def _gauge(fix, host, key="NUMOK", x=0):
    g = numeric.NumericDisplay(host)
    g.setDbkey(key)
    g.decimal_places = 2
    g.encoder_multiplier = 0.01
    g.encoder_set_real_time = True
    g.touch_edit = True
    g.setupGauge()
    g.setGeometry(x, 0, 160, 60)
    host.instruments[len(host.instruments)] = g
    return g


def _show(qtbot, host):
    qtbot.addWidget(host)
    host.resize(400, 200)
    host.show()
    qtbot.waitExposed(host)


def test_value_text_does_not_jump_when_an_edit_starts(fix, qtbot):
    host = _Host()
    g = _gauge(fix, host)
    g.font_mask = "XXXXXX"
    _show(qtbot, host)
    at_rest = g.valueText
    qtbot.mouseClick(g, Qt.MouseButton.LeftButton, pos=QPoint(80, 30))
    assert g.encoder_selected is True
    assert g.valueText == at_rest
    assert len(g.valueText) == len("XXXXXX")


def test_gauge_touch_fine_coarse_and_push(fix, qtbot):
    host = _Host()
    g = _gauge(fix, host)
    _show(qtbot, host)
    qtbot.mouseClick(g, Qt.MouseButton.LeftButton, pos=QPoint(80, 30))
    assert g.encoder_selected is True
    assert host.encoder_controller.focused_instrument() is g
    start = g.encoder_set_value
    host.encoder_controller.changed(2)            # inner: 2 x 0.01
    assert g.encoder_set_value == pytest.approx(start + 0.02)
    host.encoder_controller.outer_changed(1)      # outer: 1 x 0.01 x 10
    assert g.encoder_set_value == pytest.approx(start + 0.12)
    host.encoder_controller.button_changed(True)  # push: accept
    assert g.encoder_selected is False
    assert fix.db.get_item("NUMOK").value == pytest.approx(start + 0.12)
    assert edit_focus.owner() is None


def test_press_elsewhere_clears_focus(fix, qtbot):
    host = _Host()
    g = _gauge(fix, host)
    other = QWidget(host)
    other.setGeometry(200, 100, 100, 60)
    _show(qtbot, host)
    qtbot.mouseClick(g, Qt.MouseButton.LeftButton, pos=QPoint(80, 30))
    assert host.encoder_control is True
    qtbot.mouseClick(other, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
    assert host.encoder_control is False
    assert g.encoder_selected is False
    assert edit_focus.owner() is None


def test_press_on_another_touch_value_moves_focus_to_it(fix, qtbot):
    host = _Host()
    a = _gauge(fix, host, "NUMOK", x=0)
    b = _gauge(fix, host, "NUMOLD", x=200)
    _show(qtbot, host)
    qtbot.mouseClick(a, Qt.MouseButton.LeftButton, pos=QPoint(80, 30))
    qtbot.mouseClick(b, Qt.MouseButton.LeftButton, pos=QPoint(80, 30))
    assert a.encoder_selected is False
    assert b.encoder_selected is True
    assert host.encoder_controller.focused_instrument() is b


def test_hiding_the_screen_clears_focus(fix, qtbot):
    host = _Host()
    g = _gauge(fix, host)
    _show(qtbot, host)
    qtbot.mouseClick(g, Qt.MouseButton.LeftButton, pos=QPoint(80, 30))
    host.hide()
    assert g.encoder_selected is False
    assert edit_focus.owner() is None


def test_real_screen_hide_event_releases_focus(qtbot):
    from pyefis.screens.screenbuilder import Screen
    parent = QWidget()
    qtbot.addWidget(parent)
    s = Screen(parent)
    s.init = True            # no config behind this parent; skip init_screen
    v = _Value()
    s.instruments = {0: v}
    parent.show()
    qtbot.waitExposed(parent)
    assert s.isVisible()
    s.encoder_controller.touch_focus(v)
    assert s.encoder_control is True
    s.hide()
    assert s.encoder_control is False
    assert v.calls[-1] == ("highlight", False)


# --- the mouse as the knob (pyEfis #321) ------------------------------------

class _WidgetValue(QWidget):
    """A _Value that is also a widget, so focus_hit() can test the pointer
    against it. Records wheel events that reach it (i.e. passed through)."""

    touch_edit = True

    def __init__(self, parent, click_keeps=False):
        super().__init__(parent)
        self.calls = []
        self.wheels_seen = 0
        self.click_keeps = click_keeps

    enc_selectable = _Value.enc_selectable
    enc_highlight = _Value.enc_highlight
    enc_changed = _Value.enc_changed
    enc_outer_changed = _Value.enc_outer_changed
    enc_clicked = _Value.enc_clicked

    def enc_select(self):
        self.calls.append(("select",))
        return True

    def wheelEvent(self, event):
        self.wheels_seen += 1
        event.accept()


def _wheel_host(qtbot, click_keeps=False):
    """A screen with NO encoder keys (the Pi-with-a-mouse case): a value at
    the left, and a bystander (stands in for the map) at the right."""
    host = _Host()
    v = _WidgetValue(host, click_keeps=click_keeps)
    v.setGeometry(0, 0, 160, 60)
    other = _WidgetValue(host)
    other.setGeometry(200, 100, 100, 60)
    host.instruments = {0: v, 1: other}
    _show(qtbot, host)
    return host, v, other


def _wheel(widget, dy=0, dx=0, shift=False, inverted=False):
    from PyQt6.QtCore import QPointF
    from PyQt6.QtGui import QWheelEvent
    from PyQt6.QtWidgets import QApplication
    local = QPointF(10, 10)
    mods = (Qt.KeyboardModifier.ShiftModifier if shift
            else Qt.KeyboardModifier.NoModifier)
    ev = QWheelEvent(local, QPointF(widget.mapToGlobal(local)),
                     QPoint(0, 0), QPoint(dx, dy), Qt.MouseButton.NoButton,
                     mods, Qt.ScrollPhase.NoScrollPhase, inverted)
    QApplication.sendEvent(widget, ev)


def _steps(v):
    return [c for c in v.calls if c[0] in ("fine", "coarse")]


def test_wheel_notch_is_one_inner_step_up_increases(qtbot):
    host, v, _ = _wheel_host(qtbot)
    host.encoder_controller.touch_focus(v)
    _wheel(v, dy=120)
    _wheel(v, dy=-120)
    _wheel(v, dy=240)
    assert _steps(v) == [("fine", 1), ("fine", -1), ("fine", 2)]
    assert v.wheels_seen == 0          # consumed: the value never sees it


def test_hi_res_wheel_accumulates_to_one_step_per_notch(qtbot):
    host, v, _ = _wheel_host(qtbot)
    host.encoder_controller.touch_focus(v)
    for _ in range(3):
        _wheel(v, dy=30)
    assert _steps(v) == []
    _wheel(v, dy=30)
    assert _steps(v) == [("fine", 1)]


def test_reversing_drops_the_part_notch(qtbot):
    host, v, _ = _wheel_host(qtbot)
    host.encoder_controller.touch_focus(v)
    _wheel(v, dy=60)
    _wheel(v, dy=-120)
    assert _steps(v) == [("fine", -1)]


def test_shift_wheel_and_horizontal_wheel_are_the_outer_ring(qtbot):
    host, v, _ = _wheel_host(qtbot)
    host.encoder_controller.touch_focus(v)
    _wheel(v, dy=120, shift=True)
    _wheel(v, dx=-120, shift=True)     # Shift reported on the x axis
    _wheel(v, dx=120)                  # tilt wheel
    assert _steps(v) == [("coarse", 1), ("coarse", -1), ("coarse", 1)]


def test_natural_scrolling_steps_by_the_physical_wheel(qtbot):
    host, v, _ = _wheel_host(qtbot)
    host.encoder_controller.touch_focus(v)
    _wheel(v, dy=-120, inverted=True)
    assert _steps(v) == [("fine", 1)]


def test_wheel_over_another_widget_passes_through(qtbot):
    host, v, other = _wheel_host(qtbot)
    host.encoder_controller.touch_focus(v)
    _wheel(other, dy=120)
    assert _steps(v) == []
    assert other.wheels_seen == 1      # the map would have zoomed
    assert host.encoder_control is True


def test_real_map_still_zooms_while_a_value_is_focused(fix, qtbot):
    from pyefis.instruments import map as moving_map
    host, v, _ = _wheel_host(qtbot)
    m = moving_map.MovingMap(host)
    m.range_ladder = "2,5,10,20,40,80,160"
    m.setGeometry(200, 0, 180, 90)
    m.show()
    m.range_nm = 10.0
    host.encoder_controller.touch_focus(v)
    _wheel(m, dy=120)                  # wheel up over the map: zoom in
    assert m.range_nm < 10.0
    _wheel(m, dy=-240)                 # and back out past where it was
    assert m.range_nm > 10.0
    assert _steps(v) == []
    assert host.encoder_control is True


def test_wheel_without_focus_does_nothing(qtbot):
    host, v, _ = _wheel_host(qtbot)
    _wheel(v, dy=120)
    assert v.calls == []
    assert v.wheels_seen == 1          # reaches the widget, as before #321
    assert host.encoder_control is False


def test_wheel_through_the_window_steps_once(qtbot):
    # A real wheel arrives at the window before the widget, and the filter
    # sees every hop; one notch must still be exactly one step.
    from PyQt6.QtCore import QPointF
    from PyQt6.QtGui import QWheelEvent
    from PyQt6.QtWidgets import QApplication
    host, v, _ = _wheel_host(qtbot)
    host.encoder_controller.touch_focus(v)
    pos = QPointF(20, 20)
    ev = QWheelEvent(pos, QPointF(host.mapToGlobal(pos)), QPoint(0, 0),
                     QPoint(0, 120), Qt.MouseButton.NoButton,
                     Qt.KeyboardModifier.NoModifier,
                     Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(host.windowHandle(), ev)
    assert _steps(v) == [("fine", 1)]


def test_wheel_step_restarts_the_timeout(qtbot):
    host, v, _ = _wheel_host(qtbot)
    host.encoder_timeout = 200
    host.encoder_controller.touch_focus(v)
    for _ in range(4):                 # 4 x 120 ms > one timeout
        qtbot.wait(120)
        _wheel(v, dy=120)
    assert host.encoder_control is True


def test_middle_click_on_the_value_is_the_push(qtbot):
    host, v, _ = _wheel_host(qtbot)
    host.encoder_controller.touch_focus(v)
    qtbot.mouseClick(v, Qt.MouseButton.MiddleButton, pos=QPoint(80, 30))
    assert ("push",) in v.calls
    assert host.encoder_control is False
    assert edit_focus.owner() is None


def test_middle_click_elsewhere_just_clears_focus(qtbot):
    host, v, other = _wheel_host(qtbot)
    host.encoder_controller.touch_focus(v)
    qtbot.mouseClick(other, Qt.MouseButton.MiddleButton, pos=QPoint(10, 10))
    assert ("push",) not in v.calls
    assert host.encoder_control is False


def test_wheel_edits_a_real_gauge(fix, qtbot):
    host = _Host()
    g = _gauge(fix, host)
    _show(qtbot, host)
    qtbot.mouseClick(g, Qt.MouseButton.LeftButton, pos=QPoint(80, 30))
    start = g.encoder_set_value
    _wheel(g, dy=240)                  # inner: 2 x 0.01
    assert g.encoder_set_value == pytest.approx(start + 0.02)
    _wheel(g, dy=120, shift=True)      # outer: 1 x 0.01 x 10
    assert g.encoder_set_value == pytest.approx(start + 0.12)
    qtbot.mouseClick(g, Qt.MouseButton.MiddleButton, pos=QPoint(80, 30))
    assert g.encoder_selected is False
    assert fix.db.get_item("NUMOK").value == pytest.approx(start + 0.12)


# --- the shared visual language --------------------------------------------

def test_icon_is_at_most_10px_square():
    for h in (12, 30, 60, 200):
        r = edit_focus.icon_rect(QRectF(0, 0, 4 * h, h))
        assert r.width() <= 10 and r.height() <= 10
        assert r.width() == r.height()


def test_marks_fit_inside_the_rect_they_were_inset_for():
    outer = QRectF(0, 0, 160, 60)
    value = edit_focus.inset_for_marks(outer)
    ring = edit_focus.ring_rect(value).adjusted(
        -edit_focus.RING_WIDTH_PX / 2, -edit_focus.RING_WIDTH_PX / 2,
        edit_focus.RING_WIDTH_PX / 2, edit_focus.RING_WIDTH_PX / 2)
    assert outer.contains(ring)
    assert outer.contains(edit_focus.icon_rect(value, bounds=outer))
    # Without bounds the icon badges the ring corner and pokes outside it.
    assert not outer.contains(edit_focus.icon_rect(value))


def _render(focused, hint):
    edit_focus.set_at_rest_hint(hint)
    img = QImage(160, 60, QImage.Format.Format_ARGB32)
    img.fill(QColor(0, 0, 0))
    p = QPainter(img)
    edit_focus.draw_edit_marks(
        p, edit_focus.inset_for_marks(QRectF(0, 0, 160, 60)), focused,
        bounds=QRectF(0, 0, 160, 60))
    p.end()
    return img


def _cyanish(img):
    n = 0
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            if c.green() > 60 and c.blue() > 60 and c.red() < 40:
                n += 1
    return n


def test_focused_draws_ring_and_icon_unfocused_draws_nothing():
    assert _cyanish(_render(True, False)) > 300   # the ring alone is ~400 px
    assert _cyanish(_render(False, False)) == 0


def test_at_rest_hint_is_on_unless_the_panel_turns_it_off():
    assert edit_focus.at_rest_hint_from_config({}) is True
    assert edit_focus.at_rest_hint_from_config(None) is True
    assert edit_focus.at_rest_hint_from_config({"editIconAtRest": False}) is False
    assert edit_focus.at_rest_hint_from_config({"editIconAtRest": True}) is True


def test_at_rest_hint_draws_only_a_small_dim_icon():
    img = _render(False, True)
    n = _cyanish(img)
    assert 0 < n <= 100
    brightest = max(img.pixelColor(x, y).blue()
                    for y in range(img.height()) for x in range(img.width()))
    assert brightest < 200       # dimmed, not full-strength cyan
