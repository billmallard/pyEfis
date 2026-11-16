"""AER-5481 / AER-5616: Data Status with the terrain regions collapsed,
rendered offscreen on the bench from a copy of its live status.json, with a
pending panel change (the live one, if any, else a synthetic one)."""
import json, os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.expanduser("~/bench-scratch/aer5481/collapse/src"))
from PyQt6.QtWidgets import QApplication, QWidget
app = QApplication([])
from pyefis.instruments import data_status
live = json.load(open(os.path.expanduser("~/.makerplane/pyefis/status.json")))
print("packs", len(live["packs"]), "panel_change", live.get("panel_change"))
if not (live.get("panel_change") or {}).get("pending"):
    live["panel_change"] = {"pending": True, "config_hash": "9f2c4b7a01de" + "0" * 52,
                            "config_version": 8, "changed": "2026-11-14T01:40:00Z",
                            "trigger": "boot"}
out = os.path.expanduser("~/bench-scratch/aer5481")
for name, size, msg in (("collapsed_800x480", (800, 480), ""),
                        ("collapsed_800x480_message", (800, 480), "Recording acknowledgement…"),
                        ("collapsed_1920x1080", (1920, 1080), ""),
                        ("collapsed_800x480_region_expired", (800, 480), "")):
    if name.endswith("region_expired"):
        for pk in live["packs"]:
            if pk.get("id") == "terrain-us-west":
                pk.update(status="EXPIRED", severity="amber", detail="2023 expired")
    p = tempfile.mktemp(suffix=".json"); open(p, "w").write(json.dumps(live))
    host = QWidget(); host.setStyleSheet("background:#000000;"); host.resize(*size)
    w = data_status.DataStatus(host, status_path=p); w.resize(*size)
    w.message = msg
    host.show(); app.processEvents()
    host.grab().save(f"{out}/{name}.png")
    print(name, "list", w._pack_span, "buttons", w.btn_continue.y())
