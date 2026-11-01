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
#  MP11 (pyEfis #204): the worker itself does no per-vertex or per-line
#  Python work either. Each pen tier is one bulk query (concatenated
#  vertices + END offsets), one vectorised projection + bbox reject +
#  pixel-grid decimation, and a few strokePaths of QPainterPaths built
#  from numpy through Qt's QDataStream wire format -- the per-line loop it
#  replaces built ~33k HighwayLine objects and QPolygonFs at 80 NM and
#  held the GIL for seconds.
#
#  LOD (docs/map_layers_roadmap.md section 1): the class set drawn scales
#  with range -- interstates alone when zoomed out, arterials added as you
#  zoom in. The class filter is pushed into the DB query so the worker only
#  fetches what it will draw. The rivers layer (#92) shares this machinery
#  and the highways sqlite schema -- it is just a subclass with its own
#  class bands + colour (map/layers/rivers.py).

import math
import threading
import time

import numpy as np
from PyQt6.QtCore import QByteArray, QDataStream
from PyQt6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen

from pyefis.instruments.ai.camera import M_PER_DEG_LAT
from pyefis.instruments.map.layers import (MapLayer, RenderHistory,
                                           paint_window_images, palette,
                                           range_bucket, register_layer)

#: per-window vertex budget (worker-side; metro windows are dense)
_MAX_VERTICES = 150000
#: polylines per stroked QPainterPath. Qt's stroke cost grows faster than
#: the path: at 80 NM (18k motorway polylines) one path stroked in 1.19 s,
#: chunks of 64 in 0.08 s, chunks of 16 in 0.07 s (sandbox, AER-4458).
_LINES_PER_PATH = 64


#: QPainterPath element type codes (QPainterPath::ElementType)
_MOVE_TO = 0
_LINE_TO = 1
#: one serialized QPainterPath element: int32 type, double x, double y,
#: big-endian (QDataStream's default byte order)
_PATH_ELEMENT = np.dtype([("t", ">i4"), ("x", ">f8"), ("y", ">f8")])


def decimate_polylines(xs, ys, ends, n):
    """Cull and decimate concatenated polylines in image-pixel space.

    *xs*/*ys* are projected image-pixel float coordinates of every
    polyline concatenated; *ends* are cumulative END offsets (one per
    polyline). Returns ``(xs, ys, starts)`` for what should be drawn,
    with *starts* a bool mask marking each surviving polyline's first
    vertex.

    Same rules as the per-line loop this replaces, vectorised:

    - polylines of fewer than 2 vertices draw nothing and are dropped;
    - a polyline whose bbox lies wholly outside ``[0, n]`` on either
      axis is dropped (the old ``xs.max() < 0 or xs.min() > n`` test);
    - MP4's pixel-grid decimation (terrain ``_decimate_to_pixel_grid``):
      a run of consecutive vertices rounding to the same pixel collapses
      to its first member. A polyline's first and last vertex always
      survive, so a line never shortens and every survivor keeps >= 2
      vertices; kept vertices keep their exact float position.
    """
    ends = np.asarray(ends, dtype=np.int64)
    m = int(ends[-1]) if ends.size else 0
    empty = (xs[:0], ys[:0], np.zeros(0, dtype=bool))
    if m == 0:
        return empty
    xs = xs[:m]
    ys = ys[:m]
    starts_ix = np.concatenate(([0], ends[:-1]))
    lens = ends - starts_ix
    line_ok = lens >= 2
    if not line_ok.any():
        return empty
    # bbox reject; reduceat needs non-empty segments, so only reduce
    # over the lines with vertices (the rest are already not ok)
    nz = lens > 0
    seg = starts_ix[nz]
    vis = np.zeros(lens.shape[0], dtype=bool)
    vis[nz] = ~((np.maximum.reduceat(xs, seg) < 0)
                | (np.minimum.reduceat(xs, seg) > n)
                | (np.maximum.reduceat(ys, seg) < 0)
                | (np.minimum.reduceat(ys, seg) > n))
    line_ok &= vis
    line_id = np.repeat(np.arange(lens.shape[0]), lens)
    keep = line_ok[line_id]

    is_start = np.zeros(m, dtype=bool)
    is_start[starts_ix[nz]] = True
    is_end = np.zeros(m, dtype=bool)
    is_end[ends[nz] - 1] = True
    px = np.round(xs).astype(np.int64)
    py = np.round(ys).astype(np.int64)
    changed = np.ones(m, dtype=bool)
    changed[1:] = (px[1:] != px[:-1]) | (py[1:] != py[:-1])
    keep &= changed | is_start | is_end
    return xs[keep], ys[keep], is_start[keep]


def polyline_paths(xs, ys, starts, per_path=_LINES_PER_PATH):
    """QPainterPaths holding the polylines as subpaths (MoveTo at each
    ``starts`` vertex, LineTo otherwise), *per_path* polylines to a path,
    each built from the arrays in a single QDataStream read: no QPointF
    per vertex and no Python call per polyline."""
    first = np.flatnonzero(starts)
    cuts = list(first[per_path::per_path]) + [xs.shape[0]]
    paths = []
    a = 0
    for b in cuts:
        if b > a:
            paths.append(_path_from_arrays(xs[a:b], ys[a:b], starts[a:b]))
        a = b
    return paths


def _path_from_arrays(xs, ys, starts):
    count = xs.shape[0]
    rec = np.empty(count, dtype=_PATH_ELEMENT)
    rec["t"] = np.where(starts, _MOVE_TO, _LINE_TO)
    rec["x"] = xs
    rec["y"] = ys
    last_move = int(np.flatnonzero(starts)[-1])
    # element count, elements, cStart (last subpath start), fill rule
    buf = QByteArray(np.array([count], ">i4").tobytes() + rec.tobytes()
                     + np.array([last_move, 0], ">i4").tobytes())
    path = QPainterPath()
    stream = QDataStream(buf)       # reads buf: keep it referenced
    stream >> path
    if stream.status() != QDataStream.Status.Ok \
            or path.elementCount() != count:
        raise ValueError("polyline path decode failed (%s, %d of %d)"
                         % (stream.status(), path.elementCount(), count))
    return path


def _with_links(bases):
    """Expand base road classes to include their ``_link`` ramps."""
    out = []
    for c in bases:
        out.append(c)
        out.append(c + "_link")
    return tuple(out)


@register_layer
class RoadsLayer(MapLayer):
    id = "roads"
    label = "Roads"
    z = 10
    default_on = True

    # --- config option names (subclasses point these elsewhere) ----------
    _DB_OPTION = "highway_db_path"
    _COLOR_OPTION = "road_color"
    _DEFAULT_COLOR = "#c0c0c0"
    #: palette key for this layer's default colour under a ``map_style``
    _PALETTE_DEFAULT_KEY = "road_default"

    # LOD bands: (max range NM, base classes drawn at/below it). Cumulative
    # and coarsest-last; above the last band the layer is hidden. Each base
    # class also matches its _link ramp. Keep in sync with
    # tools/build_highway_db.py PRESETS["roads"].
    _BAND_BASE = (
        (5.0, ("motorway", "trunk", "primary", "secondary")),
        (20.0, ("motorway", "trunk", "primary")),
        (40.0, ("motorway", "trunk")),
        (80.0, ("motorway",)),
    )
    #: base class -> pen tier (0 = boldest). Unknown classes fall to the
    #: thinnest tier.
    _TIER = {"motorway": 0, "trunk": 0, "primary": 1, "secondary": 2}
    #: tier -> (width px, alpha). Interstates boldest; arterials thin/faint.
    _TIER_PEN = {0: (1.8, 255), 1: (1.3, 220), 2: (1.0, 170)}
    #: roads carry _link ramps; waterway subclasses (rivers) do not.
    _EXPAND_LINKS = True

    #: metres of travel before the window re-anchors (hysteresis)
    _SNAP_FRAC = 0.15

    def __init__(self):
        super(RoadsLayer, self).__init__()
        self._db = None
        self._color = self._DEFAULT_COLOR
        self._img = None            # (QImage, key, meta)
        self._history = RenderHistory()   # MP13: recent images, pinch-out
        self._job = None
        self._worker = None
        self._lock = threading.Lock()

    def configure(self, owner):
        self._owner = owner
        self._color = str(getattr(owner, self._COLOR_OPTION, "")
                          or self._DEFAULT_COLOR)
        # A map_style swaps the DEFAULT colour only; a colour the screen
        # set explicitly still wins (G12: nav_only dims roads that would
        # otherwise be the brightest lines on a black background).
        if self._color.strip().lower() == self._DEFAULT_COLOR:
            self._color = palette(owner)[self._PALETTE_DEFAULT_KEY]
        path = str(getattr(owner, self._DB_OPTION, "") or "")
        if path:
            try:
                from pyefis.instruments.ai.highway_db import HighwayDB
                self._db = HighwayDB(path)   # own connection, not the SVS's
            except Exception:
                import logging
                logging.getLogger(__name__).exception(
                    "map %s db unavailable", self.id)

    # --- LOD ---------------------------------------------------------------
    def _classes_for_range(self, range_nm):
        """fclass set to draw at ``range_nm`` (with _link ramps), or None
        when the layer is hidden (zoomed out past the coarsest band)."""
        for max_r, bases in self._BAND_BASE:
            if range_nm <= max_r:
                return _with_links(bases) if self._EXPAND_LINKS else tuple(bases)
        return None

    def _tier_for(self, fclass):
        base = (fclass or "")
        if base.endswith("_link"):
            base = base[:-5]
        return self._TIER.get(base, 2)

    # --- window key: snapped centre + range bucket (terrain pattern) -----
    def _key(self, x):
        span_m = x.range_nm * 1852.0 * 2.0
        snap = span_m * self._SNAP_FRAC
        return (round(x.lat0 * M_PER_DEG_LAT / snap),
                round(x.lon0 * M_PER_DEG_LAT / snap),
                range_bucket(x.range_nm), round(x.w), round(x.h))

    def is_settled(self, x):
        if self._db is None or not self._db.ready \
                or self._classes_for_range(x.range_nm) is None:
            return True
        key = self._key(x)
        with self._lock:
            img = self._img
        return img is not None and img[1] == key

    def paint(self, p, x):
        if self._db is None or not self._db.ready \
                or self._classes_for_range(x.range_nm) is None:
            return
        key = self._key(x)
        with self._lock:
            img = self._img
            have = img is not None and img[1] == key
        if not have and not getattr(x, "defer_render", False):
            self._request(key, x)
        paint_window_images(p, x, img, self._history, key, smooth=True)

    # --- async build ------------------------------------------------------
    def _request(self, key, x):
        job = (key, x.lat0, x.lon0, x.range_nm, x.w, x.h, x.cy)
        with self._lock:
            # same-key reposts must not refresh the in-flight job (#89)
            if self._job is not None and self._job[0] == key:
                return
            self._job = job
            perf = getattr(self._owner, "perf", None)
            if perf is not None:
                perf.layer(self.id).jobs_requested += 1
            if self._worker is None:
                self._worker = threading.Thread(
                    target=self._worker_loop, name="map-" + self.id,
                    daemon=True)
                self._worker.start()

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
                return                        # widget destroyed

    def _process_job(self, job):
        """MP6 instrumentation around the newest-wins render/publish the
        terrain layer uses (AER-588): a finished render is always
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
            img, meta = self._render(job)
            ms = (time.perf_counter() - t0) * 1000.0
            with self._lock:
                superseded = self._job != job
                self._img = (img, job[0], meta)
            self._history.add(self._img)
            if ls is not None:
                ls.record_render_ms(ms)
                ls.jobs_published += 1
                if superseded:
                    ls.jobs_superseded += 1
        except Exception:
            import logging
            logging.getLogger(__name__).exception(
                "map %s render failed", self.id)
            with self._lock:
                if self._job == job:
                    self._job = None   # let the next paint re-request

    def _pens(self):
        """Build one QPen per tier from the layer colour (cached per render)."""
        pens = {}
        for tier, (width, alpha) in self._TIER_PEN.items():
            col = QColor(self._color)
            if not col.isValid():
                col = QColor(self._DEFAULT_COLOR)
            col.setAlpha(alpha)
            pen = QPen(col)
            pen.setWidthF(width)
            pens[tier] = pen
        return pens

    def _fetch(self, lat0, lon0, query_nm, classes):
        """``(vertices, ends)`` for *classes* in range. Readers without
        the bulk query (test fakes) are concatenated from the per-line
        generator."""
        bulk = getattr(self._db, "polyline_arrays_in_range", None)
        if bulk is not None:
            return bulk(lat0, lon0, query_nm, classes=classes)
        lines = [np.asarray(line.vertices, dtype=np.float32).reshape(-1, 2)
                 for line in self._db.polylines_in_range(
                     lat0, lon0, query_nm, classes=classes)]
        if not lines:
            return (np.empty((0, 2), dtype=np.float32),
                    np.empty(0, dtype=np.int64))
        return (np.concatenate(lines),
                np.cumsum([len(a) for a in lines], dtype=np.int64))

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

        # One fetch + one stroke per pen tier, boldest tier fetched first
        # so the vertex budget sheds the faintest classes, and stroked
        # last so it sits on top.
        by_tier = {}
        for fclass in self._classes_for_range(range_nm):   # LOD filter
            by_tier.setdefault(self._tier_for(fclass), []).append(fclass)
        query_nm = half_diag_m / 1852.0
        budget = _MAX_VERTICES
        paths = []
        for tier in sorted(by_tier):
            if budget <= 0:
                break
            v, ends = self._fetch(lat0, lon0, query_nm, by_tier[tier])
            if ends.size == 0:
                continue
            # a polyline is drawn while budget remains before it
            starts = np.concatenate(([0], ends[:-1]))
            ends = ends[starts < budget]
            budget -= int(ends[-1])
            xs = (v[:, 1] - lon0) * px_per_deg_lon + half
            ys = (lat0 - v[:, 0]) * px_per_deg_lat + half
            xs, ys, first = decimate_polylines(xs, ys, ends, n)
            paths.append((tier, polyline_paths(xs, ys, first)))

        img = QImage(n, n, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(0)
        pens = self._pens()
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        try:
            for tier, tier_paths in reversed(paths):
                for path in tier_paths:
                    p.strokePath(path, pens[tier])
        finally:
            p.end()
        return img, (lat0, lon0, mpp)
