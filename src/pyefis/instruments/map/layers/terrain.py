#  SPDX-License-Identifier: GPL-2.0-or-later
#  Moving map terrain layer (spec 5.1, Phase B).
#
#  Renders a NORTH-UP window image covering the view (oversized by
#  sqrt(2) so track-up rotation never shows edges) from the same
#  GLO-30/SRTM tiles the SVS uses, via TileCache and the Track-1c mip
#  pyramid. Hypsometric palette + NW-light hillshade, all vectorised
#  numpy. The image rebuilds on a WORKER thread (latest wins) whenever
#  the snapped window key changes; paint() only blits with the
#  painter's rotation. TODO(Phase E): ride the SVS shared collect slot
#  when map + SVS run on one screen.

import math
import threading
import time

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (QBrush, QColor, QImage, QPainter, QPainterPath,
                         QPolygonF)

from pyefis.instruments.ai.camera import M_PER_DEG_LAT
from pyefis.instruments.map import raster
from pyefis.instruments.map.layers import MapLayer, range_bucket, register_layer

# Hypsometric stops: (elevation ft, r, g, b) -- sectional-inspired.
_STOPS = [
    (-1000, 60, 110, 160),      # water sentinel band
    (0,     92, 130,  82),
    (1000, 110, 145,  88),
    (2000, 150, 160,  95),
    (4000, 185, 160, 100),
    (7000, 170, 130,  90),
    (10000, 160, 120, 105),
    (14000, 235, 235, 235),
]


_STOP_E = np.array([s[0] for s in _STOPS], np.float64)
_STOP_R = np.array([s[1] for s in _STOPS], np.float64)
_STOP_G = np.array([s[2] for s in _STOPS], np.float64)
_STOP_B = np.array([s[3] for s in _STOPS], np.float64)


def _decimate_to_pixel_grid(xs, ys, ring_ends):
    """MP4 (brief section 4): drop water-ring vertices that round to the
    same image pixel as the previously KEPT vertex, per ring; drop a
    ring outright if fewer than 3 vertices survive. *xs*/*ys* are the
    already-projected image-pixel float coordinates for one polygon's
    concatenated rings; *ring_ends* are cumulative END offsets (the
    WaterPolygon.rings convention -- a single-ring polygon passes
    ``[len(xs)]``).

    Fully vectorised, no per-vertex or per-ring Python loop: a run of
    consecutive vertices sharing a rounded pixel collapses to its first
    member (equivalent to comparing against the previous KEPT vertex,
    since every vertex in the run shares the same rounded value as the
    run's first/kept member); ring starts are forced to survive so
    decimation never bridges across a ring boundary; ring membership
    for the "keep >= 3" rule comes from `searchsorted` against
    *ring_ends* rather than a Python loop over rings -- the Florida
    Keys #44 cell carries 3,322 island rings in one row."""
    n = xs.shape[0]
    ring_ends = np.asarray(ring_ends, dtype=np.int64)
    if n == 0 or ring_ends.size == 0:
        return (xs[:0], ys[:0], ring_ends[:0])
    ring_starts = np.concatenate(([0], ring_ends[:-1]))

    px = np.round(xs).astype(np.int64)
    py = np.round(ys).astype(np.int64)

    is_ring_start = np.zeros(n, dtype=bool)
    is_ring_start[ring_starts] = True

    changed = np.ones(n, dtype=bool)
    changed[1:] = (px[1:] != px[:-1]) | (py[1:] != py[:-1])
    keep = changed | is_ring_start

    idx = np.arange(n)
    ring_id = np.searchsorted(ring_ends, idx, side="right")

    counts = np.bincount(ring_id[keep], minlength=ring_ends.size)
    good_ring = counts >= 3
    keep &= good_ring[ring_id]

    new_ring_ends = np.cumsum(counts[good_ring])
    return xs[keep], ys[keep], new_ring_ends


def _palette(elev_ft):
    """Vectorised hypsometric colour lookup (elev in FEET).

    Piecewise-linear over _STOPS via np.interp -- one C pass per
    channel (np.interp clamps to the end stops, matching the old
    per-segment masking). #89: the masked-segment version was ~24% of
    the terrain worker's GIL time."""
    e = elev_ft.ravel()
    shape = elev_ft.shape
    r = np.interp(e, _STOP_E, _STOP_R).astype(np.float32).reshape(shape)
    g = np.interp(e, _STOP_E, _STOP_G).astype(np.float32).reshape(shape)
    b = np.interp(e, _STOP_E, _STOP_B).astype(np.float32).reshape(shape)
    return r, g, b


@register_layer
class TerrainLayer(MapLayer):
    id = "terrain"
    label = "Terrain"
    z = 0
    default_on = True

    #: metres of travel before the window re-anchors (hysteresis)
    _SNAP_FRAC = 0.15
    #: rendered image pixels per screen pixel (1 = exact; <1 = softer/faster)
    _RES = 1.0
    #: at/below this NOMINAL (pilot-facing, widget.range_nm) range the full
    #: water overlay draws (ocean coastline + all lakes). Above it, the ocean
    #: is dropped (terrain void-water still shows oceans) and only large
    #: inland lakes -- Great Lakes scale -- draw, for orientation.
    #:
    #: Compared against the NOMINAL range on purpose (AER-1149) -- the query
    #: window the water overlay actually reads is the rotated viewport's
    #: half-diagonal, oversized 1.25x, which runs 1.47x-2.43x nominal
    #: depending on widget aspect. A window-range comparison made the full/
    #: wide split a function of screen geometry: the same 160 NM ladder top
    #: stayed full-detail on a portrait widget and silently dropped the
    #: coastline on a landscape one. The nominal range is a fixed property
    #: of what the pilot chose; every shipped screen now means the same
    #: thing at the same range_nm.
    #:
    #: 160 NM is the range ladder's own shipped/default maximum
    #: (MovingMap.range_ladder, _range_bounds clamps range_nm to it) --
    #: measured against the published water-na (2026q2r6) pack at every
    #: shipped widget aspect, full overlay at 160 NM nominal costs at most
    #: 120,576 vertices (Raleigh, 800x480), a 20% margin under the 150k
    #: budget. The same scene climbs past budget (~150,600) once nominal
    #: range reaches ~179 NM on that aspect, and an uncapped nominal range
    #: still reproduces the original blow-up this constant exists to avoid
    #: (12.1M vertices decoded, 15 s query, at 450 NM). So the ocean-drop
    #: still earns its keep above the ladder -- it just has to fire on the
    #: ladder's own units, not a geometry-inflated proxy for them. Held at
    #: the ladder's actual maximum, with no headroom borrowed from the
    #: untested margin above it: a future ladder stop past 160 NM falls
    #: through to wide mode by design until it is measured too.
    _WATER_FULL_MAX_NM = 160.0
    #: above _WATER_FULL_MAX_NM the lake size floor scales with the QUERY
    #: window range (bbox diagonal deg = window_range_nm * this, clamped to
    #: _WATER_WIDE_DIAG_MAX) so the drawn-poly count stays bounded (~dozens)
    #: as you zoom out -- only progressively larger bodies survive, and the
    #: Great Lakes (6-8 deg) always do. This DB tags everything kind='water'
    #: with no elev, so SIZE is the only discriminator
    #: (map_wide_range_perf_plan.md). Unlike the full/wide gate above, this
    #: shaping is legitimately about the rendered image's footprint, not the
    #: pilot's selection, so it stays keyed on the window range.
    _WATER_WIDE_DIAG_PER_NM = 0.001
    _WATER_WIDE_DIAG_MAX = 3.0

    def __init__(self):
        super(TerrainLayer, self).__init__()
        self._cache = None          # TileCache
        self._mode = "relief"
        self._img = None            # (QImage, key)
        self._job = None            # latest requested key
        self._worker = None
        self._lock = threading.Lock()
        self._alt_ft = 0.0
        self._water = None          # WaterDB (set in configure)

    def configure(self, owner):
        tile_path = str(getattr(owner, "tile_path", "") or "")
        self._mode = str(getattr(owner, "terrain_mode", "relief"))
        if tile_path:
            from pathlib import Path
            from pyefis.instruments.ai.svs import TileCache
            self._cache = TileCache(Path(tile_path))
        # Water pack (#91): lakes + crisp coastline rasterized into the
        # window image on the worker thread. Own WaterDB instance (own
        # sqlite connection) -- never shared with the SVS's.
        self._water = None
        water_path = str(getattr(owner, "water_db_path", "") or "")
        if water_path:
            try:
                from pyefis.instruments.ai.water_db import WaterDB
                cap = int(getattr(owner, "water_max_vertices", 512)
                          or 512)
                self._water = WaterDB(water_path, max_vertices=cap)
            except Exception:
                import logging
                logging.getLogger(__name__).exception(
                    "map water db unavailable")
        self._owner = owner

    # --- window key: snapped centre + range bucket ------------------------
    def _key(self, x):
        span_m = x.range_nm * 1852.0 * 2.0
        snap = span_m * self._SNAP_FRAC
        # Ownship altitude only shapes the image in caution mode (TAWS
        # tint). Keying on it in relief mode forced a full re-render
        # every 500 ft of climb/descent for an identical image (#89).
        alt_band = (round(self._alt_ft / 500.0)
                    if self._mode == "caution" else 0)
        return (round(x.lat0 * M_PER_DEG_LAT / snap),
                round(x.lon0 * M_PER_DEG_LAT / snap),
                range_bucket(x.range_nm), round(x.w), round(x.h),
                self._mode, alt_band)

    def is_settled(self, x):
        if self._cache is None:
            return True
        key = self._key(x)
        with self._lock:
            img = self._img
        return img is not None and img[1] == key

    def paint(self, p, x):
        if self._cache is None:
            return
        self._alt_ft = float(getattr(self._owner, "_alt_ft", 0.0) or 0.0)
        key = self._key(x)
        with self._lock:
            img = self._img
            have = img is not None and img[1] == key
        if not have and not getattr(x, "defer_render", False):
            self._request(key, x)
        if img is None:
            return
        qimg, _, meta = img[0], img[1], img[2]
        # meta: (centre lat, lon, metres/px of the image)
        clat, clon, mpp = meta
        c = x.to_screen(clat, clon)
        scale = (1.0 / mpp) / x._px_per_m   # image px per screen px inverse
        p.save()
        p.translate(c)
        if x.rot:
            # to_screen applies R(+rot) to world EN vectors; carrying a
            # NORTH-UP image onto that screen therefore needs the
            # painter rotated by -rot (QPainter.rotate is clockwise,
            # y-down). +rot painted the terrain 2*track degrees off --
            # a coastline reads as mirrored on east/west tracks (#90).
            p.rotate(-math.degrees(x.rot))
        s = mpp * x._px_per_m               # screen px per image px
        w = qimg.width() * s
        h = qimg.height() * s
        p.drawImage(QRectF(-w / 2.0, -h / 2.0, w, h), qimg)
        p.restore()

    # --- async build --------------------------------------------------------
    def _request(self, key, x):
        job = (key, x.lat0, x.lon0, x.range_nm, x.w, x.h, x.cy)
        with self._lock:
            # Same window already queued/in flight: do NOT refresh the
            # job. The tuple carries the raw (unsnapped) pose, so each
            # repaint used to post a same-key-different-pose job; the
            # worker's latest-wins check then threw away every finished
            # image while the aircraft moved -- an endless render loop
            # that never updated the display (#89).
            if self._job is not None and self._job[0] == key:
                return
            self._job = job
            perf = getattr(self._owner, "perf", None)
            if perf is not None:
                perf.layer(self.id).jobs_requested += 1
            if self._worker is None:
                self._worker = threading.Thread(
                    target=self._worker_loop, name="map-terrain",
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
        """Render *job* and publish it unconditionally -- MP6
        instrumentation around the newest-wins publish rule (AER-588):
        paint() already blits a stale image by its own meta and
        re-requests on key mismatch, so a finished render is always
        used even if a newer job replaced ``_job`` while it ran. That
        race is still counted as ``jobs_superseded`` (published, but
        already stale by the time it landed)."""
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
            if ls is not None:
                ls.record_render_ms(ms)
                ls.jobs_published += 1
                if superseded:
                    ls.jobs_superseded += 1
        except Exception:
            import logging
            logging.getLogger(__name__).exception(
                "map terrain render failed")
            with self._lock:
                if self._job == job:
                    self._job = None   # let the next paint re-request

    def _render(self, job):
        key, lat0, lon0, range_nm, w, h, cy = job
        # Cover the rotated viewport: half-diagonal in metres, oversize.
        px_per_m = max(1.0, cy) / max(1.0, range_nm * 1852.0)
        half_diag_m = 0.5 * math.hypot(w, h) / px_per_m * 1.25
        res = max(1.0, px_per_m / self._RES)   # px per metre of image
        n = int(min(1024, max(64, 2 * half_diag_m * px_per_m * self._RES)))
        mpp = 2 * half_diag_m / n              # metres per image pixel
        # Pick the mip whose pitch best matches mpp (native ~30-93 m). The
        # ceiling is the deepest pyramid level a terrain pack ships
        # (docs/terrain_mip_pyramid.md); high-range views select coarse levels.
        lat_cos = math.cos(math.radians(lat0))
        idx = np.arange(n, dtype=np.float64) - (n - 1) / 2.0
        lats = lat0 + (-idx * mpp) / M_PER_DEG_LAT      # row 0 = north
        lons = lon0 + (idx * mpp) / (M_PER_DEG_LAT * lat_cos)
        tile = self._cache.get(int(math.floor(lat0)), int(math.floor(lon0)))
        native = M_PER_DEG_LAT / ((tile.shape[0] - 1) if tile is not None
                                  else 1200)
        mip = max(0, min(6, int(round(math.log2(max(1.0, mpp / native))))))
        elev_m, water = self._sample(lats, lons, mip)
        elev_ft = elev_m * 3.28084
        r, g, b = _palette(elev_ft)
        if self._mode == "caution":
            # TAWS-style: amber within 1000 ft below ownship, red above
            # -100 ft relative. Keeps relief under the tint.
            rel = self._alt_ft - elev_ft
            amber = (rel < 1000) & (rel >= 100) & ~water
            red = (rel < 100) & ~water
            r[amber], g[amber], b[amber] = 220, 160, 40
            r[red], g[red], b[red] = 200, 50, 40
        # Hillshade: NW light, central differences on the sampled grid.
        gy, gx = np.gradient(elev_m, mpp)
        shade = 0.75 + 0.25 * np.clip(
            (-gx + gy) / np.maximum(1e-3, np.hypot(gx, gy) + 8.0) + 0.5,
            0, 1)
        r *= shade; g *= shade; b *= shade
        r[water], g[water], b[water] = 60, 110, 160
        rgbx = np.empty((n, n, 4), np.uint8)
        rgbx[..., 0] = r
        rgbx[..., 1] = g
        rgbx[..., 2] = b
        rgbx[..., 3] = 255
        have_water = self._water is not None and self._water.ready
        # MP5: numpy is the default -- the mask lands directly on rgbx
        # BEFORE the QImage exists, after the caution tint (water is
        # not a TAWS surface). `water_raster: qt` keeps the legacy
        # QPointF/QPolygonF/drawPath path for one release of A/B (brief
        # section 4 MP5 guardrail).
        raster_mode = str(getattr(self._owner, "water_raster", "numpy")
                          or "numpy")
        if have_water and raster_mode != "qt":
            self._draw_water_numpy(rgbx, lat0, lon0, mpp, n, lat_cos, range_nm)
        qimg = QImage(rgbx.data, n, n, 4 * n,
                      QImage.Format.Format_RGBX8888).copy()
        if have_water and raster_mode == "qt":
            self._draw_water_qt(qimg, lat0, lon0, mpp, n, lat_cos, range_nm)
        return qimg, (lat0, lon0, mpp)

    def _draw_water_numpy(self, rgbx, lat0, lon0, mpp, n, lat_cos,
                          nominal_range_nm):
        """MP5 (brief section 4): numpy even-odd scanline fill, replacing
        the Qt QPointF/QPolygonF/drawPath path. Every ring of every
        polygon in range is collected first; ONE raster.fill_even_odd()
        call over the whole set then handles island holes (#44) and
        disjoint/nested lakes for free via the even-odd rule -- no
        per-polygon special-casing. Mutates *rgbx* in place; the caller
        builds the QImage from it afterwards, so this never constructs a
        QPointF/QPolygonF and touches the raster only once.

        *nominal_range_nm* is the widget's own ``range_nm`` (what the pilot
        selected), NOT the query window computed below -- see
        ``_WATER_FULL_MAX_NM`` (AER-1149) for why the full/wide gate has to
        use the former."""
        half_px = (n - 1) / 2.0
        window_range_nm = (half_px * mpp) / 1852.0
        wide = nominal_range_nm > self._WATER_FULL_MAX_NM
        min_diag = (min(self._WATER_WIDE_DIAG_MAX,
                        window_range_nm * self._WATER_WIDE_DIAG_PER_NM) if wide
                    else 3.0 * mpp / M_PER_DEG_LAT)
        px_per_deg_lat = M_PER_DEG_LAT / mpp
        px_per_deg_lon = M_PER_DEG_LAT * lat_cos / mpp
        n_polys = 0
        n_polys_after = 0
        n_verts = 0
        n_verts_after = 0
        rings = []
        try:
            for poly in self._water.polygons_in_range(
                    lat0, lon0, window_range_nm, min_bbox_diag_deg=min_diag,
                    drop_ocean=wide):
                n_polys += 1
                v = np.asarray(poly.vertices, dtype=np.float64)
                n_verts += v.shape[0]
                if v.shape[0] == 0:
                    continue
                xs = (v[:, 1] - lon0) * px_per_deg_lon + half_px
                ys = (lat0 - v[:, 0]) * px_per_deg_lat + half_px
                poly_rings = getattr(poly, "rings", None)
                ring_ends = (np.asarray(poly_rings, dtype=np.int64)
                             if poly_rings
                             else np.array([v.shape[0]], dtype=np.int64))
                xs, ys, ring_ends = _decimate_to_pixel_grid(
                    xs, ys, ring_ends)
                n_verts_after += xs.shape[0]
                if xs.shape[0] == 0:
                    continue
                n_polys_after += 1
                start = 0
                for end in ring_ends.tolist():
                    if end - start >= 3:
                        rings.append(np.stack(
                            (xs[start:end], ys[start:end]), axis=1))
                    start = end
        except Exception:
            import logging
            logging.getLogger(__name__).exception(
                "map water rasterize failed")
            rings = []
        if rings:
            mask = raster.fill_even_odd(rings, n)
            rgbx[mask] = (60, 110, 160, 255)
        perf = getattr(self._owner, "perf", None)
        if perf is not None:
            perf.water.record(n_polys, n_verts, n_polys_after,
                               n_verts_after, 0)

    def _draw_water_qt(self, qimg, lat0, lon0, mpp, n, lat_cos,
                       nominal_range_nm):
        """Legacy per-vertex QPointF/QPolygonF/drawPath rasterizer, kept
        behind ``water_raster: qt`` for one release of A/B against MP5's
        numpy path (brief section 4 MP5 guardrail). Rasterize water-pack
        polygons (lakes + coastline) into the north-up window image --
        on the worker thread, so per-frame cost is zero: the paint path
        still blits one image (#91). Painted AFTER the caution tint on
        purpose: water is not a TAWS threat surface. The
        elevation-derived water (void-tile ocean) stays underneath as
        the backstop.

        *nominal_range_nm* is the widget's own ``range_nm``, not the query
        window computed below -- see ``_WATER_FULL_MAX_NM`` (AER-1149)."""
        half_px = (n - 1) / 2.0
        window_range_nm = (half_px * mpp) / 1852.0
        # Wide zoom: drop the ocean coastline (terrain void-water already shows
        # oceans) and keep only large inland lakes -- the Great Lakes etc. --
        # for orientation. The never-size-filtered coastline is what dominated
        # the worker (2.8 s @ 800 NM pre-MP4/MP5). Close in: full overlay,
        # sub-3-px pieces skipped before the BLOB decode. Gated on the
        # NOMINAL range (AER-1149) so the split doesn't move with widget
        # aspect ratio.
        wide = nominal_range_nm > self._WATER_FULL_MAX_NM
        min_diag = (min(self._WATER_WIDE_DIAG_MAX,
                        window_range_nm * self._WATER_WIDE_DIAG_PER_NM) if wide
                    else 3.0 * mpp / M_PER_DEG_LAT)
        px_per_deg_lat = M_PER_DEG_LAT / mpp
        px_per_deg_lon = M_PER_DEG_LAT * lat_cos / mpp
        p = QPainter(qimg)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(60, 110, 160)))
        # MP6 counters: polygons/vertices before vs after MP4's per-pixel
        # decimation, and the QPointF count actually constructed (0 once
        # MP5 replaces this with the numpy scanline fill) -- brief
        # section 4.
        n_polys = 0
        n_polys_after = 0
        n_verts = 0
        n_verts_after = 0
        n_qpointf = 0
        try:
            for poly in self._water.polygons_in_range(
                    lat0, lon0, window_range_nm, min_bbox_diag_deg=min_diag,
                    drop_ocean=wide):
                n_polys += 1
                # Vectorised deg->px projection (#125): vertices arrive
                # as an (n, 2) ndarray, so the per-vertex Python
                # arithmetic (the measured hot line here) collapses to
                # two array ops; only the QPointF construction remains
                # per-vertex.
                v = np.asarray(poly.vertices, dtype=np.float64)
                n_verts += v.shape[0]
                if v.shape[0] == 0:
                    continue
                xs = (v[:, 1] - lon0) * px_per_deg_lon + half_px
                ys = (lat0 - v[:, 0]) * px_per_deg_lat + half_px
                rings = getattr(poly, "rings", None)
                ring_ends = (np.asarray(rings, dtype=np.int64) if rings
                             else np.array([v.shape[0]], dtype=np.int64))
                # MP4: drop vertices that round to the same image pixel
                # as the previous kept vertex, per ring; a ring that
                # decimates below 3 vertices is dropped outright (#98,
                # brief section 4 MP4).
                xs, ys, ring_ends = _decimate_to_pixel_grid(
                    xs, ys, ring_ends)
                n_verts_after += xs.shape[0]
                if xs.shape[0] == 0:
                    continue
                n_polys_after += 1
                pts = [QPointF(x, y) for x, y in zip(xs.tolist(), ys.tolist())]
                n_qpointf += len(pts)
                if rings:
                    # Multi-ring row (outer + island holes, #44):
                    # even-odd fill leaves the hole rings — islands —
                    # unpainted. The vertices list concatenates all
                    # rings, so a plain drawPolygon would be garbage.
                    path = QPainterPath()
                    path.setFillRule(Qt.FillRule.OddEvenFill)
                    start = 0
                    for end in ring_ends.tolist():
                        ring_pts = pts[start:end]
                        if len(ring_pts) >= 3:
                            path.addPolygon(QPolygonF(ring_pts))
                            path.closeSubpath()
                        start = end
                    p.drawPath(path)
                elif len(pts) >= 3:
                    p.drawPolygon(QPolygonF(pts))
        except Exception:
            import logging
            logging.getLogger(__name__).exception(
                "map water rasterize failed")
        finally:
            p.end()
        perf = getattr(self._owner, "perf", None)
        if perf is not None:
            perf.water.record(n_polys, n_verts, n_polys_after,
                               n_verts_after, n_qpointf)

    def _sample(self, lats, lons, mip):
        """Vectorised elevation sampling straight off the TileCache.

        Unlike SVSRenderer._sample_elevations (arbitrary camera-ray
        grids), the map window is a separable north-up raster: *lats*
        varies only by row, *lons* only by column. Bilinear weights are
        therefore computed on the 1-D axes and gathered per 1-degree
        tile block by broadcasting -- no full-grid tile masks and no
        per-pixel Python. #89: the previous per-pixel unique-tile set
        comprehension was 54% of the whole process's GIL time.

        Wide-range fast path: when a coarse mosaic exists for this mip level, the
        whole window is one memmap slice + one bilinear -- no per-degree file
        opens (the measured cold-I/O bottleneck; map_wide_range_perf_plan.md)."""
        mos = (self._cache.get_mosaic(mip)
               if hasattr(self._cache, "get_mosaic") else None)
        if mos is not None:
            return self._sample_mosaic(lats, lons, mos)
        elev = np.full((lats.size, lons.size), -9999.0, dtype=np.float32)
        tl = np.floor(lats).astype(np.int32)   # per-row tile latitude
        tn = np.floor(lons).astype(np.int32)   # per-col tile longitude
        for la in np.unique(tl):
            rsel = np.nonzero(tl == la)[0]
            for lo in np.unique(tn):
                csel = np.nonzero(tn == lo)[0]
                # Track-1c pyramid when the branch has it; raw tile
                # otherwise (aliasing at far zooms until 1c merges).
                t = (self._cache.get_mip(int(la), int(lo), mip)
                     if hasattr(self._cache, "get_mip")
                     else self._cache.get(int(la), int(lo)))
                if t is None:
                    continue
                nn = t.shape[0]
                rf = np.clip((la + 1.0 - lats[rsel]) * (nn - 1), 0, nn - 2)
                cf = np.clip((lons[csel] - lo) * (nn - 1), 0, nn - 2)
                r0 = np.floor(rf).astype(np.int32)
                c0 = np.floor(cf).astype(np.int32)
                dr = (rf - r0).astype(np.float32)[:, None]
                dc = (cf - c0).astype(np.float32)[None, :]
                r0 = r0[:, None]
                c0 = c0[None, :]
                elev[np.ix_(rsel, csel)] = (
                    t[r0, c0] * (1 - dr) * (1 - dc)
                    + t[r0, c0 + 1] * (1 - dr) * dc
                    + t[r0 + 1, c0] * dr * (1 - dc)
                    + t[r0 + 1, c0 + 1] * dr * dc)
        water = (elev < -4500.0) | (elev == 0.0)
        return np.where(water, 0.0, elev), water

    def _sample_mosaic(self, lats, lons, mos):
        """One vectorised bilinear off the memory-mapped coarse mosaic -- the
        wide-range fast path. No per-tile file opens and no Python tile loop:
        the north-up window is separable, so row/col indices are computed on the
        1-D axes and a single fancy-index gather pages in just the touched span
        of the one mmap (map_wide_range_perf_plan.md)."""
        arr, meta = mos
        spd = meta["spd"]
        R = meta["rows"]
        C = meta["cols"]
        rf_raw = (meta["lat_n"] - lats) * spd
        cf_raw = (lons - meta["lon_w"]) * spd
        oob = (((rf_raw < 0) | (rf_raw > R - 1))[:, None]
               | ((cf_raw < 0) | (cf_raw > C - 1))[None, :])
        rf = np.clip(rf_raw, 0, R - 2)
        cf = np.clip(cf_raw, 0, C - 2)
        r0 = np.floor(rf).astype(np.int64)
        c0 = np.floor(cf).astype(np.int64)
        dr = (rf - r0).astype(np.float32)[:, None]
        dc = (cf - c0).astype(np.float32)[None, :]
        v00 = arr[np.ix_(r0, c0)].astype(np.float32)
        v01 = arr[np.ix_(r0, c0 + 1)].astype(np.float32)
        v10 = arr[np.ix_(r0 + 1, c0)].astype(np.float32)
        v11 = arr[np.ix_(r0 + 1, c0 + 1)].astype(np.float32)
        elev = (v00 * (1 - dr) * (1 - dc) + v01 * (1 - dr) * dc
                + v10 * dr * (1 - dc) + v11 * dr * dc)
        water = (elev < -4500.0) | (elev == 0.0) | oob
        return np.where(water, 0.0, elev), water
