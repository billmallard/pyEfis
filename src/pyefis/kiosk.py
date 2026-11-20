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
  script wants up, as ``SCREEN`` or ``SCREEN/TAB``. It joins the script at
  start and on a gateway reconnect, not only on a change. Any touch holds the panel
  where the attendee left it for ``idle_return_s``; then it rejoins the
  script at the page the script is on now.
* **The visitor reset** (kiosk only, DEMO12). The settings an attendee may
  change (brief 6.2: the HSI source tab, baro, the selected altitude, the
  map range) go back to configured show defaults at each loop restart
  (``DEMOLOOP`` moving), when the demo goes live, and on the idle return,
  so one visitor's VLOC tap does not leave the needle flagged for the next.
  pyEfis already writes these keys from the HSI, the altimeter and the map,
  so the kiosk writing them is the same writer, not a second one.
* **The touch lock** (kiosk only). :func:`locked` is read by the instruments
  that change installed state or the plan: the FPL page is read-only, the
  map banner hides Direct-To, Insert and Create WPT, the Data Status Update
  button is off, no keybindings load, and the ``exit`` and ``evaluate``
  actions are refused.

Config, a top-level ``kiosk:`` block in the pyEfis config::

    kiosk:
      enabled: true
      idle_return_s: 60
      defaults:          # the visitor reset; only VISITOR_KEYS are accepted
        NAVSRC: 2        # GPS
        BARO: 29.92
        ALTSEL: 3000
        MAPRANGE: 2      # ladder index (10 NM on the default ladder)

Absent or ``enabled: false`` is today's panel, unchanged except for the
marking. No ``defaults`` is no visitor reset. Like every FIX consumer here, a missing key is logged and the piece
that needs it stays off; nothing in this module raises into boot.
"""

import logging

from PyQt6.QtCore import QEvent, QObject, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QApplication, QWidget

log = logging.getLogger(__name__)

LIVE_KEY = "DEMOLIVE"
PAGE_KEY = "DEMOPAGE"
LOOP_KEY = "DEMOLOOP"
# The settings an attendee may change and the kiosk resets (brief 6.2). Only
# these: a key the demo or an engine writes must never get a second writer
# from a kiosk default.
VISITOR_KEYS = ("NAVSRC", "BARO", "ALTSEL", "MAPRANGE")
MARKING_TEXT = "DEMO -- simulated data"
DEFAULT_IDLE_RETURN_S = 60.0
# Actions an attendee must not reach from a button (brief 6.2).
LOCKED_ACTIONS = frozenset({"exit", "evaluate"})

_config = {"enabled": False, "idle_return_s": DEFAULT_IDLE_RETURN_S, "defaults": {}}
# What initialize() built, for the tests and for anyone who needs to look.
marking = None
follower = None
resetter = None


def configure(cfg):
    """Read the ``kiosk:`` block. Anything malformed is logged and leaves the
    kiosk off -- a typo must not lock a panel, nor take it down."""
    _config.update(enabled=False, idle_return_s=DEFAULT_IDLE_RETURN_S, defaults={})
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
    _config.update(enabled=bool(cfg.get("enabled", False)), idle_return_s=idle,
                   defaults=_parse_defaults(cfg.get("defaults")))
    if _config["enabled"]:
        log.info("kiosk: on, idle return %.0f s", idle)


def _parse_defaults(cfg):
    """``{key: number}`` for the visitor reset. An entry that is not a
    visitor key or not a number is logged and dropped; the rest stand, and
    the lock is unaffected."""
    if not cfg:
        return {}
    if not isinstance(cfg, dict):
        log.error("kiosk: defaults is not a mapping (%r); no visitor reset", cfg)
        return {}
    out = {}
    for key, value in cfg.items():
        if key not in VISITOR_KEYS:
            log.error("kiosk: defaults: %r is not one of %s; dropped",
                      key, " ".join(VISITOR_KEYS))
            continue
        try:
            if isinstance(value, bool):
                raise TypeError("a bool")
            out[key] = float(value)
        except (TypeError, ValueError):
            log.error("kiosk: defaults: %s: %r is not a number; dropped", key, value)
    return out


def locked():
    """True in kiosk mode: the touch lock applies."""
    return bool(_config["enabled"])


def idle_return_s():
    return _config["idle_return_s"]


def defaults():
    """The visitor reset's ``{key: value}``, a copy."""
    return dict(_config["defaults"])


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

    def __init__(self, window, item, idle_s, screens, on_idle_return=None):
        super().__init__(window)
        self.window = window
        self.item = item
        self.screens = screens
        self.on_idle_return = on_idle_return
        self.idle = QTimer(self)
        self.idle.setSingleShot(True)
        self.idle.setInterval(int(idle_s * 1000))
        self.idle.timeout.connect(self._idle_ran_out)
        self._bad = set()
        item.valueChanged[str].connect(self._on_page)
        # A reconnect re-reads the key, and when the value is the same it
        # clears fail with no change signal; rejoin on that too.
        item.failChanged.connect(self._on_fail)
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
        # valueChanged fires only on a change, so without this a pyEfis start
        # or restart would sit on its boot screen until the script next moved
        # (DEMO11). The screens exist by now: initialize() runs after them.
        self._on_page(item.value)

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

    def _on_fail(self, fail):
        if not fail:
            self._on_page(self.item.value)

    def _idle_ran_out(self):
        self.rejoin()
        if self.on_idle_return is not None:
            self.on_idle_return()

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


class VisitorReset(QObject):
    """Writes the configured show defaults to the visitor keys while the
    demo is live: when ``DEMOLOOP`` moves (a loop restart), when the demo
    goes live (``DEMOLIVE`` turning true and current, which is also a pyEfis
    start or a reconnect with the demo running), and on the page follower's
    idle return. With the demo not live it writes nothing."""

    def __init__(self, parent, fix, live_item, loop_item, values):
        super().__init__(parent)
        self.fix = fix
        self.live_item = live_item
        self.loop_item = loop_item
        self.values = {}
        for key, value in values.items():
            if _item(fix, key) is None:
                log.warning("kiosk: the database has no %s; it is not reset", key)
            else:
                self.values[key] = value
        self.resets = 0
        self._was_live = False
        for signal in (live_item.valueChanged[bool], live_item.oldChanged,
                       live_item.badChanged, live_item.failChanged):
            signal.connect(self._on_live)
        if loop_item is not None:
            loop_item.valueChanged[int].connect(self._on_loop)
        self._on_live()

    def live(self):
        i = self.live_item
        return bool(i.value) and not (i.old or i.bad or i.fail)

    def _on_live(self, *_):
        now = self.live()
        if now and not self._was_live:
            self.reset("demo live")
        self._was_live = now

    def _on_loop(self, *_):
        self.reset("loop restart")

    def idle_return(self):
        self.reset("idle return")

    def reset(self, why):
        """Write every default and send it to fix-gateway, as the HSI's own
        source tap does (pyEfis #294: set the value, then output it).
        Returns True if it wrote."""
        if not self.values or not self.live():
            return False
        for key, value in self.values.items():
            item = self.fix.db.get_item(key)
            item.value = value
            item.output_value()
        self.resets += 1
        log.info("kiosk: visitor settings reset (%s)", why)
        return True


def initialize(window, fix, screens):
    """Build the marking (always) and, in kiosk mode, the visitor reset and
    the page follower. Returns ``(marking, follower)``; either is None when
    it could not be built (the reset is in the module's ``resetter``).
    Never raises."""
    global marking, follower, resetter
    marking = follower = resetter = None
    try:
        live = _item(fix, LIVE_KEY)
        if live is None:
            log.info("kiosk: the database has no %s; no DEMO marking", LIVE_KEY)
        else:
            marking = DemoMarking(window, live)
    except Exception:
        log.error("kiosk: could not build the DEMO marking", exc_info=True)
    if locked() and _config["defaults"]:
        try:
            live = _item(fix, LIVE_KEY)
            if live is None:
                log.warning("kiosk: the database has no %s; no visitor reset", LIVE_KEY)
            else:
                loop = _item(fix, LOOP_KEY)
                if loop is None:
                    log.warning("kiosk: the database has no %s; visitor settings reset "
                                "only when the demo goes live and on the idle return",
                                LOOP_KEY)
                resetter = VisitorReset(window, fix, live, loop, _config["defaults"])
        except Exception:
            log.error("kiosk: could not build the visitor reset", exc_info=True)
    if locked():
        try:
            page = _item(fix, PAGE_KEY)
            if page is None:
                log.warning("kiosk: the database has no %s; the panel will not "
                            "follow the demo script", PAGE_KEY)
            else:
                follower = PageFollower(window, page, idle_return_s(), screens,
                                        resetter.idle_return if resetter else None)
        except Exception:
            log.error("kiosk: could not build the page follower", exc_info=True)
    return marking, follower
