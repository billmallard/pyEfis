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

"""Touch-select + knob-edit focus: the one shared visual language (pyEfis #308).

Every widget with a settable value (HSI HDG/CRS, baro, selected altitude, a
``numeric_display`` with ``touch_edit``) marks edit focus the same way, by
calling :func:`draw_edit_marks` at the end of its ``paintEvent``:

- **focused**: a ring in :data:`FOCUS_COLOR` outset around the value, plus the
  circular-arrow edit icon (at most :data:`ICON_MAX_PX` square) in the ring's
  top-right corner -- "turn the knob".
- **at rest** (only when the panel-wide :func:`at_rest_hint` is on): the icon
  alone, dimmed, so the pilot can see which values a touch will focus.

The colour, icon and ring live here and nowhere else, so a change to the
language is a change to this file.

The module also holds the panel-wide single-focus registry. Focus itself is
owned by each screen's ``EncoderController`` (it already routes the knob to
the instrument in control); :func:`claim` makes sure only one controller,
panel-wide, holds focus at a time, and while one does it watches the whole
application for a press outside the focused value -- touching anywhere else
clears focus.
"""

import logging

from PyQt6.QtCore import QEvent, QObject, QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QPainterPath, QPen, QBrush
from PyQt6.QtWidgets import QApplication

logger = logging.getLogger(__name__)

# Cyan, per docs/gcu_design.md section 3 (Garmin's pilot-selected colour). The
# HSI's selected-heading box is already cyan-bordered, so the focus cue cannot
# rely on hue alone: the ring is OUTSET from the value with a gap, so it reads
# as a second, separate outline even around a cyan box.
FOCUS_COLOR = QColor(0, 255, 255)
ICON_MAX_PX = 10
RING_WIDTH_PX = 2.0
RING_GAP_PX = 2.0
HINT_ALPHA = 110  # at-rest icon, of 255

_at_rest_hint = False


def set_at_rest_hint(on):
    """Panel-wide: show the dim edit icon on every touch-editable value while
    nothing has focus. Set once at start-up from ``main: editIconAtRest``."""
    global _at_rest_hint
    _at_rest_hint = bool(on)


def at_rest_hint():
    return _at_rest_hint


def icon_size(value_rect):
    """The icon edge in px: ICON_MAX_PX, smaller only for a tiny value box."""
    return float(max(6, min(ICON_MAX_PX, int(value_rect.height() * 0.6))))


def edit_icon_path(size):
    """A circular arrow inside a ``size`` x ``size`` box at the origin: a 270
    degree arc, open at the top right, with a filled arrowhead on its end.

    Returned as two paths (stroke, head) so the head stays solid at 10 px."""
    s = float(size)
    pen_w = max(1.0, s / 7.0)
    r = s / 2.0 - pen_w
    c = QPointF(s / 2.0, s / 2.0)
    arc = QPainterPath()
    box = QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r)
    # Qt arc angles run counter-clockwise from 3 o'clock. Sweeping 270 deg from
    # 0 goes 3 -> 12 -> 9 -> 6 o'clock, leaving the bottom-right quadrant open;
    # at the 6 o'clock end the direction of travel is +x, so the head points
    # right, into the gap.
    arc.arcMoveTo(box, 0.0)
    arc.arcTo(box, 0.0, 270.0)
    end = arc.currentPosition()
    h = max(2.5, s * 0.36)
    head = QPainterPath()
    head.moveTo(end.x() + h, end.y())
    head.lineTo(end.x() - h * 0.15, end.y() - h * 0.75)
    head.lineTo(end.x() - h * 0.15, end.y() + h * 0.75)
    head.closeSubpath()
    return arc, head, pen_w


def icon_rect(value_rect, bounds=None):
    """Where the icon goes for a value drawn in ``value_rect``: centred on the
    top-right corner of the focus ring, like a badge -- or, when that would
    cross ``bounds`` (the widget's own edge), pulled inside it, sitting in the
    ring's corner."""
    s = icon_size(value_rect)
    ring = ring_rect(value_rect)
    r = QRectF(ring.right() - s / 2.0, ring.top() - s / 2.0, s, s)
    if bounds is not None:
        b = QRectF(bounds)
        dx = min(0.0, b.right() - r.right())
        dy = max(0.0, b.top() - r.top())
        r.translate(dx, dy)
    return r


def ring_rect(value_rect):
    out = RING_GAP_PX + RING_WIDTH_PX / 2.0
    return QRectF(value_rect).adjusted(-out, -out, out, out)


def inset_for_marks(rect):
    """The value rect to pass to :func:`draw_edit_marks` (with
    ``bounds=rect``) for a widget whose value fills its own bounds: the ring
    then hugs the widget edge, clear of the value, and the icon sits inside
    the ring's top-right corner."""
    rect = QRectF(rect)
    m = RING_GAP_PX + RING_WIDTH_PX + 0.5
    return rect.adjusted(m, m, -m, -m)


def draw_edit_icon(painter, rect, color=None, dim=False):
    """Draw the circular-arrow icon filling ``rect`` (a square <= 10 px)."""
    col = QColor(color if color is not None else FOCUS_COLOR)
    if dim:
        col.setAlpha(HINT_ALPHA)
    s = min(rect.width(), rect.height())
    arc, head, pen_w = edit_icon_path(s)
    painter.save()
    painter.setRenderHint(painter.RenderHint.Antialiasing, True)
    painter.translate(rect.topLeft())
    # A black backing disc keeps the glyph legible over terrain or a border.
    back = QColor(0, 0, 0, 160 if dim else 200)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(back))
    painter.drawEllipse(QRectF(0, 0, s, s))
    pen = QPen(col, pen_w)
    pen.setCapStyle(Qt.PenCapStyle.FlatCap)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(arc)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(col))
    painter.drawPath(head)
    painter.restore()


def draw_focus_highlight(painter, value_rect, color=None):
    """The focus ring: an outline outset from ``value_rect`` by a gap."""
    col = QColor(color if color is not None else FOCUS_COLOR)
    painter.save()
    painter.setRenderHint(painter.RenderHint.Antialiasing, True)
    painter.setPen(QPen(col, RING_WIDTH_PX))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    r = ring_rect(value_rect)
    painter.drawRoundedRect(r, 3.0, 3.0)
    painter.restore()


def draw_edit_marks(painter, value_rect, focused, bounds=None):
    """The one entry point widgets call: ring + icon when ``focused``, the dim
    icon alone when not focused and the at-rest hint is on, else nothing.

    ``value_rect`` is the value's box in the painter's coordinates. The ring
    is drawn RING_GAP_PX outside it; the icon badges the ring's top-right
    corner, kept inside ``bounds`` when given. A widget whose value fills its
    own bounds passes ``inset_for_marks(self.rect())`` and
    ``bounds=self.rect()``."""
    value_rect = QRectF(value_rect)
    if focused:
        draw_focus_highlight(painter, value_rect)
        draw_edit_icon(painter, icon_rect(value_rect, bounds))
    elif _at_rest_hint:
        draw_edit_icon(painter, icon_rect(value_rect, bounds), dim=True)


# --- panel-wide single focus ------------------------------------------------

class _TouchAwayFilter(QObject):
    """Application event filter, installed only while a value has focus: a
    press that does not land on the focused value releases focus. It never
    consumes the event, so the press still reaches whatever was touched (which
    may itself take focus)."""

    def eventFilter(self, obj, event):
        t = event.type()
        if t in (QEvent.Type.MouseButtonPress, QEvent.Type.TouchBegin):
            owner = _owner
            if owner is not None and not owner.focus_hit(_global_pos(event)):
                owner.release_focus()
        return False


def _global_pos(event):
    try:
        return event.globalPosition()
    except AttributeError:  # pragma: no cover - older event types
        pts = event.points() if hasattr(event, "points") else []
        return pts[0].globalPosition() if pts else QPointF(-1, -1)


_owner = None
_filter = None


def owner():
    """The controller holding panel-wide focus, or None."""
    return _owner


def claim(controller):
    """``controller`` takes panel-wide focus; any other holder is released
    first (through its ``release_focus()``, which calls :func:`release`). The
    controller must provide ``release_focus()`` and
    ``focus_hit(global_pos) -> bool``."""
    global _owner, _filter
    if _owner is not None and _owner is not controller:
        prev = _owner
        prev.release_focus()
        release(prev)  # in case its release_focus() did not
    _owner = controller
    app = QApplication.instance()
    if app is not None and _filter is None:
        _filter = _TouchAwayFilter()
        app.installEventFilter(_filter)


def release(controller):
    """Clear the registry if ``controller`` holds focus (no-op otherwise).
    Called by the controller from its own ``release_focus()``; this never calls
    back into the controller."""
    global _owner, _filter
    if _owner is not controller:
        return
    _owner = None
    if _filter is not None:
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(_filter)
        _filter = None
