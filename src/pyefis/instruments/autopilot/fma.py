#  SPDX-License-Identifier: GPL-2.0-or-later
"""The `ap_annunciator` instrument (AFC4): the autopilot mode annunciation
strip across the top of the attitude display.

    [ AP  YD ] [ HDG   GPS ] [ VS +500   ALT ]
                 active armed  active+target armed

Three groups, AP/YD | lateral | vertical by default: Bill, AER-5808
(2026-11-16), "AP YD first ... matches unwritten convention from
competitors". ``ap_position: center`` puts AP/YD between lateral and vertical
instead, the left-to-right order of the control head's groups (AFC3; AC
25.1329-1C 43.b(4), p.41, positions annunciations like their controls). Active
modes are green, armed modes white and in their own place (44.c(1), (2) and
(4), p.41-42; AC 25-11B Table 5-1, p.43).

- A change of active mode -- including armed to active, a reversion, and the
  start of altitude capture -- is boxed and flashes for ``mode_flash_s``
  seconds (AC 25.1329-1C 44.d(1)-(2), p.42: "boxing and flashing ... for
  example, ten seconds").
- ``APDISC`` (an autopilot disconnect, any cause) flashes a red boxed ``AP``
  for as long as the source holds the flag. The latch is the source's (AFC1):
  this strip never times it out, and every display clears together. A tap on
  the strip acknowledges it -- ``APCMD`` ``DISC`` -- but only while the flag is
  set and the autopilot reads disengaged, so the tap can never disconnect
  anything.
- Only reported state is drawn (brief section 3). When any state key goes old,
  bad or failed the strip shows ``NO AP DATA`` instead (brief section 5.7),
  amber if the autopilot was engaged at the last fresh reading, grey if not.
  Before any source has been seen, and on a gateway without the AFC1 keys, the
  strip is empty: an aircraft with no autopilot gets no permanent caption.

The vertical target is shown only where the contract names it: ``VS`` with
``VSSEL``, ``IAS`` with ``IASSEL``, ``ALT`` with ``APALTREF``, the altitude the
autopilot reports it is holding (Bill, AER-5808: not ``ALTSEL``, which the
pilot may already have turned to the next altitude). A target key that is
missing, old, bad or failed shows the mode alone, never a guessed number:
``ALT`` is never filled in from ``ALTSEL``. Capture (``APALTCAP``) shows
``ALT CAP``; the ``ALTSEL`` box on the altimeter tape carries the number.
"""

import logging
import time

from PyQt6.QtCore import QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from pyefis.instruments.autopilot import state as apstate
from pyefis.instruments.helpers import bugs

logger = logging.getLogger(__name__)

ROLE_ACTIVE = "active"
ROLE_ARMED = "armed"
ROLE_WARNING = "warning"
ROLE_NODATA = "nodata"
ROLE_NODATA_CAUTION = "nodata_caution"

NO_DATA_TEXT = "NO AP DATA"
CAPTURE_TEXT = "ALT CAP"
#: The capture pseudo-mode, for change detection only.
_CAPTURE = "ALTCAP"

#: The altitude ALT hold is holding (fix-gateway autopilot.yaml). Optional: a
#: gateway or source without it shows ``ALT`` alone.
ALT_REF_KEY = "APALTREF"

DEFAULT_FLASH_S = 10.0
#: Half-period of the flash: text on 0.5 s, off 0.5 s.
BLINK_HALF_S = 0.5

SLOTS = ("lat", "lat_arm", "ap", "yd", "vert", "vert_arm")
#: Worst-case text per slot: the font is sized to fit these, so it does not
#: jump as modes change.
TEMPLATES = {"lat": "LOC", "lat_arm": "LOC GPS", "ap": "AP", "yd": "YD",
             "vert": "ALT 18000", "vert_arm": "ALT GS"}


class Cell:
    __slots__ = ("text", "role", "boxed", "blink")

    def __init__(self, text, role, boxed=False, blink=False):
        self.text = text
        self.role = role
        self.boxed = boxed
        self.blink = blink

    def __repr__(self):
        return "Cell(%r, %r, boxed=%r, blink=%r)" % (
            self.text, self.role, self.boxed, self.blink)


def format_vs(fpm):
    fpm = int(round(fpm))
    return "VS %+d" % fpm if fpm else "VS 0"


def format_ias(kt):
    return "IAS %d" % int(round(kt))


def format_alt(ft):
    return "ALT %d" % int(round(ft))


class FMAModel:
    """What the strip shows, apart from Qt painting.

    ``clock`` returns seconds (monotonic); tests pass their own. ``targets``
    maps a vertical mode to a :class:`bugs.BugBinding` for its target key."""

    def __init__(self, ap, targets=None, clock=time.monotonic,
                 flash_s=DEFAULT_FLASH_S):
        self.ap = ap
        self.targets = targets or {}
        self.clock = clock
        self.flash_s = flash_s
        self._last = None          # (lat, vert) of the last fresh reading
        self._flash_until = {"lat": 0.0, "vert": 0.0}
        self.observe()

    def _vert_key(self):
        return _CAPTURE if self.ap.capturing else self.ap.vertical

    def observe(self):
        """Record a reading. A new non-empty active mode starts its flash. The
        first fresh reading is a baseline, not a change. Back from no data,
        the reading is compared with the last one the pilot saw: a mode that
        changed while the strip was blank flashes, an unchanged one does
        not."""
        if not self.ap.fresh:
            self._flash_until = {"lat": 0.0, "vert": 0.0}
            return
        now = self.clock()
        cur = (self.ap.lateral, self._vert_key())
        if self._last is not None:
            for i, slot in enumerate(("lat", "vert")):
                if cur[i] != self._last[i] and cur[i]:
                    self._flash_until[slot] = now + self.flash_s
                elif not cur[i]:
                    self._flash_until[slot] = 0.0
        self._last = cur

    def flashing(self, slot, now=None):
        now = self.clock() if now is None else now
        return now < self._flash_until.get(slot, 0.0)

    @property
    def disconnect(self):
        return self.ap.fresh and bool(self.ap.value("APDISC"))

    def animating(self, now=None):
        """Does anything on the strip still flash (the widget's timer)?"""
        if self.disconnect:
            return True
        now = self.clock() if now is None else now
        return any(self.flashing(s, now) for s in ("lat", "vert"))

    def _vertical_text(self):
        if self.ap.capturing:
            return CAPTURE_TEXT
        mode = self.ap.vertical
        binding = self.targets.get(mode)
        if binding is not None and binding.state == bugs.STATE_OK:
            if mode == "VS":
                return format_vs(binding.value)
            if mode == "IAS":
                return format_ias(binding.value)
            if mode == "ALT":
                return format_alt(binding.value)
        return mode

    def cells(self, now=None):
        """``{slot: Cell}`` for the slots that show something, or
        ``{"nodata": Cell}``; empty when there is nothing to show."""
        ap = self.ap
        if not ap.available:
            return {}
        if not ap.fresh:
            if not ap.seen_live:
                return {}
            role = ROLE_NODATA_CAUTION if ap.last_engaged else ROLE_NODATA
            return {"nodata": Cell(NO_DATA_TEXT, role)}
        now = self.clock() if now is None else now
        out = {}
        if self.disconnect:
            out["ap"] = Cell("AP", ROLE_WARNING, boxed=True, blink=True)
        elif ap.value("APENG"):
            out["ap"] = Cell("AP", ROLE_ACTIVE)
        if ap.value("YDENG"):
            out["yd"] = Cell("YD", ROLE_ACTIVE)
        if ap.lateral:
            f = self.flashing("lat", now)
            out["lat"] = Cell(ap.lateral, ROLE_ACTIVE, boxed=f, blink=f)
        if ap.lateral_armed:
            out["lat_arm"] = Cell(" ".join(ap.lateral_armed), ROLE_ARMED)
        if ap.vertical or ap.capturing:
            f = self.flashing("vert", now)
            out["vert"] = Cell(self._vertical_text(), ROLE_ACTIVE,
                               boxed=f, blink=f)
        if ap.vertical_armed:
            out["vert_arm"] = Cell(" ".join(ap.vertical_armed), ROLE_ARMED)
        return out

    def can_acknowledge(self):
        """A disconnect alert the pilot may clear from here: set, and the
        autopilot disengaged, so ``DISC`` acknowledges and cannot also
        disconnect (AFC1: ``DISC`` while engaged disconnects)."""
        return self.disconnect and not self.ap.value("APENG")


class ModeAnnunciator(QWidget):
    def __init__(self, parent=None, font_family="DejaVu Sans Condensed",
                 font_percent=None, clock=time.monotonic):
        super().__init__(parent)
        self.font_family = font_family
        self.font_percent = font_percent
        # Panel options (InstrumentSpec Props in screenbuilder_factory).
        self.ap_position = "left"
        self.mode_flash_s = DEFAULT_FLASH_S
        self.touch_ack = True
        self.active_color = "#00ff00"
        self.armed_color = "#ffffff"
        self.warning_color = "#ff0000"
        self.background_color = "#000000"
        self.background_opacity = 0.75

        self.ap = apstate.APState(parent=self)
        self.targets = {"VS": bugs.BugBinding("VSSEL", self),
                        "IAS": bugs.BugBinding("IASSEL", self),
                        "ALT": bugs.BugBinding(ALT_REF_KEY, self)}
        self.model = FMAModel(self.ap, self.targets, clock=clock,
                              flash_s=self.mode_flash_s)
        self.ap.changed.connect(self._on_state)
        for b in self.targets.values():
            b.changed.connect(self.update)
        self._timer = QTimer(self)
        self._timer.setInterval(int(BLINK_HALF_S * 1000 / 2))
        self._timer.timeout.connect(self._tick)

    @property
    def mode_flash_s(self):
        return self._mode_flash_s

    @mode_flash_s.setter
    def mode_flash_s(self, value):
        # Applied by apply_options after construction, so pass it through.
        self._mode_flash_s = float(value)
        model = getattr(self, "model", None)
        if model is not None:
            model.flash_s = self._mode_flash_s

    def _on_state(self):
        self.model.observe()
        self._sync_timer()
        self.update()

    def _sync_timer(self):
        if self.model.animating():
            if not self._timer.isActive():
                self._timer.start()
        elif self._timer.isActive():
            self._timer.stop()

    def _tick(self):
        self._sync_timer()
        self.update()

    # -- layout -----------------------------------------------------------
    def slot_rects(self):
        """``{slot: QRectF}``: three groups, each split active | armed."""
        w, h = float(self.width()), float(self.height())
        groups = [("lat", 0.34), ("ap", 0.20), ("vert", 0.46)]
        if self.ap_position != "center":
            groups = [groups[1], groups[0], groups[2]]
        rects = {}
        x = 0.0
        for name, frac in groups:
            gw = w * frac
            if name == "ap":
                rects["ap"] = QRectF(x, 0.0, gw / 2.0, h)
                rects["yd"] = QRectF(x + gw / 2.0, 0.0, gw / 2.0, h)
            else:
                aw = gw * 0.55
                rects[name] = QRectF(x, 0.0, aw, h)
                rects[name + "_arm"] = QRectF(x + aw, 0.0, gw - aw, h)
            x += gw
        return rects

    def group_dividers(self):
        w = float(self.width())
        first = 0.34 if self.ap_position == "center" else 0.20
        return [w * first, w * 0.54]

    def _font(self, px):
        font = QFont(self.font_family)
        font.setPixelSize(max(1, int(px)))
        font.setBold(True)
        return font

    def _fit_px(self, device, text, width, px):
        for _ in range(40):
            fm = QFontMetricsF(self._font(px), device)
            if fm.horizontalAdvance(text) <= width or px <= 4.0:
                break
            px = max(4.0, px - 1.0)
        return px

    def _color(self, role):
        return {ROLE_ACTIVE: QColor(self.active_color),
                ROLE_ARMED: QColor(self.armed_color),
                ROLE_WARNING: QColor(self.warning_color),
                ROLE_NODATA: QColor(bugs.BUG_DEGRADED_COLOR),
                ROLE_NODATA_CAUTION: QColor(bugs.BUG_ALERT_COLOR)}[role]

    def paintEvent(self, event):
        cells = self.model.cells()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not cells:
            p.end()
            return
        bg = QColor(self.background_color)
        bg.setAlphaF(max(0.0, min(1.0, float(self.background_opacity))))
        p.fillRect(self.rect(), bg)
        h = float(self.height())
        scale = self.font_percent if self.font_percent else 1.0
        rects = self.slot_rects()
        pad = h * 0.12
        if "nodata" in cells:
            cell = cells["nodata"]
            r = QRectF(self.rect())
            px = self._fit_px(p.device(), cell.text, r.width() - 2 * pad,
                              h * 0.6 * scale)
            p.setFont(self._font(px))
            p.setPen(QPen(self._color(cell.role)))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, cell.text)
            p.end()
            return
        divider = QColor(bugs.BUG_DEGRADED_COLOR)
        p.setPen(QPen(divider, max(1.0, h * 0.04)))
        for x in self.group_dividers():
            p.drawLine(int(x), int(h * 0.15), int(x), int(h * 0.85))
        px = h * 0.6 * scale
        for slot in SLOTS:
            px = self._fit_px(p.device(), TEMPLATES[slot],
                              rects[slot].width() - 2 * pad, px)
        on = int(self.model.clock() / BLINK_HALF_S) % 2 == 0
        for slot, cell in cells.items():
            r = rects[slot]
            color = self._color(cell.role)
            cpx = self._fit_px(p.device(), cell.text, r.width() - 2 * pad, px)
            font = self._font(cpx)
            p.setFont(font)
            if cell.boxed:
                fm = QFontMetricsF(font, p.device())
                bw = min(r.width() - pad, fm.horizontalAdvance(cell.text) + 2 * pad)
                bh = min(h - 2.0, fm.height() + pad)
                box = QRectF(r.center().x() - bw / 2.0, (h - bh) / 2.0, bw, bh)
                p.setPen(QPen(color, max(1.0, h * 0.06)))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(box)
            if cell.blink and not on:
                continue
            p.setPen(QPen(color))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, cell.text)
        p.end()

    # -- tap: acknowledge a disconnect ------------------------------------
    def acknowledge(self):
        """Send ``DISC`` to clear a disconnect alert. Writes nothing unless
        :meth:`FMAModel.can_acknowledge`."""
        if not (self.touch_ack and self.model.can_acknowledge()):
            return False
        return apstate.send_request("DISC")

    def mousePressEvent(self, event):
        if self.acknowledge():
            event.accept()
            return
        super().mousePressEvent(event)
