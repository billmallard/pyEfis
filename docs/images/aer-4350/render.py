"""Render the picker's software-notice screen (AER-4350) offscreen.

    QT_QPA_PLATFORM=offscreen PYTHONPATH=src python docs/images/aer-4350/render.py [FONT_DIR]

FONT_DIR (optional): a directory of .ttf files to register, for a box with
no system fonts. If "DejaVu Sans Condensed" (the instrument default) is not
available after that, "DejaVu Sans" is used.

Drives the real DataStatus flow: picker -> Install -> the updater's refusal
(a notice_required line + exit 3) -> the notice screen. The updater is
stubbed at DataStatus._run; the event line is the exact one pyefis-data
emits."""
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtGui import QFontDatabase
from PyQt6.QtWidgets import QApplication

from pyefis.instruments import data_status

OUT = Path(__file__).parent
NOTICE = ("pyEfis is experimental software for Experimental / Amateur-Built "
          "aircraft. It is not certified. It is provided as-is with no warranty, "
          "and any use of it is at your own risk.")
CATALOG = {"ok": True, "storage": {"root": "/data/makerplane-data",
                                   "free_bytes": 50 << 30, "total_bytes": 100 << 30},
           "packs": [{"id": "airports-conus", "name": "Airports & Runways",
                      "kind": "airports", "bytes": 4 << 20, "tracked": True}]}

app = QApplication.instance() or QApplication(sys.argv[:1])
if len(sys.argv) > 1:
    for f in sorted(Path(sys.argv[1]).glob("*.ttf")):
        QFontDatabase.addApplicationFont(str(f))
FAMILY = "DejaVu Sans Condensed"
if FAMILY not in QFontDatabase.families():
    FAMILY = "DejaVu Sans"
print("font:", FAMILY)
for w_px, h_px in ((800, 480), (1024, 600)):
    w = data_status.DataStatus(status_path="/nonexistent", font_family=FAMILY)
    calls = []
    w._run = lambda args, on_finish, on_line=None: calls.append((args, on_finish))
    w.resize(w_px, h_px)
    w.show()
    w._on_update()
    calls[0][1](0, json.dumps({"network": True, "usb": []}))
    calls[1][1](0, json.dumps(CATALOG))
    w._install_selected(w.picker.selected_ids())
    w._on_progress_line(json.dumps({"event": "notice_required", "notice": NOTICE,
                                    "notice_id": "pyefis-software-2026-10-30"}))
    calls[2][1](data_status.NOTICE_RC, "")
    app.processEvents()
    assert w.mode == "notice"
    w.grab().save(str(OUT / f"notice_{w_px}x{h_px}.png"))
    w.hide()
print("ok")
