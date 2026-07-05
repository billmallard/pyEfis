#  SPDX-License-Identifier: GPL-2.0-or-later
#  Moving map roads layer -- major roads from the highways pack (the
#  same highways.sqlite the SVS reads, via HighwayDB).
#
#  Same contract as the terrain layer: a WORKER renders a NORTH-UP
#  transparent overlay image for the snapped window (oversized so
#  track-up rotation never shows edges); paint() only rotate-blits.
#  Rendering polylines per frame would cost tens of thousands of
#  Python->QPointF conversions at the frame clock rate -- the exact
#  per-vertex-Python failure mode of SVS #74 -- so all vertex work
#  happens once per window change, off the paint path.
#
#  When the rivers pack lands (#92) it shares the highways sqlite
#  schema, so a rivers layer is a config variation of this one.

import math
import threading

import numpy as np
from PyQt6.QtCore import QPointF, QRectF
from PyQt6.QtGui import QColor, QImage, QPainter, QPen, QPolygonF

from pyefis.instruments.ai.camera import M_PER_DEG_LAT
from pyefis.instruments.map.layers import MapLayer, register_layer

#: NM: layer hidden above this range
_SHOW_RANGE = 40.0
#: above this range only the arterial classes draw
_DECLUTTER_RANGE = 20.0
_MAJOR = ("motorway", "trunk", "primary")
#: per-window vertex budget (worker-side; metro windows are dense)
_MAX_VERTICES = 150000


@register_layer
class RoadsLayer(MapLayer):
    id = "roads"
    label = "Roads"
    z = 10
    default_on = True

    #: metres of travel before the window re-anchors (hysteresis)
    _SNAP_FRAC = 0.15

    def __init__(self):
        super(RoadsLayer, self).__init__()
        self._db = None
        self._color = "#c0c0c0"
        self._img = None            # (QImage, key, meta)
        self._job = None
        self._worker = None
        self._lock = threading.Lock()

    def configure(self, owner):
        self._owner = owner
        self._color = str(getattr(owner, "road_color", "") or "#c0c0c0")
        path = str(getattr(owner, "highway_db_path", "") or "")
        if path:
            try:
                from pyefis.instruments.ai.highway_db import HighwayDB
                self._db = HighwayDB(path)   # own connection, not the SVS's
            except Exception:
                import logging
                logging.getLogger(__name__).exception(
                    "map roads db unavailable")

    # --- window key: snapped centre + range bucket (terrain pattern) -----
    def _key(self, x):
        span_m = x.range_nm * 1852.0 * 2.0
        snap = span_m * self._SNAP_FRAC
        return (round(x.lat0 * M_PER_DEG_LAT / snap),
                round(x.lon0 * M_PER_DEG_LAT / snap),
                round(x.range_nm, 2), round(x.w), round(x.h))

    def paint(self, p, x):
        if self._db is None or not self._db.ready \
                or x.range_nm > _SHOW_RANGE:
            return
        key = self._key(x)
        with self._lock:
            img = self._img
            have = img is not None and img[1] == key
        if not have:
            self._request(key, x)
        if img is None:
            return
        qimg, _, (clat, clon, mpp) = img
        c = x.to_screen(clat, clon)
        p.save()
        p.translate(c)
        if x.rot:
            # north-up image onto an R(+rot) screen: painter -rot (#90)
            p.rotate(-math.degrees(x.rot))
        s = mpp * x._px_per_m
        w = qimg.width() * s
        h = qimg.height() * s
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawImage(QRectF(-w / 2.0, -h / 2.0, w, h), qimg)
        p.restore()

    # --- async build ------------------------------------------------------
    def _request(self, key, x):
        job = (key, x.lat0, x.lon0, x.range_nm, x.w, x.h, x.cy)
        with self._lock:
            # same-key reposts must not refresh the in-flight job (#89)
            if self._job is not None and self._job[0] == key:
                return
            self._job = job
            if self._worker is None:
                self._worker = threading.Thread(
                    target=self._worker_loop, name="map-roads",
                    daemon=True)
                self._worker.start()

    def _worker_loop(self):
        import time
        last = None
        while True:
            with self._lock:
                job = self._job
            if job is None or job == last:
                time.sleep(0.05)
                continue
            try:
                img, meta = self._render(job)
                with self._lock:
                    if self._job == job:      # latest wins
                        self._img = (img, job[0], meta)
            except Exception:
                import logging
                logging.getLogger(__name__).exception(
                    "map roads render failed")
                with self._lock:
                    if self._job == job:
                        self._job = None   # let the next paint re-request
            last = job
            try:
                self._owner.update()
            except RuntimeError:
                return                        # widget destroyed

    def _render(self, job):
        key, lat0, lon0, range_nm, w, h, cy = job
        # Same window geometry as the terrain layer, so the overlay
        # registers exactly with the relief underneath.
        px_per_m = max(1.0, cy) / max(1.0, range_nm * 1852.0)
        half_diag_m = 0.5 * math.hypot(w, h) / px_per_m * 1.25
        n = int(min(1024, max(64, 2 * half_diag_m * px_per_m)))
        mpp = 2 * half_diag_m / n
        lat_cos = math.cos(math.radians(lat0))
        half = (n - 1) / 2.0
        px_per_deg_lat = M_PER_DEG_LAT / mpp
        px_per_deg_lon = M_PER_DEG_LAT * lat_cos / mpp

        img = QImage(n, n, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(0)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        col = QColor(self._color)
        if not col.isValid():
            col = QColor("#c0c0c0")
        major_pen = QPen(col)
        major_pen.setWidthF(1.6)
        minor = QColor(col)
        minor.setAlpha(170)
        minor_pen = QPen(minor)
        minor_pen.setWidthF(1.0)

        arterial_only = range_nm > _DECLUTTER_RANGE
        query_nm = half_diag_m / 1852.0
        budget = _MAX_VERTICES
        try:
            for line in self._db.polylines_in_range(lat0, lon0, query_nm):
                fc = (line.fclass or "")
                is_major = fc.startswith(_MAJOR)
                if arterial_only and not is_major:
                    continue
                v = line.vertices
                if budget <= 0:
                    break
                budget -= len(v)
                xs = (v[:, 1] - lon0) * px_per_deg_lon + half
                ys = (lat0 - v[:, 0]) * px_per_deg_lat + half
                # off-window polylines: bbox reject before QPointF cost
                if (xs.max() < 0 or xs.min() > n
                        or ys.max() < 0 or ys.min() > n):
                    continue
                p.setPen(major_pen if is_major else minor_pen)
                p.drawPolyline(QPolygonF(
                    [QPointF(float(a), float(b))
                     for a, b in zip(xs, ys)]))
        finally:
            p.end()
        return img, (lat0, lon0, mpp)
