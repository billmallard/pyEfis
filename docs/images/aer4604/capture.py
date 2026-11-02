#!/usr/bin/env python3
"""Before/after captures of the NE lake dedup (AER-4604).

For each scene, cuts every water row whose bbox meets the scene window
(widened to the full bbox of any NE lake in it) out of a real water
pack into a fresh database built from ``build_water_db.SCHEMA``. That
cut is "before". "After" is the same cut with
``build_water_db.drop_covered_ne_lakes`` applied -- the pass the builder
now runs after import. A lake's cover depends only on rows that meet
the lake's bbox, and the cut holds all of them, so the pass decides
exactly as it would on the whole pack. Both render through
``TerrainLayer._render`` (real worker-thread render, real ``WaterDB``)
on flat 500 m land, so every blue pixel is polygon fill.
Left = before, right = after.

Usage::

    QT_QPA_PLATFORM=offscreen PYTHONPATH=src python3 \\
        docs/images/aer4604/capture.py WATER_DB OUT_DIR
"""
import importlib.util
import math
import sqlite3
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image
from PyQt6.QtWidgets import QApplication

from pyefis.instruments import map as moving_map
from pyefis.instruments.ai.water_db import WaterDB
from pyefis.instruments.map.layers.terrain import TerrainLayer

_ROOT = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location(
    "build_water_db", _ROOT / "tools" / "build_water_db.py")
bw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bw)

# name: (lat, lon, range_nm) -- the AER-4596 scenes, plus a GSL view
# wide enough to show both the west-side mudflats and the east bays.
SCENES = {
    "mille_lacs_flat": (46.25, -93.65, 10.0),
    "gsl_flat": (41.1, -112.5, 10.0),
    "gsl_wide_flat": (41.15, -112.45, 30.0),
}
W = H = 600
_COLS = ("min_lat, max_lat, min_lon, max_lon, kind, elev_ft, "
         "vertices, triangles, rings")


class _FlatLand:
    def get(self, la, lo):
        return np.full((1201, 1201), 500.0, dtype=np.float32)


def _cut(src, path, lat, lon, rng):
    half_lat = rng / 60.0 * 1.5
    half_lon = half_lat / math.cos(math.radians(lat))
    box = [lat - half_lat, lat + half_lat, lon - half_lon, lon + half_lon]
    for a, b, c, d in src.execute(
            "SELECT p.min_lat, p.max_lat, p.min_lon, p.max_lon "
            "FROM water_polygons p WHERE p.id IN (SELECT id FROM water_rtree "
            "WHERE max_lat >= ? AND min_lat <= ? AND max_lon >= ? "
            "AND min_lon <= ?) AND p.kind = 'lake'", box).fetchall():
        box = [min(box[0], a), max(box[1], b), min(box[2], c), max(box[3], d)]
    dst = sqlite3.connect(str(path))
    dst.executescript(bw.SCHEMA)
    rows = src.execute(
        f"SELECT {_COLS} FROM water_polygons WHERE id IN (SELECT id FROM "
        "water_rtree WHERE max_lat >= ? AND min_lat <= ? AND max_lon >= ? "
        "AND min_lon <= ?)", box).fetchall()
    for r in rows:
        cur = dst.execute(
            f"INSERT INTO water_polygons ({_COLS}) VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?)", r)
        dst.execute("INSERT INTO water_rtree VALUES (?, ?, ?, ?, ?)",
                    (cur.lastrowid, *r[:4]))
    dst.commit()
    return dst, len(rows)


def _render(water_db, lat, lon, rng):
    lay = TerrainLayer()
    lay._cache = _FlatLand()
    lay._water = WaterDB(str(water_db), max_vertices=1024)

    class Owner:
        _alt_ft = 0.0
    lay._owner = Owner
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


def main(water_db, out_dir):
    QApplication.instance() or QApplication([])
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(f"file:{water_db}?mode=ro", uri=True)
    with tempfile.TemporaryDirectory() as tmp:
        for name, (lat, lon, rng) in SCENES.items():
            b_path = Path(tmp) / f"{name}_before.sqlite"
            a_path = Path(tmp) / f"{name}_after.sqlite"
            con, n = _cut(src, b_path, lat, lon, rng)
            con.close()
            con, _ = _cut(src, a_path, lat, lon, rng)
            dropped = bw.drop_covered_ne_lakes(con)
            con.commit()
            con.close()
            before = _render(b_path, lat, lon, rng)
            after = _render(a_path, lat, lon, rng)
            gap = np.full((before.shape[0], 8, 3), 255, np.uint8)
            Image.fromarray(np.hstack((before, gap, after))).save(
                out / f"{name}.png")
            diff = int((before != after).any(axis=2).sum())
            drops = ", ".join(f"{c:.2f}/{i:.2f}" for _, c, i in dropped)
            print(f"{name}: {n} rows cut, NE lakes dropped "
                  f"(cover/bbox IoU): [{drops}], {diff} px differ")


if __name__ == "__main__":
    main(*sys.argv[1:])
