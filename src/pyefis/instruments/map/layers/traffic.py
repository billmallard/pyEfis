#  SPDX-License-Identifier: GPL-2.0-or-later
"""ADS-B traffic on the moving map (P3b, CAP-401, billmallard/pyEfis#53).

Consumes the ``TFCk*`` key block that the fix-gateway traffic writer fills
from GDL90 Traffic Reports. The contract is ``docs/fix_dynamic_list_spec.md``
section 5 (what the display may assume); this module implements it and adds
nothing the spec does not carry. The reader and the classification live in
``pyefis.instruments.traffic``, shared with the synthetic vision (SVSTFC1);
this module paints them.

Reading rules, each from the spec:

- **Act on the commit key.** A slot is read only when its ``TFCkTGT`` is
  written (section 2.5). The handler runs synchronously in the thread that
  wrote ``TGT`` (the FIX client thread, or the test), and the writer writes
  every field before ``TGT``, so the fields it reads belong to that target.
  It builds an immutable :class:`Target` and stores it under a lock; paint
  only reads the stored targets.
- **Key state by identity, not slot.** Targets are stored by their ``TGT``
  value. A slot only says which identity to drop when it is emptied.
- **Flags.** ``TGT`` ``fail`` (the source failed, section 4.7) hides the
  target and raises ``TFC FAIL`` on the map. ``TGT`` ``old`` (no report for
  3 s) draws the target as stale, until the writer evicts it (section 4.6:
  ``evict_s`` exceeds ``tol`` so that a stale target is shown as stale
  before it disappears). A stale target the writer never evicts -- the
  writer itself has died -- is hidden after :data:`STALE_HIDE_S`.
- A field marked ``bad`` is unavailable: its part of the symbol is dashed or
  left out, never drawn as zero. ``TTYP = 0`` (``TRK`` bad) gives a
  non-directional symbol (GDL90 G§3.5.1.9).
- **Relative altitude** is ``TFCkALT - PALT`` (section 4.9). With ``PALT``
  absent, ``old``, ``bad`` or ``fail``, it is dashed, never computed from
  another altitude.
- **No geometry filter.** Ownship is removed by identity in the writer
  (section 4.8, Bill's F6 ruling). Every target on the bus is drawn,
  including one at ownship's own position.

Symbology follows GDL90's display recommendations (G§3.5.1.1, G§3.5.1.6):
alert = yellow, flashing; degraded (NIC or NACp 4 or lower) = an open
outline instead of a filled symbol; stale = grey, dashed.
"""

import logging
import math
import time

import pyavtools.fix as pyavtools_fix
from PyQt6.QtCore import QObject, QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QBrush, QColor, QFont, QPen, QPolygonF

from pyefis.instruments.map.layers import MapLayer, register_layer
from pyefis.instruments.traffic import (  # noqa: F401 -- Target re-exported
    ALERT_COLOR, FAIL_COLOR, FLASH_S, NORMAL_COLOR, OUTLINE_COLOR,
    STALE_COLOR, STALE_HIDE_S, Target, TrafficBlock, _float_or_none,
    alt_tag, draw_order, is_degraded, relative_alt_ft, trend, true_track,
    visible)

log = logging.getLogger(__name__)


def symbol_polygon(s, directional):
    """Symbol outline about (0, 0), nose up: an arrowhead when the track is
    known, a diamond when it is not (G§3.5.1.9)."""
    if directional:
        return QPolygonF([QPointF(0, -s), QPointF(s * 0.75, s * 0.75),
                          QPointF(0, s * 0.3), QPointF(-s * 0.75, s * 0.75)])
    return QPolygonF([QPointF(0, -s), QPointF(s * 0.8, 0),
                      QPointF(0, s), QPointF(-s * 0.8, 0)])


@register_layer
class TrafficLayer(MapLayer):
    id = "traffic"
    label = "Traffic"
    z = 50                      # over the flight plan, under ownship
    default_on = True

    def __init__(self):
        super().__init__()
        self._owner = None
        self._block = None
        self._palt = None
        self._magvar = None
        self._timer = None
        self._flash_on = True

    def configure(self, owner, db=None):
        self._owner = owner
        db = db if db is not None else getattr(pyavtools_fix, "db", None)
        if db is None:
            return
        self._block = TrafficBlock(db, self._mark_dirty)
        if not self._block.available:
            log.info("map traffic: no TFC block on the bus; layer inert")
            self._block = None
            return
        for key, attr in (("PALT", "_palt"), ("MAGVAR", "_magvar")):
            try:
                setattr(self, attr, db.get_item(key))
            except KeyError:
                if key == "PALT":
                    log.warning("map traffic: no PALT key; relative "
                                "altitude is dashed")
        if isinstance(owner, QObject):
            self._timer = QTimer(owner)
            self._timer.timeout.connect(self._tick)
            self._timer.start(int(FLASH_S * 1000))

    def _mark_dirty(self):
        # Any thread: the map's frame clock repaints on its next tick.
        if self._owner is not None:
            self._owner._frame_dirty = True

    def _tick(self):
        """Flash alerted targets and drop over-age stale ones. Repaints
        only while one of them is on screen."""
        if self._block is None or not self.enabled:
            return
        self._flash_on = not self._flash_on
        now = time.monotonic()
        for t in self._block.targets():
            if t.alert and not t.stale:
                self._mark_dirty()
                return
            if t.stale and now - t.t_write > STALE_HIDE_S:
                self._mark_dirty()
                return

    def palt_ft(self):
        """Ownship pressure altitude, or None when unusable (spec 4.9)."""
        it = self._palt
        if it is None or it.old or it.bad or it.fail:
            return None
        return _float_or_none(it.value)

    def magvar(self):
        it = self._magvar
        if it is None or it.old or it.bad or it.fail:
            return None
        return _float_or_none(it.value)

    def source_failed(self):
        return self._block is not None and self._block.source_failed()

    def targets(self):
        return [] if self._block is None else self._block.targets()

    def paint(self, p, x):
        if self._block is None:
            return
        t0 = time.perf_counter()
        try:
            self._paint(p, x)
        finally:
            perf = getattr(self._owner, "perf", None)
            if perf is not None:
                perf.layer(self.id).record_render_ms(
                    (time.perf_counter() - t0) * 1000.0)

    def _paint(self, p, x):
        now = time.monotonic()
        palt = self.palt_ft()
        magvar = self.magvar()
        s = max(7.0, x.w * 0.02)
        f = QFont(x.font_family)
        f.setPixelSize(max(9, int(x.w * 0.026)))
        f.setBold(True)
        p.setFont(f)
        rot_deg = math.degrees(x.rot)
        margin = 3.0 * s
        for t in draw_order(self._block.targets()):
            if not visible(t, now):
                continue
            c = x.to_screen(t.lat, t.lon)
            if (c.x() < -margin or c.y() < -margin
                    or c.x() > x.w + margin or c.y() > x.h + margin):
                continue
            self._paint_target(p, c, t, s, true_track(t, magvar), rot_deg,
                               relative_alt_ft(t, palt))
        if self.source_failed():
            self._paint_fail(p, x, f)

    def _paint_target(self, p, c, t, s, trk, rot_deg, rel_ft):
        if t.stale:
            color = STALE_COLOR
        elif t.alert:
            color = ALERT_COLOR
        else:
            color = NORMAL_COLOR
        # Degraded and stale are open outlines; an alert flashes between
        # filled and open so it is never invisible.
        filled = not t.stale and not is_degraded(t)
        if t.alert and not t.stale and not self._flash_on:
            filled = False
        directional = trk is not None
        poly = symbol_polygon(s, directional)

        p.save()
        p.translate(c)
        if directional:
            p.rotate(trk - rot_deg)
        if filled:
            p.setPen(QPen(OUTLINE_COLOR, 1.0))
            p.setBrush(QBrush(color))
            p.drawPolygon(poly)
        else:
            halo = QPen(OUTLINE_COLOR, 4.0)
            halo.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(halo)
            p.drawPolygon(poly)
            ink = QPen(color, 2.0)
            ink.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
            if t.stale:
                ink.setStyle(Qt.PenStyle.DashLine)
            p.setPen(ink)
            p.drawPolygon(poly)
        p.restore()

        # Data tag: relative altitude above the symbol for traffic above,
        # below it for traffic below or unknown; trend arrow to the right.
        tag = alt_tag(rel_ft)
        fm = p.fontMetrics()
        tw = fm.horizontalAdvance(tag)
        th = fm.height()
        above = rel_ft is not None and rel_ft > 0
        ty = c.y() - s * 1.2 - th if above else c.y() + s * 1.2
        rect = QRectF(c.x() - tw / 2.0 - 2.0, ty, tw + 4.0, th)
        p.setPen(QPen(OUTLINE_COLOR))
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            p.drawText(rect.translated(dx, dy), Qt.AlignmentFlag.AlignCenter, tag)
        p.setPen(QPen(color))
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, tag)

        d = trend(t)
        if d:
            ax = c.x() + s * 1.3
            half = s * 0.8
            tip = QPointF(ax, c.y() - d * half)
            tail = QPointF(ax, c.y() + d * half)
            head = s * 0.35
            wing_l = QPointF(ax - head, tip.y() + d * head)
            wing_r = QPointF(ax + head, tip.y() + d * head)
            for pen in (QPen(OUTLINE_COLOR, 4.0), QPen(color, 2.0)):
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                p.setPen(pen)
                p.drawLine(tail, tip)
                p.drawLine(wing_l, tip)
                p.drawLine(wing_r, tip)

    def _paint_fail(self, p, x, font):
        """``TFC FAIL``, bottom left: the traffic source is not delivering,
        so an empty map does not mean an empty sky (GDL90 G§3.1.1 asks the
        display to annunciate receiver status)."""
        p.setFont(font)
        label = "TFC FAIL"
        fm = p.fontMetrics()
        pad = 4.0
        bw = fm.horizontalAdvance(label) + 2 * pad
        bh = fm.height() + 2 * pad
        box = QRectF(6.0, x.h - bh - 6.0, bw, bh)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(30, 30, 30, 190)))
        p.drawRoundedRect(box, 3.0, 3.0)
        p.setPen(QPen(FAIL_COLOR))
        p.drawText(box, Qt.AlignmentFlag.AlignCenter, label)
