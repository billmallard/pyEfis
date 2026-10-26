#  SPDX-License-Identifier: GPL-2.0-or-later
"""The `nav_status` instrument (FP7, billmallard/pyEfis#189): the GNX 375's
from-to-next field (Pilot's Guide 190-02488-01 Rev. B, 3-41/3-42) as a
one-line chip.

    [LEG] KSBA > GVO > RZS   12.4 NM  0:06  TERM

``WPFROM`` -> ``WPNAME`` (the TO waypoint, active colour) -> ``WPNEXT``, a
``FPLSTATE`` badge (LEG / DIRECT / SUSP, none while no plan is active),
optional ``WPDIS`` / ``WPETE`` and the flight phase (``FPLPHASE``, green;
yellow for ``LOI``). A missing ident is drawn as underscores. A tap fires the
``flightplan page fpl`` HMI action so the flight_plan instrument opens its FPL
page; ``tap_screen`` optionally switches to the screen that holds it first.

Reads only engine outputs (fix-gateway ``flightplan`` plugin, brief section
3.3); it owns no FIX keys and never writes. Construct-never-raises: a key the
gateway does not define is treated as permanently absent (the graceful-
missing-key convention in ``ai/__init__.py``), so the chip draws underscores
rather than failing the screen build.

Quality: ``fail`` on a numeric field draws a red ``XXX`` in that field;
``old`` (the engine stopped publishing) greys the whole chip; ``bad`` greys a
field and ``WPETE`` bad (ground speed under 30 kt) is drawn as ``--:--``.
While ``FPLPHASE`` is ``VECTORS`` the engine publishes no distance or time
(it writes 0 with no flag), so both fields are blank rather than "0.0 NM".
"""

import logging

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from pyavtools import fix
from pyefis import hmi

logger = logging.getLogger(__name__)

# FPLSTATE (Appendix A): 0 NONE, 1 LEG, 2 DIRECT, 3 SUSP.
STATE_LABELS = {1: "LEG", 2: "DIRECT", 3: "SUSP"}

NAV_KEYS = ("FPLSTATE", "FPLPHASE", "WPFROM", "WPNAME", "WPNEXT", "WPDIS",
            "WPETE")

MISSING_IDENT = "____"
FAIL_TEXT = "XXX"
BAD_ETE = "--:--"
SEPARATOR = ">"
TEMPLATE_IDENT = "WWWWW"

_GREY = QColor("#808080")
_FAIL = QColor("#ff0000")
_PHASE = QColor("#00ff00")
_PHASE_LOI = QColor("#ffff00")
_BADGE_COLORS = {"LEG": QColor("#ffffff"), "DIRECT": QColor("#ff00ff"),
                 "SUSP": QColor("#ffff00")}


def format_distance(nm):
    return "%.1f NM" % nm if nm < 100.0 else "%.0f NM" % nm


def format_ete(seconds):
    # H:MM, the flight_plan FPL page's ETE format (FlightPlan._fmt_ete).
    seconds = int(seconds)
    return "%d:%02d" % (seconds // 3600, (seconds % 3600) // 60)


class NavStatus(QWidget):
    def __init__(self, parent=None, font_family="DejaVu Sans Condensed",
                 font_percent=None):
        super(NavStatus, self).__init__(parent)
        self.font_family = font_family
        self.font_percent = font_percent
        # Panel options (InstrumentSpec Props in screenbuilder_factory).
        self.show_distance = True
        self.show_ete = True
        self.show_phase = True
        self.hmi_group = ""
        self.tap_screen = ""
        self.active_color = "#ff00ff"
        self.text_color = "#ffffff"

        self._items = {}
        for key in NAV_KEYS:
            try:
                item = fix.db.get_item(key)
            except KeyError:
                logger.warning("nav_status: FIX key %s not defined by the "
                               "gateway; the chip shows it as absent", key)
                continue
            self._items[key] = item
            item.valueChanged[item.dtype].connect(self._changed)
            item.oldChanged.connect(self._changed)
            item.badChanged.connect(self._changed)
            item.failChanged.connect(self._changed)

    @property
    def available(self):
        return all(k in self._items for k in NAV_KEYS)

    def _changed(self, *_):
        self.update()

    # -- model ------------------------------------------------------------
    def _read(self, key):
        """(value, old, bad, fail) for a key; an undefined key reads as
        (None, False, False, False)."""
        item = self._items.get(key)
        if item is None:
            return None, False, False, False
        return item.value, item.old, item.bad, item.fail

    def fields(self):
        """The chip's content as a list of (text, QColor) runs plus the
        badge. Factored out of paintEvent so tests can assert what is drawn
        without scraping pixels."""
        text = QColor(self.text_color)
        active = QColor(self.active_color)

        state, state_old, _, _ = self._read("FPLSTATE")
        stale = bool(state_old)
        badge = STATE_LABELS.get(state) if state is not None else None

        def ident(key):
            value, _, _, _ = self._read(key)
            value = (value or "").strip() if isinstance(value, str) else ""
            return value or MISSING_IDENT

        # No active leg: all three are underscores, whatever stale idents the
        # keys may still carry.
        if not badge:
            idents = [MISSING_IDENT] * 3
        else:
            idents = [ident("WPFROM"), ident("WPNAME"), ident("WPNEXT")]

        # Magenta means "the active TO waypoint"; underscores are not one.
        to_color = text if idents[1] == MISSING_IDENT else active
        runs = [(idents[0], text), (SEPARATOR, text), (idents[1], to_color),
                (SEPARATOR, text), (idents[2], text)]

        phase, _, _, _ = self._read("FPLPHASE")
        phase = phase.strip() if isinstance(phase, str) else ""
        vectors = phase == "VECTORS"

        data = []
        if self.show_distance and badge and not vectors:
            dis, _, bad, fail = self._read("WPDIS")
            if fail:
                data.append((FAIL_TEXT, _FAIL))
            elif dis is not None:
                data.append((format_distance(dis), _GREY if bad else text))
        if self.show_ete and badge and not vectors:
            ete, _, bad, fail = self._read("WPETE")
            if fail:
                data.append((FAIL_TEXT, _FAIL))
            elif bad:
                data.append((BAD_ETE, _GREY))
            elif ete is not None:
                data.append((format_ete(ete), text))
        if self.show_phase and phase:
            data.append((phase, _PHASE_LOI if phase == "LOI" else _PHASE))

        if stale:
            runs = [(t, _GREY) for t, _ in runs]
            data = [(t, _GREY) for t, _ in data]
        return badge, runs, data, stale

    # -- paint ------------------------------------------------------------
    def _font(self, px):
        font = QFont(self.font_family)
        font.setPixelSize(max(1, int(px)))
        font.setBold(True)
        return font

    def _layout(self, fm, badge, runs, data):
        """Place every run left to right; returns ([(x, width, text, color,
        is_badge)], right edge). paintEvent lays out once at the nominal size
        to measure, then again at the fitted size to draw."""
        space = fm.horizontalAdvance(" ")
        out = []
        x = 0.0
        if badge:
            bw = fm.horizontalAdvance(badge) + space * 2
            out.append((x, bw, badge, None, True))
            x += bw + space * 2
        for text, color in runs:
            adv = fm.horizontalAdvance(text)
            out.append((x, adv, text, color, False))
            x += adv + space
        x += space * 2
        for text, color in data:
            adv = fm.horizontalAdvance(text)
            out.append((x, adv, text, color, False))
            x += adv + space * 3
        return out, x - space * 3

    def _template(self):
        """Worst-case content for the enabled fields. The chip is sized to fit
        this, not the live text, so the font does not jump as idents, badge
        and phase change in flight."""
        runs = [(TEMPLATE_IDENT, None), (SEPARATOR, None)] * 2 + [(TEMPLATE_IDENT, None)]
        data = []
        if self.show_distance:
            data.append(("888.8 NM", None))
        if self.show_ete:
            data.append(("88:88", None))
        if self.show_phase:
            data.append(("0.30 NM", None))
        return "DIRECT", runs, data

    def _fit_px(self, device, avail, h, badge, runs, data):
        """Pixel size for the chip: the nominal size (font_percent of 60% of
        the height), reduced until the worst-case template fits ``avail``,
        then further only if the live content is wider still (an ident
        longer than the template). Text width is close to linear in pixel
        size but not exactly (hinting), so the ratio step is followed by 1 px
        steps until it fits."""
        scale = self.font_percent if self.font_percent else 1.0
        px = max(1.0, h * 0.6 * scale)
        for content in (self._template(), (badge, runs, data)):
            for _ in range(50):
                fm = QFontMetricsF(self._font(px), device)
                _, right = self._layout(fm, *content)
                if right <= avail or px <= 4.0:
                    break
                px = max(4.0, min(px - 1.0, px * avail / right))
        return px

    def paintEvent(self, event):
        badge, runs, data, stale = self.fields()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("#000000"))

        w, h = float(self.width()), float(self.height())
        margin = h * 0.15
        px = self._fit_px(p.device(), w - 2 * margin, h, badge, runs, data)
        font = self._font(px)
        p.setFont(font)
        fm = QFontMetricsF(font, p.device())
        bh = fm.height()
        placed, _ = self._layout(fm, badge, runs, data)
        for x, adv, text, color, is_badge in placed:
            x += margin
            if is_badge:
                color = _GREY if stale else _BADGE_COLORS[text]
                rect = QRectF(x, (h - bh) / 2.0, adv, bh)
                p.setPen(QPen(color, max(1.0, h * 0.04)))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(rect, bh * 0.2, bh * 0.2)
                p.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
                continue
            p.setPen(QPen(color))
            p.drawText(QRectF(x, 0.0, adv + 1.0, h),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       text)
        p.end()

    # -- tap --------------------------------------------------------------
    def mousePressEvent(self, event):
        if hmi.actions is None:
            return
        try:
            if self.tap_screen:
                hmi.actions.trigger("show screen", self.tap_screen)
            arg = "fpl %s" % self.hmi_group if self.hmi_group else "fpl"
            hmi.actions.trigger("flightplan page", arg)
        except Exception:
            logger.warning("nav_status: tap action failed", exc_info=True)
