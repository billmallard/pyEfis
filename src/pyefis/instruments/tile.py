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

"""The shared lamp tile: one caption in a box, coloured by level.

The ``annunciator`` instrument (ANN1) is the first user; the CAS window and
marker (CAS3) draw their messages with the same tile, so a caution reads the
same on every lamp-like widget.

Levels, most severe first:

    warning   red     reverse video (filled box, dark text)
    caution   amber   reverse video
    status    green   coloured caption and outline
    advisory  white   coloured caption and outline
    info      cyan    coloured caption and outline
    off       muted   dim caption, thin outline

``warning`` and ``caution`` are the tier-1 alerting colours. Which callers may
ask for them is the caller's rule (the annunciator allows them only for the
key's own ``annunciate`` flag; Bill, 2026-11-22). This module only draws.

A *stale* tile -- its source old, bad or failed -- is drawn in the degraded
grey with a dashed outline whatever its level, so it never reads as current.
A tile that is ``None`` is not drawn at all: nothing has been seen yet.
"""

from dataclasses import dataclass

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QPen

WARNING = "warning"
CAUTION = "caution"
STATUS = "status"
ADVISORY = "advisory"
INFO = "info"
OFF = "off"

LEVELS = (WARNING, CAUTION, STATUS, ADVISORY, INFO, OFF)
#: The levels that are alerts: reverse video, and restricted by the caller.
ALERT_LEVELS = (WARNING, CAUTION)

#: Built-in colour per level. Each is the current value of the style-contract
#: token the instruments' colour props map it to (``state.warning``,
#: ``state.caution``, ``state.valid``, ``ink.primary``, ``accent``,
#: ``ink.muted``).
DEFAULT_COLORS = {
    WARNING: "#ff0000",
    CAUTION: "#ffaa00",
    STATUS: "#00ff00",
    ADVISORY: "#ffffff",
    INFO: "#00ffff",
    OFF: "#aaaaaa",
}
#: The degraded grey of every old/bad source (helpers/bugs.py
#: BUG_DEGRADED_COLOR). Not themeable: it is what "stale" looks like.
STALE_COLOR = "#808080"
#: Text on a reverse-video tile.
REVERSE_TEXT_COLOR = "#000000"

#: Half-period of the flash: on 0.5 s, off 0.5 s (as the AFC4 strip).
BLINK_HALF_S = 0.5


@dataclass
class Tile:
    """What one lamp shows.

    ``boxed`` draws the outline heavier (a change being called out);
    ``flash`` blinks the caption (and a reverse-video fill) on the shared
    phase; ``stale`` overrides the level with the degraded look."""

    text: str
    level: str = ADVISORY
    boxed: bool = False
    flash: bool = False
    stale: bool = False


def blink_on(now):
    """Is the shared flash phase 'on' at monotonic time *now*?"""
    return int(now / BLINK_HALF_S) % 2 == 0


def font(family, px):
    f = QFont(family)
    f.setPixelSize(max(1, int(px)))
    f.setBold(True)
    return f


def fit_px(device, family, texts, width, height, px):
    """The largest pixel size, at most *px*, at which every one of *texts*
    fits *width* x *height* (one size for a whole block, so captions do not
    change size as states change)."""
    px = max(4.0, float(px))
    for _ in range(60):
        fm = QFontMetricsF(font(family, px), device)
        ok = True
        for text in texts:
            lines = str(text).split("\n") or [""]
            if (max(fm.horizontalAdvance(line) for line in lines) > width
                    or fm.height() * len(lines) > height):
                ok = False
                break
        if ok or px <= 4.0:
            return px
        px = max(4.0, px - 1.0)
    return px


def tile_color(tile, colors=None):
    """The QColor a tile's level is drawn in (the degraded grey if stale)."""
    if tile.stale:
        return QColor(STALE_COLOR)
    colors = colors or {}
    return QColor(colors.get(tile.level) or DEFAULT_COLORS.get(
        tile.level, DEFAULT_COLORS[ADVISORY]))


def paint_tile(p, rect, tile, colors=None, family="DejaVu Sans Condensed",
               px=12.0, border_px=2.0, radius=0.0, now=0.0,
               align=Qt.AlignmentFlag.AlignCenter, flash_blank=True):
    """Paint *tile* into *rect* with painter *p*. ``None`` paints nothing.

    *colors* maps level -> colour (a hex string or QColor), falling back to
    :data:`DEFAULT_COLORS`. *px* is the caption's pixel size (use
    :func:`fit_px` once for a block). *now* drives the flash phase.

    *align* places the caption (CAS lines are left-aligned, inset from the
    border). With ``flash_blank=False`` a flashing tile never goes blank: it
    swaps reverse video and outline each half-period, so its caption reads in
    both phases (CAS3, where the flashing text is the message itself)."""
    if tile is None:
        return
    rect = QRectF(rect)
    color = tile_color(tile, colors)
    lit = blink_on(now) or not tile.flash
    reverse = tile.level in ALERT_LEVELS and not tile.stale
    width = max(1.0, float(border_px))
    if tile.boxed:
        width *= 2.0
    elif tile.level == OFF and not tile.stale:
        width = max(1.0, width / 2.0)
    half = width / 2.0
    box = rect.adjusted(half, half, -half, -half)
    if tile.flash and not flash_blank and not tile.stale:
        reverse = reverse != (not lit)
        lit = True

    p.save()
    pen = QPen(color, width)
    if tile.stale:
        pen.setStyle(Qt.PenStyle.DashLine)
    p.setPen(pen)
    if reverse and lit:
        p.setBrush(color)
    else:
        p.setBrush(Qt.BrushStyle.NoBrush)
    if radius > 0:
        p.drawRoundedRect(box, radius, radius)
    else:
        p.drawRect(box)
    if lit and tile.text:
        p.setFont(font(family, px))
        p.setPen(QPen(QColor(REVERSE_TEXT_COLOR) if reverse else color))
        inset = 0.0 if align & Qt.AlignmentFlag.AlignHCenter else px * 0.4
        p.drawText(box.adjusted(inset, 0, -inset, 0), align, str(tile.text))
    p.restore()
