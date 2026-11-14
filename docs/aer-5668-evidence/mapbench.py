"""MAPPAINT1 offscreen microbench: the bench panel's map (650x1000, live
layer set) flown at a 10 Hz noisy feed through the real frame clock.
Reports map paint count, layer redraws vs reuses, and ms of GUI thread per
second spent in paintEvent, split by layer.

Run from a pyEfis tree: QT_QPA_PLATFORM=offscreen python mapbench.py
  [--orientation track_up|north_up] [--nd ctr|expanded|off] [--secs 30]
"""
import argparse
import json
import math
import os
import random
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path.cwd()
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import bench_map_gestures as bmg  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--orientation", default="track_up")
ap.add_argument("--nd", default="ctr")
ap.add_argument("--range", type=float, default=10.0)
ap.add_argument("--secs", type=float, default=30.0)
ap.add_argument("--w", type=int, default=650)
ap.add_argument("--h", type=int, default=1000)
ap.add_argument("--lat", type=float, default=35.70)
ap.add_argument("--lon", type=float, default=-83.38)
ap.add_argument("--track", type=float, default=307.0)
ap.add_argument("--gs", type=float, default=136.0)
ap.add_argument("--data", default="/data/makerplane-data")
ap.add_argument("--seed", type=int, default=1)
ap.add_argument("--label", default="")
ap.add_argument("--feed", default="smooth", choices=["smooth", "jitter"])
ap.add_argument("--callers", action="store_true")
a = ap.parse_args()
random.seed(a.seed)

fix = bmg._bootstrap_fix_db(a.lat, a.lon, a.track, 4500.0, a.gs)


def _def(key, dtype, value, lo=0.0, hi=100000.0):
    fix.db.define_item(key, key, dtype, lo, hi, "", 50000, "")
    fix.db.set_value(key, value)
    it = fix.db.get_item(key)
    it.bad = False
    it.fail = False


_def("WINDDIR", "float", 250.0, 0, 360)
_def("WINDSPD", "float", 18.0)
_def("FPLSTATE", "int", 2, 0, 10)
_def("FPLPHASE", "str", "ENROUTE")
_def("WPNAME", "str", "SUGOE")
_def("WPDIS", "float", 24.0)
_def("WPETE", "float", 640.0)
_def("MAGVAR", "float", -6.0, -180, 180)

from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

from pyefis.instruments import map as moving_map  # noqa: E402
from pyefis.instruments.map import nd as map_nd  # noqa: E402

D = a.data
w = moving_map.MovingMap(font_family="B612")
w.resize(a.w, a.h)
for k, v in dict(
        font_percent=0.2,
        highway_db_path=D + "/highways/current/highways.sqlite",
        layer_airways=True, layer_fixes=True,
        nasr_db_path=D + "/navdata/current/airports.sqlite",
        navaid_db_path=D + "/navaids/current/navaids.sqlite",
        nd_mode=a.nd, orientation=a.orientation,
        range_ladder="2,10,50,200,500,2000",
        terrain_mode="relief", tile_path=D + "/terrain/tiles",
        water_db_path=D + "/water/current/water.sqlite",
        water_max_vertices=1024, zoom_rail=True).items():
    setattr(w, k, v)
w.range_nm = a.range
w.show()

# Per-layer timing: wrap each layer's paint once the layers exist.
layer_ms = {}
nd_ms = [0.0]


def _wrap_layers():
    for layer in w._layers:
        orig = layer.paint

        def timed(p, x, _o=orig, _id=layer.id):
            t0 = time.perf_counter()
            try:
                return _o(p, x)
            finally:
                layer_ms[_id] = layer_ms.get(_id, 0.0) + \
                    (time.perf_counter() - t0) * 1000.0
        layer.paint = timed


orig_nd = map_nd.paint


def timed_nd(*args, **kw):
    t0 = time.perf_counter()
    try:
        return orig_nd(*args, **kw)
    finally:
        nd_ms[0] += (time.perf_counter() - t0) * 1000.0


map_nd.paint = timed_nd

import collections
import traceback
callers = collections.Counter()
_orig_update = type(w).update


def _counting_update(self, *args):
    st = traceback.extract_stack(limit=3)[0]
    callers["%s:%s" % (st.filename.rsplit("/", 1)[-1], st.name)] += 1
    return _orig_update(self, *args)


if a.callers:
    type(w).update = _counting_update
paint_ms = []
orig_pe = w.paintEvent


slow = []


def timed_pe(ev):
    before = dict(layer_ms)
    nd0 = nd_ms[0]
    r0 = getattr(w.perf, "layer_renders", 0)
    t0 = time.perf_counter()
    orig_pe(ev)
    ms = (time.perf_counter() - t0) * 1000.0
    paint_ms.append(ms)
    if ms > 40.0 and len(slow) < 12:
        slow.append(dict(ms=round(ms, 1), render=getattr(w.perf, "layer_renders", 0) - r0,
                         nd=round(nd_ms[0] - nd0, 1),
                         layers={k: round(v - before.get(k, 0.0), 1)
                                 for k, v in layer_ms.items()
                                 if v - before.get(k, 0.0) > 2.0}))


w.paintEvent = timed_pe


def pump(secs):
    end = time.perf_counter() + secs
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.002)


pump(1.0)
_wrap_layers()
pump(12.0)        # let every worker publish at the start pose

lat, lon, trk = a.lat, a.lon, a.track
gs, wd, ws, wpdis, wpete = a.gs, 250.0, 18.0, 24.0, 640.0
layer_ms.clear()
nd_ms[0] = 0.0
paint_ms.clear()
callers.clear()
snap0 = w.perf.snapshot()
t_start = time.perf_counter()
next_feed = t_start
while time.perf_counter() - t_start < a.secs:
    now = time.perf_counter()
    if now >= next_feed:
        next_feed += 0.1        # 10 Hz, the bench RREF rate requested
        lat, lon = bmg._dead_reckon_step(lat, lon, gs, trk, 0.1)  # noqa
        el_s = now - t_start
        if a.feed == "jitter":
            t = trk + random.gauss(0.0, 0.15)
            gs_now = gs + random.gauss(0.0, 0.6)
        else:   # X-Plane-like: smooth hand-flown drift, little noise
            t = trk + 1.0 * math.sin(2 * math.pi * el_s / 40.0) \
                + random.gauss(0.0, 0.02)
            gs_now = gs + 1.5 * math.sin(2 * math.pi * el_s / 25.0) \
                + random.gauss(0.0, 0.05)
        fix.db.set_value("LAT", lat)
        fix.db.set_value("LONG", lon)
        fix.db.set_value("TRACK", t % 360.0)
        fix.db.set_value("TRACKM", (t + 6.0) % 360.0)
        fix.db.set_value("GS", gs_now)
        fix.db.set_value("TAS", 128.0 + random.gauss(0.0, 0.6))
        fix.db.set_value("WINDDIR", wd + random.gauss(0.0, 1.0))
        fix.db.set_value("WINDSPD", ws + random.gauss(0.0, 0.5))
        wpdis -= gs * 0.1 / 3600.0
        wpete -= 0.1
        fix.db.set_value("WPDIS", wpdis)
        fix.db.set_value("WPETE", wpete)
    app.processEvents()
    time.sleep(0.002)
el = time.perf_counter() - t_start
snap = w.perf.snapshot()
n = len(paint_ms)
v = sorted(paint_ms)
out = dict(
    label=a.label, feed=a.feed, orientation=a.orientation, nd=a.nd, range=a.range,
    secs=round(el, 2), paints=n, paints_per_s=round(n / el, 2),
    layer_renders=snap.get("layer_renders", 0) - snap0.get("layer_renders", 0),
    layer_reuses=snap.get("layer_reuses", 0) - snap0.get("layer_reuses", 0),
    paint_ms_med=round(v[n // 2], 2) if n else None,
    paint_ms_p90=round(v[int(0.9 * (n - 1))], 2) if n else None,
    paint_ms_max=round(v[-1], 2) if n else None,
    gui_ms_per_s=round(sum(v) / el, 1),
    layer_ms_per_s={k: round(t / el, 1) for k, t in
                    sorted(layer_ms.items(), key=lambda kv: -kv[1])},
    nd_ms_per_s=round(nd_ms[0] / el, 1),
    update_callers=dict(callers.most_common(8)),
    slow=slow,
    jobs={k: (v["jobs_published"] - snap0["layers"].get(k, {}).get("jobs_published", 0))
          for k, v in snap["layers"].items()},
)
print(json.dumps(out))
