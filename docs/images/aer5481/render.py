"""Render the Data Status screen with and without a pending panel change
(AER-5481, CERT17). Offscreen; writes PNGs beside this file.

    QT_QPA_PLATFORM=offscreen PYTHONPATH=src python3 docs/images/aer5481/render.py
"""
import json
import os
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication, QWidget  # noqa: E402

app = QApplication([])
from pyefis.instruments import data_status  # noqa: E402

OUT = Path(__file__).parent
PACKS = [
    {"id": "airports-conus", "name": "Airports & Runways", "status": "current",
     "severity": "none", "detail": "2611"},
    {"id": "obstacles-conus", "name": "Obstacles", "status": "current",
     "severity": "none", "detail": "261101"},
    {"id": "terrain-us-west", "name": "Terrain us-west", "status": "current",
     "severity": "none", "detail": "glo30 2026.1"},
    {"id": "water-na", "name": "Water", "status": "EXPIRED", "severity": "amber",
     "detail": "2026.04 expired 2026-10-31"},
]
PENDING = {"pending": True, "config_hash": "9f2c4b7a01de" + "0" * 52,
           "config_version": 8, "changed": "2026-11-12T14:03:22Z",
           "trigger": "boot", "acknowledged": None}


def render(name, doc, size=(800, 480)):
    path = Path(tempfile.mkdtemp()) / "status.json"
    path.write_text(json.dumps(doc))
    host = QWidget()                      # the screen's black background
    host.setStyleSheet("background:#000000;")
    host.resize(*size)
    w = data_status.DataStatus(host, status_path=str(path))
    w.resize(*size)
    host.show()
    app.processEvents()
    host.grab().save(str(OUT / f"{name}.png"))


base = {"ok": True, "generated": "2026-11-12T00:00:00Z", "packs": PACKS}
render("pending_800x480", dict(base, panel_change=PENDING))
render("pending_1024x600", dict(base, panel_change=PENDING), (1024, 600))
render("acknowledged_800x480", dict(base, panel_change=dict(PENDING, pending=False)))
