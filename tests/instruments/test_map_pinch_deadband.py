"""#202/AER-1216: a zoom-only pinch must not also pan/rotate the map, zoom
must feel continuous throughout AND across release (Bill, 2026-09-15 --
supersedes the original release-snap requirement), and range_key (when
bound) always reflects the range actually on screen without clobbering a
live pinch's continuity.

Every test here drives the gesture through ``event()`` (a real
``QPinchGesture`` reports RotationAngleChanged/CenterPointChanged/
ScaleFactorChanged deltas the same way these fakes do) -- calling
``zoom_by``/``rotate_by``/``pan_by`` directly, as the MP7 bench harness does,
cannot observe any of this: the defect is entirely in how ``event()``/the
range_key write-back apply those components."""
import pytest
from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtWidgets import QPinchGesture

import pyefis.hmi.functions as functions
from pyefis.instruments import map as moving_map
from pyefis.instruments.map.layers import format_range_nm

_LADDER = [2.0, 5.0, 10.0, 20.0, 40.0, 80.0, 160.0]


class _FakePinch:
    """QPinchGesture stand-in: any subset of scale/rotation/center changes,
    plus a state. Absent params leave that ChangeFlag unset, matching how a
    real update can touch only some of the three."""

    def __init__(self, state=None, scale=None, rotation=None,
                 last_rotation=0.0, center=None, last_center=None):
        self._state = state
        self._scale = scale
        self._rotation = rotation
        self._last_rotation = last_rotation
        self._center = center
        self._last_center = last_center

    def state(self):
        return self._state

    def changeFlags(self):
        flags = QPinchGesture.ChangeFlag(0)
        if self._scale is not None:
            flags |= QPinchGesture.ChangeFlag.ScaleFactorChanged
        if self._rotation is not None:
            flags |= QPinchGesture.ChangeFlag.RotationAngleChanged
        if self._center is not None:
            flags |= QPinchGesture.ChangeFlag.CenterPointChanged
        return flags

    def scaleFactor(self):
        return self._scale

    def rotationAngle(self):
        return self._rotation

    def lastRotationAngle(self):
        return self._last_rotation

    def centerPoint(self):
        return self._center

    def lastCenterPoint(self):
        return self._last_center


class _FakeGestureEvent:
    def __init__(self, g):
        self._g = g

    def type(self):
        return QEvent.Type.Gesture

    def gesture(self, which):
        return self._g


def _send(w, **kw):
    w.event(_FakeGestureEvent(_FakePinch(**kw)))


GS = Qt.GestureState


# --- dead-band: a zoom-only pinch must leave pan/rotate untouched ----------

def test_wobbly_zoom_only_pinch_leaves_orientation_and_pan_unchanged(fix, qtbot):
    """Fingers spreading with a few degrees of wobble and a few px of
    centroid jitter -- well under both thresholds -- must not rotate or pan
    the view, and must raise no CTR chip (is_offset stays False)."""
    w = moving_map.MovingMap()
    qtbot.addWidget(w)
    w.range_ladder = "2,5,10,20,40,80,160"
    w.range_nm = 10.0

    _send(w, state=GS.GestureStarted, scale=1.05, rotation=0.0,
          last_rotation=0.0, center=QPointF(100, 100),
          last_center=QPointF(100, 100))
    updates = [
        dict(scale=1.10, rotation=1.0, last_rotation=0.0,
             center=QPointF(102, 101), last_center=QPointF(100, 100)),
        dict(scale=1.15, rotation=2.5, last_rotation=1.0,
             center=QPointF(104, 99), last_center=QPointF(102, 101)),
        dict(scale=1.20, rotation=1.5, last_rotation=2.5,
             center=QPointF(103, 100), last_center=QPointF(104, 99)),
    ]
    for u in updates:
        _send(w, state=GS.GestureUpdated, **u)
    _send(w, state=GS.GestureFinished)

    assert w._rot_offset == 0.0
    assert not w.is_offset                  # no CTR chip
    assert w.range_nm != 10.0                # the pinch DID zoom


def test_pinch_rotation_engages_after_threshold_and_catches_up(fix, qtbot):
    """Below pinch_rotate_threshold_deg (default 15) cumulative twist,
    rotate_by is never called; once crossed, the WHOLE accumulated twist
    applies in one step so no motion is lost at the crossing, and every
    later delta applies directly. 5 events of +4 deg raw twist (total 20)
    must land at the same -20 deg offset a continuous, undead-banded pinch
    would reach (#114: clockwise twist -> negative offset)."""
    w = moving_map.MovingMap()
    qtbot.addWidget(w)
    _send(w, state=GS.GestureStarted, rotation=0.0, last_rotation=0.0)
    prev = 0.0
    for _ in range(5):
        cur = prev + 4.0
        _send(w, state=GS.GestureUpdated, rotation=cur, last_rotation=prev)
        prev = cur
    assert w._rot_offset == pytest.approx(-20.0)


def test_pinch_pan_engages_after_centroid_threshold_and_catches_up(fix, qtbot):
    """Same dead-band shape for pan, gated on cumulative centroid
    displacement from gesture start rather than a single event's delta.
    The total landed offset must equal what continuous (undead-banded)
    pan_by calls covering the same total motion would reach -- dead-banding
    only delays when pan starts engaging, never where it ends up."""
    w = moving_map.MovingMap()
    qtbot.addWidget(w)
    w.resize(400, 400)
    start = QPointF(100.0, 100.0)
    _send(w, state=GS.GestureStarted, center=start, last_center=start)
    prev = start
    for _ in range(4):
        cur = QPointF(prev.x() + 8.0, prev.y())
        _send(w, state=GS.GestureUpdated, center=cur, last_center=prev)
        prev = cur
    assert w.is_offset

    ref = moving_map.MovingMap()
    qtbot.addWidget(ref)
    ref.resize(400, 400)
    for _ in range(4):
        ref.pan_by(8.0, 0.0)
    assert (w._pan_e, w._pan_n) == pytest.approx((ref._pan_e, ref._pan_n))


# --- continuous zoom, release does not snap, one range-write path ----------

def test_pinch_release_does_not_snap_range_stays_where_fingers_left_it(fix, qtbot):
    """Bill's 2026-09-15 verdict on #220 (bench feel: 'practically unusable
    ... very unpredictable'): the release-to-ladder snap is withdrawn.
    range_nm must land exactly where the pinch left it, not jump to a rung
    -- with the default 4-5x-spaced ladder a snap sprang most zooms back to
    the start and jumped the rest 5x. A real 'RNG+' press afterward must
    still step from the range actually on screen (the one-range-write-path
    requirement, #202 requirement 3), not a stale pre-pinch index."""
    fix.db.define_item("MAPRANGE", "MAPRANGE", "int", 0, 7, "", 50000, "")
    fix.db.set_value("MAPRANGE", 0)
    item = fix.db.get_item("MAPRANGE")
    item.bad = False
    item.fail = False

    w = moving_map.MovingMap()
    qtbot.addWidget(w)
    w.range_ladder = "2,5,10,20,40,80,160"
    w.range_key = "MAPRANGE"
    w.init_live_bindings(w._live_binding_specs())
    w.range_nm = 10.0

    _send(w, state=GS.GestureStarted, scale=1.0)
    _send(w, state=GS.GestureUpdated, scale=10.0 / 16.0)   # zoom OUT to 16 NM
    _send(w, state=GS.GestureFinished)

    assert w.range_nm == pytest.approx(16.0)      # exactly where fingers left it
    assert item.value == _LADDER.index(20.0)      # nearest rung to 16, for RNG+

    functions.changeValueWrap("MAPRANGE,1")       # a real RNG+ button press
    assert w.range_nm == 40.0                     # steps from the landed range


def test_bound_range_key_pinch_stays_continuous_across_linear_midpoint(fix, qtbot):
    """#202 requirement 3 / AER-1216 item 3: with range_key bound, the
    range_nm setter's write-back to the key must not re-apply onto range_nm.
    Before the fix, pyavtools' DB_Item.value setter emits valueChanged
    whenever the nearest-index-by-LINEAR-distance flips, and
    LiveBindingMixin._apply_bind's setattr forced range_nm to that rung mid-
    gesture -- so a pinch could never be continuous on a bound panel (e.g.
    the map-controls screen, which binds MAPRANGE). 10 -> 20 is a ladder gap
    whose linear midpoint is 15: drive a pinch through it and require the
    bound widget to track a reference (unbound) widget seeing the identical
    event stream, step for step."""
    fix.db.define_item("MAPRANGE", "MAPRANGE", "int", 0, 7, "", 50000, "")
    fix.db.set_value("MAPRANGE", 0)
    item = fix.db.get_item("MAPRANGE")
    item.bad = False
    item.fail = False

    bound = moving_map.MovingMap()
    qtbot.addWidget(bound)
    bound.range_ladder = "2,5,10,20,40,80,160"
    bound.range_key = "MAPRANGE"
    bound.init_live_bindings(bound._live_binding_specs())
    bound.range_nm = 10.0

    ref = moving_map.MovingMap()
    qtbot.addWidget(ref)
    ref.range_ladder = "2,5,10,20,40,80,160"
    ref.range_nm = 10.0

    _send(bound, state=GS.GestureStarted, scale=1.0)
    _send(ref, state=GS.GestureStarted, scale=1.0)
    # 10 -> 12 -> 14 -> 16 -> 18: straddles the 10/20 linear midpoint (15).
    # scale is CUMULATIVE since gesture start (real QPinchGesture semantics,
    # AER-1216 follow-up), i.e. baseline(10.0) / target -- not a per-step
    # delta against the moving range_nm.
    for target in (12.0, 14.0, 16.0, 18.0):
        factor = 10.0 / target
        _send(bound, state=GS.GestureUpdated, scale=factor)
        _send(ref, state=GS.GestureUpdated, scale=factor)
        assert bound.range_nm == pytest.approx(ref.range_nm), (
            "bound range_key clobbered a continuous pinch at %.1f NM" % target)

    _send(bound, state=GS.GestureFinished)
    _send(ref, state=GS.GestureFinished)
    assert bound.range_nm == pytest.approx(ref.range_nm)
    assert item.value == _LADDER.index(20.0)   # write-back still landed once settled


def test_pinch_dead_band_composes_with_continuous_zoom(fix, qtbot):
    """A real pinch mixes all three components: this drives a zoom-out with
    rotation/pan under threshold and checks release leaves range exactly
    where the pinch landed (no snap) while orientation/pan stay untouched."""
    w = moving_map.MovingMap()
    qtbot.addWidget(w)
    w.range_ladder = "2,5,10,20,40,80,160"
    w.range_nm = 10.0

    _send(w, state=GS.GestureStarted, scale=1.0, rotation=0.0,
          last_rotation=0.0, center=QPointF(0, 0), last_center=QPointF(0, 0))
    _send(w, state=GS.GestureUpdated, scale=10.0 / 13.0, rotation=3.0,
          last_rotation=0.0, center=QPointF(2, 1), last_center=QPointF(0, 0))
    _send(w, state=GS.GestureFinished)

    assert w.range_nm == pytest.approx(13.0)
    assert w._rot_offset == 0.0
    assert not w.is_offset


# --- scaleFactor is cumulative-since-start, not a per-event delta ---------

def test_finely_sampled_pinch_does_not_overshoot_from_scaleFactor_compounding(
        fix, qtbot):
    """QPinchGesture.scaleFactor() is cumulative since the gesture STARTED
    (it is the same value as totalScaleFactor() -- Qt's own imagegestures
    example computes a live preview as ``originalScale * totalScaleFactor()``
    on every frame and only commits it once, on GestureFinished; lastScaleFactor()
    is a separate, distinct property precisely because scaleFactor() is not
    already a delta). A real touch panel fires many GestureUpdated events
    over one continuous finger spread -- if each event's cumulative factor
    is committed onto the ALREADY-zoomed range_nm (as a naive per-event
    ``zoom_by(g.scaleFactor())`` does), the effective total zoom is the
    PRODUCT of every intermediate cumulative factor, not just the final
    one. The more finely the gesture is sampled, the worse the runaway --
    which is exactly backwards from what a touchscreen pinch should do, and
    matches Bill's report that a fluid, naturally-sampled pinch went wild
    while a very slow, sparse one (fewer samples) stayed usable.

    This drives 30 events smoothly interpolating the cumulative scaleFactor
    from 1.0 to 0.5 -- a plain 2x zoom-out. Landing anywhere near the
    ladder's extreme end (160) instead of ~20 NM is the compounding bug."""
    w = moving_map.MovingMap()
    qtbot.addWidget(w)
    w.range_ladder = "2,5,10,20,40,80,160"
    w.range_nm = 10.0

    _send(w, state=GS.GestureStarted, scale=1.0)
    steps = 30
    for i in range(1, steps + 1):
        cumulative = 1.0 - (i / steps) * 0.5   # 1.0 -> 0.5 over `steps` samples
        _send(w, state=GS.GestureUpdated, scale=cumulative)
    _send(w, state=GS.GestureFinished)

    assert w.range_nm == pytest.approx(20.0, rel=0.05), (
        "a 2x zoom-out sampled at 30 events landed at %.1f NM instead of "
        "~20 -- scaleFactor() is being compounded across events instead of "
        "applied once from the gesture's start-of-pinch baseline" % w.range_nm)


# --- displayed-range rounding (display only, #202's original complaint) ----

def test_format_range_nm_rounds_for_readability():
    """"14 NM" instead of "13.7234" -- display-only, range_nm stays
    continuous (Bill, AER-1216 2026-09-15)."""
    assert format_range_nm(13.7234) == "14"
    assert format_range_nm(2.53) == "2.5"
    assert format_range_nm(160.0) == "160"


# --- synthesized mouse drag suppression (unverified on real hardware) ------

class _Press:
    def button(self):
        return Qt.MouseButton.LeftButton

    def position(self):
        return QPointF(10, 10)

    def accept(self):
        pass


def test_mousepress_during_active_pinch_does_not_start_a_drag(fix, qtbot):
    """A mouse press synthesized from the same two fingers driving an active
    pinch must not also start a competing drag/pan. Whether Qt actually
    synthesizes such an event on the touchscreen is unverified without real
    hardware (#202) -- this pins the suppression logic itself."""
    w = moving_map.MovingMap()
    qtbot.addWidget(w)
    _send(w, state=GS.GestureStarted, scale=1.0)
    assert w._pinch_active

    w.mousePressEvent(_Press())
    assert w._drag_last is None

    _send(w, state=GS.GestureFinished)
    assert not w._pinch_active
    w.mousePressEvent(_Press())
    assert w._drag_last is not None   # normal desktop press still works


def test_pinch_start_clears_any_in_flight_drag(fix, qtbot):
    w = moving_map.MovingMap()
    qtbot.addWidget(w)
    w._drag_last = QPointF(5, 5)
    _send(w, state=GS.GestureStarted, scale=1.0)
    assert w._drag_last is None
