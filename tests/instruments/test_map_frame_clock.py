"""MP3: gesture repaints through the frame clock (`gesture_frame_rate`)
(briefs/map_gesture_perf_plan.md section 4, pyEfis #98).

zoom_by/pan_by/rotate_by no longer call update() per event; they mark a
frame dirty and the existing frame clock (_frame_tick, #89) is what
actually repaints, at most once per clock tick. The clock itself runs at
gesture_frame_rate (default 30, clamped 10-60) while a gesture is live,
and at the normal frame_rate the rest of the time."""
from PyQt6.QtCore import QEvent, Qt

from pyefis.instruments import map as moving_map


class _FakeGesture:
    def __init__(self, state):
        self._state = state

    def state(self):
        return self._state

    def changeFlags(self):
        from PyQt6.QtWidgets import QPinchGesture
        return QPinchGesture.ChangeFlag(0)


class _FakeGestureEvent:
    def __init__(self, g):
        self._g = g

    def type(self):
        return QEvent.Type.Gesture

    def gesture(self, which):
        return self._g


def _start_gesture(w):
    w.event(_FakeGestureEvent(_FakeGesture(Qt.GestureState.GestureStarted)))


def _finish_gesture(w):
    w.event(_FakeGestureEvent(_FakeGesture(Qt.GestureState.GestureFinished)))


# --- gesture_frame_rate option ---------------------------------------------

def test_gesture_frame_rate_default_and_clamp(fix, qtbot):
    w = moving_map.MovingMap()
    qtbot.addWidget(w)
    assert w.gesture_frame_rate == 30.0
    w.gesture_frame_rate = 5
    assert w.gesture_frame_rate == 10.0
    w.gesture_frame_rate = 1000
    assert w.gesture_frame_rate == 60.0
    w.gesture_frame_rate = 45
    assert w.gesture_frame_rate == 45.0


def test_gesture_frame_rate_in_schema():
    """Registered in schema.json (lockstep with the configurator twin),
    mirroring gesture_timeout's own schema test."""
    from pyefis.editor import schema as sch
    opts = sch.build_schema()["instruments"]["moving_map"]["options"]
    assert "gesture_frame_rate" in opts
    assert opts["gesture_frame_rate"]["default"] == 30


def test_frame_timer_speeds_up_during_gesture_and_restores(fix, qtbot):
    w = moving_map.MovingMap()
    qtbot.addWidget(w)
    assert w._frame_timer.interval() == 100     # 1000 / frame_rate(10)
    _start_gesture(w)
    assert w._frame_timer.interval() == 33      # round(1000 / 30)
    _finish_gesture(w)
    assert w._frame_timer.interval() == 100


def test_mouse_drag_also_speeds_up_frame_clock(fix, qtbot):
    class _Press:
        def button(self):
            return Qt.MouseButton.LeftButton

        def position(self):
            from PyQt6.QtCore import QPointF
            return QPointF(10, 10)

        def accept(self):
            pass

    class _Release(_Press):
        pass

    w = moving_map.MovingMap()
    qtbot.addWidget(w)
    w.mousePressEvent(_Press())
    assert w._frame_timer.interval() == 33
    w.mouseReleaseEvent(_Release())
    assert w._frame_timer.interval() == 100


# --- zoom_by/pan_by/rotate_by mark dirty, do not repaint per call ----------

def test_rotate_by_marks_dirty_without_calling_update(fix, qtbot):
    w = moving_map.MovingMap()
    qtbot.addWidget(w)
    calls = []
    w.update = lambda: calls.append(1)
    w.rotate_by(10.0)
    assert calls == []
    assert w._frame_dirty is True


def test_zoom_by_marks_dirty_without_calling_update(fix, qtbot):
    w = moving_map.MovingMap()
    qtbot.addWidget(w)
    w.range_ladder = "2,5,10,20,40,80,160"
    w.range_nm = 10.0
    calls = []
    w.update = lambda: calls.append(1)
    w.zoom_by(1.25)
    assert calls == []
    assert w._frame_dirty is True


def test_pan_by_marks_dirty_without_calling_update(fix, qtbot):
    w = moving_map.MovingMap()
    qtbot.addWidget(w)
    calls = []
    w.update = lambda: calls.append(1)
    w.pan_by(10.0, 0.0)
    assert calls == []
    assert w._frame_dirty is True


# --- HMI actions stay immediate ---------------------------------------------

def test_hmi_actions_still_paint_immediately(fix, qtbot):
    """DoD: range/orientation HMI actions still paint immediately -- they
    must not be routed through the dirty-flag/frame-clock path."""
    w = moving_map.MovingMap()
    qtbot.addWidget(w)
    w.range_ladder = "2,5,10,20,40,80,160"
    w.range_nm = 10.0
    calls = []
    w.update = lambda: calls.append(1)
    w.range_up()
    assert calls == [1]
    w.range_down()
    assert calls == [1, 1]
    w.toggle_orientation()
    assert calls == [1, 1, 1]


# --- DoD: paint counts -------------------------------------------------------

def test_lone_rotate_by_outside_gesture_paints_within_one_tick(fix, qtbot):
    """DoD: a lone rotate_by outside a gesture paints within one tick."""
    w = moving_map.MovingMap()
    qtbot.addWidget(w)
    w.resize(300, 300)
    paints = []
    w.update = lambda: paints.append(1)
    w.rotate_by(5.0)
    assert paints == []                      # not synchronous
    qtbot.waitUntil(lambda: len(paints) >= 1, timeout=500)
    assert len(paints) == 1


def test_rotate_by_burst_in_gesture_paints_at_most_4_in_100ms(fix, qtbot):
    """DoD: 200 rotate_by calls in 100 ms -> <= 4 paints. At the default
    gesture_frame_rate (30 Hz, ~33 ms/tick) a 100 ms window admits at
    most 4 ticks, and _frame_tick paints at most once per tick regardless
    of how many dirty-marking calls landed since the last one."""
    w = moving_map.MovingMap()
    qtbot.addWidget(w)
    w.resize(300, 300)
    assert w.gesture_frame_rate == 30.0
    paints = []
    w.update = lambda: paints.append(1)
    _start_gesture(w)
    for _ in range(200):
        w.rotate_by(0.05)
    qtbot.wait(100)
    assert 1 <= len(paints) <= 4
