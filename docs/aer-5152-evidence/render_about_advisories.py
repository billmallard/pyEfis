"""Render the About/System screen with each advisory state (AER-5152).

    QT_QPA_PLATFORM=offscreen PYTHONPATH=src:tools \
        python3 docs/aer-5152-evidence/render_about_advisories.py docs/aer-5152-evidence

Writes one PNG per case at 1024 x 600 (the Pi 5 panel) plus a provenance
sidecar for each. The status.json documents are built here in the shape of
makerplane-data docs/advisories.md; pyefis.__version__ is pinned to 2.2.1 so
the pyEfis target is settled the same way on every run.
"""

import json
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

import pyefis
from pyefis.instruments import about
from evidence_sidecar import write_sidecar

W, H = 1024, 600

PACKS = [
    {"id": "navaids-conus", "name": "navaids-conus", "kind": "navaids",
     "status": "current", "severity": "none", "cycle": "2612",
     "notice": "Experimental / Amateur-Built use only. Not certified. This data "
               "is provided as-is with no warranty and any use of the data is "
               "at your own risk."},
    {"id": "obstacles-conus", "name": "obstacles-conus", "kind": "obstacles",
     "status": "current", "severity": "none", "cycle": "260611", "notice": ""},
]

ON = {"enabled": True, "sequence": 3, "generated": "2026-12-01T00:00:00Z",
      "checked": "2026-12-02T09:15:03Z", "error": None}

WARNING = {
    "id": "MPA-2026-001", "issued": "2026-12-01", "severity": "warning",
    "title": "Altitude tape can freeze after a fix-gateway restart",
    "description": "After fix-gateway restarts in flight, the altitude tape keeps "
                   "showing the last value and raises no failure flag.",
    "action": "Update pyEfis to 2.2.2 before the next flight.",
    # As the daily timer writes it: the updater cannot see pyEfis's version.
    "applies": "unknown",
    "affects": [{"software": "pyefis", "introduced": "2.2.0", "fixed": "2.2.2",
                 "result": "unknown"}],
}

CAUTION = {
    "id": "MPA-2026-002", "issued": "2026-12-01", "severity": "caution",
    "title": "Two towers near KSBA are missing from obstacle cycle 260611",
    "description": "Two 400 ft towers east of the field were dropped from this cycle.",
    "action": "Install obstacle cycle 260709 when it is published.",
    "applies": "yes",
    "affects": [{"pack": "obstacles-conus", "cycles": ["260611"], "result": "yes"}],
}

CASES = {
    "empty": dict(ON, active=[]),
    "applicable": dict(ON, active=[WARNING, CAUTION]),
    "off": {"enabled": False},
}


def main(out_dir):
    pyefis.__version__ = "2.2.1"
    app = QApplication.instance() or QApplication([])
    os.environ["MAKERPLANE_ACK_LOG"] = os.path.join(tempfile.mkdtemp(), "none.jsonl")
    for name, block in CASES.items():
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"ok": True, "packs": PACKS, "advisories": block}, f)
        w = about.AboutSystem(status_path=f.name, font_family="DejaVu Sans")
        w.resize(W, H)
        w.show()
        app.processEvents()
        w._apply_fonts()
        app.processEvents()
        out = os.path.join(out_dir, f"about_{name}.png")
        w.grab().save(out)
        write_sidecar(out, extra={"case": name, "pyefis_version_pinned": "2.2.1"})
        print(out)
        w.close()
        os.unlink(f.name)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
