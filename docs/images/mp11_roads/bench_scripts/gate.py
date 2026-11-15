"""MP11 gate: roads worker render time + MP6 GuiProbe gaps while it runs.
usage: gate.py <highways.sqlite> [roads_module.py]  (default: the checkout's roads.py)"""
import sys, time, types, threading, importlib.util, statistics
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer
app = QApplication(sys.argv[:1])
from pyefis.instruments.map.perf import GuiProbe
DB = sys.argv[1]
if len(sys.argv) > 2:
    spec = importlib.util.spec_from_file_location("roads_x", sys.argv[2]); mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    tag = "old"
else:
    import pyefis.instruments.map.layers.roads as mod; tag = "new"
L = mod.RoadsLayer(); L.configure(types.SimpleNamespace(highway_db_path=DB, road_color="", perf=None))
lat, lon, w, h = 35.8, -78.8, 650, 1040
for r in [5, 20, 40, 80, 160]:
    job = (None, lat, lon, r, w, h, h * 0.5)
    if L._classes_for_range(r) is None:
        print(f"{tag} {r:3d} NM  layer hidden at this range (coarsest LOD band is 80 NM): no render, no job"); continue
    L._render(job)                      # warm
    times = []
    probe = GuiProbe(); probe.start(app)
    done = threading.Event()
    def work():
        for _ in range(5):
            t = time.perf_counter(); L._render(job); times.append((time.perf_counter() - t) * 1000)
        done.set()
    def go():
        threading.Thread(target=work, daemon=True).start()
    QTimer.singleShot(200, go)          # let the probe settle first
    while not done.is_set():
        app.processEvents(); time.sleep(0.0005)
    for _ in range(50):
        app.processEvents(); time.sleep(0.002)
    probe.stop(); s = probe.stats()
    print(f"{tag} {r:3d} NM  render ms median {statistics.median(times):6.0f}  min {min(times):6.0f}  max {max(times):6.0f} | "
          f"probe max gap {s['max_ms']:5.1f} ms  p95 {s['p95_ms']:5.1f}  over50 {s['over_count']}  starved {s['starved_ms']:.0f}/{s['window_ms']:.0f} ms", flush=True)
