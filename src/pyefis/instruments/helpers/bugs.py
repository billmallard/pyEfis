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

"""Shared parts of a selected-value bug (docs/instrument_bugs_design.md s.3).

A bug is one FIX set-point painted into an instrument's own geometry. What
every bug repeats lives here; where the bug goes stays with the instrument:

- :class:`BugBinding` -- the guarded FIX subscription and the visibility
  policy (hidden on fail, greyed on old/bad, absent when the key is missing),
  plus the alert colour while the key's annunciate flag is set.
- :func:`tape_bug_path` -- the tape-edge glyph (a notched block, the notch
  pointing at the scale).
- :func:`clamp_to_span` -- the off-scale policy: a target beyond the visible
  tape pegs at the edge, centred on it, so half the glyph shows.

The altimeter tape's selected-altitude bug (pyEfis #310) is the first user.
The HSI heading bug predates this module and keeps its own copy for now.
"""

import logging

from PyQt6.QtCore import QObject, QPointF, pyqtSignal
from PyQt6.QtGui import QColor, QPainterPath, QPolygonF

import pyavtools.fix as fix

logger = logging.getLogger(__name__)

#: Garmin cyan, the pilot-selected colour (matches heading_bug_color).
BUG_COLOR = QColor(0, 255, 255)
#: A bug whose source is old or bad is drawn in this colour instead.
BUG_DEGRADED_COLOR = QColor(128, 128, 128)
#: A bug whose key is annunciated (a deviation the gateway flagged, e.g. the
#: ALTSEL altitude alert, EFIS-ALTSEL-006) is drawn in amber: a caution.
BUG_ALERT_COLOR = QColor(255, 176, 0)

STATE_MISSING = "missing"    # the key is not in the FIX database
STATE_INVALID = "invalid"    # failed: no usable value (draw dashes, no bug)
STATE_DEGRADED = "degraded"  # old or bad: draw greyed
STATE_OK = "ok"


class BugBinding(QObject):
    """One FIX set-point key, subscribed once.

    Construction never raises: a database without ``key`` logs a warning and
    leaves :attr:`item` None, so the host instrument still builds. ``changed``
    fires on any value or quality change."""

    changed = pyqtSignal()

    def __init__(self, key, parent=None):
        super().__init__(parent)
        self.key = key
        self.item = None
        try:
            self.item = fix.db.get_item(key)
        except KeyError:
            logger.warning("FIX key %s not in the database; its bug is off", key)
            return
        try:
            self.item.valueChanged[self.item.dtype].connect(self._emit)
        except (KeyError, TypeError):
            self.item.valueChanged[float].connect(self._emit)
        for sig in (self.item.oldChanged, self.item.badChanged,
                    self.item.failChanged, self.item.annunciateChanged):
            sig.connect(self._emit)

    def _emit(self, *_):
        self.changed.emit()

    @property
    def value(self):
        return None if self.item is None else self.item.value

    @property
    def state(self):
        if self.item is None:
            return STATE_MISSING
        if self.item.fail:
            return STATE_INVALID
        if self.item.old or self.item.bad:
            return STATE_DEGRADED
        return STATE_OK

    @property
    def alerting(self):
        """Is the key's annunciate flag set on a drawable value?

        The flag is the only input: whoever computes the alert (fix-gateway's
        annunciate plugin for ALTSEL) owns the threshold and the arming. As on
        the gauges and ``value_text``, the alert outranks old/bad but not
        fail, which draws no bug at all."""
        return (self.item is not None and bool(self.item.annunciate)
                and not self.item.fail)

    def color(self, normal=None, alert=None):
        """The colour to draw the bug in for the current state."""
        if self.alerting:
            return QColor(alert if alert is not None else BUG_ALERT_COLOR)
        if self.state == STATE_DEGRADED:
            return QColor(BUG_DEGRADED_COLOR)
        return QColor(normal if normal is not None else BUG_COLOR)

    def drawable(self):
        """Is there a value worth putting on the scale?"""
        return self.state in (STATE_OK, STATE_DEGRADED)


def clamp_to_span(pos, lo, hi):
    """The off-scale policy for a tape: ``pos`` clamped to ``[lo, hi]``.

    Returns ``(pos, off)`` with ``off`` -1 when the target was beyond ``lo``,
    +1 beyond ``hi``, else 0. The caller centres the glyph on the returned
    position, so a pegged bug shows half of itself at the edge -- the
    direction cue (EFIS-ALTSEL-004)."""
    if pos < lo:
        return lo, -1
    if pos > hi:
        return hi, 1
    return pos, 0


def tape_bug_path(x, y, width, height, point_right=True):
    """The tape-edge bug glyph, centred vertically on ``y``.

    A block ``width`` wide standing on the tape edge at ``x``, with a V notch
    cut into the side facing the scale (``point_right``: the scale is to the
    right of ``x``). The notch apex sits on ``y`` so the bug reads against the
    same tick the read pointer does."""
    h2 = height / 2.0
    notch_h = height / 3.0
    notch_d = width * 0.45
    s = 1.0 if point_right else -1.0
    far = x + s * width
    pts = [
        QPointF(x, y - h2),
        QPointF(far, y - h2),
        QPointF(far, y - notch_h / 2.0),
        QPointF(far - s * notch_d, y),
        QPointF(far, y + notch_h / 2.0),
        QPointF(far, y + h2),
        QPointF(x, y + h2),
    ]
    path = QPainterPath()
    path.addPolygon(QPolygonF(pts))
    path.closeSubpath()
    return path
