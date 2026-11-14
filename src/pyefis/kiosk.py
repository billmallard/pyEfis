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

"""Demo kiosk (DEMO4, makerplane/briefs/demo_mode_redesign.md sections 4,
6.2 and 7).

Three pieces, each driven by the fix-gateway demo source's own keys
(fix-gateway ``database/demo.yaml``):

* **The DEMO marking.** A small permanent strip on top of every screen while
  ``DEMOLIVE`` is true and current. The demo writes it about once a second and
  it goes old two seconds after the last write, so the marking cannot be on
  without the demo. It is built on every install, kiosk or not: the glass
  says DEMO whenever the data is the demo's.
* **The page follower** (kiosk only). ``DEMOPAGE`` names the screen the demo
  script wants up, as ``SCREEN`` or ``SCREEN/TAB``. Any touch holds the panel
  where the attendee left it for ``idle_return_s``; then it rejoins the
  script at the page the script is on now.
* **The touch lock** (kiosk only). :func:`locked` is read by the instruments
  that change installed state or the plan: the FPL page is read-only, the
  map banner hides Direct-To, Insert and Create WPT, the Data Status Update
  button is off, no keybindings load, and the ``exit`` and ``evaluate``
  actions are refused.

Config, a top-level ``kiosk:`` block in the pyEfis config::

    kiosk:
      enabled: true
      idle_return_s: 60

Absent or ``enabled: false`` is today's panel, unchanged except for the
marking. Like every FIX consumer here, a missing key is logged and the piece
that needs it stays off; nothing in this module raises into boot.
"""

import logging

from PyQt6.QtCore import QEvent, QObject, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QApplication, QWidget

log = logging.getLogger(__name__)

LIVE_KEY = "DEMOLIVE"
PAGE_KEY = "DEMOPAGE"
MARKING_TEXT = "DEMO -- simulated data"
DEFAULT_IDLE_RETURN_S = 60.0
# Actions an attendee must not reach from a button (brief 6.2).
LOCKED_ACTIONS = frozenset({"exit", "evaluate"})

_config = {"enabled": False, "idle_return_s": DEFAULT_IDLE_RETURN_S}
# What initialize() built, for the tests and for anyone who needs to look.
marking = None
follower = None


def configure(cfg):
    """Read the ``kiosk:`` block. Anything malformed is logged and leaves the
    kiosk off -- a typo must not lock a panel, nor take it down."""
    _config.update(enabled=False, idle_return_s=DEFAULT_IDLE_RETURN_S)
    if not cfg:
        return
    if not isinstance(cfg, dict):
        log.error("kiosk: config is not a mapping (%r); kiosk off", cfg)
        return
    try:
        idle = float(cfg.get("idle_return_s", DEFAULT_IDLE_RETURN_S))
        if idle <= 0:
            raise ValueError("idle_return_s must be positive")
    except (TypeError, ValueError) as e:
        log.error("kiosk: bad idle_return_s (%s); kiosk off", e)
        return
    _config.update(enabled=bool(cfg.get("enabled", False)), idle_return_s=idle)
    if _config["enabled"]:
        log.info("kiosk: on, idle return %.0f s", idle)


def locked():
    """True in kiosk mode: the touch lock applies."""
    return bool(_config["enabled"])


def idle_return_s():
    return _config["idle_return_s"]


def action_allowed(action):
    """False for an action the kiosk lock refuses."""
    return not (locked() and str(action).strip().lower() in LOCKED_ACTIONS)


def _item(fix, key):
    try:
        return fix.db.get_item(key)
    except KeyError:
        return None


class DemoMarking(QWidget):
    """The permanent DEMO strip. Transparent to touch, stacked over every
    screen, refitted when the window resizes. How it looks is Bill's call
    (brief section 7, check 3)."""

    def __init__(self, parent, item, font_family="DejaVu Sans Condensed"):
        super().__init__(parent)
        self.item = item
        self.font_family = font_family
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        item.valueChanged[bool].connect(self._refresh)
        for signal in (item.oldChanged, item.badChanged, item.failChanged):
            signal.connect(self._refresh)
        parent.installEventFilter(self)
        self.fit_to_parent()
        self._refresh()

    def live(self):
        i = self.item
        return bool(i.value) and not (i.old or i.bad or i.fail)

    def _refresh(self, *_):
        if self.live():
            self.show()
            self.raise_()
        else:
            self.hide()

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
        w, h = p.size().width(), p.size().height()
        bh = max(18, int(h * 0.035))
        bw = max(bh * 9, int(w * 0.24))
        self.setGeometry(int((w - bw) / 2), 0, bw, bh)

    def paintEvent(self, event):
        qp = QPainter(self)
        qp.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        qp.setPen(QPen(QColor(255, 255, 255), 1))
        qp.setBrush(QColor(0, 0, 0, 190))
        qp.drawRoundedRect(r, 3, 3)
        font = QFont(self.font_family)
        font.setPixelSize(max(10, int(self.height() * 0.62)))
        font.setBold(True)
        qp.setFont(font)
        qp.drawText(r, Qt.AlignmentFlag.AlignCenter, MARKING_TEXT)


class PageFollower(QObject):
    """Shows the screen (and tab) ``DEMOPAGE`` names, except within
    ``idle_s`` of the last touch, and rejoins the script when that runs out."""

    INPUT_EVENTS = frozenset({
        QEvent.Type.MouseButtonPress, QEvent.Type.TouchBegin,
        QEvent.Type.Wheel, QEvent.Type.KeyPress,
    })

    def __init__(self, window, item, idle_s, screens):
        super().__init__(window)
        self.window = window
        self.item = item
        self.screens = screens
        self.idle = QTimer(self)
        self.idle.setSingleShot(True)
        self.idle.setInterval(int(idle_s * 1000))
        self.idle.timeout.connect(self.rejoin)
        self._bad = set()
        item.valueChanged[str].connect(self._on_page)
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() in self.INPUT_EVENTS:
            self.touched()
        return False

    def touched(self):
        self.idle.start()

    def holding(self):
        return self.idle.isActive()

    def _on_page(self, value):
        if not self.holding():
            self.apply(value)

    def rejoin(self):
        self.apply(self.item.value)

    def apply(self, value):
        """Show ``SCREEN`` or ``SCREEN/TAB``. Returns True if it did. An
        unknown name is logged once per value and otherwise ignored: a
        script typo must not move the panel somewhere surprising."""
        value = str(value or "").strip()
        if not value:
            return False
        screen, _, tab = value.partition("/")
        screen, tab = screen.strip(), tab.strip()
        try:
            self.window.showScreen(screen)
        except KeyError:
            self._warn(value, "no screen named {!r}".format(screen))
            return False
        if tab and not self._show_tab(screen, tab):
            self._warn(value, "screen {!r} has no tab labelled {!r}".format(screen, tab))
        return True

    def _show_tab(self, screen, label):
        from pyefis.instruments.tab_section import TabSection
        for s in self.screens:
            if s.name != screen:
                continue
            root = s.object
            sections = root.findChildren(TabSection)
            if isinstance(root, TabSection):
                sections.insert(0, root)
            return any(sec.show_tab_labelled(label) for sec in sections)
        return False

    def _warn(self, value, why):
        if value not in self._bad:
            self._bad.add(value)
            log.warning("kiosk: DEMOPAGE %r: %s; ignored", value, why)


def initialize(window, fix, screens):
    """Build the marking (always) and, in kiosk mode, the page follower.
    Returns ``(marking, follower)``; either is None when it could not be
    built. Never raises."""
    global marking, follower
    marking = follower = None
    try:
        live = _item(fix, LIVE_KEY)
        if live is None:
            log.info("kiosk: the database has no %s; no DEMO marking", LIVE_KEY)
        else:
            marking = DemoMarking(window, live)
    except Exception:
        log.error("kiosk: could not build the DEMO marking", exc_info=True)
    if locked():
        try:
            page = _item(fix, PAGE_KEY)
            if page is None:
                log.warning("kiosk: the database has no %s; the panel will not "
                            "follow the demo script", PAGE_KEY)
            else:
                follower = PageFollower(window, page, idle_return_s(), screens)
        except Exception:
            log.error("kiosk: could not build the page follower", exc_info=True)
    return marking, follower
