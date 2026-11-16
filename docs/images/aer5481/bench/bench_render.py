"""AER-5481 bench look: render DataStatus offscreen with the bench's real
status.json (copied, with a pending panel_change injected) and real fonts."""
import json, os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.expanduser("~/pyEfis/src"))
from PyQt6.QtWidgets import QApplication, QWidget
app = QApplication([])
from pyefis.instruments import data_status
live = json.load(open(os.path.expanduser("~/.makerplane/pyefis/status.json")))
print("packs", len(live.get("packs", [])), "panel_change", live.get("panel_change"))
pend = dict(live, panel_change={"pending": True, "config_hash": "9f2c4b7a01de" + "0" * 52,
            "config_version": 8, "changed": "2026-11-14T01:40:00Z", "trigger": "boot",
            "acknowledged": None})
out = os.path.expanduser("~/bench-scratch/aer5481")
for name, doc in (("pending", pend), ("live", live)):
    for w_, h_ in ((800, 480), (1024, 600), (1920, 1080)):
        p = tempfile.mktemp(suffix=".json"); open(p, "w").write(json.dumps(doc))
        host = QWidget(); host.setStyleSheet("background:#000000;"); host.resize(w_, h_)
        w = data_status.DataStatus(host, status_path=p); w.resize(w_, h_)
        host.show(); app.processEvents()
        host.grab().save(f"{out}/{name}_{w_}x{h_}.png")
        if name == "pending":
            r = w._banner_rect
            rows = len(doc["packs"])
            last = r.bottom() + w.row_h * 0.6 + rows * w.row_h
            print(f"{w_}x{h_}: banner {r.top():.0f}-{r.bottom():.0f}, last pack row ends {last:.0f}, "
                  f"message line at {h_*0.74:.0f}, buttons at {w.btn_continue.y()}")
