"""Regenerate the About/System screen evidence images (AER-4341, BACKLOG L4).

    QT_QPA_PLATFORM=offscreen PYTHONPATH=src python3 docs/images/about/render.py

On a host with no system fonts, set RENDER_FONT_DIR to a directory of .ttf
files (these images used matplotlib's bundled DejaVu set).

Renders the bundled About screen and the Data Status button row at 1024x600
against a sample status.json: one pack carrying the L1 notice, one published
before the field existed.
"""
import json, os, sys, tempfile
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
path = os.path.join(tempfile.mkdtemp(), "status.json")
with open(path, "w") as f:
    json.dump(status, f)
from PyQt6.QtWidgets import QWidget
for name, cls in (("about_1024x600.png", about.AboutSystem),
                  ("datastatus_1024x600.png", data_status.DataStatus)):
    # In pyEfis the screen behind an instrument is black; a bare top-level
    # widget would paint the platform's light default instead.
    host = QWidget()
    host.setStyleSheet("background-color: black;")
    host.resize(1024, 600)
    w = cls(host, status_path=path)
    w.resize(1024, 600)
    host.show()
    app.processEvents()
    host.grab().save(os.path.join(out, name))
    print("wrote", name)
