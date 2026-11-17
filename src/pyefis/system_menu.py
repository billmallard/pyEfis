#  Copyright (c) 2026 MakerPlane
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.

"""The system menu (BACKLOG MENU1): one route to Data Status, About and the
screen list from any flight screen, with nothing added to a panel.

Two ways in, one menu:

* **The corner swipe.** A one-finger swipe that starts in the top-right
  corner of the glass and moves down and to the left, the way iOS opens its
  control centre (Bill's ruling, 2026-11-16). :class:`CornerSwipe` is the
  recogniser; it is pure geometry, so its accept and reject cases are tested
  without Qt. The filter only watches -- it never consumes an event -- so a
  tap on a control in the corner still reaches that control.
* **The bus key.** A write of true to ``SYSMENU`` opens the same menu. It is
  a momentary command, like a button key: the writer (MENU1b's Tessera icon,
  a later encoder binding) writes true on the press and false on the release.
  pyEfis only reads it.

The menu is an overlay over whichever screen is up: Data Status, About,
Screens, Close. It closes on Close, on a tap outside its panel, or after
``IDLE_TIMEOUT_S`` with no touch on it. It works in flight and on the
ground: every entry is read-only or already safe in flight (Data Status's
Update button keeps its own rule).

Data Status and About opened from here come back to the screen the pilot
left: their Continue and Back are pointed at it for the trip, and put back
to their configured targets as soon as any other screen shows.

Like every FIX consumer here, a missing key is logged and the piece that
needs it stays off; nothing in this module raises into boot.
"""

import functools
import logging
import time

from PyQt6.QtCore import QEvent, QObject, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QPainter, QWindow
from PyQt6.QtWidgets import (QApplication, QGridLayout, QLabel, QPushButton,
                             QVBoxLayout, QWidget)

from pyefis import display_metrics
from pyefis.instruments import edit_focus

log = logging.getLogger(__name__)

MENU_KEY = "SYSMENU"
DATA_STATUS_SCREEN = "DataStatus"
ABOUT_SCREEN = "About"

# --- the corner swipe (settled in the MENU1 PR, brief 3.3.1) ---------------
# The start zone is a strip along the top edge at the right-hand corner. The
# height is the lever that keeps the swipe off the instruments: a finger has
# to land within 8 mm of the bezel, where no drag on a map, list or tape
# begins by accident. The width covers the corner a right thumb reaches.
CORNER_WIDTH_MM = 25.0
CORNER_HEIGHT_MM = 8.0
# On a small or low-density panel the millimetre zone must not swallow a
# large share of the glass.
CORNER_MAX_WIDTH_FRAC = 0.25
CORNER_MAX_HEIGHT_FRAC = 0.12
# Travel from the start point to the release point. Down is the main motion;
# the leftward part separates it from a vertical scroll (the FPL page) and
# from a plain downward drag. A swipe flatter than about 27 deg below the
# horizontal is a sideways drag, not this gesture.
TRAVEL_DOWN_MM = 15.0
TRAVEL_LEFT_MM = 4.0
MAX_LEFT_PER_DOWN = 2.0
# A swipe is quick; a slow drag from the corner is a pan.
MAX_DURATION_S = 1.5
# The menu closes itself after this long with no touch on it.
IDLE_TIMEOUT_S = 10.0

MOUSE = "mouse"
TOUCH = "touch"


class CornerSwipe:
    """Recognise the top-right corner swipe from press/release points.

    Coordinates are window pixels, y down. ``press`` starts a contact,
    ``release`` ends it and returns True when the contact was the gesture.
    Only the start and release points are judged, so a drag that Qt
    coalesces into press, one far move, release is the same swipe.

    Touch delivers each contact twice -- once as touch events, once as the
    mouse events Qt synthesizes from them -- so the first source to press
    owns the contact and the other is ignored until it ends. ``cancel``
    rejects the contact (a second finger: a pinch is never the swipe)."""

    def __init__(self, width, height, px_per_mm, clock=time.monotonic):
        self.px_per_mm = float(px_per_mm)
        self.clock = clock
        self.resize(width, height)
        self._source = None
        self._start = None
        self._t0 = 0.0

    def resize(self, width, height):
        self.width = float(width)
        self.height = float(height)

    def _mm(self, mm):
        return mm * self.px_per_mm

    def zone(self):
        """``(x0, y1)``: the start zone is ``x >= x0`` and ``y <= y1``."""
        w = min(self._mm(CORNER_WIDTH_MM), self.width * CORNER_MAX_WIDTH_FRAC)
        h = min(self._mm(CORNER_HEIGHT_MM), self.height * CORNER_MAX_HEIGHT_FRAC)
        return self.width - w, h

    def in_zone(self, x, y):
        x0, y1 = self.zone()
        return x >= x0 and 0 <= y <= y1 and x <= self.width

    def accepts(self, dx, dy, dt):
        """True when a contact that started in the zone and moved by
        ``(dx, dy)`` px in ``dt`` s is the swipe."""
        left = -dx
        return (dt <= MAX_DURATION_S
                and dy >= self._mm(TRAVEL_DOWN_MM)
                and left >= self._mm(TRAVEL_LEFT_MM)
                and left <= MAX_LEFT_PER_DOWN * dy)

    def press(self, x, y, source):
        now = self.clock()
        if (self._source is not None and source != self._source
                and now - self._t0 < 2 * MAX_DURATION_S):
            return     # the other stream of a contact already being tracked
        self._source = source
        self._t0 = now
        self._start = (x, y) if self.in_zone(x, y) else None

    def cancel(self, source=None):
        """Reject the current contact. It stays owned until it is released,
        so its other stream cannot restart it."""
        if source is None or source == self._source:
            self._start = None

    def release(self, x, y, source):
        if self._source is None or source != self._source:
            return False
        start, self._start, self._source = self._start, None, None
        if start is None:
            return False
        return self.accepts(x - start[0], y - start[1], self.clock() - self._t0)


def _point(event):
    # At the QWindow, scene coordinates are window coordinates, for mouse
    # events and touch points alike.
    try:
        return event.scenePosition()
    except AttributeError:   # pragma: no cover - older event types
        return None


class SwipeFilter(QObject):
    """Feeds the window's raw mouse and touch input to a :class:`CornerSwipe`
    and opens the menu on a recognised swipe. Watches the top-level QWindow,
    which sees each input event once, before any widget does. Never
    consumes an event."""

    def __init__(self, window, menu, recogniser):
        super().__init__(window)
        self.window = window
        self.menu = menu
        self.rec = recogniser

    def _ours(self, obj):
        handle = getattr(self.window, "windowHandle", None)
        return isinstance(obj, QWindow) and handle is not None and obj is handle()

    def eventFilter(self, obj, event):
        try:
            if self._ours(obj):
                self._feed(event)
        except Exception:
            log.debug("system menu: swipe filter error", exc_info=True)
        return False

    def _feed(self, event):
        t = event.type()
        T = QEvent.Type
        if t == T.MouseButtonPress:
            if event.button() == Qt.MouseButton.LeftButton:
                self._press(_point(event), MOUSE)
        elif t == T.MouseButtonRelease:
            if event.button() == Qt.MouseButton.LeftButton:
                self._release(_point(event), MOUSE)
        elif t == T.TouchBegin:
            pts = event.points()
            if len(pts) == 1:
                self._press(_point(pts[0]), TOUCH)
            else:
                self.rec.press(-1, -1, TOUCH)
        elif t == T.TouchUpdate:
            if len(event.points()) > 1:
                self.rec.cancel(TOUCH)
        elif t == T.TouchEnd:
            pts = event.points()
            if len(pts) == 1:
                self._release(_point(pts[0]), TOUCH)
            else:
                self.rec.cancel(TOUCH)
                self.rec.release(-1, -1, TOUCH)
        elif t == T.TouchCancel:
            self.rec.cancel(TOUCH)
            self.rec.release(-1, -1, TOUCH)

    def _press(self, pos, source):
        if pos is None or self.menu.isVisible():
            return
        size = self.window.size()
        self.rec.resize(size.width(), size.height())
        self.rec.press(pos.x(), pos.y(), source)

    def _release(self, pos, source):
        if pos is None:
            return
        if self.rec.release(pos.x(), pos.y(), source):
            log.info("system menu: opened by the corner swipe")
            # After the release has reached the widget under the finger.
            QTimer.singleShot(0, self.menu.open_menu)


_BTN_STYLE = (
    "QPushButton { color: #EEEEEE; background-color: #202830;"
    " border: 1px solid #4A5A6A; border-radius: 6px; padding: 0 12px; }"
    "QPushButton:pressed { background-color: #38444F; }"
)
_BTN_CURRENT_STYLE = (
    "QPushButton { color: #FFFFFF; background-color: #2C3A48;"
    " border: 2px solid #8FB4D8; border-radius: 6px; padding: 0 12px; }"
    "QPushButton:pressed { background-color: #38444F; }"
)


class _Panel(QWidget):
    """The menu card. A tap on it (not on a button) counts as activity and
    does not fall through to the scrim, which would close the menu."""

    def __init__(self, menu):
        super().__init__(menu)
        self.menu = menu
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("systemMenuPanel")
        self.setStyleSheet("#systemMenuPanel { background-color: #0B1015;"
                           " border: 1px solid #4A5A6A; border-radius: 10px; }")

    def mousePressEvent(self, event):
        self.menu.touched()
        event.accept()


class SystemMenu(QWidget):
    """The overlay: a dimmed full-window scrim with the menu card at the
    top-right, where the swipe starts. How it looks is Bill's call on the
    bench (MENU1)."""

    MAIN = "main"
    SCREENS = "screens"

    def __init__(self, window, screens, idle_s=IDLE_TIMEOUT_S,
                 font_family="DejaVu Sans", px_per_mm=None):
        super().__init__(window)
        self.window = window
        self.screens = screens
        self.font_family = font_family
        self.px_per_mm = px_per_mm or display_metrics.pixels_per_mm()
        self.page = self.MAIN
        self._cols = 1
        self.buttons = {}
        self._overrides = []    # [(widget, attr, configured value)]
        self.idle = QTimer(self)
        self.idle.setSingleShot(True)
        self.idle.setInterval(int(idle_s * 1000))
        self.idle.timeout.connect(self._idle_close)
        self.panel = _Panel(self)
        self._layout = QVBoxLayout(self.panel)
        for scr in screens:
            sig = getattr(scr, "screenShow", None)
            if sig is not None:
                sig.connect(functools.partial(self._screen_shown, scr.name))
        window.installEventFilter(self)
        self.hide()
        self.fit_to_parent()

    # --- geometry ---
    def eventFilter(self, obj, event):
        if obj is self.parentWidget() and event.type() == QEvent.Type.Resize:
            self.fit_to_parent()
        return False

    def fit_to_parent(self):
        p = self.parentWidget()
        if p is None:
            return
        # size(), not width()/height(): gui.initialize assigns plain ints over
        # mainWindow.width/height in windowed mode.
        self.setGeometry(0, 0, p.size().width(), p.size().height())
        self._place_panel()

    def _row_px(self):
        # A touch target at least 10 mm tall, never under 44 px.
        return max(44, int(round(self.px_per_mm * 10.0)))

    def _place_panel(self):
        w, h = self.width(), self.height()
        row = self._row_px()
        cols = self._cols
        pw = min(int(w * 0.9), max(int(row * 5.5) * cols, int(w * 0.28) * cols))
        self.panel.setFixedWidth(pw)
        ph = min(self._layout.totalSizeHint().height(), int(h * 0.94))
        margin = max(6, int(round(self.px_per_mm * 3)))
        self.panel.setGeometry(w - pw - margin, margin, pw, ph)

    # --- open / close ---
    def open_menu(self):
        """Show the main page over the current screen. Idempotent.

        Drops any panel-wide knob focus first: a swipe that starts on a
        touch-editable box (the altimeter tape's, in the corner on
        PFD_AI_ONLY) takes focus on the press, and the knob must not go on
        editing a value hidden under the menu."""
        held = edit_focus.owner()
        if held is not None:
            try:
                held.release_focus()
            except Exception:
                log.debug("system menu: release_focus failed", exc_info=True)
        self.show_page(self.MAIN)
        self.fit_to_parent()
        self.show()
        self.raise_()
        self.touched()

    def close_menu(self):
        self.idle.stop()
        self.hide()

    def _idle_close(self):
        log.info("system menu: closed after %.0f s idle", self.idle.interval() / 1000)
        self.close_menu()

    def touched(self):
        if self.isVisible():
            self.idle.start()

    def mousePressEvent(self, event):
        # Any press that reaches the overlay itself is outside the card.
        self.close_menu()
        event.accept()

    def paintEvent(self, event):
        qp = QPainter(self)
        qp.fillRect(QRectF(self.rect()), QColor(0, 0, 0, 120))

    # --- pages ---
    def _font(self, scale=0.42):
        f = QFont(self.font_family)
        f.setPixelSize(max(12, int(round(self._row_px() * scale))))
        return f

    def _clear(self):
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
            elif item.layout() is not None:
                lay = item.layout()
                while lay.count():
                    sub = lay.takeAt(0).widget()
                    if sub is not None:
                        sub.setParent(None)
                        sub.deleteLater()
        self.buttons = {}

    def _button(self, label, slot, current=False):
        b = QPushButton(label)
        b.setStyleSheet(_BTN_CURRENT_STYLE if current else _BTN_STYLE)
        b.setFont(self._font())
        b.setMinimumHeight(self._row_px())
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        b.clicked.connect(slot)
        self.buttons[label] = b
        return b

    def _title(self, text):
        t = QLabel(text)
        t.setFont(self._font(0.36))
        t.setStyleSheet("color:#969696;")
        self._layout.addWidget(t)

    def show_page(self, page):
        self._clear()
        self.page = page
        pad = max(8, int(round(self.px_per_mm * 2.5)))
        self._layout.setContentsMargins(pad, pad, pad, pad)
        self._layout.setSpacing(max(6, int(round(self.px_per_mm * 2))))
        if page == self.SCREENS:
            self._title("Screens")
            names = self.screen_names()
            running = self.running_name()
            grid = QGridLayout()
            grid.setSpacing(self._layout.spacing())
            cols = 2 if len(names) > 6 else 1
            self._cols = cols
            for i, name in enumerate(names):
                b = self._button(name, functools.partial(self.go_screen, name),
                                 current=(name == running))
                grid.addWidget(b, i // cols, i % cols)
            self._layout.addLayout(grid)
            self._layout.addWidget(self._button("Back", self._back))
        else:
            self._cols = 1
            self._title("System")
            for label, slot in (("Data Status", self.go_data_status),
                                ("About", self.go_about),
                                ("Screens", self._to_screens),
                                ("Close", self.close_menu)):
                self._layout.addWidget(self._button(label, slot))
        # Widgets added to a visible card are shown by a queued call, and a
        # layout sizes only visible widgets: show them now, so the card's
        # height counts them.
        for w in self.panel.findChildren(
                QWidget, options=Qt.FindChildOption.FindDirectChildrenOnly):
            w.show()
        if self.isVisible():
            self._place_panel()
        self.touched()

    def _to_screens(self):
        self.show_page(self.SCREENS)

    def _back(self):
        self.show_page(self.MAIN)

    # --- navigation ---
    def screen_names(self):
        """The screens the Screens page lists: every loaded screen except
        Data Status and About, which have their own entries."""
        return [s.name for s in self.screens
                if s.name not in (DATA_STATUS_SCREEN, ABOUT_SCREEN)]

    def running_name(self):
        idx = getattr(self.window, "running_screen", None)
        if isinstance(idx, int) and 0 <= idx < len(self.screens):
            return self.screens[idx].name
        return None

    def _show(self, name):
        try:
            self.window.showScreen(name)
            return True
        except KeyError:
            log.warning("system menu: no screen named %r", name)
            return False

    def go_screen(self, name):
        self.close_menu()
        self._show(name)

    def go_data_status(self):
        self._go_with_return(DATA_STATUS_SCREEN, "data_status", "DataStatus",
                             "continue_screen")

    def go_about(self):
        self._go_with_return(ABOUT_SCREEN, "about", "AboutSystem",
                             "back_screen")

    def _go_with_return(self, name, module, cls_name, attr):
        """Show ``name`` with its Continue/Back pointed at the screen the
        pilot left, for this trip only. From Data Status or About the
        configured targets stand (a trip that began there has no flight
        screen to return to)."""
        self.close_menu()
        origin = self.running_name()
        if origin is not None and origin not in (DATA_STATUS_SCREEN, ABOUT_SCREEN):
            self._restore()
            self._point_return(name, module, cls_name, attr, origin)
        self._show(name)

    def _point_return(self, name, module, cls_name, attr, origin):
        try:
            import importlib
            cls = getattr(importlib.import_module("pyefis.instruments." + module),
                          cls_name)
        except Exception:
            log.warning("system menu: cannot point %s back to %s", name, origin,
                        exc_info=True)
            return
        for scr in self.screens:
            if scr.name != name or scr.object is None:
                continue
            found = scr.object.findChildren(cls)
            if isinstance(scr.object, cls):
                found.insert(0, scr.object)
            for w in found:
                self._overrides.append((w, attr, getattr(w, attr, None)))
                setattr(w, attr, origin)

    def _restore(self):
        for w, attr, value in self._overrides:
            try:
                setattr(w, attr, value)
            except RuntimeError:   # the widget has gone with a rebuilt screen
                pass
        self._overrides = []

    def _screen_shown(self, name):
        if name not in (DATA_STATUS_SCREEN, ABOUT_SCREEN) and self._overrides:
            self._restore()

    # --- the bus key ---
    def on_key(self, value):
        if value:
            log.info("system menu: opened by %s", MENU_KEY)
            self.open_menu()


def initialize(window, fix, screens):
    """Build the menu, the corner swipe and the bus route. Returns the
    :class:`SystemMenu`, or None when it could not be built. Never raises."""
    try:
        diag = getattr(window, "screenDiagonalInches", None)
        size = window.size()
        handle = window.windowHandle()
        qscreen = handle.screen() if handle is not None else None
        ppm = display_metrics.pixels_per_mm(size.width(), size.height(), diag,
                                            qscreen)
        menu = SystemMenu(window, screens, px_per_mm=ppm)
    except Exception:
        log.error("system menu: could not build the menu", exc_info=True)
        return None
    try:
        rec = CornerSwipe(size.width(), size.height(), ppm)
        menu.swipe = SwipeFilter(window, menu, rec)
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(menu.swipe)
        x0, y1 = rec.zone()
        log.info("system menu: corner swipe on (start x >= %.0f, y <= %.0f px; "
                 "%.1f px/mm)", x0, y1, ppm)
    except Exception:
        log.error("system menu: could not install the corner swipe",
                  exc_info=True)
    try:
        item = fix.db.get_item(MENU_KEY)
    except KeyError:
        log.warning("system menu: the database has no %s; the bus route is "
                    "off (the corner swipe still opens the menu)", MENU_KEY)
        item = None
    except Exception:
        log.error("system menu: could not read %s", MENU_KEY, exc_info=True)
        item = None
    if item is not None:
        try:
            item.valueWrite[bool].connect(menu.on_key)
            menu.key_item = item
        except Exception:
            log.error("system menu: could not subscribe to %s", MENU_KEY,
                      exc_info=True)
    return menu
