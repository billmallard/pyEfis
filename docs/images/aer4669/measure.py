#!/usr/bin/env python3
"""Size-scaled water vertex cap: renders, timing, pack-size bound (AER-4669).

Inputs are two state rebuilds of the OSM inland-water layer through
``tools/build_water_db.py`` with the water-na recipe (``--max-vertices 32
--min-area-km2 0.05 --keep-fclass water reservoir``): one at the plain cap
(``*_base.sqlite``) and one with ``--large-ring-cap 1024`` (``*_s1024``).
The README beside this file has the build commands.

Subcommands::

    render  PACK DB_DIR OUT_DIR   before/after PNGs (AER-4604 method)
    timing  DB_DIR                query + raster timing, base vs scaled
    size    PACK DB_DIR           full-pack size estimate, calibrated on
                                  the state rebuilds

Run with ``QT_QPA_PLATFORM=offscreen PYTHONPATH=src``.
"""
import importlib.util
import math
import sqlite3
import statistics
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location(
    "build_water_db", _ROOT / "tools" / "build_water_db.py")
bw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bw)

# name: (lat, lon, range_nm, state). 20 NM is the widest range at which
# the polygons draw over a terrain pack that ships a water mask
# (water_polygon_max_nm); past it the mask, built from the same pack,
# draws instead.
SCENES = {
    "gsl_10nm": (41.1, -112.5, 10.0, "ut"),
    "gsl_20nm": (41.15, -112.45, 20.0, "ut"),
    "mille_lacs_10nm": (46.25, -93.65, 10.0, "mn"),
}
# Dense timing scenes: the Brainerd lakes country (hundreds of lakes,
# Mille Lacs and Leech in the window at 20 NM) and the GSL.
TIMING = {
    "brainerd_20nm": (46.55, -94.15, 20.0, "mn"),
    "mille_lacs_20nm": (46.25, -93.65, 20.0, "mn"),
    "gsl_20nm": (41.15, -112.45, 20.0, "ut"),
}
W = H = 600
_COLS = ("min_lat, max_lat, min_lon, max_lon, kind, elev_ft, "
         "vertices, triangles, rings")
_INLAND = ("water", "lake", "river")


def _box(lat, lon, rng):
    half_lat = rng / 60.0 * 1.5
    half_lon = half_lat / math.cos(math.radians(lat))
    return [lat - half_lat, lat + half_lat, lon - half_lon, lon + half_lon]


def _copy_rows(src, dst, box, kinds=None):
    sql = (f"SELECT {_COLS} FROM water_polygons WHERE id IN (SELECT id FROM "
           "water_rtree WHERE max_lat >= ? AND min_lat <= ? AND max_lon >= ? "
           "AND min_lon <= ?)")
    params = list(box)
    if kinds:
        sql += f" AND kind IN ({','.join('?' * len(kinds))})"
        params += list(kinds)
    n = 0
    for r in src.execute(sql, params):
        cur = dst.execute(
            f"INSERT INTO water_polygons ({_COLS}) VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?)", r)
        dst.execute("INSERT INTO water_rtree VALUES (?, ?, ?, ?, ?)",
                    (cur.lastrowid, *r[:4]))
        n += 1
    return n


def _cut(path, parts, lat, lon, rng):
    """New water db at *path* holding, for each (src, kinds) in *parts*,
    every row of *src* whose bbox meets the scene window."""
    dst = sqlite3.connect(str(path))
    dst.executescript(bw.SCHEMA)
    box = _box(lat, lon, rng)
    for src, kinds in parts:
        _copy_rows(src, dst, box, kinds)
    dst.commit()
    dst.close()


class _FlatLand:
    def get(self, la, lo):
        return np.full((1201, 1201), 500.0, dtype=np.float32)


def _layer(water_db):
    from pyefis.instruments.ai.water_db import WaterDB
    from pyefis.instruments.map.layers.terrain import TerrainLayer
    lay = TerrainLayer()
    lay._cache = _FlatLand()
    lay._water = WaterDB(str(water_db), max_vertices=512)

    class Owner:
        _alt_ft = 0.0
    lay._owner = Owner
    return lay


def _job(lay, lat, lon, rng):
    from pyefis.instruments import map as moving_map
    x = moving_map.MapTransform(lat, lon, rng, 0.0, W, H, 0.5)
    return (lay._key(x), x.lat0, x.lon0, x.range_nm, x.w, x.h, x.cy)


def _render(water_db, lat, lon, rng):
    lay = _layer(water_db)
    img, _ = lay._render(_job(lay, lat, lon, rng))
    img = img.convertToFormat(img.Format.Format_RGB888)
    ptr = img.constBits()
    ptr.setsize(img.sizeInBytes())
    arr = np.frombuffer(ptr, np.uint8).reshape(img.height(),
                                               img.bytesPerLine())
    return arr[:, :img.width() * 3].reshape(img.height(), img.width(),
                                            3).copy()


def cmd_render(pack, db_dir, out_dir):
    from PIL import Image
    from PyQt6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    db_dir = Path(db_dir)
    src = sqlite3.connect(f"file:{pack}?mode=ro", uri=True)
    with tempfile.TemporaryDirectory() as tmp:
        for name, (lat, lon, rng, st) in SCENES.items():
            base = sqlite3.connect(f"file:{db_dir}/{st}_base.sqlite?mode=ro",
                                   uri=True)
            scal = sqlite3.connect(f"file:{db_dir}/{st}_s1024.sqlite?mode=ro",
                                   uri=True)
            # Top row: Natural Earth lakes kept (the glass if only the cap
            # changes). Bottom row: OSM alone (the glass if the AER-4604
            # NE drop also ships). Left to right: published r6, rebuild at
            # cap 32, rebuild with the size-scaled cap.
            variants = {
                "pub_ne": [(src, None)],
                "base_ne": [(base, None), (src, ("lake",))],
                "scal_ne": [(scal, None), (src, ("lake",))],
                "pub_osm": [(src, ("water",))],
                "base_osm": [(base, None)],
                "scal_osm": [(scal, None)],
            }
            imgs = {}
            for k, parts in variants.items():
                p = Path(tmp) / f"{name}_{k}.sqlite"
                _cut(p, parts, lat, lon, rng)
                imgs[k] = _render(p, lat, lon, rng)
            gap_v = np.full((imgs["pub_ne"].shape[0], 8, 3), 255, np.uint8)
            rows = []
            for row in (("pub_ne", "base_ne", "scal_ne"),
                        ("pub_osm", "base_osm", "scal_osm")):
                rows.append(np.hstack((imgs[row[0]], gap_v, imgs[row[1]],
                                       gap_v, imgs[row[2]])))
            gap_h = np.full((8, rows[0].shape[1], 3), 255, np.uint8)
            Image.fromarray(np.vstack((rows[0], gap_h, rows[1]))).save(
                out / f"{name}.png")
            d = {r: int((imgs[f"base_{r}"] != imgs[f"scal_{r}"])
                        .any(axis=2).sum()) for r in ("ne", "osm")}
            print(f"{name}: base vs scaled differ by {d['ne']} px (NE kept), "
                  f"{d['osm']} px (OSM only)")


def cmd_timing(db_dir, reps="15"):
    """Base and scaled timed INTERLEAVED (A, B, A, B ...) so machine
    drift lands on both equally; medians and the median per-rep B - A."""
    from PyQt6.QtWidgets import QApplication
    from pyefis.instruments.ai.water_db import WaterDB
    QApplication.instance() or QApplication([])
    reps = int(reps)
    db_dir = Path(db_dir)
    print(f"scene | variant | polys | verts | query cold ms | render cold ms "
          f"| render warm ms  (median of {reps}, interleaved, 600x600)")
    for name, (lat, lon, rng, st) in TIMING.items():
        ctx = {}
        for var in ("base", "s1024"):
            db = db_dir / f"{st}_{var}.sqlite"
            lay = _layer(db)
            job = _job(lay, lat, lon, rng)
            n, mpp, *_ = lay._window(job)
            window_nm = ((n - 1) / 2.0 * mpp) / 1852.0
            min_diag = 3.0 * mpp / 111320.0

            def query(db=db, window_nm=window_nm, min_diag=min_diag):
                w = WaterDB(str(db), max_vertices=512)
                return list(w.polygons_in_range(
                    lat, lon, window_nm, min_bbox_diag_deg=min_diag))
            polys = query()
            lay._render(job)
            ctx[var] = dict(
                polys=len(polys),
                verts=sum(len(p.vertices) for p in polys),
                fns=(query,
                     lambda db=db, job=job: _layer(db)._render(job),
                     lambda lay=lay, job=job: lay._render(job)),
                t=([], [], []))
        for _ in range(reps):
            for var in ("base", "s1024"):
                for k, fn in enumerate(ctx[var]["fns"]):
                    t0 = time.perf_counter()
                    fn()
                    ctx[var]["t"][k].append(
                        (time.perf_counter() - t0) * 1000.0)
        for var in ("base", "s1024"):
            c = ctx[var]
            med = [statistics.median(x) for x in c["t"]]
            print(f"{name} | {var} | {c['polys']} | {c['verts']} | "
                  f"{med[0]:.1f} | {med[1]:.1f} | {med[2]:.1f}")
        d = [statistics.median(b - a for a, b in zip(ctx["base"]["t"][k],
                                                     ctx["s1024"]["t"][k]))
             for k in range(3)]
        print(f"{name} | scaled - base, median per rep | | | {d[0]:+.1f} | "
              f"{d[1]:+.1f} | {d[2]:+.1f}")


def _rings(con, kinds=_INLAND):
    """Yield (row_id, [ring arrays]) for every inland row of *con*."""
    q = (f"SELECT id, vertices, rings FROM water_polygons WHERE kind IN "
         f"({','.join('?' * len(kinds))})")
    for rid, v, r in con.execute(q, kinds):
        p = np.frombuffer(v, "<f8").reshape(-1, 2)
        n = len(p)
        ends = (np.frombuffer(r, "<u2" if n <= 65535 else "<u4")
                if r else np.array([n]))
        start = 0
        out = []
        for e in ends.tolist():
            out.append(p[start:e])
            start = e
        yield rid, out


def _area_km2(ring):
    if len(ring) < 3:
        return 0.0
    lat0 = ring[:, 0].mean()
    x, y = ring[:, 1], ring[:, 0]
    s = np.dot(x, np.roll(y, -1)) - np.dot(np.roll(x, -1), y)
    return abs(s) / 2.0 * 110.574 * 111.320 * math.cos(math.radians(lat0))


def _estimate(con, base=32, area0=10.0, cap=1024):
    """Vertices the size-scaled cap would add, read off a built pack: every
    ring whose STORED area exceeds *area0* grows to its scaled cap. NOT a
    bound -- the real delta was 79% (Utah) and 185% (Minnesota) of it. It
    over-counts rings whose source is shorter than the scaled cap, and
    under-counts two ways: a coarse ring's stored area can be far below
    its source area, and a finer outer ring can fail hole verification
    and escalate the row's island rings as well."""
    add = 0
    rings_hit = 0
    stored = 0
    for _rid, rings in _rings(con):
        for ring in rings:
            stored += len(ring)
            a = _area_km2(ring)
            if a <= area0:
                continue
            c = int(min(cap, round(base * math.sqrt(a / area0))))
            if c > len(ring):
                add += c - len(ring)
                rings_hit += 1
    return add, rings_hit, stored


def _blob_bytes(con, kinds=_INLAND):
    q = ("SELECT count(*), sum(length(vertices)), "
         "sum(coalesce(length(triangles), 0)), "
         "sum(coalesce(length(rings), 0)) FROM water_polygons WHERE kind IN "
         f"({','.join('?' * len(kinds))})")
    n, v, t, r = con.execute(q, kinds).fetchone()
    return n, v or 0, t or 0, r or 0


def cmd_size(pack, db_dir):
    db_dir = Path(db_dir)
    # Calibration on the state rebuilds: estimate read off the base
    # build vs the real delta of the scaled build.
    ratios = []
    for st in ("ut", "mn"):
        b = sqlite3.connect(f"file:{db_dir}/{st}_base.sqlite?mode=ro",
                            uri=True)
        s = sqlite3.connect(f"file:{db_dir}/{st}_s1024.sqlite?mode=ro",
                            uri=True)
        add, hit, stored = _estimate(b)
        nb, vb, tb, rb = _blob_bytes(b)
        ns, vs, ts, rs = _blob_bytes(s)
        real_v = (vs - vb) // 16
        fb = (Path(db_dir) / f"{st}_base.sqlite").stat().st_size
        fs = (Path(db_dir) / f"{st}_s1024.sqlite").stat().st_size
        print(f"{st}: {nb} rows, {stored} stored vertices; estimate "
              f"+{add} vertices on {hit} rings; real +{real_v} vertices "
              f"({real_v / max(1, add):.0%} of estimate); blob bytes "
              f"{vb + tb + rb} -> {vs + ts + rs} "
              f"(+{(vs + ts + rs) - (vb + tb + rb)}); file {fb} -> {fs} "
              f"(+{fs - fb}, {100.0 * (fs - fb) / fb:+.2f}%)")
        ratios.append((real_v, add, (vs + ts + rs) - (vb + tb + rb),
                       vb + tb + rb))
    bpv = sum(r[2] for r in ratios) / max(1, sum(r[0] for r in ratios))
    print(f"measured bytes per added vertex (vertices + triangles): {bpv:.1f}")
    p = sqlite3.connect(f"file:{pack}?mode=ro", uri=True)
    add, hit, stored = _estimate(p)
    n, v, t, r = _blob_bytes(p)
    size = Path(pack).stat().st_size
    est = add * bpv
    worst = max(x[0] / max(1, x[1]) for x in ratios)
    print(f"water-na inland: {n} rows, {stored} stored vertices, "
          f"{v + t + r} blob bytes; file {size} bytes")
    for st, x in zip(("ut", "mn"), ratios):
        g = x[2] / x[3] * (v + t + r)
        print(f"  scaled by {st}'s inland blob growth "
              f"({100.0 * x[2] / x[3]:.3f}%): +{g / 1e6:.1f} MB "
              f"({100.0 * g / size:+.2f}% of the file)")
    print(f"  read off the pack: +{add} vertices on {hit} rings -> "
          f"+{est / 1e6:.1f} MB; x{worst:.2f} (worst calibration) -> "
          f"+{est * worst / 1e6:.1f} MB "
          f"({100.0 * est * worst / size:+.2f}% of the file)")


if __name__ == "__main__":
    cmd = sys.argv[1]
    {"render": cmd_render, "timing": cmd_timing,
     "size": cmd_size}[cmd](*sys.argv[2:])
