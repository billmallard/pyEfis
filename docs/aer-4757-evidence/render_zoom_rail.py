#!/usr/bin/env python3
#  SPDX-License-Identifier: GPL-2.0-or-later
"""Evidence for the moving map's one-finger zoom rail (G22,
billmallard/pyEfis#205).

The real ``MovingMap`` widget, real layer workers and real data packs, with
the in-memory mock FIX database from render_instrument.py. Each scene waits
until every enabled layer reports ``is_settled`` before it grabs. The map is
QPainter-drawn (a plain QWidget, no GL), so an offscreen grab is the same
pixels the panel draws.

Run it where the data and the fonts are (the Beelink, under
``~/bench-scratch/<issue>``)::

    QT_QPA_PLATFORM=offscreen ~/pyefis-venv/bin/python \\
        docs/aer-4757-evidence/render_zoom_rail.py OUTDIR [scene ...]

Writes ``<OUTDIR>/<scene>.png`` (plus a ``.json`` sidecar) and
``<OUTDIR>/rail_10nm_x3.png``, the rail region of ``rail_10nm`` enlarged 3x
nearest-neighbour.
"""

import hashlib
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (_REPO, os.path.join(_REPO, "src"), os.path.join(_REPO, "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import render_instrument as ri  # noqa: E402  (mock FIX swap happens here)

from PyQt6.QtCore import QRect, Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

# The bench's map pane: the Map tab of the PFD screen's tab_section on a
# 1920 x 1080 panel is about 650 x 1000 px.
W, H = 650, 1000
DATA = "/data/makerplane-data"
# Aspen: busy relief, the hard case for reading a thin rail over terrain.
LAT, LON, TRACK, ALT = 39.2232, -106.8688, 150.0, 12500.0

SCENES = {
    "no_rail": {"zoom_rail": False},
    "rail_10nm": {"zoom_rail": True},
    "rail_10nm_touched": {"zoom_rail": True, "_rail_active": "track"},
    "rail_between_rungs": {"zoom_rail": True, "range_nm": 13.7},
    "rail_right": {"zoom_rail": True, "zoom_rail_side": "right"},
    "rail_bench_ladder": {"zoom_rail": True,
                          "range_ladder": "2,10,50,200,500,2000"},
}


def _paths():
    j = lambda *p: os.path.join(DATA, *p)  # noqa: E731
    return {
        "tile_path": j("terrain", "tiles"),
        "water_db_path": j("water", "current", "water.sqlite"),
        "highway_db_path": j("highways", "current", "highways.sqlite"),
        "nasr_db_path": j("navdata", "current", "airports.sqlite"),
        "navaid_db_path": j("navaids", "current", "navaids.sqlite"),
    }


def render(name, out_dir, app):
    from pyavtools import fix
    from pyefis.instruments.map import MovingMap

    for key, lo, hi in (("LAT", -90.0, 90.0), ("LONG", -180.0, 180.0),
                        ("TRACKM", 0.0, 360.0), ("ALT", -1000.0, 60000.0)):
        fix.db.define_item(key, key, "float", lo, hi, "", 50000, "")
    for key, val in (("LAT", LAT), ("LONG", LON), ("TRACKM", TRACK),
                     ("ALT", ALT)):
        it = fix.db.get_item(key)
        fix.db.set_value(key, val)
        it.bad = it.fail = it.old = False

    w = MovingMap(font_family="B612")
    for k, v in _paths().items():
        if os.path.exists(v):
            setattr(w, k, v)
    w.orientation = "north_up"
    w.range_nm = 10.0
    for k, v in SCENES[name].items():
        setattr(w, k, v)
    w.resize(W, H)
    w.show()
    deadline = time.monotonic() + 60.0
    settled = False
    while time.monotonic() < deadline:
        app.processEvents()
        w.repaint()
        if w._layers_built:
            x = w._transform()
            if all(not lay.enabled or lay.is_settled(x) for lay in w._layers):
                settled = True
                break
        time.sleep(0.05)
    for _ in range(2):
        w.repaint()
        app.processEvents()
    img = w.grab()
    path = os.path.join(out_dir, name + ".png")
    img.save(path)
    _sidecar(path)
    if name == "rail_10nm":
        g = w.zoom_rail_geometry()
        r = g["claim"].toAlignedRect().adjusted(0, -12, 140, 12)
        crop = img.copy(r.intersected(QRect(0, 0, W, H)))
        big = crop.scaled(crop.width() * 3, crop.height() * 3,
                          Qt.AspectRatioMode.IgnoreAspectRatio,
                          Qt.TransformationMode.FastTransformation)
        zpath = os.path.join(out_dir, "rail_10nm_x3.png")
        big.save(zpath)
        _sidecar(zpath)
        print("  rail column %.0f px wide (%.2f px/mm)"
              % (g["touch"], w._px_per_mm()))
    w.close()
    with open(path, "rb") as fh:
        digest = hashlib.sha256(fh.read()).hexdigest()
    print("%s  %s%s" % (digest, path, "" if settled else "  (NOT SETTLED)"))
    return settled


def _sidecar(path):
    try:
        from evidence_sidecar import write_sidecar
        write_sidecar(path)
    except ImportError:
        pass


def main(argv):
    out = argv[1]
    names = argv[2:] or list(SCENES)
    os.makedirs(out, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    ri._load_fonts()
    ri._setup_fix()
    ok = all([render(n, out, app) for n in names])
    sys.stdout.flush()
    # Skip interpreter teardown: the layers' daemon workers and the mock
    # FIX scheduler's timers do not shut down cleanly at exit.
    os._exit(0 if ok else 3)


if __name__ == "__main__":
    main(sys.argv)
