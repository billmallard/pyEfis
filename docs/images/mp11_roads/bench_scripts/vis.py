"""MP11 visual A/B: old | new over a dark background, full image and a 4x
nearest-neighbour crop of the image centre.
usage: vis.py <old roads.py> <highways.sqlite> <outdir>"""
import sys, types, importlib.util, numpy as np
from PyQt6.QtGui import QGuiApplication
app = QGuiApplication(sys.argv)
import pyefis.instruments.map.layers.roads as R
from PIL import Image, ImageDraw
spec = importlib.util.spec_from_file_location("roads_old", sys.argv[1]); old = importlib.util.module_from_spec(spec); spec.loader.exec_module(old)
DB = sys.argv[2]
out = sys.argv[3]
def rgb(img):
    b = img.constBits(); b.setsize(img.sizeInBytes())
    a = np.frombuffer(b, np.uint8).reshape(img.height(), img.bytesPerLine()//4, 4)[:, :img.width()].astype(float)
    bg = np.array([38, 52, 40], float)  # dark relief-ish green
    al = a[..., 3:4] / 255.0
    return (a[..., [2,1,0]] + bg * (1 - al)).clip(0,255).astype(np.uint8)  # premultiplied BGRA -> RGB over bg
own = types.SimpleNamespace(highway_db_path=DB, road_color="", perf=None)
O = old.RoadsLayer(); O.configure(own); N = R.RoadsLayer(); N.configure(own)
for r in [5, 20, 80]:
    job = (None, 35.8, -78.8, r, 650, 1040, 520.0)
    a = rgb(O._render(job)[0]); b = rgb(N._render(job)[0])
    full = Image.fromarray(np.hstack([a, np.full((a.shape[0], 8, 3), 255, np.uint8), b]))
    full.save(f"{out}/ab_full_{r}nm.png")
    c0 = 512 - 80
    crop = np.hstack([a[c0:c0+160, c0:c0+160], np.full((160, 2, 3), 255, np.uint8), b[c0:c0+160, c0:c0+160]])
    Image.fromarray(crop).resize((crop.shape[1]*4, crop.shape[0]*4), Image.NEAREST).save(f"{out}/ab_crop4x_{r}nm.png")
