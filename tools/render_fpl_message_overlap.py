#!/usr/bin/env python3
#  SPDX-License-Identifier: GPL-2.0-or-later
"""Renders of the FPL page header with a message up (AER-6156).

Draws the real ``flight_plan`` widget with an active plan, so the header
carries the engine-state badge and the remaining distance/time readout on
its top line and the approach state / LOI on its second, then puts each
message on ``_message`` and grabs it. Pane sizes: the Beelink's Flight Plan
tab (649 x 993 px, ``font_percent`` 0.8, the geometry
``tests/instruments/flight_plan/test_row_geometry.py`` pins), the 800 x 480
render AER-6156 was filed from, and a short 649 x 400 pane.

For each case it prints the message's ink box and the number of header
pixels the message ink lands on: pixels that are inked (not black) with no
message up AND change when the message is drawn. That count is the
overprint, measured in pixels rather than in text boxes.

Writes, to OUTDIR: ``<W>x<H>_<n>.png`` per case and ``strip_<W>x<H>.png``
(the header band of every case, stacked, nearest-neighbour 2x).

    QT_QPA_PLATFORM=offscreen PYTHONPATH=src python3 \\
        tools/render_fpl_message_overlap.py OUTDIR
"""

import argparse
import os
import sys
import time
from types import SimpleNamespace

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "src"))

from tools import render_instrument as ri  # noqa: E402,F401  (installs the mock FIX db)

import pyavtools.fix as fix  # noqa: E402
from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from pyefis.flightplan import fixbridge  # noqa: E402
from pyefis.flightplan import model as fp_model  # noqa: E402

SIZES = [(649, 993), (800, 480), (649, 400)]
BEELINK = SimpleNamespace(screenWidth=1920, screenHeight=1080, screenDiagonalInches=21.5)

_BOUNDS = {"float": (-1e9, 1e9), "int": (-1_000_000, 1_000_000),
           "bool": (None, None), "str": (None, None)}
_ENGINE = {
    "FPLSTATE": "int", "FPLACTLEG": "int", "FPLPHASE": "str", "FPLAPR": "int",
    "FPLINTEG": "bool", "CDISCALE": "float", "FPLCRS": "float", "FPLXTK": "float",
    "FPLCDI": "float", "FPLTF": "int", "FPLFRLAT": "float", "FPLFRLON": "float",
    "WPNAME": "str", "WPLAT": "float", "WPLON": "float", "WPFROM": "str",
    "WPNEXT": "str", "WPDIS": "float", "WPETE": "int", "FPLREMDIS": "float",
    "FPLREMETE": "int", "FPLALERT": "bool", "GPSSRC": "int",
    "FPLACTSEG": "int", "FPLSEGREM": "float", "MAGVAR": "float",
}
_BLANK = {"int": 0, "float": 0.0, "bool": False, "str": ""}

# (FPLSTATE, FPLAPR, FPLINTEG, message). The messages are ones the page sets
# today, plus the longest OBS refusal from pyEfis #531, which #522 shows on
# this line. FPLAPR 2 is LNAV; FPLINTEG False raises LOI.
CASES = [
    (1, 0, True, "STORED"),
    (2, 0, True, "NO AIRWAYS AT GVO"),
    (1, 0, True, "ROUTE FULL -- V27 NEEDS 3 MORE SLOTS"),
    (1, 2, False, "OBS NOT AVAILABLE: NO ACTIVE WAYPOINT"),
]


def _define(key, dtype, value):
    mn, mx = _BOUNDS[dtype]
    fix.db.define_item(key, key, dtype, mn, mx, "", 0, "")
    fix.db.set_value(key, value)
    item = fix.db.get_item(key)
    item.bad = item.fail = False


def _settle(app, n=20):
    for _ in range(n):
        app.processEvents()
        time.sleep(0.01)


def _grab(app, w):
    w.update()
    _settle(app)
    return w.grab().toImage().convertToFormat(QImage.Format.Format_RGB32)


def _overprint(base, withmsg, band_h):
    """(pixels where the message changes an inked header pixel, message ink
    box) inside the top *band_h* rows."""
    hits = 0
    xs, ys = [], []
    for y in range(band_h):
        for x in range(base.width()):
            b, m = base.pixel(x, y), withmsg.pixel(x, y)
            if b != m:
                xs.append(x)
                ys.append(y)
                if b & 0xFFFFFF:
                    hits += 1
    box = (min(xs), max(xs), min(ys), max(ys)) if xs else None
    return hits, box


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("outdir")
    args = ap.parse_args(argv)
    os.makedirs(args.outdir, exist_ok=True)

    app = QApplication.instance() or QApplication(sys.argv)
    fix.initialize({"main": {"FixServer": "localhost", "FixPort": "3490"}})
    for key, dtype, blank in fixbridge.route_key_specs():
        _define(key, dtype, blank)
    for key, dtype in _ENGINE.items():
        _define(key, dtype, _BLANK[dtype])

    from pyefis.instruments import flight_plan
    w = flight_plan.FlightPlan(None, font_percent=0.8)   # the bench's option
    w.toast_ms = 10 ** 8
    w.parent = SimpleNamespace(parent=BEELINK)
    w._plan = fp_model.FlightPlan(waypoints=[
        fp_model.Waypoint(id="KSBA", type="airport", lat=34.42621, lon=-119.84037),
        fp_model.Waypoint(id="GVO", type="vor", lat=34.53131944, lon=-120.09108889),
        fp_model.Waypoint(id="KSMX", type="airport", lat=34.89892, lon=-120.45758),
    ])
    w._commit()
    fix.db.set_value("FPLACTLEG", 2)
    fix.db.set_value("FPLREMDIS", 48.0)
    fix.db.set_value("FPLREMETE", 1440)

    for pw, ph in SIZES:
        w.resize(pw, ph)
        _settle(app)
        header_h = int(w._chrome_h(ph, 2.0, 0.26))
        band = max(header_h, int(ph * 0.08)) + 8
        print(f"pane {pw}x{ph}: header 0-{header_h} px (top line 2-{header_h * 0.5:.0f}),"
              f" message band {ph * 0.02:.0f}-{ph * 0.08:.0f} px")
        crops = []
        for n, (state, apr, integ, msg) in enumerate(CASES):
            fix.db.set_value("FPLSTATE", state)
            fix.db.set_value("FPLAPR", apr)
            fix.db.set_value("FPLINTEG", integ)
            w._sync_engine_from_bridge()
            w._message = ""
            base = _grab(app, w)
            w._message = msg
            img = _grab(app, w)
            img.save(os.path.join(args.outdir, f"{pw}x{ph}_{n}.png"))
            hits, box = _overprint(base, img, band)
            boxs = "-" if box is None else f"x {box[0]}-{box[1]} y {box[2]}-{box[3]}"
            print(f"  {n} {flight_plan._STATE_BADGES[state]:6s} {msg!r:40s}"
                  f" ink {boxs:22s} overprinted header px {hits}")
            crops.append(img.copy(0, 0, pw, band))
        strip = QImage(pw, (band + 4) * len(crops), QImage.Format.Format_RGB32)
        strip.fill(QColor("#404040"))
        p = QPainter(strip)
        for n, img in enumerate(crops):
            p.drawImage(0, n * (band + 4), img)
        p.end()
        strip.scaled(pw * 2, strip.height() * 2,
                     transformMode=Qt.TransformationMode.FastTransformation
                     ).save(os.path.join(args.outdir, f"strip_{pw}x{ph}.png"))
    print("wrote", args.outdir)


if __name__ == "__main__":
    main()
