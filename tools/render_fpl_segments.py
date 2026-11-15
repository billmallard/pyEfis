#!/usr/bin/env python3
#  SPDX-License-Identifier: GPL-2.0-or-later
"""Renders of the RS3 FPL page (route segments, pyEfis #306, AER-3792).

Draws the real ``flight_plan`` widget -- its own paint path, not a drawing of
it -- at the Beelink's Flight Plan tab size (649 x 993 px on a 21.5 in
1920 x 1080 panel, the geometry ``tests/instruments/flight_plan/
test_row_geometry.py`` pins), with the golden route "KSBA GVO V27 AVOLS KSMX"
expanded from a real procedures pack and published through the real FIX
bridge into the in-memory mock FIX db.

Writes, to OUTDIR:

1. ``1_summary.png`` -- active leg KSBA -> GVO; V27 is one segment row.
2. ``2_in_airway.png`` -- active leg KWANG -> DEANO; V27 opens into its
   nested working rows, the rest folded.
3. ``3_segment_menu.png`` -- a tap on the V27 row.
4. ``4_show_fixes.png`` -- Show Fixes from that menu.
5. ``sheet.png`` -- all four side by side at 1:1.

    QT_QPA_PLATFORM=offscreen PYTHONPATH=src python3 tools/render_fpl_segments.py \\
        OUTDIR --procedures /data/makerplane-data/procedures/current/procedures.sqlite

``--magvar`` sets MAGVAR (positive west; default -11.6, about Santa Barbara's
11.6 E) so DTK shows magnetic, as on the aircraft.
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
from PyQt6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from pyefis.flightplan import airways, fixbridge  # noqa: E402
from pyefis.flightplan import model as fp_model  # noqa: E402

PANE_W, PANE_H = 649, 993
BEELINK = SimpleNamespace(screenWidth=1920, screenHeight=1080, screenDiagonalInches=21.5)

KSBA = fp_model.Waypoint(id="KSBA", type="airport", lat=34.42621, lon=-119.84037)
GVO = fp_model.Waypoint(id="GVO", type="vor", lat=34.53131944, lon=-120.09108889)
KSMX = fp_model.Waypoint(id="KSMX", type="airport", lat=34.89892, lon=-120.45758)

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


def _define(key, dtype, value):
    mn, mx = _BOUNDS[dtype]
    fix.db.define_item(key, key, dtype, mn, mx, "", 0, "")
    fix.db.set_value(key, value)
    item = fix.db.get_item(key)
    item.bad = item.fail = False


def _set(key, value):
    fix.db.set_value(key, value)


def _settle(app, n=20):
    for _ in range(n):
        app.processEvents()
        time.sleep(0.01)


def _grab(app, w, path):
    w.update()
    _settle(app)
    img = w.grab().toImage()
    img.save(path)
    return img


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("outdir")
    ap.add_argument("--procedures", required=True, help="procedures.sqlite (airways)")
    ap.add_argument("--magvar", type=float, default=-11.6)
    args = ap.parse_args(argv)
    os.makedirs(args.outdir, exist_ok=True)

    app = QApplication.instance() or QApplication(sys.argv)
    fix.initialize({"main": {"FixServer": "localhost", "FixPort": "3490"}})
    for key, dtype, blank in fixbridge.route_key_specs():
        _define(key, dtype, blank)
    for key, dtype in _ENGINE.items():
        _define(key, dtype, _BLANK[dtype])
    _set("MAGVAR", args.magvar)
    _set("FPLINTEG", True)

    graph = airways.AirwayGraph(args.procedures)
    if not graph.ready:
        sys.exit(f"procedures pack not readable: {args.procedures}")

    from pyefis.instruments import flight_plan
    w = flight_plan.FlightPlan(None, font_percent=0.8)   # the bench's option
    w.procedures_db_path = args.procedures
    w.parent = SimpleNamespace(parent=BEELINK)
    w.resize(PANE_W, PANE_H)

    plan = fp_model.FlightPlan(waypoints=[KSBA, GVO, KSMX])
    plan.insert_airway(1, "V27", "AVOLS", graph)
    w._plan = plan
    w._commit()
    ids = [wp.id for wp in w._plan.waypoints]
    print("route:", " ".join(ids))

    def fly(to_id):
        to = ids.index(to_id)
        _set("FPLSTATE", 1)
        _set("FPLACTLEG", to + 1)
        rem = w._plan.total_nm - w._plan.cumulative(to - 1)
        _set("FPLREMDIS", rem)
        _set("FPLREMETE", int(rem / 120.0 * 3600))
        w._sync_engine_from_bridge()

    out = []
    fly("GVO")
    out.append(_grab(app, w, os.path.join(args.outdir, "1_summary.png")))
    fly("DEANO")
    out.append(_grab(app, w, os.path.join(args.outdir, "2_in_airway.png")))
    k = next(n for n, s in enumerate(w._plan.segments) if s.kind == "airway")
    w._open_seg_menu(k)
    out.append(_grab(app, w, os.path.join(args.outdir, "3_segment_menu.png")))
    w._seg_menu_show_fixes()
    out.append(_grab(app, w, os.path.join(args.outdir, "4_show_fixes.png")))

    gap = 16
    sheet = QImage(PANE_W * len(out) + gap * (len(out) - 1), PANE_H, QImage.Format.Format_RGB32)
    sheet.fill(QColor("#404040"))
    p = QPainter(sheet)
    for n, img in enumerate(out):
        p.drawImage(n * (PANE_W + gap), 0, img)
    p.end()
    sheet.save(os.path.join(args.outdir, "sheet.png"))
    print("wrote", args.outdir)


if __name__ == "__main__":
    main()
