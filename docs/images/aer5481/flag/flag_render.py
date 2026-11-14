"""AER-5481: the PFD DATA flag at the bench PFD's size (18x5 cells of a
200x110 grid on 1920x1080 = 173x49), from the bench's live status.json copy,
with and without a pending panel change."""
import json, os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.expanduser("~/bench-scratch/aer5481/flag/src"))
from PyQt6.QtWidgets import QApplication, QWidget
app = QApplication([])
from pyefis.instruments import data_status
live = json.load(open(os.path.expanduser("~/.makerplane/pyefis/status.json")))
live["panel_change"] = dict(live.get("panel_change") or {}, pending=False)
pend = dict(live, panel_change={"pending": True, "config_hash": "9f2c4b7a01de" + "0" * 52,
            "config_version": 8, "changed": "2026-11-14T01:40:00Z", "trigger": "boot"})
out = os.path.expanduser("~/bench-scratch/aer5481")
for name, doc in (("flag_pending", pend), ("flag_no_change", live)):
    p = tempfile.mktemp(suffix=".json"); open(p, "w").write(json.dumps(doc))
    host = QWidget(); host.setStyleSheet("background:#3A6EA5;"); host.resize(233, 89)
    a = data_status.DataAnnunciation(host, status_path=p); a.setGeometry(30, 20, 173, 49)
    host.show(); app.processEvents()
    host.grab().scaled(466, 178).save(f"{out}/{name}.png")
    print(name, data_status.annunciation_severity(a.status))
