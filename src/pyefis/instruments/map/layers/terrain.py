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

import numpy as np
from PyQt6.QtCore import QPointF, QRectF
from PyQt6.QtGui import QImage

from pyefis.instruments.ai.camera import M_PER_DEG_LAT
from pyefis.instruments.map.layers import MapLayer, register_layer

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

    def __init__(self):
        super(TerrainLayer, self).__init__()
        self._cache = None          # TileCache
        self._mode = "relief"
        self._img = None            # (QImage, key)
        self._job = None            # latest requested key
        self._worker = None
        self._lock = threading.Lock()
        self._alt_ft = 0.0

    def configure(self, owner):
        tile_path = str(getattr(owner, "tile_path", "") or "")
        self._mode = str(getattr(owner, "terrain_mode", "relief"))
        if tile_path:
            from pathlib import Path
            from pyefis.instruments.ai.svs import TileCache
            self._cache = TileCache(Path(tile_path))
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
                round(x.range_nm, 2), round(x.w), round(x.h),
                self._mode, alt_band)

    def paint(self, p, x):
        if self._cache is None:
            return
        self._alt_ft = float(getattr(self._owner, "_alt_ft", 0.0) or 0.0)
        key = self._key(x)
        with self._lock:
            img = self._img
            have = img is not None and img[1] == key
        if not have:
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
            p.rotate(math.degrees(x.rot))
        s = mpp * x._px_per_m               # screen px per image px
        w = qimg.width() * s
        h = qimg.height() * s
        p.drawImage(QRectF(-w / 2.0, -h / 2.0, w, h), qimg)
        p.restore()

    # --- async build --------------------------------------------------------
    def _request(self, key, x):
        job = (key, x.lat0, x.lon0, x.range_nm, x.w, x.h, x.cy)
        with self._lock:
            self._job = job
            if self._worker is None:
                self._worker = threading.Thread(
                    target=self._worker_loop, name="map-terrain",
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
                    "map terrain render failed")
            last = job
            try:
                self._owner.update()
            except RuntimeError:
                return                        # widget destroyed

    def _render(self, job):
        key, lat0, lon0, range_nm, w, h, cy = job
        # Cover the rotated viewport: half-diagonal in metres, oversize.
        px_per_m = max(1.0, cy) / max(1.0, range_nm * 1852.0)
        half_diag_m = 0.5 * math.hypot(w, h) / px_per_m * 1.25
        res = max(1.0, px_per_m / self._RES)   # px per metre of image
        n = int(min(1024, max(64, 2 * half_diag_m * px_per_m * self._RES)))
        mpp = 2 * half_diag_m / n              # metres per image pixel
        # Pick the mip whose pitch best matches mpp (native ~30-93 m).
        lat_cos = math.cos(math.radians(lat0))
        idx = np.arange(n, dtype=np.float64) - (n - 1) / 2.0
        lats = lat0 + (-idx * mpp) / M_PER_DEG_LAT      # row 0 = north
        lons = lon0 + (idx * mpp) / (M_PER_DEG_LAT * lat_cos)
        tile = self._cache.get(int(math.floor(lat0)), int(math.floor(lon0)))
        native = M_PER_DEG_LAT / ((tile.shape[0] - 1) if tile is not None
                                  else 1200)
        mip = max(0, min(4, int(round(math.log2(max(1.0, mpp / native))))))
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
        qimg = QImage(rgbx.data, n, n, 4 * n,
                      QImage.Format.Format_RGBX8888).copy()
        return qimg, (lat0, lon0, mpp)

    def _sample(self, lats, lons, mip):
        """Vectorised elevation sampling straight off the TileCache.

        Unlike SVSRenderer._sample_elevations (arbitrary camera-ray
        grids), the map window is a separable north-up raster: *lats*
        varies only by row, *lons* only by column. Bilinear weights are
        therefore computed on the 1-D axes and gathered per 1-degree
        tile block by broadcasting -- no full-grid tile masks and no
        per-pixel Python. #89: the previous per-pixel unique-tile set
        comprehension was 54% of the whole process's GIL time."""
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
