#  Copyright (c) 2018-2019 Garrett Herschleb
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

from PyQt6.QtGui import *
from PyQt6.QtCore import *
from PyQt6.QtWidgets import *

from pyefis.instruments import helpers

#: Horizontal padding inside the rounded readout panel, as a fraction of the
#: widget width -- keeps the outermost digit clear of the corner arc.
_READOUT_PAD_X = 0.045
#: Panel height as a multiple of the digit height, so the value sits inside the
#: border with a little air rather than touching it top and bottom.
_READOUT_PANEL_H = 1.20


class NumericalDisplay(QGraphicsView):
    def __init__(
        self,
        parent=None,
        total_decimals=3,
        scroll_decimal=1,
        font_family="DejaVu Sans Mono",
        font_size=15,
    ):
        super(NumericalDisplay, self).__init__(parent)
        # Transparent so the rounded readout panel's translucent fill reveals
        # the tape (and whatever is behind it) instead of a widget-shaped block.
        self.setStyleSheet("background: transparent; border: 0px")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setBackgroundBrush(QBrush(Qt.BrushStyle.NoBrush))
        #: Readout panel geometry in widget coordinates, set in resizeEvent.
        #: None until the first resize (the tapes fall back to their own width).
        self.readout_rect = None
        self.font_family = font_family
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.scroll_decimal = scroll_decimal
        self.total_decimals = total_decimals
        self.f = QFont(font_family, font_size)
        self.font_family = font_family
        self.font_size = font_size
        self._value = 0
        self.myparent = parent
        self._bad = False
        self._old = False
        self._fail = False

    def resizeEvent(self, event):
        self.w = self.width()
        self.h = self.height()

        # Fit the digits inside the panel's padded interior, not edge-to-edge:
        # the rounded corners (P5c) would otherwise clip the outermost glyph.
        pad_x = self.w * _READOUT_PAD_X
        avail = max(1.0, self.w - 2 * pad_x)

        t = QGraphicsSimpleTextItem("9")
        t.setFont(self.f)
        font_width = t.boundingRect().width()
        font_height = t.boundingRect().height()
        while font_width * (self.total_decimals) >= avail - 0.1:
            self.font_size -= 0.1
            self.f.setPointSizeF(self.font_size)
            t.setFont(self.f)
            rect = t.boundingRect()
            font_width = rect.width()
            font_height = rect.height()

        while font_width * (self.total_decimals) <= avail - 0.1:
            self.font_size += 0.1
            self.f.setPointSizeF(self.font_size)
            t.setFont(self.f)
            rect = t.boundingRect()
            font_width = rect.width()
            font_height = rect.height()
        self.font_size = qRound(self.font_size)
        self.f = QFont(self.font_family, self.font_size)

        self.scene = QGraphicsScene(0, 0, self.w, self.h)
        # The readout container (P5c): one rounded, translucent panel in the
        # shared house style (helpers.READOUT_*), replacing the old solid
        # white-on-black rectangle plus the bracket "arms" that used to frame
        # the scrolling column out to the widget edges.
        border_width = max(1.0, font_height * helpers.READOUT_PEN_RATIO)
        panel_h = font_height * _READOUT_PANEL_H
        top = (self.h - panel_h) / 2.0
        text_top = (self.h - font_height) / 2.0
        radius = panel_h * helpers.READOUT_RADIUS_RATIO
        rect_pen, rect_brush = helpers.readout_panel_pen_brush(
            QColor(Qt.GlobalColor.white), border_width
        )
        inset = border_width / 2.0
        self.readout_rect = QRectF(
            inset, top, max(1.0, self.w - border_width), panel_h
        )
        #: Published for tests: the corner radius is READOUT_RADIUS_RATIO of the
        #: panel's own height, the same invariant the HSI panel uses (AER-413).
        self.readout_radius = radius
        panel = QPainterPath()
        panel.addRoundedRect(self.readout_rect, radius, radius)
        self.scene.addPath(panel, rect_pen, rect_brush)
        self.setScene(self.scene)
        self.scrolling_area = NumericalScrollDisplay(
            self, self.scroll_decimal, self.font_family, self.font_size
        )
        self.scene.addWidget(self.scrolling_area)
        self.digit_vertical_spacing = font_height
        # Clip the scrolling drum to one digit height: it used to be the full
        # widget height, so the neighbouring digits spilled out above and below
        # the box entirely. One digit tall, the drum shows only the value at
        # rest and rolls its neighbour in through the panel as the value moves.
        self.scrolling_area.resize(
            max(1, qRound(font_width * self.scroll_decimal + border_width)),
            max(1, qRound(font_height)),
        )
        sax = qRound(self.w - pad_x - font_width * self.scroll_decimal)
        self.scrolling_area.move(sax, qRound(text_top))
        prest = "0" * (self.total_decimals - self.scroll_decimal)
        if self._bad or self._old:
            prest = ""
        self.pre_scroll_text = self.scene.addSimpleText(prest, self.f)
        self.pre_scroll_text.setPen(QPen(QColor(Qt.GlobalColor.white)))
        self.pre_scroll_text.setBrush(QBrush(QColor(Qt.GlobalColor.white)))

        self.pre_scroll_text.setX(pad_x)
        self.pre_scroll_text.setY(text_top)

        # Get a failure scene ready in case it's needed. Same rounded panel so
        # the box does not change shape when the source fails -- only its fill
        # (solid grey, an annunciation rather than a value) and the red XXX.
        self.fail_scene = QGraphicsScene(0, 0, self.w, self.h)
        fail_path = QPainterPath()
        fail_path.addRoundedRect(self.readout_rect, radius, radius)
        self.fail_scene.addPath(
            fail_path,
            QPen(QColor(Qt.GlobalColor.white), border_width),
            QBrush(QColor(50, 50, 50)),
        )
        warn_font = QFont(self.font_family, 10, QFont.Weight.Bold)
        t = self.fail_scene.addSimpleText("XXX", warn_font)
        t.setPen(QPen(QColor(Qt.GlobalColor.red)))
        t.setBrush(QBrush(QColor(Qt.GlobalColor.red)))
        r = t.boundingRect()
        t.setPos((self.w - r.width()) / 2, (self.h - r.height()) / 2)

        """ Not sure if this is needed:
        self.bad_text = self.scene.addSimpleText("BAD", warn_font)
        warn_pen = QPen(QColor(255, 150, 0))
        warn_brush = QBrush(QColor(255, 150, 0))
        self.bad_text.setPen (warn_pen)
        self.bad_text.setBrush (warn_brush)
        r = self.bad_text.boundingRect()
        self.bad_text.setPos ((self.w-r.width())/2, (self.h-r.height())/2)
        if not self._bad:
            self.bad_text.hide()

        self.old_text = self.scene.addSimpleText("OLD", warn_font)
        self.old_text.setPen (warn_pen)
        self.old_text.setBrush (warn_brush)
        r = self.old_text.boundingRect()
        self.old_text.setPos ((self.w-r.width())/2, (self.h-r.height())/2)
        if not self._old:
            self.old_text.hide()
        """

    def redraw(self):
        prevalue = int(self._value / (10**self.scroll_decimal))
        scroll_value = self._value - (prevalue * (10**self.scroll_decimal))
        if self.scroll_decimal > 1:
            scroll_value = scroll_value / (10 ** (self.scroll_decimal - 1))
        prest = str(prevalue)
        prelen = self.total_decimals - self.scroll_decimal
        prest = "{1:0{0}d}".format(prelen, prevalue)
        if scroll_value < 0:
            scroll_value = abs(scroll_value)
        if self._value < 0 and prevalue >= 0:
            # IF negative ensure the sign it displayed
            prest = "-{1:0{0}d}".format(prelen - 1, prevalue)
        if self._bad or self._old:
            prest = ""
        self.pre_scroll_text.setText(prest)
        if not (self._bad or self._old or self._fail):
            self.scrolling_area.value = scroll_value

    def getValue(self):
        return self._value

    def setValue(self, val):
        self._value = val
        if self.isVisible():
            self.redraw()

    value = property(getValue, setValue)

    def flagDisplay(self):
        if self._bad or self._old or self._fail:
            self.pre_scroll_text.setText("")
            self.scrolling_area.hide()
        else:
            self.pre_scroll_text.setBrush(QBrush(QColor(Qt.GlobalColor.white)))
            self.redraw()
            self.scrolling_area.show()

    def getBad(self):
        return self._bad

    def setBad(self, b):
        if self._bad != b:
            self._bad = b
            # if b:
            #    self.bad_text.show()
            # else:
            #    self.bad_text.hide()
            self.flagDisplay()

    bad = property(getBad, setBad)

    def getOld(self):
        return self._old

    def setOld(self, b):
        if self._old != b:
            self._old = b
            # if b:
            #    self.old_text.show()
            # else:
            #    self.old_text.hide()
            self.flagDisplay()

    old = property(getOld, setOld)

    def getFail(self):
        return self._fail

    def setFail(self, b):
        if self._fail != b:
            self._fail = b
            if b:
                self.setScene(self.fail_scene)
            else:
                self.setScene(self.scene)
                self.flagDisplay()

    fail = property(getFail, setFail)


class NumericalScrollDisplay(QGraphicsView):
    def __init__(self, parent=None, scroll_decimal=1, font_family="Sans", font_size=10):
        super(NumericalScrollDisplay, self).__init__()
        # Transparent: the drum sits inside the readout panel and takes its
        # tint from the panel's translucent fill. Its own opaque black plate
        # would punch a solid block back through it.
        self.setStyleSheet("background: transparent; border: 0px")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.scroll_decimal = scroll_decimal
        self.f = QFont(font_family, font_size)
        self._value = 0

    def resizeEvent(self, event):
        self.w = self.width()
        self.h = self.height()

        t = QGraphicsSimpleTextItem("9")
        t.setFont(self.f)
        font_width = t.boundingRect().width()
        font_height = t.boundingRect().height()
        # One digit height per step (was 0.8, which left ~20% of the next digit
        # showing under the value at rest -- tolerable when the drum bled past
        # the old box, clutter now that it is clipped inside the panel).
        self.digit_vertical_spacing = font_height
        nsh = self.digit_vertical_spacing * 12 + self.h
        self.scene = QGraphicsScene(0, 0, self.w, nsh)
        self.setBackgroundBrush(QBrush(Qt.BrushStyle.NoBrush))
        for i in range(20):
            y = self.y_offset(i) - font_height / 2
            if y < 0:
                break
            text = str(i % 10)
            if len(text) < self.scroll_decimal:
                add0s = self.scroll_decimal - len(text)
                text = text + "0" * add0s
            t = self.scene.addSimpleText(text, self.f)
            t.setX(2)
            t.setPen(QPen(QColor(Qt.GlobalColor.white)))
            t.setBrush(QBrush(QColor(Qt.GlobalColor.white)))
            t.setY(y)
        for i in range(9, 0, -1):
            sv = i - 10
            y = self.y_offset(sv) - font_height / 2
            if y > nsh - font_height:
                break
            text = str(i)
            if len(text) < self.scroll_decimal:
                add0s = self.scroll_decimal - len(text)
                text = text + "0" * add0s
            t = self.scene.addSimpleText(text, self.f)
            t.setPen(QPen(QColor(Qt.GlobalColor.white)))
            t.setBrush(QBrush(QColor(Qt.GlobalColor.white)))
            t.setX(2)
            t.setY(y)
        self.setScene(self.scene)

    def y_offset(self, sv):
        return (10.0 - (sv)) * self.digit_vertical_spacing + self.h / 2

    def redraw(self):
        scroll_value = self._value
        self.resetTransform()
        self.centerOn(self.width() / 2, self.y_offset(scroll_value))

    def getValue(self):
        return self._value # pragma: no cover

    def setValue(self, val):
        self._value = val
        if self.isVisible():
            self.redraw()

    value = property(getValue, setValue)
