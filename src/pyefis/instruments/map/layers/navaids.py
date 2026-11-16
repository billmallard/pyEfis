#  SPDX-License-Identifier: GPL-2.0-or-later
#  Moving map navaid / fix / airway layers (spec 5.3, Phase D).
#
#  Reads navaids.sqlite (tools/build_navaid_db.py from NASR NAV/FIX/
#  AWY). Sectional-style symbols: VOR family = compass-rose hexagon
#  with a centre dot (VORTAC/VOR-DME share it v1), NDB = stippled
#  disc, fixes = open triangles, airways = light blue lines with the
#  ident at segment midpoints. Same async snapshot contract as the
#  other layers. Defaults per the spec: navaids on, airways off,
#  fixes off (70k fixes need range-gating, <=20 NM only).

import math
import sqlite3
import threading
import time

import numpy as np
from PyQt6.QtCore import QLineF, QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QFont, QPen, QPolygonF

from pyefis.flightplan.waypoints import Waypoint
from pyefis.instruments.map.layers import (STANDARD_PALETTE, MapLayer,
                                           hit_distance, mark_drawn, qcolor,
                                           range_bucket, register_layer)

BLUE = qcolor(STANDARD_PALETTE["navaid"])
DARKBLUE = qcolor(STANDARD_PALETTE["fix"])


class _DbLayer(MapLayer):
    """Shared windowed-sqlite snapshot machinery."""

    _SNAP_FRAC = 0.25

    def __init__(self):
        super(_DbLayer, self).__init__()
        self._path = ""
        self._snap = None
        self._job = None
        self._worker = None
        self._lock = threading.Lock()

    def configure(self, owner):
        self._owner = owner
        self._path = str(getattr(owner, "navaid_db_path", "") or "")

    def _key(self, x):
        snap = max(1.0, x.range_nm * self._SNAP_FRAC)
        return (round(x.lat0 * 60.0 / snap), round(x.lon0 * 60.0 / snap),
                range_bucket(x.range_nm))

    def is_settled(self, x):
        if not self._path or x.range_nm > self._MAX_RANGE:
            return True
        key = self._key(x)
        with self._lock:
            snap = self._snap
        return snap is not None and snap[0] == key

    def _snapshot(self, x, max_range):
        if not self._path or x.range_nm > max_range:
            return None
        key = self._key(x)
        with self._lock:
            snap = self._snap
            if snap is not None and snap[0] == key:
                return snap[1]
            if getattr(x, "defer_render", False):
                return snap[1] if snap else None
            # Don't refresh an in-flight job for the same window: the
            # tuple carries the raw pose, so a same-key repost makes
            # the worker's latest-wins check discard the finished
            # snapshot every time the aircraft is moving (#89).
            if self._job is None or self._job[0] != key:
                self._job = (key, x.lat0, x.lon0, x.range_nm)
                perf = getattr(self._owner, "perf", None)
                if perf is not None:
                    perf.layer(self.id).jobs_requested += 1
            if self._worker is None:
                self._worker = threading.Thread(
                    target=self._worker_loop,
                    name="map-" + self.id, daemon=True)
                self._worker.start()
        return snap[1] if snap else None

    def _painted_rows(self, x):
        """FP10 hit-test: the rows the last ``paint()`` drew from, under
        the same range gate -- never a new query."""
        if not self._path or x.range_nm > self._MAX_RANGE:
            return []
        with self._lock:
            snap = self._snap
        return snap[1] if snap else []

    def _columns(self, rows, *cols):
        """Float arrays of the given row columns, built once per snapshot
        (the rows list is replaced, never mutated, on publish)."""
        cached = getattr(self, "_cols", None)
        if cached is None or cached[0] is not rows:
            arrs = tuple(np.array([r[c] for r in rows], dtype=float)
                         for c in cols)
            cached = self._cols = (rows, arrs)
        return cached[1]

    def _worker_loop(self):
        last = None
        con = None
        while True:
            with self._lock:
                job = self._job
            if job is None or job == last:
                time.sleep(0.05)
                continue
            con = self._process_job(job, con)
            last = job
            try:
                self._owner.update()
            except RuntimeError:
                return

    def _process_job(self, job, con):
        """MP6 instrumentation around the same latest-wins collect/publish
        the other layers use (AER-588): a finished collect is always
        published, even if a newer job replaced ``_job`` while it ran --
        see terrain.py's ``_process_job`` for the rationale. That race is
        still counted as ``jobs_superseded`` (published, but already
        stale by the time it landed). Returns the sqlite connection so
        the loop can keep reusing it."""
        perf = getattr(self._owner, "perf", None)
        ls = perf.layer(self.id) if perf is not None else None
        if ls is not None:
            ls.jobs_started += 1
        t0 = time.perf_counter()
        try:
            if con is None:
                con = sqlite3.connect(self._path)
            rows = self._query(con, *job[1:])
            ms = (time.perf_counter() - t0) * 1000.0
            with self._lock:
                superseded = self._job != job
                self._snap = (job[0], rows)
            if ls is not None:
                ls.record_render_ms(ms)
                ls.jobs_published += 1
                if superseded:
                    ls.jobs_superseded += 1
        except Exception:
            import logging
            logging.getLogger(__name__).exception(
                "map %s collect failed", self.id)
            with self._lock:
                if self._job == job:
                    self._job = None   # let the next paint re-request
        return con

    @staticmethod
    def _bbox(lat0, lon0, range_nm):
        d = range_nm * 2.2 / 60.0
        dl = d / max(0.2, math.cos(math.radians(lat0)))
        return lat0 - d, lat0 + d, lon0 - dl, lon0 + dl


@register_layer
class NavaidsLayer(_DbLayer):
    id = "navaids"
    label = "Navaids"
    z = 40
    default_on = True
    _MAX_RANGE = 160.0

    def _query(self, con, lat0, lon0, range_nm):
        a, b, c, d = self._bbox(lat0, lon0, range_nm)
        return con.execute(
            "SELECT id, type, freq, lat, lon FROM navaids "
            "WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?",
            (a, b, c, d)).fetchall()

    def hit(self, x, px, py, tol_px):
        out = []
        for nid, ntype, freq, lat, lon in self._painted_rows(x):
            d = hit_distance(x, lat, lon, px, py, tol_px)
            if d is not None and nid:
                # Same type rule as flightplan.waypoints.WaypointIndex.
                wtype = "ndb" if "NDB" in (ntype or "").upper() else "vor"
                out.append((d, Waypoint(id=nid, type=wtype, lat=lat, lon=lon,
                                        freq=freq or None)))
        return out

    def paint(self, p, x):
        rows = self._snapshot(x, self._MAX_RANGE)
        if not rows:
            return
        r = max(5.0, min(12.0, x.w * 0.014))
        f = QFont(x.font_family)
        f.setPixelSize(max(8, int(x.w * 0.022)))
        p.setFont(f)
        show_freq = x.range_nm <= 40
        blue = qcolor(getattr(x, "palette", STANDARD_PALETTE)["navaid"])
        for nid, ntype, freq, lat, lon in rows:
            c = x.to_screen(lat, lon)
            if not (-r < c.x() < x.w + r and -r < c.y() < x.h + r):
                continue
            pen = QPen(blue)
            pen.setWidthF(max(1.2, r * 0.18))
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            t = (ntype or "").upper()
            if "NDB" in t:
                p.setPen(QPen(blue, 1))
                for ring, npts in ((r * 0.55, 8), (r, 12)):
                    for i in range(npts):
                        ang = 2 * math.pi * i / npts
                        p.drawEllipse(
                            QPointF(c.x() + ring * math.cos(ang),
                                    c.y() + ring * math.sin(ang)),
                            r * 0.07, r * 0.07)
                p.setBrush(QBrush(blue))
                p.drawEllipse(c, r * 0.14, r * 0.14)
            else:
                # VOR family: hexagon + centre dot.
                hexa = QPolygonF([
                    QPointF(c.x() + r * math.cos(math.radians(a2)),
                            c.y() + r * math.sin(math.radians(a2)))
                    for a2 in range(0, 360, 60)])
                p.drawPolygon(hexa)
                p.setBrush(QBrush(blue))
                p.drawEllipse(c, r * 0.14, r * 0.14)
            label = nid + ((" " + freq) if (show_freq and freq) else "")
            p.setPen(QPen(QColor(220, 230, 255)))
            p.drawText(QRectF(c.x() - 70, c.y() + r + 1, 140,
                              f.pixelSize() + 4),
                       Qt.AlignmentFlag.AlignHCenter, label)
            mark_drawn(x, nid, c, c.y() + r + 1 + f.pixelSize() + 4, True)


@register_layer
class FixesLayer(_DbLayer):
    id = "fixes"
    label = "Waypoints"
    z = 38
    default_on = False
    _MAX_RANGE = 20.0           # range-gated: fixes are dense

    def _query(self, con, lat0, lon0, range_nm):
        a, b, c, d = self._bbox(lat0, lon0, range_nm)
        return con.execute(
            "SELECT id, lat, lon FROM fixes "
            "WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ? "
            "LIMIT 400", (a, b, c, d)).fetchall()

    def hit(self, x, px, py, tol_px):
        out = []
        for fid, lat, lon in self._painted_rows(x):
            d = hit_distance(x, lat, lon, px, py, tol_px)
            if d is not None and fid:
                out.append((d, Waypoint(id=fid, type="fix", lat=lat, lon=lon)))
        return out

    def paint(self, p, x):
        rows = self._snapshot(x, self._MAX_RANGE)
        if not rows:
            return
        s = max(3.0, x.w * 0.008)
        f = QFont(x.font_family)
        f.setPixelSize(max(7, int(x.w * 0.018)))
        p.setFont(f)
        p.setBrush(Qt.BrushStyle.NoBrush)
        pal = getattr(x, "palette", STANDARD_PALETTE)
        fix_pen = QPen(qcolor(pal["fix"]), pal["fix_width"])
        lat, lon = self._columns(rows, 1, 2)
        sx, sy = x.to_screen_xy(lat, lon)
        on = np.flatnonzero((sx > 0) & (sx < x.w) & (sy > 0) & (sy < x.h))
        for i, cx, cy in zip(on.tolist(), sx[on].tolist(), sy[on].tolist()):
            fid = rows[i][0]
            c = QPointF(cx, cy)
            p.setPen(fix_pen)
            p.drawPolygon(QPolygonF([
                QPointF(c.x(), c.y() - s),
                QPointF(c.x() + s * 0.87, c.y() + s * 0.5),
                QPointF(c.x() - s * 0.87, c.y() + s * 0.5)]))
            p.setPen(QPen(QColor(200, 210, 235, 220)))
            p.drawText(QRectF(c.x() - 50, c.y() + s + 1, 100,
                              f.pixelSize() + 4),
                       Qt.AlignmentFlag.AlignHCenter, fid)
            mark_drawn(x, fid, c, c.y() + s + 1 + f.pixelSize() + 4, True)


@register_layer
class AirwaysLayer(_DbLayer):
    id = "airways"
    label = "Airways"
    z = 25
    default_on = False
    _MAX_RANGE = 160.0

    def _query(self, con, lat0, lon0, range_nm):
        a, b, c, d = self._bbox(lat0, lon0, range_nm)
        return con.execute(
            "SELECT awy_id, lat1, lon1, lat2, lon2 FROM awy_segments "
            "WHERE (lat1 BETWEEN ? AND ? AND lon1 BETWEEN ? AND ?) "
            "   OR (lat2 BETWEEN ? AND ? AND lon2 BETWEEN ? AND ?)",
            (a, b, c, d, a, b, c, d)).fetchall()

    def paint(self, p, x):
        rows = self._snapshot(x, self._MAX_RANGE)
        if not rows:
            return
        pen = QPen(qcolor(getattr(x, "palette", STANDARD_PALETTE)["airway"]))
        pen.setWidthF(max(1.0, x.w * 0.003))
        f = QFont(x.font_family)
        f.setPixelSize(max(7, int(x.w * 0.018)))
        p.setFont(f)
        la1, lo1, la2, lo2 = self._columns(rows, 1, 2, 3, 4)
        x1, y1 = x.to_screen_xy(la1, lo1)
        x2, y2 = x.to_screen_xy(la2, lo2)
        # A segment with both ends past the same edge, by more than the
        # pen reaches, draws nothing; neither does its label, whose
        # midpoint is past that edge too. The rest draw in row order, as
        # before, so a later line still crosses an earlier label.
        m = pen.widthF() + 2.0
        off = (((x1 < -m) & (x2 < -m)) | ((x1 > x.w + m) & (x2 > x.w + m))
               | ((y1 < -m) & (y2 < -m)) | ((y1 > x.h + m) & (y2 > x.h + m)))
        first = self._first_rows(rows) if x.range_nm <= 80 else ()
        p.setPen(pen)
        for i in np.flatnonzero(~off).tolist():
            a, b, c, d = x1[i], y1[i], x2[i], y2[i]
            p.drawLine(QLineF(a, b, c, d))
            if i in first:
                mx, my = (a + c) / 2, (b + d) / 2
                if 0 < mx < x.w and 0 < my < x.h:
                    p.setPen(QPen(QColor(150, 180, 240)))
                    p.drawText(QRectF(mx - 30, my - f.pixelSize() - 2,
                                      60, f.pixelSize() + 4),
                               Qt.AlignmentFlag.AlignHCenter, rows[i][0])
                    p.setPen(pen)

    def _first_rows(self, rows):
        """Indices of each airway's first row: the segment its label goes
        on, whether or not that segment is on screen."""
        cached = getattr(self, "_first", None)
        if cached is None or cached[0] is not rows:
            seen = {}
            for i, r in enumerate(rows):
                seen.setdefault(r[0], i)
            cached = self._first = (rows, frozenset(seen.values()))
        return cached[1]
