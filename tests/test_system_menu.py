#  SPDX-License-Identifier: GPL-2.0-or-later
"""MENU1 (AER-5892): the system menu -- the top-right corner swipe, the
overlay (Data Status, About, Screens, Close), the return route and the
SYSMENU bus key."""

import logging

import pytest
from PyQt6.QtCore import QEvent, QObject, QPointF, Qt, pyqtSignal
from PyQt6.QtGui import (QInputDevice, QMouseEvent, QPointingDevice,
                         QTouchEvent, QEventPoint)
from PyQt6.QtWidgets import QApplication, QPushButton, QWidget

import pyefis.hmi as hmi
import pyefis.system_menu as sm
from pyefis.instruments.about import AboutSystem
from pyefis.instruments.data_status import DataStatus

PPM = 6.0                       # px per mm for the pure-geometry cases
W, H = 1024, 600
MM = PPM                        # readability: n * MM is n millimetres


class _Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def _rec(w=W, h=H, ppm=PPM):
    clock = _Clock()
    return sm.CornerSwipe(w, h, ppm, clock=clock), clock


def _swipe(rec, clock, start, end, dt=0.3, source=sm.TOUCH):
    rec.press(start[0], start[1], source)
    clock.t += dt
    return rec.release(end[0], end[1], source)


# a start point inside the zone: 10 mm in from the right, 3 mm down
IN = (W - 10 * MM, 3 * MM)


# ---------------------------------------------------------------------------
# the recogniser: accept and reject
# ---------------------------------------------------------------------------

def test_zone_is_the_top_right_strip():
    rec, _ = _rec()
    x0, y1 = rec.zone()
    assert x0 == pytest.approx(W - sm.CORNER_WIDTH_MM * PPM)
    assert y1 == pytest.approx(sm.CORNER_HEIGHT_MM * PPM)
    assert rec.in_zone(W - 1, 0)
    assert rec.in_zone(x0, y1)
    assert not rec.in_zone(x0 - 1, 0)          # left of the corner
    assert not rec.in_zone(W - 1, y1 + 1)      # below the strip
    assert not rec.in_zone(W - 1, -1)


def test_zone_is_capped_on_a_small_dense_panel():
    # 20 px/mm on a 400x200 window: 25 mm x 8 mm would be 500x160 px
    rec, _ = _rec(400, 200, 20.0)
    x0, y1 = rec.zone()
    assert x0 == pytest.approx(400 * (1 - sm.CORNER_MAX_WIDTH_FRAC))
    assert y1 == pytest.approx(200 * sm.CORNER_MAX_HEIGHT_FRAC)


@pytest.mark.parametrize("start,end,dt", [
    # the swipe: down and to the left from the corner
    (IN, (IN[0] - 10 * MM, IN[1] + 25 * MM), 0.3),
    # at the thresholds exactly
    (IN, (IN[0] - sm.TRAVEL_LEFT_MM * MM, IN[1] + sm.TRAVEL_DOWN_MM * MM), 0.3),
    # as flat as it may be: left = 2 x down
    (IN, (IN[0] - 40 * MM, IN[1] + 20 * MM), 0.3),
    # slow but inside the time limit
    (IN, (IN[0] - 10 * MM, IN[1] + 25 * MM), sm.MAX_DURATION_S),
    # from the very corner pixel
    ((W - 1, 0), (W - 1 - 10 * MM, 30 * MM), 0.2),
], ids=["swipe", "at-thresholds", "flattest", "slowest", "corner-pixel"])
def test_accepts(start, end, dt):
    rec, clock = _rec()
    assert _swipe(rec, clock, start, end, dt)


@pytest.mark.parametrize("start,end,dt", [
    # a tap on a control in the corner (PFD's top-right button column)
    (IN, IN, 0.1),
    # a vertical scroll from the corner (FPL page): no leftward part
    (IN, (IN[0], IN[1] + 40 * MM), 0.3),
    # a map pan that starts below the strip, same motion as the swipe
    ((IN[0], 9 * MM), (IN[0] - 10 * MM, 40 * MM), 0.3),
    # a map pan that starts left of the corner
    ((W - 30 * MM, 3 * MM), (W - 40 * MM, 30 * MM), 0.3),
    # down and to the RIGHT is not it
    ((W - 20 * MM, 3 * MM), (W - 10 * MM, 30 * MM), 0.3),
    # up and to the left (cannot go up from the strip, but never accept)
    ((W - 10 * MM, 7 * MM), (W - 30 * MM, 0), 0.3),
    # too short downward
    (IN, (IN[0] - 10 * MM, IN[1] + (sm.TRAVEL_DOWN_MM - 0.5) * MM), 0.3),
    # too little leftward
    (IN, (IN[0] - (sm.TRAVEL_LEFT_MM - 0.5) * MM, IN[1] + 25 * MM), 0.3),
    # too flat: a sideways drag along the top edge
    (IN, (IN[0] - 41 * MM, IN[1] + 20 * MM), 0.3),
    # too slow: a deliberate pan from the corner
    (IN, (IN[0] - 10 * MM, IN[1] + 25 * MM), sm.MAX_DURATION_S + 0.05),
], ids=["tap", "vertical-scroll", "pan-below-strip", "pan-left-of-corner",
        "down-right", "up-left", "short-down", "short-left", "too-flat",
        "too-slow"])
def test_rejects(start, end, dt):
    rec, clock = _rec()
    assert not _swipe(rec, clock, start, end, dt)


def test_coalesced_drag_is_judged_by_its_release_point():
    # xcb merges motion under load: press, (no moves), release far away
    rec, clock = _rec()
    rec.press(*IN, sm.MOUSE)
    clock.t += 0.2
    assert rec.release(IN[0] - 10 * MM, IN[1] + 25 * MM, sm.MOUSE)


def test_touch_and_its_synthesized_mouse_open_once():
    rec, clock = _rec()
    end = (IN[0] - 10 * MM, IN[1] + 25 * MM)
    rec.press(*IN, sm.TOUCH)
    rec.press(*IN, sm.MOUSE)            # the synthesized twin: ignored
    clock.t += 0.3
    assert rec.release(*end, sm.TOUCH)
    assert not rec.release(*end, sm.MOUSE)   # its twin's release: no second open


def test_synthesized_mouse_first_owns_the_contact_too():
    rec, clock = _rec()
    end = (IN[0] - 10 * MM, IN[1] + 25 * MM)
    rec.press(*IN, sm.MOUSE)
    rec.press(*IN, sm.TOUCH)
    clock.t += 0.3
    assert not rec.release(*end, sm.TOUCH)
    assert rec.release(*end, sm.MOUSE)


def test_a_second_finger_cancels_and_the_twin_cannot_restart_it():
    # a pinch whose first finger lands in the corner
    rec, clock = _rec()
    end = (IN[0] - 10 * MM, IN[1] + 25 * MM)
    rec.press(*IN, sm.TOUCH)
    rec.cancel(sm.TOUCH)
    rec.press(*IN, sm.MOUSE)            # the twin may not take over
    clock.t += 0.3
    assert not rec.release(*end, sm.MOUSE)
    assert not rec.release(*end, sm.TOUCH)


def test_a_lost_release_does_not_wedge_the_recogniser():
    rec, clock = _rec()
    rec.press(*IN, sm.TOUCH)            # its release never arrives
    clock.t += 2 * sm.MAX_DURATION_S + 0.1
    assert _swipe(rec, clock, IN, (IN[0] - 10 * MM, IN[1] + 25 * MM),
                  source=sm.MOUSE)


def test_a_press_outside_the_zone_then_a_swipe_shape_is_rejected():
    # the recogniser keeps no memory across contacts
    rec, clock = _rec()
    assert not _swipe(rec, clock, (100, 300), (50, 500))
    assert _swipe(rec, clock, IN, (IN[0] - 10 * MM, IN[1] + 25 * MM))


# ---------------------------------------------------------------------------
# the window: real Qt events, a fake screen set
# ---------------------------------------------------------------------------

class _FakeScreen(QObject):
    screenShow = pyqtSignal()
    screenHide = pyqtSignal()

    def __init__(self, name, obj=None):
        super().__init__()
        self.name = name
        self.object = obj

    def show(self):
        if self.object is not None:
            self.object.show()
        self.screenShow.emit()

    def hide(self):
        if self.object is not None:
            self.object.hide()
        self.screenHide.emit()


class _Window(QWidget):
    """The parts of gui.Main the menu uses."""

    def __init__(self, screens, running=0):
        super().__init__()
        self.screens = screens
        self.running_screen = running
        self.shown = []
        self.screenDiagonalInches = None

    def showScreen(self, name):
        for i, s in enumerate(self.screens):
            if s.name == name:
                if i != self.running_screen:
                    s.show()
                    self.screens[self.running_screen].hide()
                    self.running_screen = i
                self.shown.append(name)
                return
        raise KeyError(name)


NAMES = ["PFD", "EMS", "MAP", "DataStatus", "About"]


@pytest.fixture
def ui(qtbot, tmp_path):
    screens = [_FakeScreen(n) for n in NAMES]
    win = _Window(screens)
    qtbot.addWidget(win)
    win.resize(W, H)
    status = tmp_path / "status.json"
    ds = DataStatus(win, status_path=str(status), continue_screen="PFD")
    ab = AboutSystem(win, status_path=str(status), back_screen="DataStatus")
    ds.hide()
    ab.hide()
    screens[3].object = ds
    screens[4].object = ab
    # a control sitting in the top-right corner, as on the stock PFD
    corner_btn = QPushButton("BTN", win)
    corner_btn.setGeometry(W - 60, 0, 60, 40)
    clicks = []
    corner_btn.clicked.connect(lambda: clicks.append(1))
    win.show()
    qtbot.waitExposed(win)
    menu = sm.initialize(win, _NoKeyFix(), screens)
    assert menu is not None
    # pin the geometry so the event coordinates below mean the same mm
    menu.swipe.rec.px_per_mm = PPM
    yield win, menu, ds, ab, clicks
    QApplication.instance().removeEventFilter(menu.swipe)


class _NoKeyFix:
    class db:
        @staticmethod
        def get_item(key, *a, **k):
            raise KeyError(key)


def _mouse(win, kind, x, y, button=Qt.MouseButton.LeftButton):
    t = {"press": QEvent.Type.MouseButtonPress,
         "move": QEvent.Type.MouseMove,
         "release": QEvent.Type.MouseButtonRelease}[kind]
    buttons = button if kind != "release" else Qt.MouseButton.NoButton
    p = QPointF(x, y)
    ev = QMouseEvent(t, p, p, win.mapToGlobal(p), button, buttons,
                     Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(win.windowHandle(), ev)


_DEV = None


def _touch_dev():
    global _DEV
    if _DEV is None:
        _DEV = QPointingDevice(
            "test-ts", 4242, QInputDevice.DeviceType.TouchScreen,
            QPointingDevice.PointerType.Finger,
            QInputDevice.Capability.Position, 10, 0)
    return _DEV


def _touch(win, kind, *pts):
    t = {"begin": QEvent.Type.TouchBegin, "update": QEvent.Type.TouchUpdate,
         "end": QEvent.Type.TouchEnd}[kind]
    state = {"begin": QEventPoint.State.Pressed,
             "update": QEventPoint.State.Updated,
             "end": QEventPoint.State.Released}[kind]
    points = [QEventPoint(i, state, QPointF(x, y), QPointF(x, y))
              for i, (x, y) in enumerate(pts)]
    ev = QTouchEvent(t, _touch_dev(), Qt.KeyboardModifier.NoModifier, points)
    QApplication.sendEvent(win.windowHandle(), ev)


START = (W - 10 * MM, 3 * MM)
END = (START[0] - 10 * MM, START[1] + 25 * MM)


def _flush(qtbot):
    qtbot.wait(20)


def test_mouse_swipe_opens_the_menu(ui, qtbot):
    win, menu, *_ = ui
    assert not menu.isVisible()
    _mouse(win, "press", *START)
    _mouse(win, "move", *END)
    _mouse(win, "release", *END)
    qtbot.waitUntil(menu.isVisible, timeout=1000)
    assert set(menu.buttons) == {"Data Status", "About", "Screens", "Close"}


def test_touch_swipe_opens_the_menu(ui, qtbot):
    win, menu, *_ = ui
    _touch(win, "begin", START)
    _touch(win, "update", END)
    _touch(win, "end", END)
    qtbot.waitUntil(menu.isVisible, timeout=1000)


def test_pinch_starting_in_the_corner_does_not_open(ui, qtbot):
    win, menu, *_ = ui
    # Qt interleaves the first finger's synthesized mouse twin
    _touch(win, "begin", START)
    _mouse(win, "press", *START)
    _touch(win, "update", START, (START[0] - 200, 300))
    _touch(win, "end", END, (START[0] - 300, 400))
    _mouse(win, "release", *END)
    _flush(qtbot)
    assert not menu.isVisible()


def test_pinch_whose_second_finger_lifts_first_does_not_open(ui, qtbot):
    # the contact ends with one point, on the swipe's end point
    win, menu, *_ = ui
    _touch(win, "begin", START)
    _mouse(win, "press", *START)
    _touch(win, "update", START, (START[0] - 200, 300))
    _touch(win, "update", END)
    _touch(win, "end", END)
    _mouse(win, "release", *END)
    _flush(qtbot)
    assert not menu.isVisible()


def test_map_style_pan_does_not_open(ui, qtbot):
    win, menu, *_ = ui
    _mouse(win, "press", W - 200, 200)
    _mouse(win, "move", W - 300, 400)
    _mouse(win, "release", W - 300, 400)
    _flush(qtbot)
    assert not menu.isVisible()


def test_vertical_scroll_from_the_corner_does_not_open(ui, qtbot):
    win, menu, *_ = ui
    _mouse(win, "press", *START)
    _mouse(win, "release", START[0], START[1] + 60 * MM)
    _flush(qtbot)
    assert not menu.isVisible()


def test_tap_on_the_corner_control_still_clicks_it_and_opens_nothing(ui, qtbot):
    win, menu, _ds, _ab, clicks = ui
    qtbot.mouseClick(win.windowHandle(), Qt.MouseButton.LeftButton,
                     pos=win.rect().topRight() + type(win.rect().topRight())(-20, 10))
    _flush(qtbot)
    assert clicks == [1]
    assert not menu.isVisible()


def test_the_filter_never_consumes(ui):
    win, menu, *_ = ui
    ev = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(*START),
                     QPointF(*START), Qt.MouseButton.LeftButton,
                     Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    assert menu.swipe.eventFilter(win.windowHandle(), ev) is False


def test_events_for_other_objects_are_ignored(ui, qtbot):
    win, menu, *_ = ui
    other = QWidget()
    qtbot.addWidget(other)
    for kind, pos in (("press", START), ("release", END)):
        t = (QEvent.Type.MouseButtonPress if kind == "press"
             else QEvent.Type.MouseButtonRelease)
        ev = QMouseEvent(t, QPointF(*pos), QPointF(*pos),
                         Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier)
        menu.swipe.eventFilter(other, ev)
    _flush(qtbot)
    assert not menu.isVisible()


# ---------------------------------------------------------------------------
# the overlay
# ---------------------------------------------------------------------------

def _click(button):
    button.click()


def test_close_button_closes(ui, qtbot):
    _win, menu, *_ = ui
    menu.open_menu()
    _click(menu.buttons["Close"])
    assert not menu.isVisible()


def test_tap_outside_the_card_closes_and_on_the_card_does_not(ui, qtbot):
    _win, menu, *_ = ui
    win = _win
    menu.open_menu()
    card = menu.panel.geometry()
    # through the window, so Qt hit-tests the card the way a finger does
    qtbot.mouseClick(win.windowHandle(), Qt.MouseButton.LeftButton,
                     pos=card.bottomLeft() + type(card.bottomLeft())(5, -5))
    assert menu.isVisible()
    qtbot.mouseClick(win.windowHandle(), Qt.MouseButton.LeftButton,
                     pos=type(card.topLeft())(10, menu.height() - 10))
    assert not menu.isVisible()


def test_card_sits_top_right_inside_the_window(ui):
    _win, menu, *_ = ui
    menu.open_menu()
    card = menu.panel.geometry()
    assert menu.rect().contains(card)
    assert card.right() > menu.width() * 0.9
    assert card.top() < menu.height() * 0.1


def test_idle_timeout_closes(qtbot, tmp_path):
    screens = [_FakeScreen("PFD")]
    win = _Window(screens)
    qtbot.addWidget(win)
    win.resize(W, H)
    win.show()
    menu = sm.SystemMenu(win, screens, idle_s=0.15, px_per_mm=PPM)
    menu.open_menu()
    assert menu.isVisible()
    qtbot.waitUntil(lambda: not menu.isVisible(), timeout=2000)


def test_activity_restarts_the_idle_timer(qtbot):
    screens = [_FakeScreen("PFD")]
    win = _Window(screens)
    qtbot.addWidget(win)
    win.resize(W, H)
    win.show()
    menu = sm.SystemMenu(win, screens, idle_s=0.3, px_per_mm=PPM)
    menu.open_menu()
    for _ in range(4):
        qtbot.wait(150)
        _click(menu.buttons.get("Screens") or menu.buttons["Back"])
        assert menu.isVisible()
    qtbot.waitUntil(lambda: not menu.isVisible(), timeout=2000)


def test_screens_page_lists_flight_screens_and_switches(ui, qtbot):
    win, menu, *_ = ui
    menu.open_menu()
    _click(menu.buttons["Screens"])
    assert [n for n in menu.buttons if n != "Back"] == ["PFD", "EMS", "MAP"]
    assert menu.isVisible()
    _click(menu.buttons["MAP"])
    assert not menu.isVisible()
    assert win.screens[win.running_screen].name == "MAP"


def test_screens_page_back_returns_to_the_main_page(ui):
    _win, menu, *_ = ui
    menu.open_menu()
    _click(menu.buttons["Screens"])
    _click(menu.buttons["Back"])
    assert set(menu.buttons) == {"Data Status", "About", "Screens", "Close"}


def test_opening_releases_panel_wide_knob_focus(ui):
    from pyefis.instruments import edit_focus

    class _Holder:
        released = 0

        def release_focus(self):
            self.released += 1
            edit_focus.release(self)

        def focus_hit(self, pos):
            return False

    _win, menu, *_ = ui
    holder = _Holder()
    edit_focus.claim(holder)
    try:
        menu.open_menu()
        assert holder.released == 1
        assert edit_focus.owner() is None
    finally:
        edit_focus.release(holder)


def test_reopening_always_starts_on_the_main_page(ui):
    _win, menu, *_ = ui
    menu.open_menu()
    _click(menu.buttons["Screens"])
    menu.close_menu()
    menu.open_menu()
    assert "Data Status" in menu.buttons


# ---------------------------------------------------------------------------
# entries reach their screen and come back
# ---------------------------------------------------------------------------

@pytest.fixture
def actions(ui):
    win = ui[0]
    hmi.initialize({})
    hmi.actions.showScreen.connect(win.showScreen)
    yield hmi.actions
    hmi.actions.showScreen.disconnect(win.showScreen)


def test_data_status_continue_returns_to_where_the_pilot_was(ui, actions):
    win, menu, ds, _ab, _ = ui
    win.showScreen("EMS")
    menu.open_menu()
    _click(menu.buttons["Data Status"])
    assert win.screens[win.running_screen].name == "DataStatus"
    assert not menu.isVisible()
    ds._on_continue()                       # the Continue button's slot
    assert win.screens[win.running_screen].name == "EMS"
    # and the configured target is back for the annunciation route
    assert ds.continue_screen == "PFD"


def test_about_back_returns_to_where_the_pilot_was(ui, actions):
    win, menu, ds, ab, _ = ui
    win.showScreen("MAP")
    menu.open_menu()
    _click(menu.buttons["About"])
    assert win.screens[win.running_screen].name == "About"
    ab.btn_back.click()
    assert win.screens[win.running_screen].name == "MAP"
    assert ab.back_screen == "DataStatus"


def test_about_from_data_status_still_goes_back_to_data_status(ui, actions):
    # menu -> Data Status -> its own About button -> Back -> Continue
    win, menu, ds, ab, _ = ui
    win.showScreen("EMS")
    menu.open_menu()
    _click(menu.buttons["Data Status"])
    ds._on_about()
    assert win.screens[win.running_screen].name == "About"
    ab.btn_back.click()
    assert win.screens[win.running_screen].name == "DataStatus"
    ds._on_continue()
    assert win.screens[win.running_screen].name == "EMS"


def test_menu_opened_on_data_status_keeps_the_configured_targets(ui, actions):
    win, menu, ds, ab, _ = ui
    win.showScreen("DataStatus")
    menu.open_menu()
    _click(menu.buttons["About"])
    assert ab.back_screen == "DataStatus"
    assert ds.continue_screen == "PFD"


def test_data_status_from_the_menu_on_about_continues_to_the_flight_screen(
        ui, actions):
    win, menu, ds, ab, _ = ui
    win.showScreen("About")
    menu.open_menu()
    _click(menu.buttons["Data Status"])
    assert ds.continue_screen == "PFD"
    ds._on_continue()
    assert win.screens[win.running_screen].name == "PFD"


def test_leaving_by_the_screens_page_restores_the_targets(ui, actions):
    win, menu, ds, _ab, _ = ui
    win.showScreen("EMS")
    menu.open_menu()
    _click(menu.buttons["Data Status"])
    assert ds.continue_screen == "EMS"
    menu.open_menu()
    _click(menu.buttons["Screens"])
    _click(menu.buttons["MAP"])
    assert ds.continue_screen == "PFD"


def test_a_missing_screen_is_logged_not_raised(ui, caplog):
    win, menu, *_ = ui
    with caplog.at_level(logging.WARNING, logger="pyefis.system_menu"):
        menu.go_screen("NOPE")
    assert "no screen named 'NOPE'" in caplog.text


# ---------------------------------------------------------------------------
# the bus key
# ---------------------------------------------------------------------------

def _menu_key(fix):
    fix.db.define_item(sm.MENU_KEY, "Open the system menu", "bool", None, None,
                       "", 0, "")
    item = fix.db.get_item(sm.MENU_KEY)
    item.value = False
    item.bad = item.fail = False
    return item


def _bus_window(qtbot):
    screens = [_FakeScreen("PFD"), _FakeScreen("DataStatus")]
    win = _Window(screens)
    qtbot.addWidget(win)
    win.resize(W, H)
    win.show()
    qtbot.waitExposed(win)
    return win, screens


def test_setting_the_bus_key_opens_the_menu(fix, qtbot):
    item = _menu_key(fix)
    win, screens = _bus_window(qtbot)
    menu = sm.initialize(win, fix, screens)
    try:
        assert not menu.isVisible()
        item.value = True
        assert menu.isVisible()
        item.value = False                  # the release: stays open
        assert menu.isVisible()
        menu.close_menu()
        item.value = True
        item.value = False                  # a press and release while closed
        menu.close_menu()
        item.value = False                  # a write of false never opens it
        assert not menu.isVisible()
        item.value = True                   # the next press opens it again
        assert menu.isVisible()
    finally:
        QApplication.instance().removeEventFilter(menu.swipe)


def test_a_key_already_true_at_start_does_not_open(fix, qtbot):
    item = _menu_key(fix)
    item.value = True
    win, screens = _bus_window(qtbot)
    menu = sm.initialize(win, fix, screens)
    try:
        assert not menu.isVisible()
    finally:
        QApplication.instance().removeEventFilter(menu.swipe)


def test_a_missing_key_leaves_the_swipe_working(qtbot, caplog):
    win, screens = _bus_window(qtbot)
    with caplog.at_level(logging.WARNING, logger="pyefis.system_menu"):
        menu = sm.initialize(win, _NoKeyFix(), screens)
    try:
        assert "has no SYSMENU" in caplog.text
        menu.swipe.rec.px_per_mm = PPM
        _mouse(win, "press", *START)
        _mouse(win, "release", *END)
        qtbot.waitUntil(menu.isVisible, timeout=1000)
    finally:
        QApplication.instance().removeEventFilter(menu.swipe)


def test_initialize_never_raises(caplog):
    with caplog.at_level(logging.ERROR, logger="pyefis.system_menu"):
        assert sm.initialize(object(), _NoKeyFix(), []) is None
    assert "could not build the menu" in caplog.text
