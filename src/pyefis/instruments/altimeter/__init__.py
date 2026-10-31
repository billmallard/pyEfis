#  Copyright (c) 2013 Neil Domalik, 2018-2019 Garrett Herschleb
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

import logging
import math
import time

from PyQt6.QtGui import *
from PyQt6.QtCore import *
from PyQt6.QtWidgets import *

import pyavtools.fix as fix

from pyefis.instruments.NumericalDisplay import NumericalDisplay
import pyefis.hmi as hmi
from pyefis.instruments import edit_focus
from pyefis.instruments import helpers
from pyefis.instruments.helpers import bugs
from pyefis.instruments.altimeter import altsel

logger = logging.getLogger(__name__)

# Baro setting box (pyEfis #311). BARO is inHg on the bus in both display
# units; only the readout and the knob steps convert.
HPA_PER_INHG = 33.863889532610884
BARO_STD_INHG = 29.92
# Settable range, per docs/gcu_design.md (BARO: min 27.5, max 31.5), further
# narrowed by the FIX item's own min/max.
BARO_MIN_INHG = 27.5
BARO_MAX_INHG = 31.5
BARO_COLOR = QColor(0, 255, 255)  # pilot-selected value (gcu_design.md sec 3)

# The two settable boxes on the tape (see the enc_* dispatch).
EDIT_ALTSEL = "altsel"
EDIT_BARO = "baro"


class Altimeter(QWidget):
    FULL_WIDTH = 300

    def __init__(
        self, parent=None, bg_color=Qt.GlobalColor.black, font_family="DejaVu Sans Condensed"
    ):
        super(Altimeter, self).__init__(parent)
        # Transparent widget background so bg_opacity < 1 reveals what's behind.
        self.setStyleSheet("background: transparent; border: 0px")
        self.font_family = font_family
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._altimeter = 0
        self.bg_color = bg_color
        self.bg_opacity = 100  # percent (100 = solid, the default)
        self.item = fix.db.get_item("ALT")
        self.item.valueChanged[float].connect(self.setAltimeter)
        self.item.oldChanged[bool].connect(self.repaint)
        self.item.badChanged[bool].connect(self.repaint)
        self.item.failChanged[bool].connect(self.repaint)

        self.conversionFunction1 = lambda x: x
        self.conversionFunction2 = lambda x: x
        self.conversionFunction = lambda x: x

    def getRatio(self):
        # Return X for 1:x specifying the ratio for this instrument
        return 1

    # TODO We continuously draw things that don't change.  Should draw the
    # background save to pixmap or something and then blit it and draw arrows.
    def paintEvent(self, event):
        w = self.width()
        h = self.height()
        dial = QPainter(self)
        dial.setRenderHint(QPainter.RenderHint.Antialiasing)
        radius = int(round(min(w, h) * 0.45))
        diameter = radius * 2
        center_x = w / 2
        center_y = h / 2

        # Draw the background (bg_opacity percent < 100 lets what's behind show)
        _bg = QColor(self.bg_color)
        _bg.setAlphaF(max(0.0, min(1.0, float(getattr(self, "bg_opacity", 100)) / 100.0)))
        dial.fillRect(0, 0, w, h, _bg)
        dialPen = QPen()
        # Setup Pens
        if self.item.old or self.item.bad:
            warn_font = QFont(self.font_family, 30, QFont.Weight.Bold)
            dialPen.setColor(QColor(Qt.GlobalColor.gray))
            dialBrush = QBrush(QColor(Qt.GlobalColor.gray))
        else:
            dialPen.setColor(QColor(Qt.GlobalColor.white))
            dialBrush = QBrush(QColor(Qt.GlobalColor.white))
        dialPen.setWidth(2)

        # Dial Setup
        dial.setPen(dialPen)
        dial.drawEllipse(
            QRectF(center_x - radius, center_y - radius, diameter, diameter)
        )

        f = QFont(self.font_family)
        fs = int(round(20 * w / self.FULL_WIDTH))
        f.setPixelSize(fs)
        fontMetrics = QFontMetricsF(f)
        dial.setFont(f)
        dial.setPen(dialPen)
        dial.setBrush(dialBrush)

        dial.translate(w / 2, h / 2)
        count = 0
        altimeter_numbers = 0
        while count < 360:
            dial.drawLine(0, -(radius), 0, -(radius - 15))
            x = fontMetrics.horizontalAdvance(str(altimeter_numbers)) / 2
            y = f.pixelSize()
            dial.drawText(
                qRound(-x), qRound(-(radius - 15 - y)), str(altimeter_numbers)
            )
            altimeter_numbers += 1

            dial.rotate(36)
            count += 36
        count = 0
        while count < 360:
            dial.drawLine(0, -(radius), 0, -(radius - 10))

            dial.rotate(7.2)
            count += 7.2

        if self.item.fail:
            warn_font = QFont(self.font_family, 30, QFont.Weight.Bold)
            dial.resetTransform()
            dial.setPen(QPen(QColor(Qt.GlobalColor.red)))
            dial.setBrush(QBrush(QColor(Qt.GlobalColor.red)))
            dial.setFont(warn_font)
            dial.drawText(0, 0, w, h, Qt.AlignmentFlag.AlignCenter, "XXX")
            return

        dial.setBrush(dialBrush)
        # Needle Movement
        sm_dial = QPolygonF(
            [QPointF(5, 0), QPointF(0, +5), QPointF(-5, 0), QPointF(0, -(radius - 15))]
        )
        lg_dial = QPolygonF(
            [
                QPointF(10, -(radius / 9)),
                QPointF(5, 0),
                QPointF(0, +5),
                QPointF(-5, 0),
                QPointF(-10, -(radius / 9)),
                QPointF(0, -int(round((radius * 0.6)))),
            ]
        )
        outside_dial = QPolygonF(
            [
                QPointF(7.5, -(radius)),
                QPointF(-7.5, -(radius)),
                QPointF(0, -(radius - 10)),
            ]
        )

        sm_dial_angle = self._altimeter * 0.36 - 7.2
        lg_dial_angle = self._altimeter / 10 * 0.36 - 7.2
        outside_dial_angle = self._altimeter / 100 * 0.36 - 7.2

        dial.rotate(sm_dial_angle)
        dial.drawPolygon(sm_dial)
        dial.rotate(-sm_dial_angle)
        dial.rotate(lg_dial_angle)
        dial.drawPolygon(lg_dial)
        dial.rotate(-lg_dial_angle)
        dial.rotate(outside_dial_angle)
        dial.drawPolygon(outside_dial)

        """ Not sure if this is needed
        if self.item.bad:
            dial.resetTransform()
            dial.setPen (QPen(QColor(255, 150, 0)))
            dial.setBrush (QBrush(QColor(255, 150, 0)))
            dial.setFont (warn_font)
            dial.drawText (0,0,w,h, Qt.AlignmentFlag.AlignCenter, "BAD")
        elif self.item.old:
            dial.resetTransform()
            dial.setPen (QPen(QColor(255, 150, 0)))
            dial.setBrush (QBrush(QColor(255, 150, 0)))
            dial.setFont (warn_font)
            dial.drawText (0,0,w,h, Qt.AlignmentFlag.AlignCenter, "OLD")
        """

    def setUnitSwitching(self):
        """When this function is called the unit switching features are used"""
        self.__currentUnits = 1
        self.unitsOverride = self.unitsOverride1
        self.conversionFunction = self.conversionFunction1
        hmi.actions.setInstUnits.connect(self.setUnits)
        self.update()

    def setUnits(self, args):
        x = args.split(":")
        command = x[1].lower()
        names = x[0].split(",")
        if self.item.key in names or "*" in names or self.unitGroup in names:
            # item = fix.db.get_item(self.dbkey)
            if command == "toggle":
                if self.__currentUnits == 1:
                    self.unitsOverride = self.unitsOverride2
                    self.conversionFunction = self.conversionFunction2
                    self.__currentUnits = 2
                else:
                    self.unitsOverride = self.unitsOverride1
                    self.conversionFunction = self.conversionFunction1
                    self.__currentUnits = 1
            elif command == str(self.unitsOverride1).lower():
                self.unitsOverride = self.unitsOverride1
                self.conversionFunction = self.conversionFunction1
                self.__currentUnits = 1
            elif command == str(self.unitsOverride2).lower():
                self.unitsOverride = self.unitsOverride2
                self.conversionFunction = self.conversionFunction2
                self.__currentUnits = 2
            # self.setAuxData(item.aux) # Trigger conversion for aux data
            self.altimeter = self.item.value  # Trigger the conversion for value

    def getAltimeter(self):
        return self._altimeter

    def setAltimeter(self, altimeter):
        cvalue = self.conversionFunction(altimeter)
        if cvalue != self._altimeter:
            self._altimeter = cvalue
            self.update()

    altimeter = property(getAltimeter, setAltimeter)


class Altimeter_Tape(QGraphicsView):
    def __init__(
        self,
        parent=None,
        dbkey="ALT",
        maxalt=50000,
        fontsize=15,
        font_percent=None,
        font_family="DejaVu Sans Condensed",
        majorDiv=200,
        minorDiv=100,
        total_decimals=5,
        font_mask="00000",
        round_to=0,
        numeric_box=True,
        font_scale=1.0,
        show_trend=None,
        trend_lookahead=6.0,
        trend_window=3.0,
        trend_min_change=20.0,
        show_baro=None,
        altsel_box=None,
        alt_bug_enabled=None,
        alt_bug_color="#00ffff",
        alt_bug_alert_color="#ffb000",
        alt_bug_dbkey="ALTSEL",
    ):
        super(Altimeter_Tape, self).__init__(parent)
        # Checkbox option: alpha-fade the scrolling scale into the
        # background over the top/bottom 15% of the tape.
        self.edge_fade = False
        self.setStyleSheet("background: transparent")
        self.font_family = font_family
        self.font_mask = font_mask
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.font_percent = font_percent
        if self.font_percent:
            self.fontsize = qRound(self.width() * self.font_percent)
            self.pph = self.fontsize / 50
        else:
            self.fontsize = fontsize
            self.pph = 0.3

        self.item = fix.db.get_item(dbkey)
        self._altimeter = self.item.value
        self.backgroundOpacity = 0.3
        self.foregroundOpacity = 0.6
        self.majorDiv = majorDiv
        self.minorDiv = minorDiv

        self.maxalt = maxalt
        self._maxalt = maxalt
        self.total_decimals = total_decimals
        # Round the value shown in the numeric box to this step (0 = off). For a
        # jittery source like VS, rounding to e.g. 100 makes the box snap in
        # 100-fpm steps instead of the digits scrolling continuously; the tape
        # scroll itself stays smooth (it uses the unrounded value).
        self.round_to = round_to
        # When False, the embedded numeric readout box is omitted entirely and
        # only the scrolling tape (with its fixed read pointer) is shown.
        self.numeric_box = numeric_box
        # Multiplier on the tape's scale-number (tick label) font size.
        self.font_scale = font_scale
        self.myparent = parent

        # 6-second altitude-trend indicator (AC 23.1311-1C sec 17.8.b): a cyan
        # vector predicting where the altitude will be trend_lookahead seconds
        # ahead, for level-off look-ahead. It is an ALTITUDE cue, so default it
        # on only for an ALT tape -- a VS tape shares this class and should not
        # sprout a trend-of-VS. An explicit show_trend (config/caller) always wins.
        self.show_trend = (dbkey == "ALT") if show_trend is None else show_trend
        self.trend_lookahead = trend_lookahead
        self.trend_window = trend_window
        self.trend_min_change = trend_min_change
        self._trend_history = []   # (monotonic_time, altitude) samples
        self._trend_px = 0.0

        # Baro setting box at the bottom of the tape (pyEfis #311), touch-
        # selectable and knob-edited through the shared edit focus (#308).
        # Like show_trend it defaults on only for an ALT tape; an explicit
        # show_baro always wins. With the default, a screen that already has
        # its own BARO readout turns the box off (configure_baro), so an older
        # screen never shows two.
        self.show_baro = (dbkey == "ALT") if show_baro is None else show_baro
        self._show_baro_explicit = show_baro is not None
        self.baro_hpa = False          # display unit: inHg, or hPa when True
        self._baro_walk = False        # knob-walk highlight (not in control)
        self.encoder_selected = False  # holds edit focus
        self.enc_has_outer = False
        self._touch_edit = True
        self._baro_units_hooked = False
        # Push-to-standard undo (AER-4009): the setting a push replaced, held
        # until a second push restores it or anything else changes BARO.
        self._baro_saved = None
        try:
            self._baro_item = fix.db.get_item("BARO")
        except KeyError:
            logger.warning("Altimeter_Tape: FIX key BARO not found; "
                           "no baro setting box")
            self._baro_item = None
        if self._baro_item is not None:
            for sig in (self._baro_item.valueChanged[float],
                        self._baro_item.oldChanged[bool],
                        self._baro_item.badChanged[bool],
                        self._baro_item.failChanged[bool]):
                sig.connect(self._baro_repaint)
            self._baro_item.valueChanged[float].connect(self._baro_value_changed)
        # Selected altitude (pyEfis #310): a touch-selectable ALTSEL box at the
        # top of the tape, and the matching bug on the scale. Like the trend
        # these are ALTITUDE cues: on by default for an ALT tape only. The bug
        # follows the box unless set on its own.
        self.altsel_box = (dbkey == "ALT") if altsel_box is None else altsel_box
        self.alt_bug_enabled = alt_bug_enabled
        self.alt_bug_color = alt_bug_color
        # Box and bug colour while the gateway annunciates an altitude
        # deviation on the key (EFIS-ALTSEL-006).
        self.alt_bug_alert_color = alt_bug_alert_color
        self.alt_bug_dbkey = alt_bug_dbkey
        self._altsel = None          # bugs.BugBinding, made on first use
        self._altsel_editor = None
        self.altsel_display = None   # the box widget, made in resizeEvent
        self._edit_box = None        # EDIT_ALTSEL / EDIT_BARO holding focus
        self._touch_pending = None
        if self.altsel_box or self.alt_bug_enabled:
            self._altsel_binding()

        self.conversionFunction1 = lambda x: x
        self.conversionFunction2 = lambda x: x
        self.conversionFunction = lambda x: x

    def resizeEvent(self, event):
        if self.font_percent:
            self.fontsize = qRound(self.width() * self.font_percent)
        self.pph = self.height() / 1000
        w = self.width()
        w_2 = w / 2
        h = self.height()
        f = QFont(self.font_family)
        if self.font_mask:
            self.font_size = helpers.fit_to_mask(
                self.width() * 0.55,
                self.height() * 0.05,
                self.font_mask,
                self.font_family,
            )
            f.setPointSizeF(self.font_size * self.font_scale)
        else:
            f.setPixelSize(qRound(self.fontsize * self.font_scale))
        self.height_pixel = (
            self.maxalt * 2 * self.pph + h
        )  # + abs(self.minalt*self.pph)
        dialPen = QPen(QColor(Qt.GlobalColor.white))
        dialPen.setWidth(int(self.height() * 0.005))

        self.scene = QGraphicsScene(0, 0, w, self.height_pixel)
        x = self.scene.addRect(
            0,
            0,
            w,
            self.height_pixel,
            QPen(QColor(32, 32, 32)),
            QBrush(QColor(32, 32, 32)),
        )
        x.setOpacity(self.backgroundOpacity)

        for i in range(self.maxalt * 2, -1, -self.minorDiv):
            y = self.y_offset(i)
            alt = i - self.maxalt
            # Three tick tiers denoting the standard increments (AC 23.1311-1C
            # sec 17.8.a): 1,000-ft longest, 500-ft intermediate, minorDiv short.
            # Labels ride every 1,000-ft tick and every majorDiv tick, so a
            # config's chosen label spacing is preserved while the 500/1,000-ft
            # sense of altitude is reinforced.
            if alt % 1000 == 0:
                tick_x0 = w_2                       # longest
                labeled = True
            elif alt % 500 == 0:
                tick_x0 = w_2 + 15                  # intermediate
                labeled = (alt % self.majorDiv == 0)
            elif alt % self.majorDiv == 0:
                tick_x0 = w_2 + 15                  # labeled major
                labeled = True
            else:
                tick_x0 = w_2 + 30                  # short minor
                labeled = False
            l = self.scene.addLine(tick_x0, y, w, y, dialPen)
            l.setOpacity(self.foregroundOpacity)
            if labeled:
                t = self.scene.addText(str(alt))
                t.setFont(f)
                self.scene.setFont(f)
                t.setDefaultTextColor(QColor(Qt.GlobalColor.white))
                t.setX(0)
                t.setY(y - t.boundingRect().height() / 2)
                t.setOpacity(self.foregroundOpacity)
        self.setScene(self.scene)

        nbh = w / 1.20
        box_w = qRound(w / 1.20)
        self.numeric_box_pos = QPoint(0, qRound(h / 2 - (nbh / 1.45) / 2))
        if self.numeric_box:
            self.numerical_display = NumericalDisplay(
                self, total_decimals=self.total_decimals, scroll_decimal=2
            )
            self.numerical_display.resize(box_w, qRound(nbh / 1.45))
            self.numerical_display.move(self.numeric_box_pos)
            self.numerical_display.show()
            self.numerical_display.value = self._altimeter
        else:
            self.numerical_display = None
        self._layout_altsel_box()
        # Read-pointer position (drawn in paintEvent) — same spot whether or not
        # the numeric box is shown, so the tape stays readable.
        self.numeric_box_pos.setX(self.numeric_box_pos.x() + box_w)
        self.numeric_box_pos.setY(
            qRound(self.numeric_box_pos.y() + (nbh / 1.45) / 2) + 1
        )
        self.centerOn(
            self.scene.width() / 2, self.y_offset(self._altimeter + self.maxalt)
        )
        self.setAltOld(self.item.old)
        self.setAltBad(self.item.bad)
        self.setAltFail(self.item.fail)
        self.item.valueChanged[float].connect(self.setAltimeter)
        self.item.oldChanged[bool].connect(self.setAltOld)
        self.item.badChanged[bool].connect(self.setAltBad)
        self.item.failChanged[bool].connect(self.setAltFail)

    def y_offset(self, alt):
        return self.height_pixel - (alt * self.pph) - self.height()

    def redraw(self):
        if not self.isVisible():
            return
        self.resetTransform()
        self.centerOn(
            self.scene.width() / 2, self.y_offset(self._altimeter + self.maxalt)
        )
        if self.baro_shown():
            # centerOn() may blit-scroll the viewport, which would drag the
            # fixed baro box along with the scale; repaint it in place.
            self.viewport().update()
        if self.numerical_display is not None:
            if self.round_to:
                self.numerical_display.value = (
                    round(self._altimeter / self.round_to) * self.round_to
                )
            else:
                self.numerical_display.value = self._altimeter

    def _trend_offset_base(self):
        """Base unit for the trend vector's horizontal offset from the tape
        edge, taken from the readout panel so it scales with the box. Falls
        back to a width-derived size when the numeric box is switched off
        (numeric_box=False)."""
        rect = getattr(getattr(self, "numerical_display", None),
                       "readout_rect", None)
        if rect is not None and rect.height() > 0:
            return rect.height() * 0.42
        return self.width() / 12.0

    #  Index Line that doesn't move to make it easy to read the altimeter.
    def paintEvent(self, event):
        # edge_fade (percent of height, 0 = off): melt the scrolling
        # scale in/out at the top and bottom instead of hard-clipping.
        _fade = bool(getattr(self, "edge_fade", False))
        if _fade > 0:
            helpers.render_view_edge_faded(self, 15.0)
        else:
            super(Altimeter_Tape, self).paintEvent(event)
        w = self.width()
        h = self.height()
        p = QPainter(self.viewport())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        self._paint_alt_bug(p)

        p.translate(self.numeric_box_pos.x(), self.numeric_box_pos.y())

        # Altitude-trend vector (AC 23.1311-1C sec 17.8.b) -- a cyan look-ahead
        # from the read pointer: up when climbing, down when descending. Only
        # shown once it clears a noise floor so a level-flight jitter stays quiet.
        if self.show_trend:
            noise_floor_px = self.trend_min_change * self.pph
            if abs(self._trend_px) >= noise_floor_px:
                trend_color = QColor(0, 220, 255)
                line_w = max(2, qRound(w / 40))
                p.setPen(QPen(trend_color, line_w))
                p.setBrush(QBrush(trend_color))
                max_trend_px = qRound(h * 0.45)
                trend_y = max(-max_trend_px, min(max_trend_px, qRound(-self._trend_px)))
                x0 = qRound(self._trend_offset_base() * 1.3)
                p.drawLine(x0, 0, x0, trend_y)
                arrow = max(3, qRound(w / 14))
                if trend_y < 0:      # climbing
                    tip = [QPointF(x0, trend_y),
                           QPointF(x0 - arrow, trend_y + arrow),
                           QPointF(x0 + arrow, trend_y + arrow)]
                else:                # descending
                    tip = [QPointF(x0, trend_y),
                           QPointF(x0 - arrow, trend_y - arrow),
                           QPointF(x0 + arrow, trend_y - arrow)]
                p.drawPolygon(QPolygonF(tip))

        if self.baro_shown():
            p.resetTransform()
            self._paint_baro(p)

    # --- baro setting box (pyEfis #311) -------------------------------------

    def baro_shown(self):
        return bool(self.show_baro) and self._baro_item is not None

    def _baro_zone(self):
        """The strip at the bottom of the tape that the box and its focus
        marks live in, in viewport coordinates."""
        vw = self.viewport().width()
        vh = self.viewport().height()
        zone_h = max(18.0, min(vh * 0.055, vw * 0.42))
        return QRectF(0, vh - zone_h, vw, zone_h)

    def baro_box_rect(self):
        """The baro box itself, inset so the focus ring fits around it."""
        return edit_focus.inset_for_marks(self._baro_zone())

    def baro_text(self):
        """(value, unit) as displayed: ``("29.92", "IN")`` or
        ``("1013", "HPA")``."""
        v = self._baro_item.value
        if self.baro_hpa:
            return "{0:d}".format(int(round(v * HPA_PER_INHG))), "HPA"
        return "{0:.2f}".format(v), "IN"

    def _paint_baro(self, p):
        item = self._baro_item
        box = self.baro_box_rect()
        p.save()
        # Mask the scale under the whole strip, so ticks do not show through
        # the margin left for the focus ring.
        p.fillRect(self._baro_zone(), QColor(Qt.GlobalColor.black))
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        border = QColor(255, 165, 0) if self._baro_walk else QColor(Qt.GlobalColor.white)
        p.setPen(QPen(border, 2 if self._baro_walk else 1))
        p.setBrush(QBrush(QColor(Qt.GlobalColor.black)))
        p.drawRect(box)

        if item.fail:
            value, unit, color = "XXX", "", QColor(Qt.GlobalColor.red)
        else:
            value, unit = self.baro_text()
            color = QColor(Qt.GlobalColor.gray) if (item.old or item.bad) else BARO_COLOR
        # Size the value to the widest reading in either unit so the digits do
        # not jump when the unit changes.
        vf = QFont(self.font_family)
        vf.setPixelSize(max(6, int(box.height() * 0.78)))
        uf = QFont(vf)
        uf.setPixelSize(max(5, int(vf.pixelSize() * 0.6)))
        gap = box.height() * 0.12
        need = (QFontMetricsF(vf).horizontalAdvance("88.88")
                + gap + QFontMetricsF(uf).horizontalAdvance("HPA"))
        avail = box.width() * 0.92
        if need > avail:
            scale = avail / need
            vf.setPixelSize(max(6, int(vf.pixelSize() * scale)))
            uf.setPixelSize(max(5, int(uf.pixelSize() * scale)))
            gap *= scale
        vw = QFontMetricsF(vf).horizontalAdvance(value)
        uw = QFontMetricsF(uf).horizontalAdvance(unit) if unit else 0.0
        total = vw + (gap + uw if unit else 0.0)
        x = box.center().x() - total / 2.0
        p.setPen(QPen(color))
        p.setFont(vf)
        p.drawText(QRectF(x, box.top(), vw + 1, box.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, value)
        if unit:
            # Unit sits on the value's baseline.
            base = box.center().y() + (QFontMetricsF(vf).ascent()
                                       - QFontMetricsF(vf).descent()) / 2.0
            p.setFont(uf)
            p.drawText(QPointF(x + vw + gap, base), unit)
        p.restore()
        if self.touch_edit or self.encoder_selected:
            edit_focus.draw_edit_marks(p, box, focused=self.encoder_selected,
                                       bounds=self._baro_zone())

    def _baro_value_changed(self, value):
        # Any BARO change drops a saved setting: a knob step on this box,
        # another display, the gateway, a script. The push's own write lands
        # here too, which is why baro_set_standard saves only after it.
        self._baro_saved = None

    def _baro_repaint(self, *args):
        if self.baro_shown():
            self._baro_refresh()

    def _baro_refresh(self):
        """Repaint now, synchronously, after a box state change.

        On the live X11 panel (SVS QOpenGLWidget in the window, tape with
        edge_fade) a queued viewport update() of the box reached the glass
        0.5-8 s late when nothing else on the screen was changing: the focus
        ring appeared late after a touch, or stayed up after the timeout.
        The focus state itself was right and a touch_edit numeric_display on
        the same screen was not affected (bench probes, AER-3914). repaint()
        paints and flushes immediately; it runs only on state changes (touch,
        knob, timeout, units, BARO), never per frame."""
        vp = self.viewport()
        if vp.isVisible():
            vp.repaint()
        else:
            vp.update()

    def _baro_limits(self):
        lo, hi = BARO_MIN_INHG, BARO_MAX_INHG
        item = self._baro_item
        try:
            if item.min is not None:
                lo = max(lo, float(item.min))
            if item.max is not None:
                hi = min(hi, float(item.max))
        except (TypeError, ValueError):
            pass
        return lo, hi

    def baro_step(self, steps, coarse=False):
        """Move BARO by ``steps`` knob detents: 0.01 / 0.10 inHg, or 1 / 10 hPa.

        In hPa the step is taken in whole hPa from the displayed (rounded)
        value and the result is converted back to inHg once, so every step
        lands on a whole hPa however many steps are taken. Clamped to
        BARO_MIN_INHG..BARO_MAX_INHG and the FIX item's own range."""
        item = self._baro_item
        lo, hi = self._baro_limits()
        if self.baro_hpa:
            step = 10 if coarse else 1
            lo_h = math.ceil(lo * HPA_PER_INHG - 1e-9)
            hi_h = math.floor(hi * HPA_PER_INHG + 1e-9)
            hpa = int(round(item.value * HPA_PER_INHG)) + int(steps) * step
            new = max(lo_h, min(hi_h, hpa)) / HPA_PER_INHG
        else:
            step = 0.10 if coarse else 0.01
            new = round(round(item.value, 2) + int(steps) * step, 2)
            new = max(lo, min(hi, new))
        self._write_baro(new)

    def baro_set_standard(self):
        """Push: standard pressure, or back to the setting it replaced.

        The first push saves the current BARO and sets standard (29.92 inHg,
        which reads 1013 in hPa). A second push restores the saved value
        exactly as it was on the bus. Anything else that changes BARO in
        between, a knob step on this box or a write from another source,
        drops the saved value, so a later push sets standard again. Pushed
        with BARO already at standard (to 0.01 inHg) and nothing saved, it
        does nothing."""
        item = self._baro_item
        if self._baro_saved is not None:
            saved, self._baro_saved = self._baro_saved, None
            self._write_baro(saved)
        elif round(item.value, 2) != BARO_STD_INHG:
            saved = item.value
            self._write_baro(BARO_STD_INHG)
            self._baro_saved = saved    # after the write, which clears it

    def _write_baro(self, value):
        self._baro_item.value = value
        self._baro_item.output_value()
        self._baro_refresh()

    def configure_baro(self, preferences=None, other_readout=False):
        """Called by the screen builder once the whole screen is built.

        ``other_readout``: the screen already shows BARO in another widget (an
        older screen's numeric_display), so a defaulted box stays off and the
        screen keeps one readout. ``preferences``: the ``units: Pressure``
        boot unit (inHg | hPa). Also follows the Units action for the
        Pressure group, independently of the tape's own Altitude unit."""
        if other_readout and not self._show_baro_explicit:
            self.show_baro = False
        if not self.baro_shown():
            return
        if not self._baro_units_hooked:
            hmi.actions.setInstUnits.connect(self._baro_units_action)
            self._baro_units_hooked = True
        try:
            wanted = ((preferences or {}).get("units") or {}).get("Pressure")
        except AttributeError:
            wanted = None
        if wanted is not None:
            if str(wanted).lower() in ("inhg", "hpa"):
                self.baro_hpa = str(wanted).lower() == "hpa"
            else:
                logger.warning("preferences units.Pressure: '%s' is not inHg "
                               "or hPa; baro box keeps inHg", wanted)

    def _baro_units_action(self, args):
        try:
            names, command = args.split(":")
        except (AttributeError, ValueError):
            return
        names = names.split(",")
        if not ("Pressure" in names or "BARO" in names or "*" in names):
            return
        command = command.strip().lower()
        if command == "toggle":
            self.baro_hpa = not self.baro_hpa
        elif command in ("inhg", "hpa"):
            self.baro_hpa = command == "hpa"
        else:
            return
        self._baro_refresh()

    # Baro box half of the EncoderController protocol (#308); the tape-level
    # enc_* methods below dispatch here or to the ALTSEL box.

    def _baro_highlight(self, onoff):
        self._baro_walk = bool(onoff)
        if not onoff:
            self.encoder_selected = False
        self._baro_refresh()

    def _baro_select(self):
        if not self.baro_shown():
            return False
        self._baro_walk = False
        self.encoder_selected = True
        self._baro_refresh()
        return True

    def _baro_changed(self, data):
        self.baro_step(data)
        return True

    def _baro_outer_changed(self, data):
        self.baro_step(data, coarse=True)
        return True

    def _baro_clicked(self):
        # Push sets standard, or restores the setting the last push replaced
        # (baro_set_standard), and keeps focus; the value is live, so there is
        # nothing to accept. Focus clears on the timeout or a touch elsewhere.
        self.baro_set_standard()
        return True

    def _baro_hit(self, global_pos):
        local = self.viewport().mapFromGlobal(global_pos.toPoint())
        return self._baro_zone().contains(QPointF(local))

    def mousePressEvent(self, event):
        if self._touch_edit and self.baro_shown() \
                and self._baro_zone().contains(event.position()):
            if self._touch_box(EDIT_BARO):
                event.accept()
                return
        super().mousePressEvent(event)

    def _encoder_controller(self):
        w = self.parent()
        while w is not None:
            ctl = getattr(w, "encoder_controller", None)
            if ctl is not None:
                return ctl
            w = w.parent()
        return None

    def setUnitSwitching(self):
        """When this function is called the unit switching features are used"""
        self.__currentUnits = 1
        self.unitsOverride = self.unitsOverride1
        self.conversionFunction = self.conversionFunction1
        hmi.actions.setInstUnits.connect(self.setUnits)
        if self.isVisible():
            self.update()

    def setUnits(self, args):
        x = args.split(":")
        command = x[1].lower()
        names = x[0].split(",")
        if self.item.key in names or "*" in names or self.unitGroup in names:
            # item = fix.db.get_item(self.dbkey)
            if command == "toggle":
                if self.__currentUnits == 1:
                    self.unitsOverride = self.unitsOverride2
                    self.conversionFunction = self.conversionFunction2
                    self.__currentUnits = 2
                else:
                    self.unitsOverride = self.unitsOverride1
                    self.conversionFunction = self.conversionFunction1
                    self.__currentUnits = 1
            elif command == str(self.unitsOverride1).lower():
                self.unitsOverride = self.unitsOverride1
                self.conversionFunction = self.conversionFunction1
                self.__currentUnits = 1
            elif command == str(self.unitsOverride2).lower():
                self.unitsOverride = self.unitsOverride2
                self.conversionFunction = self.conversionFunction2
                self.__currentUnits = 2
            # self.setAuxData(item.aux) # Trigger conversion for aux data
            self.altimeter = self.item.value  # Trigger the conversion for value

    def getAltimeter(self):
        return self._altimeter

    def _push_trend(self, now, value):
        """Update the trend history and derive self._trend_px -- the look-ahead
        offset in scene pixels (positive = climbing -> vector up)."""
        self._trend_history.append((now, value))
        cutoff = now - self.trend_window
        while self._trend_history and self._trend_history[0][0] < cutoff:
            self._trend_history.pop(0)
        if len(self._trend_history) >= 2:
            t0, v0 = self._trend_history[0]
            t1, v1 = self._trend_history[-1]
            dt = t1 - t0
            if dt >= 0.1:
                rate = (v1 - v0) / dt                       # units per second
                self._trend_px = rate * self.trend_lookahead * self.pph
            else:
                self._trend_px = 0.0
        else:
            self._trend_px = 0.0

    def setAltimeter(self, altimeter):
        cvalue = self.conversionFunction(altimeter)
        if self.show_trend:
            self._push_trend(time.monotonic(), cvalue)
        if cvalue != self._altimeter:
            self._altimeter = cvalue
            self.redraw()
        elif self.show_trend:
            # value unchanged but the trend may have decayed -- repaint the cue.
            self.viewport().update()

    altimeter = property(getAltimeter, setAltimeter)

    def setAltOld(self, b):
        if self.numerical_display is not None:
            self.numerical_display.old = b

    def setAltBad(self, b):
        if self.numerical_display is not None:
            self.numerical_display.bad = b

    def setAltFail(self, b):
        if self.numerical_display is not None:
            self.numerical_display.fail = b

    # --- selected altitude: box, bug and knob editing (pyEfis #310) ---------

    def _altsel_binding(self):
        if self._altsel is None:
            self._altsel = bugs.BugBinding(self.alt_bug_dbkey, self)
            self._altsel.changed.connect(self._baro_refresh)
            self._altsel_editor = altsel.AltSelEditor(
                self._altsel, self._current_alt_ft)
        return self._altsel

    def _current_alt_ft(self):
        # Sync reads the ALT item itself (feet on the bus), not the displayed,
        # possibly unit-converted value.
        item = self.item
        return item.value, not (item.fail or item.bad)

    def _bug_on(self):
        if self.alt_bug_enabled is None:
            return bool(self.altsel_box)
        return bool(self.alt_bug_enabled)

    def _altsel_touchable(self):
        return bool(self.altsel_box) and self._altsel_binding().item is not None

    def _layout_altsel_box(self):
        if not self.altsel_box:
            if self.altsel_display is not None:
                self.altsel_display.hide()
            return
        binding = self._altsel_binding()
        if self.altsel_display is None:
            self.altsel_display = altsel.AltSelBox(
                self, binding, font_family=self.font_family)
            self.altsel_display.color = QColor(self.alt_bug_color)
            self.altsel_display.alert_color = QColor(self.alt_bug_alert_color)
        bh = max(16, qRound(self.width() * 0.34))
        self.altsel_display.setGeometry(0, 0, self.width(), bh)
        self.altsel_display.show()

    def alt_bug_y(self):
        """Where the bug goes, in viewport pixels, and whether it is pegged
        off the visible tape: ``(y, off)``, ``off`` -1 above, +1 below. None
        when there is no bug to draw. The span runs from the bottom of the
        ALTSEL box to the top of the baro box, whichever are shown."""
        if not self._bug_on():
            return None
        binding = self._altsel_binding()
        if not binding.drawable():
            return None
        target = self.conversionFunction(binding.value)
        y = self.mapFromScene(
            QPointF(0, self.y_offset(target + self.maxalt))).y()
        top = 0
        if self.altsel_display is not None and self.altsel_display.isVisible():
            top = self.altsel_display.geometry().bottom() + 1
        bottom = self.viewport().height()
        if self.baro_shown():
            bottom = self._baro_zone().top()
        y, off = bugs.clamp_to_span(y, top, bottom)
        return y, off

    def _paint_alt_bug(self, p):
        placed = self.alt_bug_y()
        if placed is None:
            return
        y, _off = placed
        w = self.width()
        bug_w = max(5.0, w * 0.12)
        bug_h = max(10.0, w * 0.26)
        color = self._altsel.color(QColor(self.alt_bug_color),
                                   QColor(self.alt_bug_alert_color))
        p.save()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(color))
        # On the tick edge, notch facing the scale: the left edge carries the
        # scale labels, which a bug there would cover.
        p.drawPath(bugs.tape_bug_path(float(w), y, bug_w, bug_h,
                                      point_right=False))
        p.restore()

    def _altsel_refresh(self):
        # Paint now, not queued: the same late-repaint trap the baro box hit
        # on the live panel (see _baro_refresh) applies to this tape.
        box = self.altsel_display
        if box is not None and box.isVisible():
            box.repaint()

    def _altsel_highlight(self, onoff):
        if self.altsel_display is not None:
            self.altsel_display.highlighted = bool(onoff)
            if not onoff:
                self.altsel_display.focused = False
            self._altsel_refresh()

    def _altsel_select(self):
        if not self._altsel_touchable():
            return False
        if self.altsel_display is not None:
            self.altsel_display.focused = True
            self._altsel_refresh()
        return True

    def _altsel_changed(self, steps):
        self._altsel_binding()
        return self._altsel_editor.step(altsel.FINE_STEP_FT * steps)

    def _altsel_outer_changed(self, steps):
        self._altsel_binding()
        return self._altsel_editor.step(altsel.COARSE_STEP_FT * steps)

    def _altsel_clicked(self):
        # Push: sync to the current altitude and end the edit (Bill,
        # 2026-10-27, AER-3915). With no valid altitude nothing is written and
        # the box stays focused.
        self._altsel_binding()
        return not self._altsel_editor.sync()

    def _altsel_hit(self, global_pos):
        box = self.altsel_display
        if box is None or not box.isVisible():
            return False
        local = box.mapFromGlobal(global_pos)
        return box.rect().contains(local.toPoint())

    # --- the EncoderController protocol (#308), dispatched per box ----------
    #
    # The tape is ONE encoder instrument carrying two settable boxes: ALTSEL
    # at the top (#310) and baro at the bottom (#311). A touch names its box
    # (_touch_box); the knob walk, which only knows the tape, lands on the
    # first box shown, top to bottom. Every enc_* call goes to the box that
    # holds focus, and edit_focus_hit counts only that box, so a press on the
    # other box or on the scale releases focus.

    @property
    def touch_edit(self):
        return self._touch_edit and bool(self._edit_boxes())

    @touch_edit.setter
    def touch_edit(self, on):
        self._touch_edit = bool(on)

    def _edit_boxes(self):
        boxes = []
        if self._altsel_touchable():
            boxes.append(EDIT_ALTSEL)
        if self.baro_shown():
            boxes.append(EDIT_BARO)
        return boxes

    def _active_box(self):
        if self._edit_box is not None:
            return self._edit_box
        boxes = self._edit_boxes()
        return boxes[0] if boxes else None

    def _touch_box(self, which):
        """A press on box ``which``: give the tape focus for that box. A tape
        already in control for the OTHER box is released first, since the
        controller would otherwise just restart its timeout."""
        ctl = self._encoder_controller()
        if ctl is None:
            return False
        if ctl.focused_instrument() is self and self._edit_box != which:
            ctl.release_focus()
        self._touch_pending = which
        try:
            ctl.touch_focus(self)
        finally:
            self._touch_pending = None
        return True

    def _claim_pending(self):
        if self._touch_pending is not None:
            self._edit_box = self._touch_pending

    def _dispatch(self, name, *args):
        box = self._active_box()
        if box is None:
            return False
        return getattr(self, "_%s_%s" % (box, name))(*args)

    def enc_selectable(self):
        return bool(self._edit_boxes())

    def enc_highlight(self, onoff):
        if onoff:
            self._claim_pending()
            self._dispatch("highlight", True)
            return
        # Clear both: whichever held the walk highlight or focus lets go.
        if self.altsel_display is not None:
            self._altsel_highlight(False)
        if self._baro_item is not None:
            self._baro_highlight(False)
        self._edit_box = None

    def enc_select(self):
        self._claim_pending()
        box = self._active_box()
        if box is None:
            return False
        self._edit_box = box
        return self._dispatch("select")

    def enc_changed(self, steps):
        return self._dispatch("changed", steps)

    def enc_outer_changed(self, steps):
        return self._dispatch("outer_changed", steps)

    def enc_clicked(self):
        return self._dispatch("clicked")

    def edit_focus_hit(self, global_pos):
        if self._edit_box is None:
            return False
        return self._dispatch("hit", global_pos)

    # We don't want this responding to keystrokes
    def keyPressEvent(self, event):
        pass

    # Don't want it acting with the mouse scroll wheel either
    def wheelEvent(self, event):
        pass
