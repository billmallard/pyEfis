"""MP1: gesture-phase gating + settle debounce + geometric range-bucket
render keys (briefs/map_gesture_perf_plan.md section 4, pyEfis #98)."""
from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QImage, QPaintEvent, QPainter, QWheelEvent
from PyQt6.QtWidgets import QPinchGesture

from pyefis.instruments import map as moving_map
from pyefis.instruments.map.layers import range_bucket
from pyefis.instruments.map.layers.terrain import TerrainLayer


# --- geometric range bucket -----------------------------------------------

def test_range_bucket_stable_within_5pct_differs_across_15pct():
    """DoD: keys equal across a +-5% range change, differ across 15%.
    12.1 NM sits mid-bucket (verified against the 1.12 ratio) so a +-5%
    change stays inside it while +-15% (more than one 12% bucket) does
    not -- a range picked near a bucket edge would not hold either
    direction, which is a property of geometric bucketing, not a bug."""
    base = 12.1
    assert range_bucket(base) == range_bucket(base * 1.05)
    assert range_bucket(base) == range_bucket(base * 0.95)
    assert range_bucket(base) != range_bucket(base * 1.15)
    assert range_bucket(base) != range_bucket(base * 0.85)


def test_range_bucket_monotonic_across_the_ladder():
    vals = [2.0, 5.0, 10.0, 20.0, 40.0, 80.0, 160.0]
    buckets = [range_bucket(v) for v in vals]
    assert buckets == sorted(buckets)
    assert len(set(buckets)) == len(buckets)


def test_range_bucket_deterministic():
    assert range_bucket(37.5) == range_bucket(37.5)


# --- fakes for the gesture-state / touch-math event() path -----------------

class _FakeGesture:
    def __init__(self, state):
        self._state = state

    def state(self):
        return self._state

    def changeFlags(self):
        return QPinchGesture.ChangeFlag(0)


class _NoStatePinch:
    """Stand-in with no .state() -- the shape of the pre-MP1 fake used by
    the two-finger-rotate test; must still work without engaging gating."""

    def changeFlags(self):
        return QPinchGesture.ChangeFlag.RotationAngleChanged

    def rotationAngle(self):
        return 20.0

    def lastRotationAngle(self):
        return 0.0


class _FakeGestureEvent:
    def __init__(self, g):
        self._g = g

    def type(self):
        return QEvent.Type.Gesture

    def gesture(self, which):
        return self._g


# --- widget: gesture-phase gating + settle debounce ------------------------

def test_gesture_started_updated_sets_active(fix, qtbot):
    w = moving_map.MovingMap()
    qtbot.addWidget(w)
    GS = Qt.GestureState
    assert not w.defer_render
    w.event(_FakeGestureEvent(_FakeGesture(GS.GestureStarted)))
    assert w._gesture_active and w.defer_render
    w.event(_FakeGestureEvent(_FakeGesture(GS.GestureUpdated)))
    assert w._gesture_active and w.defer_render


def test_gesture_finished_clears_active_but_holds_defer_via_settle(fix, qtbot):
    w = moving_map.MovingMap()
    qtbot.addWidget(w)
    GS = Qt.GestureState
    w.event(_FakeGestureEvent(_FakeGesture(GS.GestureStarted)))
    w.event(_FakeGestureEvent(_FakeGesture(GS.GestureFinished)))
    assert not w._gesture_active
    assert w._settle_timer.isActive()
    assert w.defer_render                  # settle timer still covers it


def test_gesture_canceled_also_arms_settle(fix, qtbot):
    w = moving_map.MovingMap()
    qtbot.addWidget(w)
    GS = Qt.GestureState
    w.event(_FakeGestureEvent(_FakeGesture(GS.GestureStarted)))
    w.event(_FakeGestureEvent(_FakeGesture(GS.GestureCanceled)))
    assert not w._gesture_active
    assert w._settle_timer.isActive()


def test_settle_timer_expiry_clears_defer_render(fix, qtbot):
    w = moving_map.MovingMap()
    qtbot.addWidget(w)
    GS = Qt.GestureState
    w.event(_FakeGestureEvent(_FakeGesture(GS.GestureStarted)))
    w.event(_FakeGestureEvent(_FakeGesture(GS.GestureFinished)))
    assert w.defer_render
    qtbot.waitUntil(lambda: not w._settle_timer.isActive(), timeout=1000)
    assert not w.defer_render


def test_fake_gesture_without_state_stays_phaseless(fix, qtbot):
    """A gesture stand-in with no .state() (matches the pre-MP1 rotate
    test's fake) must not raise and must not engage the gating."""
    w = moving_map.MovingMap()
    qtbot.addWidget(w)
    w.event(_FakeGestureEvent(_NoStatePinch()))
    assert not w._gesture_active
    assert not w.defer_render


def test_mouse_drag_brackets_gesture_active(fix, qtbot):
    class _Press:
        def button(self):
            return Qt.MouseButton.LeftButton

        def position(self):
            return QPointF(10, 10)

        def accept(self):
            pass

    class _Release:
        def position(self):
            return QPointF(10, 10)

        def accept(self):
            pass

    w = moving_map.MovingMap()
    qtbot.addWidget(w)
    w.mousePressEvent(_Press())
    assert w._gesture_active and w.defer_render
    w.mouseReleaseEvent(_Release())
    assert not w._gesture_active
    assert w._settle_timer.isActive()


def _wheel(w, dy):
    ev = QWheelEvent(
        QPointF(10, 10), QPointF(10, 10), QPoint(0, 0), QPoint(0, dy),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase, False)
    w.wheelEvent(ev)


def test_wheel_notch_restarts_settle_timer(fix, qtbot):
    w = moving_map.MovingMap()
    qtbot.addWidget(w)
    _wheel(w, 120)
    assert w._settle_timer.isActive()
    assert w.defer_render


def test_range_up_down_stay_immediate(fix, qtbot):
    """HMI range_up/down are discrete steps and must not engage the
    gesture/settle gating at all."""
    w = moving_map.MovingMap()
    qtbot.addWidget(w)
    w.range_ladder = "2,5,10,20,40,80,160"
    w.range_nm = 10.0
    w.range_up()
    assert w.range_nm == 20.0
    assert not w._gesture_active and not w._settle_timer.isActive()
    w.range_down()
    assert w.range_nm == 10.0
    assert not w._gesture_active and not w._settle_timer.isActive()


def test_transform_carries_defer_render(fix, qtbot):
    w = moving_map.MovingMap()
    qtbot.addWidget(w)
    w.resize(200, 200)
    assert w._transform().defer_render is False
    w._gesture_active = True
    assert w._transform().defer_render is True


# --- integration: zoom_by / wheel job-posting under gating -----------------

def _rig_terrain_layer(w):
    """Swap in a terrain layer with a fake cache and an instrumented
    _request, standing in for the real worker-backed one -- this isolates
    the gating logic from TileCache/render internals."""
    lay = TerrainLayer()
    lay._cache = object()          # non-None: paint() proceeds past the guard
    lay._owner = w                 # w._alt_ft defaults to 0.0
    requested = []
    lay._request = lambda key, x: requested.append(key)
    w._layers = [lay]
    w._layers_built = True
    return requested


def test_zoom_by_inside_gesture_posts_no_jobs_one_after_settle(fix, qtbot):
    """DoD: 200 zoom_by calls inside an active gesture post 0 jobs; 1 job
    once the gesture ends and the settle timer fires."""
    w = moving_map.MovingMap()
    qtbot.addWidget(w)
    w.resize(300, 300)
    w.range_ladder = "2,5,10,20,40,80,160"
    w.range_nm = 10.0
    requested = _rig_terrain_layer(w)

    GS = Qt.GestureState
    w.event(_FakeGestureEvent(_FakeGesture(GS.GestureStarted)))
    for _ in range(200):
        w.zoom_by(1.001)            # continuous zoom, as a pinch delivers
        w.paintEvent(QPaintEvent(w.rect()))
    assert requested == []

    w.event(_FakeGestureEvent(_FakeGesture(GS.GestureFinished)))
    w.paintEvent(QPaintEvent(w.rect()))
    assert requested == []          # still inside the settle window

    qtbot.waitUntil(lambda: not w._settle_timer.isActive(), timeout=1000)
    w.paintEvent(QPaintEvent(w.rect()))
    assert len(requested) == 1


def test_wheel_notches_within_150ms_post_one_job(fix, qtbot):
    """DoD: wheel notches within 150 ms post 1 job (not one per notch)."""
    w = moving_map.MovingMap()
    qtbot.addWidget(w)
    w.resize(300, 300)
    requested = _rig_terrain_layer(w)

    for _ in range(5):
        _wheel(w, 60)
        w.paintEvent(QPaintEvent(w.rect()))
        qtbot.wait(30)               # well inside the 150 ms settle window
    assert requested == []

    qtbot.waitUntil(lambda: not w._settle_timer.isActive(), timeout=1000)
    w.paintEvent(QPaintEvent(w.rect()))
    assert len(requested) == 1


def test_paint_without_gesture_requests_immediately(fix, qtbot):
    """Outside any gesture/settle window, a key change still requests a
    render right away -- MP1 must not regress the steady-state path."""
    w = moving_map.MovingMap()
    qtbot.addWidget(w)
    w.resize(300, 300)
    requested = _rig_terrain_layer(w)
    w.paintEvent(QPaintEvent(w.rect()))
    assert len(requested) == 1


# --- layer paint() gating on MapTransform.defer_render ---------------------

def test_terrain_paint_skips_request_while_deferred():
    lay = TerrainLayer()
    lay._cache = object()

    class Owner:
        _alt_ft = 0.0
    lay._owner = Owner

    requested = []
    lay._request = lambda key, x: requested.append(key)

    img = QImage(300, 300, QImage.Format.Format_RGB32)
    p = QPainter(img)
    x = moving_map.MapTransform(34.5, -120.5, 10.0, 0.0, 300, 300, 0.5)
    x.defer_render = True
    lay.paint(p, x)
    lay.paint(p, x)
    p.end()
    assert requested == []

    p = QPainter(img)
    x.defer_render = False
    lay.paint(p, x)
    p.end()
    assert len(requested) == 1
