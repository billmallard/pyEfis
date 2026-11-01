"""MP11 pixel A/B: pre-MP11 roads.py vs this checkout, alpha channel.
usage: ab.py <old roads.py> <lat> <lon> <highways.sqlite> [png prefix]"""
import sys, types, math, importlib.util, numpy as np
from PyQt6.QtGui import QGuiApplication
app = QGuiApplication(sys.argv)
from pyefis.instruments.map.layers.roads import RoadsLayer
spec = importlib.util.spec_from_file_location("roads_old", sys.argv[1]); old = importlib.util.module_from_spec(spec); spec.loader.exec_module(old)
DB = sys.argv[4]
def arr(img):
    b = img.constBits(); b.setsize(img.sizeInBytes())
    return np.frombuffer(b, np.uint8).reshape(img.height(), img.bytesPerLine()//4, 4)[:, :img.width()].copy()
own = types.SimpleNamespace(highway_db_path=DB, road_color="", perf=None)
N = RoadsLayer(); N.configure(own); O = old.RoadsLayer(); O.configure(own)
lat, lon = float(sys.argv[2]), float(sys.argv[3])
for r in [5, 20, 40, 80]:
    job = (None, lat, lon, r, 650, 1040, 520.0)
    a = arr(O._render(job)[0]).astype(int); b = arr(N._render(job)[0]).astype(int)
    d = np.abs(a - b).max(axis=2)
    ca, cb = a[..., 3] > 0, b[..., 3] > 0
    sa, sb = a[..., 3] >= 128, b[..., 3] >= 128
    iou = (ca & cb).sum() / max(1, (ca | cb).sum())
    print(f"{r:3d} NM covered old={ca.sum()} new={cb.sum()} IoU(any)={iou:.4f} "
          f"solid(>=128): old-only={(sa & ~cb).sum()} new-only={(sb & ~ca).sum()} of {sa.sum()} | "
          f"px diff>0 {np.mean(d[ca|cb]>0)*100:.1f}%  >16 {np.mean(d[ca|cb]>16)*100:.2f}%  >64 {np.mean(d[ca|cb]>64)*100:.2f}%  max {d.max()}  mean|dA| {np.abs(a[...,3]-b[...,3])[ca|cb].mean():.2f}", flush=True)
    if len(sys.argv) > 5:
        from PIL import Image
        Image.fromarray(np.dstack([a[...,3], b[...,3], np.zeros_like(a[...,3])]).astype(np.uint8)).save(f"{sys.argv[5]}_{r}.png")
