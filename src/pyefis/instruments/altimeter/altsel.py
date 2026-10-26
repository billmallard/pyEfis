#  Copyright (c) 2026 Bill Mallard
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

"""Selected-altitude (ALTSEL) box at the top of the altimeter tape (pyEfis #310).

The box shows the selected altitude in cyan. It is touch-selectable: a touch
gives the TAPE edit focus through the screen's ``EncoderController`` (pyEfis
#308), and the tape's ``enc_*`` methods step the value through
:class:`AltSelEditor`. The editing rules live in the editor, apart from Qt
painting, so they can be tested headless:

- inner knob 100 ft, outer ring 1000 ft, clamped to the key's min/max;
- push syncs to the current altitude, rounded to the nearest 100 ft;
- with no valid value, the first step starts from the synced altitude.

Every edit is written to the bus at once (the autopilot follows the target as
the knob turns). A write marks the item good: the pilot setting a target is
what makes it valid.
"""

import logging

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QPainter
from PyQt6.QtWidgets import QWidget

from pyefis.instruments import edit_focus, helpers
from pyefis.instruments.helpers import bugs

logger = logging.getLogger(__name__)

FINE_STEP_FT = 100
COARSE_STEP_FT = 1000
SYNC_ROUND_FT = 100
DASHES = "-----"
HIGHLIGHT_COLOR = QColor("orange")  # knob-walk highlight, as the gauges use
# Opaque, unlike the readout house style (0.62): the box sits over the
# scrolling scale, and a tick label showing through reads as a second number.
BOX_FILL_ALPHA = 1.0


def round_to_step(value, step=SYNC_ROUND_FT):
    """Nearest multiple of ``step``; halves round away from zero (2950 ->
    3000, -150 -> -200), not to even."""
    q = abs(value) / step
    n = int(q + 0.5)
    return int(n * step if value >= 0 else -n * step)


class AltSelEditor:
    """The ALTSEL edit rules, over a :class:`bugs.BugBinding`.

    ``current_alt`` is a callable returning ``(altitude_ft, valid)`` for the
    sync; the tape passes its own ALT item."""

    def __init__(self, binding, current_alt):
        self.binding = binding
        self.current_alt = current_alt

    @property
    def writable(self):
        return self.binding.item is not None

    def limits(self):
        item = self.binding.item
        lo = getattr(item, "min", None)
        hi = getattr(item, "max", None)
        return (-1000 if lo is None else lo), (60000 if hi is None else hi)

    def clamp(self, value):
        lo, hi = self.limits()
        return int(max(lo, min(hi, value)))

    def synced_value(self):
        """The current altitude rounded to 100 ft, or None when ALT is not
        usable (failed or bad)."""
        alt, valid = self.current_alt()
        if not valid:
            return None
        return self.clamp(round_to_step(alt))

    def step(self, delta_ft):
        """Add ``delta_ft`` and write. From no valid value, start from the
        synced altitude (or 0 with no usable altitude either)."""
        if not self.writable:
            return False
        if self.binding.drawable():
            base = self.binding.value
        else:
            base = self.synced_value()
            if base is None:
                base = 0
        self.write(base + delta_ft)
        return True

    def sync(self):
        """Push: set the target to the current altitude. Returns False (and
        writes nothing) when there is no valid altitude to sync to."""
        if not self.writable:
            return False
        v = self.synced_value()
        if v is None:
            return False
        self.write(v)
        return True

    def write(self, value):
        item = self.binding.item
        item.bad = False
        item.fail = False
        item.value = self.clamp(value)
        item.output_value()


class AltSelBox(QWidget):
    """The box itself: draws the value and the edit marks, and turns a press
    into a touch focus for the parent tape."""

    def __init__(self, tape, binding, font_family="DejaVu Sans Condensed"):
        super().__init__(tape)
        self.tape = tape
        self.binding = binding
        self.font_family = font_family
        self.highlighted = False
        self.focused = False
        self.color = QColor(bugs.BUG_COLOR)
        self._font_pt = None
        binding.changed.connect(self.update)

    def resizeEvent(self, event):
        self._font_pt = None
        super().resizeEvent(event)

    def value_rect(self):
        return edit_focus.inset_for_marks(QRectF(self.rect()))

    def text(self):
        if not self.binding.drawable():
            return DASHES
        return str(int(round(self.tape.conversionFunction(self.binding.value))))

    def _font(self, rect):
        if self._font_pt is None:
            self._font_pt = helpers.fit_to_mask(
                rect.width() * 0.86, rect.height() * 0.78, "00000",
                self.font_family)
        f = QFont(self.font_family)
        f.setPointSizeF(max(1.0, self._font_pt))
        return f

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.value_rect()
        border = self.binding.color(self.color)
        helpers.draw_readout_panel(
            p, r, helpers.READOUT_RADIUS_RATIO * r.height(), border,
            pen_width=max(1.0, r.height() * 0.05), fill_alpha=BOX_FILL_ALPHA)
        if self.highlighted and not self.focused:
            fg = QColor(HIGHLIGHT_COLOR)
        else:
            fg = self.binding.color(self.color)
        p.setPen(fg)
        p.setFont(self._font(r))
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, self.text())
        if self.tape.touch_edit:
            edit_focus.draw_edit_marks(p, r, focused=self.focused,
                                       bounds=QRectF(self.rect()))
        p.end()

    def mousePressEvent(self, event):
        ctl = self._encoder_controller()
        if ctl is not None and self.tape.touch_edit:
            ctl.touch_focus(self.tape)
            event.accept()
            return
        super().mousePressEvent(event)

    def _encoder_controller(self):
        w = self.tape.parent()
        while w is not None:
            ctl = getattr(w, "encoder_controller", None)
            if ctl is not None:
                return ctl
            w = w.parent()
        return None
