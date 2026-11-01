"""Regenerate the About/System screen evidence images (AER-4341, BACKLOG L4).

    QT_QPA_PLATFORM=offscreen PYTHONPATH=src python3 docs/images/about/render.py

On a host with no system fonts, set RENDER_FONT_DIR to a directory of .ttf
files (these images used matplotlib's bundled DejaVu set).

Renders the bundled About screen and the Data Status button row at 1024x600
against a sample status.json: one pack carrying the L1 notice, one published
before the field existed. about_history_1024x600.png adds a sample L2
acknowledgment log (a terminal accept, then a bench auto-accept) and scrolls
the About screen to its history section.
"""
import hashlib, json, os, sys, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication
from pyefis.instruments import about, data_status

app = QApplication(sys.argv)
fdir = os.environ.get("RENDER_FONT_DIR")
if fdir:
    from PyQt6.QtGui import QFontDatabase
    for fn in sorted(os.listdir(fdir)):
        if fn.endswith(".ttf"):
            QFontDatabase.addApplicationFont(os.path.join(fdir, fn))
out = os.path.dirname(os.path.abspath(__file__))
status = {"ok": True, "generated": "2026-10-30T00:00:00Z", "worst": "none",
          "packs": [
              {"id": "navaids-conus", "name": "navaids-conus", "kind": "navaids",
               "status": "current", "severity": "none", "cycle": "2612",
               "detail": "2612",
               "notice": ("Experimental / Amateur-Built use only. Not certified. "
                          "This data is provided as-is with no warranty and any "
                          "use of the data is at your own risk.")},
              {"id": "water-na", "name": "water-na", "kind": "water",
               "status": "current", "severity": "none", "cycle": "2026q2r6",
               "detail": "2026q2r6", "notice": ""},
          ]}
tmp = tempfile.mkdtemp()
path = os.path.join(tmp, "status.json")
with open(path, "w") as f:
    json.dump(status, f)
# Schema 1, as makerplane-data docs/install_acknowledgment.md defines it.
sha = hashlib.sha256(about.NOTICE.encode("utf-8")).hexdigest()
acks = [
    {"schema": 1, "event": "accept", "timestamp": "2026-10-31T14:05:09Z",
     "notice_id": "pyefis-software-2026-10-30", "notice_sha256": sha,
     "notice_text": about.NOTICE,
     "software": {"pyefis-data": "0.4.0", "pyefis": "2.2.1"}, "packs": {},
     "user": "pi", "host": "pyefis", "via": "tty", "trigger": "pyefis-install"},
    {"schema": 1, "event": "accept", "timestamp": "2026-11-01T09:30:00Z",
     "notice_id": "pyefis-software-2026-10-30", "notice_sha256": sha,
     "notice_text": about.NOTICE, "software": {"pyefis-data": "0.4.1"},
     "packs": {"navaids-conus": "2612", "water-na": "2026q2r6"},
     "user": "pi", "host": "pyefis", "via": "bench", "trigger": "update"},
]
ack_path = os.path.join(tmp, "acknowledgments.jsonl")
with open(ack_path, "w") as f:
    f.writelines(json.dumps(r) + "\n" for r in acks)
from PyQt6.QtWidgets import QWidget
for name, cls, kw in (
        ("about_1024x600.png", about.AboutSystem, {"ack_path": ack_path}),
        ("about_history_1024x600.png", about.AboutSystem,
         {"ack_path": ack_path}),
        ("datastatus_1024x600.png", data_status.DataStatus, {})):
    # In pyEfis the screen behind an instrument is black; a bare top-level
    # widget would paint the platform's light default instead.
    host = QWidget()
    host.setStyleSheet("background-color: black;")
    host.resize(1024, 600)
    w = cls(host, status_path=path, **kw)
    w.resize(1024, 600)
    host.show()
    app.processEvents()
    if name == "about_history_1024x600.png":
        app.processEvents()   # let the wrapped labels settle their heights
        sb = w.area.verticalScrollBar()
        sb.setValue(sb.maximum())
        app.processEvents()
    host.grab().save(os.path.join(out, name))
    print("wrote", name)
