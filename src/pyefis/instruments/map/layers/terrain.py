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


def _palette(elev_ft):
    """Vectorised hypsometric colour lookup (elev in FEET)."""
    r = np.empty(elev_ft.shape, np.float32)
    g = np.empty_like(r)
    b = np.empty_like(r)
    e = np.clip(elev_ft, _STOPS[0][0], _STOPS[-1][0])
    for (e0, r0, g0, b0), (e1, r1, g1, b1) in zip(_STOPS, _STOPS[1:]):
        m = (e >= e0) & (e <= e1)
        t = np.where(m, (e - e0) / max(1.0, (e1 - e0)), 0)
        for chan, c0, c1 in ((r, r0, r1), (g, g0, g1), (b, b0, b1)):
            chan[m] = (c0 + (c1 - c0) * t)[m]
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
        return (round(x.lat0 * M_PER_DEG_LAT / snap),
                round(x.lon0 * M_PER_DEG_LAT / snap),
                round(x.range_nm, 2), round(x.w), round(x.h),
                self._mode, round(self._alt_ft / 500.0))

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
        lon_g, lat_g = np.meshgrid(lons, lats)
        # Reuse the SVS sampling machinery (mip pyramid included).
        from pyefis.instruments.ai.svs import SVSRenderer  # noqa: F401
        elev_m, water = self._sample(lat_g, lon_g, mip)
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
        rgb = np.dstack([r, g, b]).astype(np.uint8)
        rgbx = np.ascontiguousarray(
            np.dstack([rgb, np.full(elev_m.shape, 255, np.uint8)]))
        qimg = QImage(rgbx.data, n, n, 4 * n,
                      QImage.Format.Format_RGBX8888).copy()
        return qimg, (lat0, lon0, mpp)

    def _sample(self, lat_g, lon_g, mip):
        """Vectorised elevation sampling straight off the TileCache
        (mirrors SVSRenderer._sample_elevations without needing a full
        renderer instance)."""
        elev = np.full(lat_g.shape, -9999.0, dtype=np.float32)
        tl = np.floor(lat_g).astype(np.int32)
        tn = np.floor(lon_g).astype(np.int32)
        for la, lo in {(int(a), int(b))
                       for a, b in zip(tl.ravel(), tn.ravel())}:
            # Track-1c pyramid when the branch has it; raw tile
            # otherwise (aliasing at far zooms until 1c merges).
            t = (self._cache.get_mip(la, lo, mip)
                 if hasattr(self._cache, "get_mip")
                 else self._cache.get(la, lo))
            if t is None:
                continue
            m = (tl == la) & (tn == lo)
            nn = t.shape[0]
            rf = np.clip((la + 1.0 - lat_g[m]) * (nn - 1), 0, nn - 2)
            cf = np.clip((lon_g[m] - lo) * (nn - 1), 0, nn - 2)
            r0 = np.floor(rf).astype(np.int32)
            c0 = np.floor(cf).astype(np.int32)
            dr = (rf - r0).astype(np.float32)
            dc = (cf - c0).astype(np.float32)
            elev[m] = (t[r0, c0] * (1 - dr) * (1 - dc)
                       + t[r0, c0 + 1] * (1 - dr) * dc
                       + t[r0 + 1, c0] * dr * (1 - dc)
                       + t[r0 + 1, c0 + 1] * dr * dc)
        water = (elev < -4500.0) | (elev == 0.0)
        return np.where(water, 0.0, elev), water
