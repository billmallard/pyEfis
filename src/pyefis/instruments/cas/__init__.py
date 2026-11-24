#  SPDX-License-Identifier: GPL-2.0-or-later
"""Crew alerting (CAS3, CAP-119): the ``cas_window`` and ``cas_marker``
instruments, and the ``CAS NOT SHOWN`` cue.

makerplane brief ``briefs/crew_alerting.md`` sections 6.1 to 6.5; spec
``docs/cas_widget_spec.md``. The gateway's ``cas`` plugin decides every alert;
these widgets draw its sorted list (:mod:`.model`) and add the alerts only a
display can see.

- **Window** (``cas_window``, the PFD): one line per message, in its level's
  colour, warnings on top. An unacknowledged line flashes; an acknowledged one
  is steady. With no message it draws nothing. More messages than ``lines``:
  the last row is ``+k`` in the colour of the most urgent hidden line.
- **Marker** (``cas_marker``, every other screen): one tile naming and
  colouring the highest active level, flashing while anything is
  unacknowledged. Empty when there is no message.
- **Touch.** On the window: acknowledge (``CASACK``) while anything shown is
  unacknowledged, otherwise open the full list; the ``+k`` row always opens
  it. On the marker: open the full list. On the full list: acknowledge, then
  close.

Every window, marker and list in one display reads one :class:`model.CASModel`
(:func:`shared_model`), so an acknowledge on the PFD stops the flash on the
marker too, and the local alerts are acknowledged once per display.

Lines are drawn with the shared lamp tile (:mod:`pyefis.instruments.tile`,
ANN1), so a caution reads the same here as on an annunciator.
"""

import logging
import os
import time

from PyQt6.QtCore import QEvent, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QPainter
from PyQt6 import sip
from PyQt6.QtWidgets import QWidget

import pyavtools.fix as fix

from pyefis import fix_watchdog
from pyefis.instruments import tile as tiles
from pyefis.instruments.cas import model as cm
from pyefis.instruments.helpers import font_scale

log = logging.getLogger(__name__)

DEFAULT_STATUS_PATH = "~/.makerplane/pyefis/status.json"
#: How often the list is read and the widgets repaint: a quarter of the flash
#: half-period, so a new message is drawn within 125 ms of reaching pyEfis.
POLL_MS = 125
#: status.json is rewritten by the updater, a few times a flight at most.
STATUS_RELOAD_S = 10.0
#: The full list closes itself after this long without a touch.
LIST_TIMEOUT_S = 20.0

TILE_LEVEL = {cm.WARNING: tiles.WARNING, cm.CAUTION: tiles.CAUTION,
              cm.ADVISORY: tiles.ADVISORY}
MARKER_TEXT = {cm.WARNING: "WARNING", cm.CAUTION: "CAUTION",
               cm.ADVISORY: "ADVISORY"}


class StatusReader:
    """status.json, re-read at most every STATUS_RELOAD_S. Never raises."""

    def __init__(self, path=DEFAULT_STATUS_PATH, clock=time.monotonic):
        self.path = path
        self.clock = clock
        self._at = None
        self._status = None

    def __call__(self):
        now = self.clock()
        if self._at is None or now - self._at >= STATUS_RELOAD_S:
            self._at = now
            self._status = _load_status(self.path)
        return self._status


def _load_status(path):
    import json
    try:
        with open(os.path.expanduser(str(path)), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _lookup(key):
    return fix.db.get_item(key, wait=False)


def _link_lost():
    return fix_watchdog.link_lost()


_shared = None


def shared_model(status_path=DEFAULT_STATUS_PATH):
    """The one CAS model of this display. The first widget built names the
    status.json path; a later one naming another path is logged and shares
    the first (one display, one updater)."""
    global _shared
    if _shared is None:
        _shared = PolledModel(cm.CASModel(_lookup, link_lost=_link_lost,
                                          status=StatusReader(status_path)))
    elif os.path.expanduser(status_path) != os.path.expanduser(
            _shared.model.status.path):
        log.warning("CAS: status_path %s ignored; this display reads %s",
                    status_path, _shared.model.status.path)
    return _shared


def reset_shared_model():
    """Forget the shared model (tests)."""
    global _shared
    _shared = None


class PolledModel:
    """Polls the model at most once per POLL_MS, however many widgets ask."""

    def __init__(self, model, clock=time.monotonic):
        self.model = model
        self.clock = clock
        self._at = None

    def poll(self):
        now = self.clock()
        if self._at is None or now - self._at >= POLL_MS / 1000.0 * 0.9:
            self._at = now
            self.model.poll()
        return self.model


class _CASWidget(QWidget):
    """What the window, the marker and the full list share: options, the
    poll timer, colours and the tile drawing."""

    def __init__(self, parent=None, font_family="DejaVu Sans Condensed",
                 font_percent=None, model=None, clock=time.monotonic):
        super().__init__(parent)
        self.font_family = font_family
        self.font_percent = font_percent
        # Panel options (InstrumentSpec Props in screenbuilder_factory).
        self.status_path = DEFAULT_STATUS_PATH
        self.warning_color = tiles.DEFAULT_COLORS[tiles.WARNING]
        self.caution_color = tiles.DEFAULT_COLORS[tiles.CAUTION]
        self.advisory_color = tiles.DEFAULT_COLORS[tiles.ADVISORY]
        self.background_color = "#000000"
        self.background_opacity = 0.75
        self.clock = clock
        self._polled = model
        self._shown = None
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    @property
    def model(self):
        if self._polled is None:
            # Built on first use, after apply_options has set status_path.
            self._polled = shared_model(self.status_path)
        return self._polled.model

    def refresh(self):
        """Poll the shared model; repaint when what is drawn changed, and on
        every tick while anything flashes."""
        if self._polled is None:
            self.model
        self._polled.poll()
        state = self.drawn_state()
        if state != self._shown:
            if self.logs_changes:
                log.info("CAS: %s shows %s", self.objectName() or
                         type(self).__name__, self.describe(state))
            self._shown = state
            self.update()
        elif self.model.unacked():
            self.update()
        # Quiet, the widget draws nothing and lets every touch through to
        # what it overlays (the AI, or the slot placement B shares).
        quiet = self.quiet()
        if quiet != self.testAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents):
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents,
                              quiet)

    def quiet(self):
        return not self.model.messages()

    #: Log each change to what is drawn (window and marker; the full list
    #: only mirrors the window). Kept to changes, never per tick.
    logs_changes = True

    @staticmethod
    def describe(state):
        if not state:
            return "nothing"
        if isinstance(state, tuple):
            return "{} {}".format(state[0], "flashing" if state[2] else "steady")
        return "; ".join("{}{} {}".format(
            cm.LEVEL_NAMES[lvl], "" if acked else " unacked", line)
            for lvl, acked, _id, line in state)

    def _tick(self):
        try:
            self.refresh()
        except Exception:
            # A fault in the alerting display must not stop the process or
            # the other instruments. A fault reading the list is CAS FAIL in
            # the model (FHA CAS-4); one here, past the read, shows as a
            # frozen window, and is logged once per tick so it cannot pass
            # unnoticed.
            log.exception("CAS: poll failed")

    def drawn_state(self):
        return [(m.level, m.acked, m.id, m.line) for m in self.model.messages()]

    def colors(self):
        return {tiles.WARNING: self.warning_color,
                tiles.CAUTION: self.caution_color,
                tiles.ADVISORY: self.advisory_color}

    def tile_for(self, m):
        return tiles.Tile(m.line, TILE_LEVEL[m.level], flash=not m.acked)

    def _background(self, p, rect):
        bg = QColor(self.background_color)
        bg.setAlphaF(max(0.0, min(1.0, float(self.background_opacity))))
        p.fillRect(rect, bg)

    def open_full_list(self):
        return CASList.open_over(self)


def _hidden_tile(hidden):
    top = max(m.level for m in hidden)
    return tiles.Tile("+{}".format(len(hidden)), TILE_LEVEL[top],
                      flash=any(not m.acked for m in hidden))


class CASWindow(_CASWidget):
    """The CAS window (``cas_window``)."""

    #: Marks a CAS surface for the "CAS NOT SHOWN" check in gui.py, which must
    #: not import this module (it is not primary-flight core).
    cas_surface = True

    def __init__(self, parent=None, font_family="DejaVu Sans Condensed",
                 font_percent=None, model=None, clock=time.monotonic):
        super().__init__(parent, font_family, font_percent, model, clock)
        self.lines = 4

    def rows(self):
        """``[(Tile, kind)]`` top to bottom; kind is "line" or "more". At most
        ``lines`` rows: past that the last row is ``+k`` for the k hidden,
        counting messages beyond the twelve slots too."""
        msgs = self.model.messages()
        n = max(1, int(self.lines))
        total = max(self.model.count(), len(msgs))
        if total <= n:
            return [(self.tile_for(m), "line") for m in msgs]
        shown = msgs[:n - 1]
        # Hidden lines beyond the twelve slots are the least urgent of all,
        # so the slots' hidden lines (or failing those, the last slot) give
        # the +k its colour.
        hidden = msgs[n - 1:] or msgs[-1:]
        more = _hidden_tile(hidden)
        more.text = "+{}".format(total - len(shown))
        return [(self.tile_for(m), "line") for m in shown] + [(more, "more")]

    def row_rects(self):
        n = max(1, int(self.lines))
        h = self.height() / float(n)
        return [QRectF(0.0, i * h, float(self.width()), h) for i in range(n)]

    def paintEvent(self, event):
        rows = self.rows()
        if not rows:
            return                      # quiet: the window draws nothing
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rects = self.row_rects()
        used = QRectF(0.0, 0.0, float(self.width()),
                      rects[len(rows) - 1].bottom())
        self._background(p, used)
        pad = max(1.0, rects[0].height() * 0.08)
        boxes = [r.adjusted(pad, pad / 2.0, -pad, -pad / 2.0) for r in rects]
        px = tiles.fit_px(p.device(), self.font_family,
                          [t.text for t, _ in rows] + ["GATEWAY LINK LOST"],
                          boxes[0].width() - 4 * pad, boxes[0].height() * 0.8,
                          boxes[0].height() * 0.7 * font_scale(self.font_percent))
        now = self.clock()
        for (t, kind), box in zip(rows, boxes):
            tiles.paint_tile(p, box, t, colors=self.colors(),
                             family=self.font_family, px=px,
                             border_px=max(1.0, box.height() * 0.06), now=now,
                             align=Qt.AlignmentFlag.AlignLeft
                             | Qt.AlignmentFlag.AlignVCenter,
                             flash_blank=False)
        p.end()

    def row_at(self, y):
        rows = self.rows()
        for (t, kind), r in zip(rows, self.row_rects()):
            if r.top() <= y < r.bottom():
                return kind
        return None

    def press(self, y):
        """A touch at height *y*: acknowledge, or open the full list.
        Returns "ack", "list" or None."""
        kind = self.row_at(y)
        if kind is None and not self.rows():
            return None
        if kind == "more":
            self.open_full_list()
            return "list"
        if self.model.unacked() and self.model.acknowledge():
            self.refresh()
            return "ack"
        if self.rows():
            self.open_full_list()
            return "list"
        return None

    def mousePressEvent(self, event):
        if self.press(event.position().y()) is not None:
            event.accept()
            return
        super().mousePressEvent(event)


class CASMarker(_CASWidget):
    """The compact marker (``cas_marker``): the highest active level."""

    cas_surface = True

    def marker_tile(self):
        level = self.model.top_level()
        if level == 0:
            return None
        return tiles.Tile(MARKER_TEXT[level], TILE_LEVEL[level],
                          flash=self.model.unacked())

    def drawn_state(self):
        t = self.marker_tile()
        return None if t is None else (t.text, t.level, t.flash)

    def paintEvent(self, event):
        t = self.marker_tile()
        if t is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        self._background(p, r)
        pad = max(1.0, r.height() * 0.06)
        box = r.adjusted(pad, pad, -pad, -pad)
        px = tiles.fit_px(p.device(), self.font_family,
                          list(MARKER_TEXT.values()),
                          box.width() - 4 * pad, box.height() * 0.8,
                          box.height() * 0.6 * font_scale(self.font_percent))
        tiles.paint_tile(p, box, t, colors=self.colors(),
                         family=self.font_family, px=px,
                         border_px=max(1.0, box.height() * 0.08),
                         now=self.clock(), flash_blank=False)
        p.end()

    def press(self):
        if self.marker_tile() is None:
            return None
        self.open_full_list()
        return "list"

    def mousePressEvent(self, event):
        if self.press() is not None:
            event.accept()
            return
        super().mousePressEvent(event)


class CASList(_CASWidget):
    """The full list, opened over the whole display by a touch on the
    window's ``+k`` row or on a marker (brief 6.1, 6.3). Every message, up
    to the twelve slots plus the local alerts, and ``+k`` for any the slots
    cannot hold. A touch acknowledges; a touch with nothing to acknowledge,
    or LIST_TIMEOUT_S without one, closes it."""

    ROWS = 16
    logs_changes = False

    def quiet(self):
        return False

    def __init__(self, parent=None, font_family="DejaVu Sans Condensed",
                 font_percent=None, model=None, clock=time.monotonic):
        super().__init__(parent, font_family, font_percent, model, clock)
        self.background_opacity = 0.9
        self._close = QTimer(self)
        self._close.setSingleShot(True)
        self._close.setInterval(int(LIST_TIMEOUT_S * 1000))
        self._close.timeout.connect(self.close)
        if parent is not None:
            parent.installEventFilter(self)

    @classmethod
    def open_over(cls, widget):
        top = widget.window()
        existing = getattr(top, "_cas_list", None)
        if existing is not None and not sip.isdeleted(existing):
            existing.raise_()
            existing._close.start()
            return existing
        lst = cls(top, font_family=widget.font_family,
                  font_percent=widget.font_percent, model=widget._polled,
                  clock=widget.clock)
        for name in ("warning_color", "caution_color", "advisory_color"):
            setattr(lst, name, getattr(widget, name))
        lst.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        # Forgotten in closeEvent. Never from the destroyed signal: that fires
        # while the parent itself may be mid-destruction, and touching it
        # then crashes the process.
        top._cas_list = lst
        lst.fit_to_parent()
        lst.show()
        lst.raise_()
        lst._close.start()
        return lst

    def eventFilter(self, obj, event):
        if obj is self.parentWidget() and event.type() == QEvent.Type.Resize:
            self.fit_to_parent()
        return False

    def fit_to_parent(self):
        p = self.parentWidget()
        if p is None:
            return
        w, h = p.size().width(), p.size().height()
        lw, lh = int(w * 0.6), int(h * 0.8)
        self.setGeometry(int((w - lw) / 2), int((h - lh) / 2), lw, lh)

    def rows(self):
        msgs = self.model.messages()
        out = [(self.tile_for(m), "line") for m in msgs[:self.ROWS - 1]]
        beyond = self.model.count() - len(out)
        if beyond > 0:
            more = tiles.Tile("+{} NOT LISTED".format(beyond), tiles.ADVISORY)
            out.append((more, "more"))
        return out

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        self._background(p, r)
        p.setPen(QColor(tiles.DEFAULT_COLORS[tiles.ADVISORY]))
        p.drawRect(r.adjusted(0.5, 0.5, -0.5, -0.5))
        rows = self.rows()
        h = r.height() / float(self.ROWS)
        pad = max(1.0, h * 0.08)
        if not rows:
            rows = [(tiles.Tile("NO MESSAGES", tiles.OFF), "line")]
        boxes = [QRectF(pad, i * h + pad / 2.0, r.width() - 2 * pad,
                        h - pad) for i in range(len(rows))]
        px = tiles.fit_px(p.device(), self.font_family,
                          [t.text for t, _ in rows],
                          boxes[0].width() - 4 * pad, boxes[0].height() * 0.8,
                          boxes[0].height() * 0.7 * font_scale(self.font_percent))
        now = self.clock()
        for (t, _), box in zip(rows, boxes):
            tiles.paint_tile(p, box, t, colors=self.colors(),
                             family=self.font_family, px=px,
                             border_px=max(1.0, box.height() * 0.06), now=now,
                             align=Qt.AlignmentFlag.AlignLeft
                             | Qt.AlignmentFlag.AlignVCenter,
                             flash_blank=False)
        p.end()

    def closeEvent(self, event):
        top = self.parentWidget()
        if top is not None and getattr(top, "_cas_list", None) is self:
            top._cas_list = None
        super().closeEvent(event)

    def press(self):
        self._close.start()
        if self.model.unacked() and self.model.acknowledge():
            self.refresh()
            return "ack"
        self.close()
        return "close"

    def mousePressEvent(self, event):
        self.press()
        event.accept()


class CASNotShownCue(QWidget):
    """``CAS NOT SHOWN`` (brief 6.4, C2): the CAS keys are live but no screen
    carries a window or a marker, so no alert can reach the pilot. Drawn over
    every screen, transparent to touch, as an advisory tile; logged as an
    error when it first shows. gui.py builds it through the instrument table
    only once the keys are live, so a panel without CAS never imports this
    module."""

    def __init__(self, parent, font_family="DejaVu Sans Condensed",
                 model=None):
        super().__init__(parent)
        self.font_family = font_family
        self._polled = model or shared_model()
        self._logged = False
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        parent.installEventFilter(self)
        self.fit_to_parent()
        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        self.refresh()

    @property
    def active(self):
        return self._polled.model.list_ok

    def refresh(self):
        self._polled.poll()
        active = self.active
        if active and not self._logged:
            self._logged = True
            log.error("CAS NOT SHOWN: the CAS keys are live but no screen "
                      "carries a cas_window or cas_marker; no alert can "
                      "reach the pilot")
        self.setVisible(active)
        if active:
            self.raise_()

    def eventFilter(self, obj, event):
        if obj is self.parentWidget() and event.type() == QEvent.Type.Resize:
            self.fit_to_parent()
        return False

    def fit_to_parent(self):
        p = self.parentWidget()
        if p is None:
            return
        w, h = p.size().width(), p.size().height()
        bh = max(22, int(h * 0.05))
        bw = max(bh * 7, int(w * 0.22))
        # Bottom centre: the top band holds the DEMO strip and LINK MON OFF.
        self.setGeometry(int((w - bw) / 2), h - bh - 4, bw, bh)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        p.fillRect(r, QColor(0, 0, 0, 220))
        t = tiles.Tile("CAS NOT SHOWN", tiles.ADVISORY)
        px = tiles.fit_px(p.device(), self.font_family, [t.text],
                          r.width() - 8, r.height() * 0.8, r.height() * 0.6)
        tiles.paint_tile(p, r, t, family=self.font_family, px=px,
                         border_px=2.0)
        p.end()
