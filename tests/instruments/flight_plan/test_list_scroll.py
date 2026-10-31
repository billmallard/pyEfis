#  SPDX-License-Identifier: GPL-2.0-or-later
"""FPL list finger scrolling (PA15, AER-2087).

Bill, 2026-09-24, on the bench: "there's no scrolling available on the flight
plan screen. It really needs a responsive finger touch scroll." The list had
only a tap hit-test in ``mousePressEvent`` and squeezed a long route into
ever-thinner rows until the rest fell off the bottom.

What these pin, because each is a way the panel can go wrong under a finger:

* rows keep their physical height and the route scrolls instead;
* a press on the list becomes a tap only on release, and only if the finger
  stayed inside ``drag_threshold_mm`` -- a drag never also selects the row it
  started on (worse than no scrolling: a stray waypoint menu mid-reach);
* the scroll clamps at both ends, including under a fling;
* the row a tap lands on is the one drawn there at the scrolled offset, and a
  row scrolled under the column header cannot be tapped through it;
* the active leg comes into view as the sequencer advances, unless the pilot
  scrolled recently;
* the knob still reaches rows scrolled offscreen.
"""

import pytest
from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QMouseEvent, QWheelEvent
from PyQt6.QtTest import QTest

from pyefis.instruments import flight_plan
from tests.instruments.flight_plan import test_flight_plan as base


class _Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def clock():
    return _Clock()


def _widget(fix, qtbot, clock, monkeypatch, n=30, size=(480, 640)):
    base._define_all_fp1_keys(fix)
    w = flight_plan.FlightPlan(None)
    qtbot.addWidget(w)
    w.resize(*size)
    monkeypatch.setattr(w, "_now", clock)
    w._plan = base._plan(n)
    w._commit()
    w.grab()
    return w


def _view(w):
    w.grab()
    return w._list_view


def _ev(kind, x, y):
    button = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseMove else Qt.MouseButton.LeftButton
    return QMouseEvent(kind, QPointF(x, y), QPointF(x, y), button,
                       Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)


def _press(w, x, y):
    w.mousePressEvent(_ev(QEvent.Type.MouseButtonPress, x, y))


def _move(w, x, y):
    w.mouseMoveEvent(_ev(QEvent.Type.MouseMove, x, y))


def _release(w, x, y):
    w.mouseReleaseEvent(_ev(QEvent.Type.MouseButtonRelease, x, y))


def _row_at(w, y):
    """Index of the display row drawn at widget y, from the paint geometry."""
    v = _view(w)
    return int((y - v["top"] + w._list_scroll) // v["row_h"])


def _drag(w, clock, x, y0, y1, steps=10, dt=0.01):
    _press(w, x, y0)
    for k in range(1, steps + 1):
        clock.t += dt
        _move(w, x, y0 + (y1 - y0) * k / steps)


# --------------------------------------------------------------------------
# layout: physical rows, overflow, the cue
# --------------------------------------------------------------------------

def test_long_route_keeps_physical_rows_and_overflows(fix, qtbot, clock, monkeypatch):
    w = _widget(fix, qtbot, clock, monkeypatch, n=30)
    v = _view(w)
    assert v["row_h"] == pytest.approx(w._row_h_cap())
    assert v["max"] == pytest.approx(30 * v["row_h"] - (v["bottom"] - v["top"]))
    assert v["max"] > 0


def test_short_route_does_not_scroll(fix, qtbot, clock, monkeypatch):
    w = _widget(fix, qtbot, clock, monkeypatch, n=3)
    assert _view(w)["max"] == 0
    _drag(w, clock, 200, _view(w)["top"] + 5, _view(w)["top"] + 200)
    assert w._list_scroll == 0


def _cue_lit(w):
    v = _view(w)
    img = w.grab().toImage()
    x = w.width() - 3
    ys = range(int(v["top"]) + 2, int(v["bottom"]) - 2)
    return any(img.pixelColor(x, y).red() > 30 for y in ys)


def test_scroll_cue_only_when_the_list_overflows(fix, qtbot, clock, monkeypatch):
    assert _cue_lit(_widget(fix, qtbot, clock, monkeypatch, n=30))
    assert not _cue_lit(_widget(fix, qtbot, clock, monkeypatch, n=3))


def test_scroll_cue_thumb_follows_the_offset(fix, qtbot, clock, monkeypatch):
    w = _widget(fix, qtbot, clock, monkeypatch, n=30)
    v = _view(w)
    x = w.width() - 3

    def thumb_rows():
        img = w.grab().toImage()
        return [y for y in range(int(v["top"]), int(v["bottom"]))
                if img.pixelColor(x, y).red() > 120]

    top_thumb = thumb_rows()
    w._scroll_list_to(v["max"])
    end_thumb = thumb_rows()
    assert top_thumb and end_thumb
    assert top_thumb[0] < v["top"] + 3
    assert end_thumb[-1] > v["bottom"] - 4


# --------------------------------------------------------------------------
# tap vs drag
# --------------------------------------------------------------------------

def test_drag_threshold_is_physical(fix, qtbot, clock, monkeypatch):
    w = _widget(fix, qtbot, clock, monkeypatch)
    assert w._drag_threshold_px() == pytest.approx(
        max(6.0, flight_plan.DRAG_THRESHOLD_MM * w._px_per_mm()))


def test_list_tap_fires_on_release_not_press(fix, qtbot, clock, monkeypatch):
    w = _widget(fix, qtbot, clock, monkeypatch)
    v = _view(w)
    y = v["top"] + v["row_h"] * 2.5
    _press(w, 200, y)
    assert w._row_menu_index is None, "a list press must not select before lift-off"
    _release(w, 200, y)
    assert w._row_menu_index == 2


def test_wobble_under_the_threshold_is_still_a_tap(fix, qtbot, clock, monkeypatch):
    w = _widget(fix, qtbot, clock, monkeypatch)
    v = _view(w)
    y = v["top"] + v["row_h"] * 1.5
    wobble = w._drag_threshold_px() * 0.6
    _press(w, 200, y)
    _move(w, 200 + wobble * 0.5, y + wobble * 0.7)
    _release(w, 200, y)
    assert w._row_menu_index == 1
    assert w._list_scroll == 0


def test_drag_past_the_threshold_scrolls_and_never_taps(fix, qtbot, clock, monkeypatch):
    w = _widget(fix, qtbot, clock, monkeypatch)
    v = _view(w)
    y0 = v["top"] + v["row_h"] * 6.5
    thr = w._drag_threshold_px()
    _drag(w, clock, 200, y0, y0 - thr - 100)
    clock.t += 0.5            # finger rests before lift-off: no fling
    _release(w, 200, y0 - thr - 100)
    assert w._row_menu_index is None, "the drag also selected the row it started on"
    # Re-anchored at the first move past the threshold: the list follows
    # the finger from there, it does not jump by the threshold.
    step = (thr + 100) / 10
    crossed = next(k for k in range(1, 11) if k * step >= thr) * step
    assert w._list_scroll == pytest.approx(thr + 100 - crossed)
    assert not w._fling_timer.isActive()


def test_sideways_slip_cancels_the_tap(fix, qtbot, clock, monkeypatch):
    w = _widget(fix, qtbot, clock, monkeypatch)
    v = _view(w)
    y = v["top"] + v["row_h"] * 1.5
    _press(w, 100, y)
    _move(w, 100 + w._drag_threshold_px() + 2, y)
    _release(w, 100 + w._drag_threshold_px() + 2, y)
    assert w._row_menu_index is None


# --------------------------------------------------------------------------
# clamping
# --------------------------------------------------------------------------

def test_drag_clamps_at_the_end(fix, qtbot, clock, monkeypatch):
    w = _widget(fix, qtbot, clock, monkeypatch)
    v = _view(w)
    for _ in range(6):        # far more than the route is long
        _drag(w, clock, 200, v["bottom"] - 5, v["top"] + 5)
        clock.t += 0.5
        _release(w, 200, v["top"] + 5)
    assert w._list_scroll == pytest.approx(v["max"])


def test_drag_clamps_at_the_top(fix, qtbot, clock, monkeypatch):
    w = _widget(fix, qtbot, clock, monkeypatch)
    v = _view(w)
    w._scroll_list_to(v["row_h"] * 2)
    _drag(w, clock, 200, v["top"] + 5, v["bottom"] - 5)
    assert w._list_scroll == 0


def test_offset_is_reclamped_when_the_route_shrinks(fix, qtbot, clock, monkeypatch):
    w = _widget(fix, qtbot, clock, monkeypatch)
    w._scroll_list_to(_view(w)["max"])
    w._plan = base._plan(3)
    w._commit()
    assert _view(w)["max"] == 0
    assert w._list_scroll == 0


# --------------------------------------------------------------------------
# hit-testing at a scrolled offset
# --------------------------------------------------------------------------

@pytest.mark.parametrize("offset_rows", [0.0, 3.0, 7.4])
def test_tap_hits_the_row_drawn_there_at_any_offset(fix, qtbot, clock, monkeypatch,
                                                    offset_rows):
    w = _widget(fix, qtbot, clock, monkeypatch)
    v = _view(w)
    w._scroll_list_to(v["row_h"] * offset_rows)
    y = v["top"] + v["row_h"] * 2.5
    expected = _row_at(w, y)
    QTest.mouseClick(w, Qt.MouseButton.LeftButton, pos=QPoint(200, int(y)))
    assert w._row_menu_index == expected
    assert expected == int(2.5 + offset_rows)


def test_row_scrolled_under_the_header_is_not_tappable_there(fix, qtbot, clock, monkeypatch):
    w = _widget(fix, qtbot, clock, monkeypatch)
    v = _view(w)
    # Half of row 0 sits above the viewport, behind the column header strip.
    w._scroll_list_to(v["row_h"] * 0.5)
    w.grab()
    QTest.mouseClick(w, Qt.MouseButton.LeftButton, pos=QPoint(200, int(v["top"] - 3)))
    assert w._row_menu_index is None
    # The visible half still taps row 0.
    QTest.mouseClick(w, Qt.MouseButton.LeftButton, pos=QPoint(200, int(v["top"] + 3)))
    assert w._row_menu_index == 0


def test_soft_keys_still_fire_on_press(fix, qtbot, clock, monkeypatch):
    w = _widget(fix, qtbot, clock, monkeypatch)
    menu = [t for t in w._tap_targets if t[4] == w._footer_menu][0]
    _press(w, menu[0] + menu[2] / 2, menu[1] + menu[3] / 2)
    assert w._menu_open is True


def test_list_under_an_overlay_does_not_scroll(fix, qtbot, clock, monkeypatch):
    w = _widget(fix, qtbot, clock, monkeypatch)
    v = _view(w)
    w._menu_open = True
    w.grab()
    assert w._list_view is None
    _drag(w, clock, 20, v["bottom"] - 5, v["top"] + 5)
    assert w._list_scroll == 0


# --------------------------------------------------------------------------
# fling
# --------------------------------------------------------------------------

def test_fast_release_flings_and_stops_at_the_end(fix, qtbot, clock, monkeypatch):
    w = _widget(fix, qtbot, clock, monkeypatch, n=60)
    v = _view(w)
    _drag(w, clock, 200, v["bottom"] - 10, v["bottom"] - 210, steps=5, dt=0.01)
    _release(w, 200, v["bottom"] - 210)
    assert w._fling_timer.isActive()
    assert w._fling_v > 0
    released_at = w._list_scroll
    for _ in range(2000):
        if not w._fling_timer.isActive():
            break
        w._fling_step(0.016)
    assert not w._fling_timer.isActive()
    assert w._list_scroll > released_at, "the fling did not carry the list on"
    assert 0 <= w._list_scroll <= v["max"]


def test_fling_clamps_and_ends_at_the_stop(fix, qtbot, clock, monkeypatch):
    w = _widget(fix, qtbot, clock, monkeypatch)
    v = _view(w)
    w._start_fling(1e6)       # far past the speed cap
    for _ in range(50):
        w._fling_step(0.05)
    assert w._list_scroll == pytest.approx(v["max"])
    assert not w._fling_timer.isActive()


def test_slow_release_does_not_fling(fix, qtbot, clock, monkeypatch):
    w = _widget(fix, qtbot, clock, monkeypatch)
    v = _view(w)
    # 1 px per 50 ms is 20 px/s, far under the 50 mm/s fling floor at any
    # plausible pixel density.
    _drag(w, clock, 200, v["top"] + 200, v["top"] + 100, steps=100, dt=0.05)
    _release(w, 200, v["top"] + 100)
    assert not w._fling_timer.isActive()


def test_press_during_a_fling_stops_it_without_a_tap(fix, qtbot, clock, monkeypatch):
    w = _widget(fix, qtbot, clock, monkeypatch, n=60)
    v = _view(w)
    w._start_fling(2000 * w._px_per_mm())
    w._fling_step(0.016)
    y = v["top"] + v["row_h"] * 2.5
    _press(w, 200, y)
    assert not w._fling_timer.isActive()
    _release(w, 200, y)
    assert w._row_menu_index is None, "the press that caught the fling also tapped a row"


# --------------------------------------------------------------------------
# keeping the active leg in view
# --------------------------------------------------------------------------

def _activate(w, fix, leg):
    fix.db.set_value("FPLSTATE", 1)
    fix.db.set_value("FPLACTLEG", leg)
    w._sync_engine_from_bridge()
    w.grab()


def _row_visible(w, n):
    v = w._list_view
    top = v["top"] + n * v["row_h"] - w._list_scroll
    return top >= v["top"] - 0.5 and top + v["row_h"] <= v["bottom"] + 0.5


def test_sequencer_advance_brings_the_active_leg_into_view(fix, qtbot, clock, monkeypatch):
    w = _widget(fix, qtbot, clock, monkeypatch)
    _activate(w, fix, 25)                    # FPLACTLEG is 1-based
    assert _row_visible(w, 24), "active leg offscreen"
    assert _row_visible(w, 23), "the FROM row above it should show too"


def test_pilot_scroll_holds_off_the_follow_until_the_hold_runs_out(fix, qtbot, clock,
                                                                    monkeypatch):
    w = _widget(fix, qtbot, clock, monkeypatch)
    _activate(w, fix, 2)
    v = w._list_view
    _drag(w, clock, 200, v["top"] + 300, v["top"] + 100)
    clock.t += 0.5
    _release(w, 200, v["top"] + 100)
    parked = w._list_scroll
    _activate(w, fix, 25)
    assert w._list_scroll == parked, "the sequencer yanked the list out from under the pilot"
    clock.t += w.scroll_hold_s + 1
    w.grab()
    assert _row_visible(w, 24)


def test_follow_leaves_an_already_visible_active_leg_alone(fix, qtbot, clock, monkeypatch):
    w = _widget(fix, qtbot, clock, monkeypatch)
    _activate(w, fix, 3)
    assert w._list_scroll == 0


def test_follow_finds_the_working_row_inside_an_open_airway(fix, qtbot, clock, monkeypatch):
    """Inside an airway the active leg is the nested TO row, not a plain
    one; a pane three rows tall makes every leg past the entry overflow."""
    from tests.instruments.flight_plan import test_segment_rows as seg
    base._define_all_fp1_keys(fix)
    w = flight_plan.FlightPlan(None)
    qtbot.addWidget(w)
    w.resize(480, 330)
    monkeypatch.setattr(w, "_now", clock)
    w._plan = seg._route()
    w._commit()
    w.grab()
    assert w._list_view["max"] > 0
    for leg in range(2, len(w._plan.waypoints) + 1):
        _activate(w, fix, leg)
        display = w._display_rows(leg - 1)
        pos = next(n for n, r in enumerate(display)
                   if (r[0] == "wpt" and r[1] == leg - 1) or (r[0] == "fix" and r[2] == "to"))
        assert _row_visible(w, pos), f"active leg {leg} (display row {pos}) offscreen"


# --------------------------------------------------------------------------
# encoder and wheel
# --------------------------------------------------------------------------

def test_knob_walks_onto_an_offscreen_row_and_scrolls_it_in(fix, qtbot, clock, monkeypatch):
    w = _widget(fix, qtbot, clock, monkeypatch)
    w.enc_highlight(True)
    assert w.enc_select() is True
    for _ in range(20):
        w.enc_changed(1)
    ring = w._enc_prepare()
    kind, rect, _cb = ring[w._enc_focus]
    v = w._list_view
    assert kind == "row"
    assert rect.top() >= v["top"] - 0.5 and rect.bottom() <= v["bottom"] + 0.5
    assert w._list_scroll > 0


def test_wheel_scrolls_by_rows(fix, qtbot, clock, monkeypatch):
    w = _widget(fix, qtbot, clock, monkeypatch)
    v = _view(w)
    ev = QWheelEvent(QPointF(200, v["top"] + 50), QPointF(200, v["top"] + 50),
                     QPoint(0, 0), QPoint(0, -240), Qt.MouseButton.NoButton,
                     Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    w.wheelEvent(ev)
    assert w._list_scroll == pytest.approx(2 * v["row_h"])
