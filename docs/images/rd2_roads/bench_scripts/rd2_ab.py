"""RD2 A/B on the real highways pack: pre-RD2 (dev) roads.py vs this branch.
Writes before|after crops (4x nearest-neighbour around the ownship) at the
near ranges, checks byte equality at 20/40/80 NM, and times the render.
usage: rd2_ab.py <pre-RD2 roads.py> <highways.sqlite> <outdir>"""
import sys, time, types, importlib.util, numpy as np
from PyQt6.QtGui import QGuiApplication, QImage
app = QGuiApplication(sys.argv)
import pyefis.instruments.map.layers.roads as R
spec = importlib.util.spec_from_file_location("roads_old", sys.argv[1])
old = importlib.util.module_from_spec(spec); spec.loader.exec_module(old)
DB, out = sys.argv[2], sys.argv[3]

def bgra(img):
    b = img.constBits(); b.setsize(img.sizeInBytes())
    return np.frombuffer(b, np.uint8).reshape(
        img.height(), img.bytesPerLine() // 4, 4)[:, :img.width()].copy()

def rgb(a):
    a = a.astype(float)
    bg = np.array([38, 52, 40], float)   # dark relief-ish green
    al = a[..., 3:4] / 255.0
    return (a[..., [2, 1, 0]] + bg * (1 - al)).clip(0, 255).astype(np.uint8)

own = types.SimpleNamespace(highway_db_path=DB, road_color="",
                            road_casing_color="", perf=None)
O = old.RoadsLayer(); O.configure(own)
N = R.RoadsLayer(); N.configure(own)
SCENES = {"dfw": (32.92, -96.93), "ksba": (34.41, -119.88)}
CROP = {"dfw"}                       # ksba has no road at the centre
W, H, CY = 650, 1040, 520.0          # the bench map window (MP11 evidence)

def timed(layer, job, reps=3):
    best = 1e9
    for _ in range(reps):
        t0 = time.perf_counter(); img = layer._render(job)[0]
        best = min(best, time.perf_counter() - t0)
    return img, best * 1000.0

for name, (lat, lon) in SCENES.items():
    for r in [1, 2, 5, 20, 40, 80]:
        job = (None, lat, lon, float(r), W, H, CY)
        ia, ta = timed(O, job); ib, tb = timed(N, job)
        a, b = bgra(ia), bgra(ib)
        diff = int((a != b).any(axis=2).sum())
        print("%s %2d NM  pre %7.1f ms  rd2 %7.1f ms  road px %7d  "
              "changed px %7d  identical %s" % (
                  name, r, ta, tb, int((a[..., 3] > 0).sum()), diff,
                  np.array_equal(a, b)), flush=True)
        if r <= 5 and name in CROP:
            n = a.shape[0]; c = n // 2 - 80
            crop = np.hstack([rgb(a)[c:c + 160, c:c + 160],
                              np.full((160, 2, 3), 255, np.uint8),
                              rgb(b)[c:c + 160, c:c + 160]])
            big = np.ascontiguousarray(crop.repeat(4, 0).repeat(4, 1))
            QImage(big.data, big.shape[1], big.shape[0], big.shape[1] * 3,
                   QImage.Format.Format_RGB888).save(
                "%s/ab_crop4x_%s_%dnm.png" % (out, name, r))
