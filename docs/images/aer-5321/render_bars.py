"""Render the EMS screen's first bar block from <root> to <out.png> (AER-5321).

Usage: QT_QPA_PLATFORM=offscreen python3 render_bars.py <repo-root> <out.png>
"""
import os, sys, yaml
root, out = sys.argv[1], sys.argv[2]
sys.path[:0] = [os.path.join(root, "tools"), root, os.path.join(root, "src")]
import render_instrument as ri
cfg = os.path.join(root, "src/pyefis/config")
prefs = yaml.safe_load(open(os.path.join(cfg, "preferences.yaml")))
scr = yaml.safe_load(open(os.path.join(cfg, "screens/ems.yaml")))["EMS"]
block = next(i for i in scr["instruments"] if i.get("type") == "ganged_vertical_bar_gauge")
inst = {k: v for k, v in block.items() if k not in ("disabled", "row", "column", "span")}
inst |= {"row": 0, "column": 0, "span": {"rows": 10, "columns": 10}}
for g in inst["groups"]:
    for e in g["instruments"]:
        e["options"] = dict(e.get("options") or {}) | prefs["gauges"].get(e.pop("preferences", None), {})
import time
from PyQt6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv[:1])
ri._load_fonts(); ri._setup_fix()
import pyefis.hmi as hmi
if hmi.actions is None: hmi.initialize({})
for k, v in {"MAP1": 24.1, "CAT": 21, "TACH1": 2350, "THR1": 65}.items():
    it = ri.fix.db.get_item(k); ri.fix.db.set_value(k, v); it.bad = it.fail = it.old = False
W, H = 640, 300
config = {"main": {"screenColor": "(0,0,0)", "screenWidth": W, "screenHeight": H, "nodeID": 1},
          "screens": {"TEST": {"module": "pyefis.screens.screenbuilder", "title": "render",
                               "layout": {"rows": 10, "columns": 10}, "instruments": [inst]}}}
from tests.screenshots import gui
gui.initialize(config, root, {}, fullscreen=False)
screen = gui.mainWindow.scr.object
screen.resize(W, H)
for _ in range(40):
    app.processEvents(); time.sleep(0.01)
print(screen.grab().save(out), out)
