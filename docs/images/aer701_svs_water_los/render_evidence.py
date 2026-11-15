#!/usr/bin/env python3
"""AER-701 / pyEfis#102 evidence renderer.

Builds a synthetic ridge + inland-lake scene, runs the REAL production
``SVSRenderer._collect_water_sync`` through it twice -- once with
``_los_masked_batch`` disabled (reproducing pre-#102 behaviour: no line-of
-sight masking) and once with the shipped fix active -- and draws a top-down
diagnostic PNG for each using QPainter (no GL / X-Plane feed required).

This is NOT a capture of the live 3D SVS screen -- that requires the
AER-658 driver.py/glReadPixels capture pipeline, itself pending the
maos-workspace write-access gap tracked on AER-659 (out of scope for this
fix per Elon's AER-701 ruling). It IS the real masking/collection code
(``_collect_water_sync``, ``_los_masked_batch``, ``_sample_elevations``)
run end-to-end against a synthetic SRTM tile + water polygon, so the
water triangles drawn/dropped in each panel are the actual output of the
production function, not a hand-drawn mockup.

Usage: QT_QPA_PLATFORM=offscreen python3 render_evidence.py <outdir>
"""
import os
import sqlite3
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PyQt6.QtGui import QGuiApplication, QImage, QPainter, QColor, QPen
from PyQt6.QtCore import Qt, QPointF
from PIL import Image, ImageDraw, ImageFont

# This script imports pyefis assuming it's already on sys.path -- the
# caller sets PYTHONPATH (see the README beside this file).
from pyefis.instruments.ai.svs import SVSRenderer, tile_name, SRTM3_SAMPLES
from pyefis.instruments.ai.water_db import encode_vertices

# --- Scene definition -------------------------------------------------
# Aircraft south of an east-west ridge; an inland lake sits north of the
# ridge -- geometrically identical shape to the reported bug (a water
# body behind a mountain from the aircraft's viewpoint).
AC_LAT, AC_LON, AC_ALT_FT = 38.00, -106.95, 6000.0
RIDGE_LAT_MIN, RIDGE_LAT_MAX = 38.10, 38.14      # ~6-8.4 NM north of ac
RIDGE_ELEV_FT = 7000.0
FLAT_ELEV_FT = 300.0
LAKE_LAT_MIN, LAKE_LAT_MAX = 38.22, 38.24        # ~13.2-14.4 NM north of ac
LAKE_LON_MIN, LAKE_LON_MAX = -107.02, -106.88
LAKE_ELEV_FT = 300.0                              # valley floor, sampled from tile
RANGE_NM = 18.0

TILE_LAT, TILE_LON = 38, -107   # SW corner; tile covers 38-39N, 107-106W


def build_tile(tile_root: Path):
    n = SRTM3_SAMPLES
    lat = TILE_LAT + 1.0 - (np.arange(n) / (n - 1))       # row 0 = north
    lon = TILE_LON + (np.arange(n) / (n - 1))               # col 0 = west
    lat_g, lon_g = np.meshgrid(lat, lon, indexing="ij")
    elev = np.full((n, n), FLAT_ELEV_FT, dtype=np.float32)
    elev[(lat_g >= RIDGE_LAT_MIN) & (lat_g <= RIDGE_LAT_MAX)] = RIDGE_ELEV_FT
    elev[(lat_g >= LAKE_LAT_MIN) & (lat_g <= LAKE_LAT_MAX)
         & (lon_g >= LAKE_LON_MIN) & (lon_g <= LAKE_LON_MAX)] = LAKE_ELEV_FT
    name = tile_name(TILE_LAT, TILE_LON)
    ns_dir = f"{'N' if TILE_LAT >= 0 else 'S'}{abs(TILE_LAT):02d}"
    tile_dir = tile_root / "srtm3" / ns_dir
    tile_dir.mkdir(parents=True, exist_ok=True)
    elev.astype(">i2").tofile(tile_dir / f"{name}.hgt")
    return tile_root / "srtm3", elev, lat, lon


def build_water_db(path: Path):
    outer = [
        (LAKE_LAT_MIN, LAKE_LON_MIN), (LAKE_LAT_MIN, LAKE_LON_MAX),
        (LAKE_LAT_MAX, LAKE_LON_MAX), (LAKE_LAT_MAX, LAKE_LON_MIN),
    ]
    con = sqlite3.connect(str(path))
    con.execute("""
        CREATE TABLE water_polygons (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            min_lat   REAL NOT NULL, max_lat   REAL NOT NULL,
            min_lon   REAL NOT NULL, max_lon   REAL NOT NULL,
            kind      TEXT NOT NULL, elev_ft   REAL,
            vertices  BLOB NOT NULL, triangles BLOB, rings BLOB)
    """)
    con.execute(
        "INSERT INTO water_polygons "
        "(min_lat, max_lat, min_lon, max_lon, kind, elev_ft, "
        " vertices, triangles, rings) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (LAKE_LAT_MIN, LAKE_LAT_MAX, LAKE_LON_MIN, LAKE_LON_MAX,
         "lake", None, encode_vertices(outer), None, None))
    con.commit()
    con.close()


def collect(renderer, masking_enabled):
    if masking_enabled:
        return renderer._collect_water_sync(AC_LAT, AC_LON, AC_ALT_FT, RANGE_NM)
    orig = renderer._los_masked_batch
    renderer._los_masked_batch = (
        lambda *a, **k: np.zeros_like(np.asarray(a[3]), dtype=bool))
    try:
        return renderer._collect_water_sync(AC_LAT, AC_LON, AC_ALT_FT, RANGE_NM)
    finally:
        renderer._los_masked_batch = orig


# --- Rendering ----------------------------------------------------------

W, H = 1400, 1000
LAT_TOP, LAT_BOT = 38.27, 37.97
LON_LEFT, LON_RIGHT = -107.06, -106.84


def proj(lat, lon):
    x = (lon - LON_LEFT) / (LON_RIGHT - LON_LEFT) * W
    y = (LAT_TOP - lat) / (LAT_TOP - LAT_BOT) * H
    return QPointF(x, y)


def render_panel(elev, lat_axis, lon_axis, tris, title, subtitle, out_path):
    img = QImage(W, H, QImage.Format.Format_RGB32)
    img.fill(QColor(10, 10, 20))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    # Terrain raster: sample the elevation grid onto screen pixels (coarse
    # stride -- this is a diagnostic, not a photoreal render).
    stride = 4
    n = elev.shape[0]
    for py in range(0, H, stride):
        lat = LAT_TOP - (py / H) * (LAT_TOP - LAT_BOT)
        row = int(round((TILE_LAT + 1.0 - lat) * (n - 1)))
        row = max(0, min(row, n - 1))
        for px in range(0, W, stride):
            lon = LON_LEFT + (px / W) * (LON_RIGHT - LON_LEFT)
            col = int(round((lon - TILE_LON) * (n - 1)))
            col = max(0, min(col, n - 1))
            e = float(elev[row, col])
            if e >= RIDGE_ELEV_FT - 1:
                c = QColor(120, 100, 90)      # ridge: grey-brown
            else:
                t = max(0.0, min(1.0, e / 1000.0))
                c = QColor(int(30 + 40 * t), int(70 + 60 * t), int(30 + 20 * t))
            p.fillRect(px, py, stride, stride, c)

    # Water triangles actually returned by _collect_water_sync.
    if tris is not None and tris.size:
        p.setBrush(QColor(30, 110, 200, 235))
        p.setPen(QPen(QColor(180, 220, 255), 1))
        for i in range(0, tris.shape[0], 3):
            pts = [proj(float(tris[i + k, 0]), float(tris[i + k, 1]))
                   for k in range(3)]
            p.drawPolygon(*pts)

    # Lake outline (always drawn, dashed) so a fully-masked lake still
    # shows WHERE it should have been.
    outline = [
        (LAKE_LAT_MIN, LAKE_LON_MIN), (LAKE_LAT_MIN, LAKE_LON_MAX),
        (LAKE_LAT_MAX, LAKE_LON_MAX), (LAKE_LAT_MAX, LAKE_LON_MIN),
    ]
    pen = QPen(QColor(255, 255, 255, 160))
    pen.setStyle(Qt.PenStyle.DashLine)
    pen.setWidth(2)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPolygon(*[proj(la, lo) for la, lo in outline])

    # Aircraft marker + sight ray to the lake centre.
    ac_pt = proj(AC_LAT, AC_LON)
    lake_ctr = proj((LAKE_LAT_MIN + LAKE_LAT_MAX) / 2,
                    (LAKE_LON_MIN + LAKE_LON_MAX) / 2)
    ridge_label_pt = proj((RIDGE_LAT_MIN + RIDGE_LAT_MAX) / 2, -107.04)
    pen = QPen(QColor(255, 210, 60, 200))
    pen.setStyle(Qt.PenStyle.DashLine)
    pen.setWidth(2)
    p.setPen(pen)
    p.drawLine(ac_pt, lake_ctr)
    p.setBrush(QColor(255, 210, 60))
    p.setPen(QPen(QColor(0, 0, 0), 1))
    p.drawEllipse(ac_pt, 8, 8)

    # Mark where the sight ray crosses the ridge -- the actual occlusion
    # point _los_masked_batch is testing for.
    cross_pt = proj((RIDGE_LAT_MIN + RIDGE_LAT_MAX) / 2, AC_LON)
    p.setPen(QPen(QColor(255, 60, 60), 4))
    r = 12
    p.drawLine(QPointF(cross_pt.x() - r, cross_pt.y() - r),
              QPointF(cross_pt.x() + r, cross_pt.y() + r))
    p.drawLine(QPointF(cross_pt.x() - r, cross_pt.y() + r),
              QPointF(cross_pt.x() + r, cross_pt.y() - r))

    p.end()

    # Text is drawn with Pillow's bundled default font -- this sandbox has
    # no fontconfig/system fonts, so Qt's QPainter.drawText silently emits
    # tofu boxes (no glyphs). Pillow's ImageFont.load_default() ships its
    # own outline font and needs no system font files.
    img.save(str(out_path))
    pil = Image.open(out_path).convert("RGB")
    draw = ImageDraw.Draw(pil)
    f_title = ImageFont.load_default(size=30)
    f_sub = ImageFont.load_default(size=18)
    f_label = ImageFont.load_default(size=18)

    ac_xy = (ac_pt.x() + 12, ac_pt.y() - 26)
    draw.text(ac_xy, "aircraft  6000 ft", fill=(255, 230, 150), font=f_label)
    ridge_xy = (ridge_label_pt.x(), ridge_label_pt.y() - 12)
    draw.text(ridge_xy, "ridge, 7000 ft", fill=(255, 255, 255), font=f_label)
    draw.text((cross_pt.x() + 16, cross_pt.y() - 30),
             "sight line to lake\nblocked by ridge here",
             fill=(255, 120, 120), font=f_label)

    draw.text((20, 12), title, fill=(255, 255, 255), font=f_title)
    draw.text((20, 55), subtitle, fill=(230, 230, 230), font=f_sub)

    n_tris = 0 if tris is None else tris.shape[0] // 3
    draw.text((20, H - 34),
             f"_collect_water_sync() returned {n_tris} triangle(s) "
             f"for the lake (dashed outline = true lake extent)",
             fill=(200, 230, 255), font=f_sub)

    pil.save(out_path)
    print(f"wrote {out_path} ({n_tris} triangles)")


def main():
    outdir = Path(sys.argv[1])
    outdir.mkdir(parents=True, exist_ok=True)
    app = QGuiApplication.instance() or QGuiApplication([])

    tile_root, elev, lat_axis, lon_axis = build_tile(outdir)
    water_path = outdir / "water.sqlite"
    build_water_db(water_path)

    r = SVSRenderer({
        "enabled": True, "tile_path": str(tile_root),
        "water_db_path": str(water_path),
    })
    assert r.water_db.ready, "water_db failed to load"
    assert r.cache is not None, "elevation cache failed to load"

    before = collect(r, masking_enabled=False)
    after = collect(r, masking_enabled=True)

    render_panel(elev, lat_axis, lon_axis, before,
                "BEFORE -- pyEfis#102 (no LOS masking)",
                "Lake triangles drawn through the ridge -- no depth test, no occlusion check",
                outdir / "before_water_through_ridge.png")
    render_panel(elev, lat_axis, lon_axis, after,
                "AFTER -- AER-701 fix",
                "Lake triangles behind the ridge are dropped before upload to the GPU",
                outdir / "after_water_los_masked.png")


if __name__ == "__main__":
    main()
