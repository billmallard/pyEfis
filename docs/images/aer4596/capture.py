#!/usr/bin/env python3
"""Before/after captures of the moving-map water raster (AER-4596).

Renders ``TerrainLayer._render`` -- the real worker-thread render, real
``WaterDB`` -- once with the pre-AER-4596 fill (every ring of every polygon
in ONE shared even-odd accumulator) and once with ``raster.fill_union``
(even-odd within a polygon, union across polygons), and writes each pair
side by side: left = before, right = after.

Usage::

    QT_QPA_PLATFORM=offscreen PYTHONPATH=src python3 \\
        docs/images/aer4596/capture.py WATER_DB OUT_DIR [TERRAIN_ROOT]

Scenes whose tiles are not under TERRAIN_ROOT render on flat 500 m land,
which isolates the polygon raster (terrain-derived water is then empty).
"""
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from PyQt6.QtWidgets import QApplication

from pyefis.instruments import map as moving_map
from pyefis.instruments.ai.svs import TileCache
from pyefis.instruments.ai.water_db import WaterDB
from pyefis.instruments.map import raster
from pyefis.instruments.map.layers.terrain import TerrainLayer

# name: (lat, lon, range_nm, use real terrain)
SCENES = {
    "gulf_seam_n26_terrain": (26.0, -82.45, 5.0, True),
    "gulf_seam_n26_flat": (26.0, -82.45, 5.0, False),
    "gsl_flat": (41.1, -112.5, 10.0, False),
    "mille_lacs_flat": (46.25, -93.65, 10.0, False),
}
W = H = 600


class _FlatLand:
    def get(self, la, lo):
        return np.full((1201, 1201), 500.0, dtype=np.float32)


def _old_fill(polygons, n):
    return raster.fill_even_odd([r for p in polygons for r in p], n)


def _render(lay, lat, lon, rng):
    x = moving_map.MapTransform(lat, lon, rng, 0.0, W, H, 0.5)
    img, _ = lay._render((lay._key(x), x.lat0, x.lon0, x.range_nm,
                          x.w, x.h, x.cy))
    img = img.convertToFormat(img.Format.Format_RGB888)
    ptr = img.constBits()
    ptr.setsize(img.sizeInBytes())
    arr = np.frombuffer(ptr, np.uint8).reshape(img.height(),
                                               img.bytesPerLine())
    return arr[:, :img.width() * 3].reshape(img.height(), img.width(),
                                            3).copy()


def main(water_db, out_dir, terrain_root=None):
    QApplication.instance() or QApplication([])
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    water = WaterDB(water_db, max_vertices=1024)
    new_fill = raster.fill_union
    for name, (lat, lon, rng, real) in SCENES.items():
        lay = TerrainLayer()
        lay._cache = (TileCache(Path(terrain_root)) if real and terrain_root
                      else _FlatLand())
        lay._water = water

        class Owner:
            _alt_ft = 0.0
        lay._owner = Owner
        raster.fill_union = _old_fill
        before = _render(lay, lat, lon, rng)
        raster.fill_union = new_fill
        after = _render(lay, lat, lon, rng)
        gap = np.full((before.shape[0], 8, 3), 255, np.uint8)
        Image.fromarray(np.hstack((before, gap, after))).save(
            out / f"{name}.png")
        diff = int((before != after).any(axis=2).sum())
        print(f"{name}: {before.shape[1]}x{before.shape[0]} px, "
              f"{diff} px differ")


if __name__ == "__main__":
    main(*sys.argv[1:])
