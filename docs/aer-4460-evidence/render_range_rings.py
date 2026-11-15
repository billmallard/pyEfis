#!/usr/bin/env python3
#  SPDX-License-Identifier: GPL-2.0-or-later
"""Evidence for the configurable map range rings (G13, billmallard/pyEfis#136).

Renders the moving map at 800 x 480 with no data packs (so the only layer that
paints anything is range rings, plus ownship and the status chip) once per
scene, writing ``<outdir>/<scene>.png``. The map is QPainter-drawn (a plain
QWidget, no GL), so an offscreen grab is the same pixels the panel draws.

    QT_QPA_PLATFORM=offscreen PYTHONPATH=src python3 \\
        docs/aer-4460-evidence/render_range_rings.py OUTDIR [scene ...]

Run on a checkout without the G13 change and only the ``default`` scene is
meaningful (the options do not exist there and are ignored).
"""

import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "src"))
sys.path.insert(0, os.path.join(_REPO, "tools"))

W, H = 800, 480

SCENES = {
    "default": {},
    "four_rings_label_right": {
        "range_ring_fractions": "0.25,0.5,0.75,1",
        "range_ring_label_angle": 90,
    },
    "labels_off": {"range_ring_labels": False},
    "styled": {
        "range_ring_fractions": "0.5,1,1.5",
        "range_ring_label_angle": 315,
        "range_ring_color": "#00ffff",
        "range_ring_opacity": 80,
        "range_ring_width": 2.5,
        "range_ring_label_size": 16,
    },
}


def _mock_fix():
    import tests.mock_db.client
    import tests.mock_db.scheduler
    sys.modules["pyavtools.fix.client"] = tests.mock_db.client
    sys.modules["pyavtools.scheduler"] = tests.mock_db.scheduler
    import pyavtools.fix as fix
    fix.initialize({"main": {"FixServer": "localhost", "FixPort": "3490"}})
    for key, lo, hi, val in (("LAT", -90, 90, 34.4275), ("LONG", -180, 180, -119.8546),
                             ("TRACKM", 0, 360, 87.0), ("ALT", -2000, 60000, 4500.0)):
        fix.db.define_item(key, key, "float", lo, hi, "", 50000, "")
        fix.db.set_value(key, val)
        item = fix.db.get_item(key)
        item.old = item.bad = item.fail = False


def main(argv):
    out = argv[1]
    names = argv[2:] or list(SCENES)
    os.makedirs(out, exist_ok=True)
    _mock_fix()
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from pyefis.instruments import map as moving_map
    for name in names:
        w = moving_map.MovingMap()
        w.range_nm = 10.0
        w.ownship_position = 30
        for k, v in SCENES[name].items():
            setattr(w, k, v)
        w.resize(W, H)
        w.show()
        app.processEvents()
        w.grab()                     # first paint builds the layers
        app.processEvents()
        path = os.path.join(out, name + ".png")
        w.grab().save(path)
        try:
            from evidence_sidecar import write_sidecar
            write_sidecar(path)
        except ImportError:          # a pre-sidecar checkout (the baseline run)
            pass
        print(path)
        w.close()


if __name__ == "__main__":
    main(sys.argv)
