#  SPDX-License-Identifier: GPL-2.0-or-later
#  Moving map airports layer (spec 5.2, Phase C).
#
#  FAA sectional symbology from the NASR airports.sqlite (the same db
#  the SVS uses): hard-surface airports 1500-8069 ft draw the classic
#  circle with real-orientation runway strips inside; >8069 ft draw
#  the runway strips alone (no circle); non-hard fields draw a plain
#  circle. All magenta until tower (TWR) data joins the pack -- then
#  towered fields turn blue (spec decision 3). Ident labels and a
#  deterministic grid declutter keep the picture stable by zoom.
#
#  RWY1 (AER-4631): per airport, once its longest runway is longer on
#  screen than the symbol is wide, the symbol gives way to the runways
#  at true size and position -- one polygon per runway from the
#  surveyed threshold pair, offset by half the published width. Hard
#  surfaces fill white; turf/gravel/dirt draw hollow; water dashes.
#  Runway numbers read from the approach end once there is room.
#
#  Same async contract as the terrain layer: a worker snapshots the
#  window's airports; paint() only projects and draws.

import math
import threading
import time

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QFont, QPainterPath, QPen, QPolygonF

from pyefis.flightplan.waypoints import Waypoint
from pyefis.instruments.map.layers import (STANDARD_PALETTE, MapLayer,
                                           hit_distance, qcolor, range_bucket,
                                           register_layer)

MAGENTA = qcolor(STANDARD_PALETTE["airport"])

#: ranges (NM): idents shown at/below the first, symbols at/below the second
_IDENT_RANGE = 40.0
_SYMBOL_RANGE = 80.0

FT_PER_NM = 6076.12
#: true-size runways never draw thinner than this (px), so a 50 ft strip
#: at 10 NM is still a visible line rather than a hairline
_MIN_RWY_WIDTH_PX = 2.0
#: runway numbers need the runway to be this many font heights long
_NUMBER_ROOM = 5.0

_HARD = ("ASPH", "CONC", "PEM")     # NASRAirportDB(paved_only=True)'s rule


def surface_class(surface):
    """NASR surface code -> ``"hard"``, ``"water"`` or ``"soft"`` (turf,
    gravel, dirt, mats, ...). Hard follows the paved-only filter's rule,
    so ``ASPH-TURF`` is hard here exactly as it is there."""
    s = (surface or "").upper()
    if any(t in s for t in _HARD):
        return "hard"
    if "WATER" in s:
        return "water"
    return "soft"


@register_layer
class AirportsLayer(MapLayer):
    id = "airports"
    label = "Airports"
    z = 30
    default_on = True

    _SNAP_FRAC = 0.25       # window re-anchor hysteresis

    def __init__(self):
        super(AirportsLayer, self).__init__()
        self._db_all = None
        self._db_paved = None
        self._snap = None       # (key, [airport dicts])
        self._job = None
        self._worker = None
        self._lock = threading.Lock()

    def configure(self, owner):
        self._owner = owner
        path = str(getattr(owner, "nasr_db_path", "") or "")
        if path:
            from pyefis.instruments.ai.airport_db import NASRAirportDB
            self._db_all = NASRAirportDB(path, paved_only=False)
            self._db_paved = NASRAirportDB(path, paved_only=True)

    def _key(self, x):
        snap = max(1.0, x.range_nm * self._SNAP_FRAC)
        return (round(x.lat0 * 60.0 / snap), round(x.lon0 * 60.0 / snap),
                range_bucket(x.range_nm))

    def is_settled(self, x):
        if self._db_all is None or not self._db_all.ready \
                or x.range_nm > _SYMBOL_RANGE:
            return True
        key = self._key(x)
        with self._lock:
            snap = self._snap
        return snap is not None and snap[0] == key

    def paint(self, p, x):
        if self._db_all is None or not self._db_all.ready \
                or x.range_nm > _SYMBOL_RANGE:
            return
        key = self._key(x)
        with self._lock:
            snap = self._snap
            have = snap is not None and snap[0] == key
        if not have and not getattr(x, "defer_render", False):
            with self._lock:
                # Same-key reposts must not refresh the in-flight job:
                # the raw pose in the tuple would make the worker's
                # latest-wins check discard every finished snapshot
                # while the aircraft is moving (#89).
                if self._job is None or self._job[0] != key:
                    self._job = (key, x.lat0, x.lon0, x.range_nm)
                    perf = getattr(self._owner, "perf", None)
                    if perf is not None:
                        perf.layer(self.id).jobs_requested += 1
                if self._worker is None:
                    self._worker = threading.Thread(
                        target=self._worker_loop, name="map-airports",
                        daemon=True)
                    self._worker.start()
        if snap is None:
            return
        show_ident = x.range_nm <= _IDENT_RANGE
        # Symbol radius: ~9 px at 500 px width, clamped sane.
        r = max(6.0, min(14.0, x.w * 0.018))
        f = QFont(x.font_family)
        f.setPixelSize(max(8, int(x.w * 0.022)))
        p.setFont(f)
        colour = qcolor(getattr(x, "palette", STANDARD_PALETTE)["airport"])
        for a in snap[1]:
            c = x.to_screen(a["lat"], a["lon"])
            rwys = (self._runway_geometry(x, a)
                    if self._true_size(x, a, r) else [])
            if rwys:
                box = rwys[0]["poly"].boundingRect()
                for g in rwys[1:]:
                    box = box.united(g["poly"].boundingRect())
                if box.intersects(QRectF(0, 0, x.w, x.h)):
                    taken = []
                    if show_ident and a["icao"]:
                        fpx = f.pixelSize()
                        taken.append((c.x(), box.bottom() + 1 + fpx * 0.6,
                                      len(a["icao"]) * fpx * 0.3))
                    self._draw_true_size(p, x, rwys, colour, f.pixelSize(),
                                         taken)
                    if show_ident and a["icao"]:
                        p.setPen(QPen(QColor(255, 255, 255, 230)))
                        p.drawText(
                            QRectF(c.x() - 60, box.bottom() + 1, 120,
                                   f.pixelSize() + 4),
                            Qt.AlignmentFlag.AlignHCenter, a["icao"])
                continue
            if not (-r < c.x() < x.w + r and -r < c.y() < x.h + r):
                continue
            pen = QPen(colour)
            pen.setWidthF(max(1.2, r * 0.16))
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            if a["hard"] and a["longest"] > 8069:
                self._runway_strips(p, x, a, r * 1.6, colour)
            elif a["hard"]:
                p.drawEllipse(c, r, r)
                p.save()
                clip = QPainterPath()
                clip.addEllipse(c, r, r)
                p.setClipPath(clip)
                self._runway_strips(p, x, a, r, colour)
                p.restore()
            else:
                p.drawEllipse(c, r, r)
            if show_ident and a["icao"]:
                p.setPen(QPen(QColor(255, 255, 255, 230)))
                p.drawText(
                    QRectF(c.x() - 60, c.y() + r + 1, 120,
                           f.pixelSize() + 4),
                    Qt.AlignmentFlag.AlignHCenter, a["icao"])

    def hit(self, x, px, py, tol_px):
        """FP10: airports whose symbol centre is within *tol_px* -- the
        snapshot ``paint()`` draws from, under the same range gate."""
        if self._db_all is None or not self._db_all.ready \
                or x.range_nm > _SYMBOL_RANGE:
            return []
        with self._lock:
            snap = self._snap
        if snap is None:
            return []
        out = []
        for a in snap[1]:
            if not a["icao"]:
                continue
            d = hit_distance(x, a["lat"], a["lon"], px, py, tol_px)
            if d is not None:
                out.append((d, Waypoint(id=a["icao"], type="airport",
                                        lat=a["lat"], lon=a["lon"])))
        return out

    @staticmethod
    def _symbol_diameter(a, r):
        """Width of the symbol ``paint()`` would draw for *a*: the ring, or
        the bare strips (half length ``1.6 r``) of a >8069 ft field."""
        if a["hard"] and a["longest"] > 8069:
            return 3.2 * r
        return 2.0 * r

    def _true_size(self, x, a, r):
        """RWY1: draw *a*'s runways at true size once its longest surveyed
        runway is longer on screen than its symbol is wide. An airport
        with no drawable runway keeps the symbol."""
        span = a.get("span_nm", 0.0)
        return span > 0.0 and x.nm_to_px(span) > self._symbol_diameter(a, r)

    @staticmethod
    def _runway_geometry(x, a):
        """Screen geometry per runway: the threshold points ``e1``/``e2``
        through ``x.to_screen``, the unit vector ``u`` from ``e1`` to
        ``e2``, and ``poly`` -- the four corners, each threshold offset by
        half the published width (floored at ``_MIN_RWY_WIDTH_PX``)."""
        out = []
        for rw in a["runways"]:
            e1 = x.to_screen(rw["lat1"], rw["lon1"])
            e2 = x.to_screen(rw["lat2"], rw["lon2"])
            dx, dy = e2.x() - e1.x(), e2.y() - e1.y()
            d = math.hypot(dx, dy)
            if d < 1e-3:
                continue
            ux, uy = dx / d, dy / d
            hw = max(_MIN_RWY_WIDTH_PX,
                     x.nm_to_px(rw["width_ft"] / FT_PER_NM)) / 2.0
            nx, ny = -uy * hw, ux * hw
            poly = QPolygonF([QPointF(e1.x() + nx, e1.y() + ny),
                              QPointF(e2.x() + nx, e2.y() + ny),
                              QPointF(e2.x() - nx, e2.y() - ny),
                              QPointF(e1.x() - nx, e1.y() - ny)])
            out.append({"rw": rw, "e1": e1, "e2": e2, "u": (ux, uy),
                        "len_px": d, "half_w": hw, "poly": poly})
        return out

    def _draw_true_size(self, p, x, rwys, edge, font_px, taken=None):
        """Runway polygons first, then displaced-threshold bars, then the
        numbers on top. A later runway's fill covers an earlier one's edge
        where they cross, so an intersection reads as joined pavement.

        *taken* holds ``(cx, cy, radius)`` circles already labelled (the
        ident); a number that would overprint one of those, or an earlier
        number (close parallels: 18L/18R), is skipped."""
        taken = list(taken or [])
        for g in rwys:
            kind = g["rw"]["kind"]
            pen = QPen(edge)
            pen.setWidthF(1.5)
            if kind == "water":
                pen.setStyle(Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.setBrush(QBrush(QColor(255, 255, 255)) if kind == "hard"
                       else Qt.BrushStyle.NoBrush)
            p.drawPolygon(g["poly"])
        for g in rwys:
            self._displaced_bars(p, x, g, edge)
        p.setPen(QPen(QColor(255, 255, 255, 230)))
        for g in rwys:
            if g["len_px"] < _NUMBER_ROOM * font_px:
                continue
            ux, uy = g["u"]
            rw = g["rw"]
            for end_id, pt, (vx, vy) in ((rw["end1"], g["e1"], (ux, uy)),
                                         (rw["end2"], g["e2"], (-ux, -uy))):
                if not end_id:
                    continue
                # Just short of the threshold on the approach side, text
                # "up" pointing down the runway: it reads upright to a
                # pilot landing on that end.
                off = font_px * 0.75
                cx, cy = pt.x() - vx * off, pt.y() - vy * off
                rad = max(len(end_id) * 0.3, 0.5) * font_px
                if any(math.hypot(cx - tx, cy - ty) < rad + tr
                       for tx, ty, tr in taken):
                    continue
                taken.append((cx, cy, rad))
                p.save()
                p.translate(cx, cy)
                p.rotate(math.degrees(math.atan2(vx, -vy)))
                p.drawText(QRectF(-font_px * 2, -font_px * 0.6,
                                  font_px * 4, font_px * 1.2),
                           Qt.AlignmentFlag.AlignCenter, end_id)
                p.restore()

    @staticmethod
    def _displaced_bars(p, x, g, edge):
        """A bar across the runway at each displaced threshold, when the
        runway is wide enough and the displacement long enough to read."""
        if g["half_w"] < 2.0:
            return
        ux, uy = g["u"]
        nx, ny = -uy * g["half_w"], ux * g["half_w"]
        rw = g["rw"]
        pen = QPen(edge)
        pen.setWidthF(2.0)
        for disp_ft, pt, s in ((rw["disp1_ft"], g["e1"], 1.0),
                               (rw["disp2_ft"], g["e2"], -1.0)):
            dpx = x.nm_to_px((disp_ft or 0.0) / FT_PER_NM)
            if dpx < 3.0 or dpx >= g["len_px"] / 2.0:
                continue
            bx, by = pt.x() + s * ux * dpx, pt.y() + s * uy * dpx
            p.setPen(pen)
            p.drawLine(QPointF(bx + nx, by + ny), QPointF(bx - nx, by - ny))

    def _runway_strips(self, p, x, a, half_len_px, edge=MAGENTA):
        """Runway strips at TRUE orientation: white fill, magenta edge,
        centred on the airport, length capped to the symbol scale."""
        c = x.to_screen(a["lat"], a["lon"])
        for (la1, lo1, la2, lo2) in a["rwys"]:
            e1 = x.to_screen(la1, lo1)
            e2 = x.to_screen(la2, lo2)
            dx, dy = e2.x() - e1.x(), e2.y() - e1.y()
            d = math.hypot(dx, dy)
            if d < 1e-3:
                continue
            ux, uy = dx / d, dy / d
            L = min(half_len_px, max(half_len_px * 0.55, d / 2.0))
            wpx = max(1.6, half_len_px * 0.22)
            p.save()
            p.translate(c)
            p.rotate(math.degrees(math.atan2(uy, ux)))
            p.setPen(QPen(edge, 1))
            p.setBrush(QBrush(QColor(255, 255, 255)))
            p.drawRect(QRectF(-L, -wpx / 2.0, 2 * L, wpx))
            p.restore()

    # --- worker -------------------------------------------------------------
    def _worker_loop(self):
        last = None
        while True:
            with self._lock:
                job = self._job
            if job is None or job == last:
                time.sleep(0.05)
                continue
            self._process_job(job)
            last = job
            try:
                self._owner.update()
            except RuntimeError:
                return

    def _process_job(self, job):
        """MP6 instrumentation around the newest-wins collect/publish the
        other layers use (AER-588): a finished collect is always
        published, even if a newer job replaced ``_job`` while it ran --
        see terrain.py's ``_process_job`` for the rationale. That race is
        still counted as ``jobs_superseded`` (published, but already
        stale by the time it landed)."""
        perf = getattr(self._owner, "perf", None)
        ls = perf.layer(self.id) if perf is not None else None
        if ls is not None:
            ls.jobs_started += 1
        t0 = time.perf_counter()
        try:
            snap = self._collect(job)
            ms = (time.perf_counter() - t0) * 1000.0
            with self._lock:
                superseded = self._job != job
                self._snap = (job[0], snap)
            if ls is not None:
                ls.record_render_ms(ms)
                ls.jobs_published += 1
                if superseded:
                    ls.jobs_superseded += 1
        except Exception:
            import logging
            logging.getLogger(__name__).exception(
                "map airports collect failed")
            with self._lock:
                if self._job == job:
                    self._job = None   # let the next paint re-request

    def _collect(self, job):
        key, lat0, lon0, range_nm = job
        # Window covers the rotated view generously.
        radius = range_nm * 2.2
        hard_ids = {a.icao for a in
                    self._db_paved.airports_in_range(lat0, lon0, radius)}
        out = []
        for a in self._db_all.airports_in_range(lat0, lon0, radius):
            longest = max((r.length_ft for r in a.runways), default=0.0)
            coslat = math.cos(math.radians(a.ref_lat))
            runways, span = [], 0.0
            for r in a.runways:
                if None in (r.thr1_lat, r.thr1_lon, r.thr2_lat, r.thr2_lon):
                    continue
                runways.append({
                    "lat1": r.thr1_lat, "lon1": r.thr1_lon,
                    "lat2": r.thr2_lat, "lon2": r.thr2_lon,
                    "width_ft": r.width_ft, "kind": surface_class(r.surface),
                    "end1": r.thr1_designator, "end2": r.thr2_designator,
                    "disp1_ft": r.thr1_displaced_ft,
                    "disp2_ft": r.thr2_displaced_ft,
                })
                span = max(span, 60.0 * math.hypot(
                    r.thr2_lat - r.thr1_lat,
                    (r.thr2_lon - r.thr1_lon) * coslat))
            out.append({
                "icao": a.icao, "lat": a.ref_lat, "lon": a.ref_lon,
                "longest": longest, "hard": a.icao in hard_ids,
                "rwys": [(r.thr1_lat, r.thr1_lon, r.thr2_lat, r.thr2_lon)
                         for r in a.runways][:4],
                # RWY1: every surveyed runway, and the longest threshold-
                # to-threshold distance (NM) that gates true-size drawing
                "runways": runways, "span_nm": span,
            })
        # Deterministic declutter: grid buckets (~1/8 of the range),
        # keep the two longest-runway airports per bucket.
        cell = max(2.0, range_nm / 4.0) / 60.0     # degrees
        buckets = {}
        for a in out:
            b = (round(a["lat"] / cell), round(a["lon"] / cell))
            buckets.setdefault(b, []).append(a)
        kept = []
        for b in buckets.values():
            b.sort(key=lambda a: -a["longest"])
            kept.extend(b[:2])
        return kept
