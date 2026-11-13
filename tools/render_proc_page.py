#!/usr/bin/env python3
#  SPDX-License-Identifier: GPL-2.0-or-later
"""Renders of the PROC page (PA7, pyEfis #238, AER-1606).

Draws the real ``flight_plan`` widget -- its own paint path, not a drawing of
it -- at the Beelink's Flight Plan tab size (649 x 993 px on a 21.5 in
1920 x 1080 panel, the geometry ``tests/instruments/flight_plan/
test_row_geometry.py`` pins), with ``font_percent`` 0.8 as the bench serves
it. The route is RZS then KSBA; the approach comes from the procedures pack
given, through the real PROC page calls and the real FIX bridge into the
in-memory mock FIX db. The engine is played by hand: a commit is accepted by
writing ``FPLLDSEQ``, refused by writing ``FPLMSG``.

Writes, to OUTDIR:

1. ``1_proc_empty.png`` -- the PROC page on Approach, airport offered.
2. ``2_pick_transition.png`` -- the transition picker for the approach.
3. ``3_ready.png`` -- the selection complete, every leg in the preview.
4. ``4_fpl_loaded.png`` -- after Load: the FPL page, the approach and its
   missed approach as two named rows.
5. ``5_fpl_active.png`` -- flying to the FAF: the approach opens.
6. ``6_refused.png`` -- a transition with a leg the engine cannot fly,
   refused with the reason from ``FPLMSG`` (only with ``--refuse``).
7. ``7_departure.png`` -- the Departure tab with a SID chosen (only with
   ``--sid``).
8. ``sheet.png`` -- all of them side by side at 1:1.

    QT_QPA_PLATFORM=offscreen PYTHONPATH=src python3 tools/render_proc_page.py OUTDIR \\
        --procedures /data/makerplane-data/procedures/current/procedures.sqlite \\
        --approach I07 --transition VECTORS --refuse GOLET "UNSUPP FC LOBER" \\
        --sid FLOUT5 RW07 VTU
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

from pyefis.flightplan import fixbridge  # noqa: E402
from pyefis.flightplan import model as fp_model  # noqa: E402
from pyefis.flightplan import procedures  # noqa: E402

PANE_W, PANE_H = 649, 993
BEELINK = SimpleNamespace(screenWidth=1920, screenHeight=1080, screenDiagonalInches=21.5)

RZS = fp_model.Waypoint(id="RZS", type="vor", lat=34.50953, lon=-119.77099)
KSBA = fp_model.Waypoint(id="KSBA", type="airport", lat=34.42621, lon=-119.84037)

_BOUNDS = {"float": (-1e9, 1e9), "int": (-1_000_000, 1_000_000),
           "bool": (None, None), "str": (None, None)}
_ENGINE = {
    "FPLSTATE": "int", "FPLACTLEG": "int", "FPLPHASE": "str", "FPLAPR": "int",
    "FPLINTEG": "bool", "CDISCALE": "float", "FPLCRS": "float", "FPLXTK": "float",
    "FPLCDI": "float", "FPLTF": "int", "FPLFRLAT": "float", "FPLFRLON": "float",
    "WPNAME": "str", "WPLAT": "float", "WPLON": "float", "WPFROM": "str",
    "WPNEXT": "str", "WPDIS": "float", "WPETE": "int", "FPLREMDIS": "float",
    "FPLREMETE": "int", "FPLALERT": "bool", "GPSSRC": "int",
    "FPLACTSEG": "int", "FPLSEGREM": "float", "MAGVAR": "float", "FPLLDSEQ": "int",
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


def _grab(app, w, path):
    w.update()
    for _ in range(20):
        app.processEvents()
        time.sleep(0.01)
    img = w.grab().toImage()
    img.save(path)
    return img


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("outdir")
    ap.add_argument("--procedures", required=True, help="procedures.sqlite")
    ap.add_argument("--airport", default="KSBA")
    ap.add_argument("--approach", default="I07", help="approach ident as the pack codes it")
    ap.add_argument("--transition", default="VECTORS")
    ap.add_argument("--refuse", nargs=2, metavar=("TRANSITION", "FPLMSG"),
                    help="load this transition and answer it with this FPLMSG")
    ap.add_argument("--sid", nargs=3, metavar=("IDENT", "RUNWAY", "TRANSITION"))
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

    index = procedures.ProcedureIndex(args.procedures)
    apr = index.find(args.airport, "approach", args.approach)
    if apr is None:
        sys.exit(f"no approach {args.approach} at {args.airport} in {args.procedures}")

    from pyefis.instruments import flight_plan
    w = flight_plan.FlightPlan(None, font_percent=0.8)   # the bench's option
    w.procedures_db_path = args.procedures
    w.parent = SimpleNamespace(parent=BEELINK)
    w.resize(PANE_W, PANE_H)
    w._plan = fp_model.FlightPlan(waypoints=[RZS.copy(), KSBA.copy()])
    w._commit()

    def accept():
        _set("FPLLDSEQ", int(fix.db.get_item("FPLSEQ").value))
        w._on_bridge_change()

    accept()
    out = []
    shot = lambda name: out.append(_grab(app, w, os.path.join(args.outdir, name)))  # noqa: E731
    w._open_proc_page("approach")
    w._proc_set_airport(args.airport)
    shot("1_proc_empty.png")
    w._proc_pick("proc", apr)
    w._proc_open_field("transition")
    shot("2_pick_transition.png")
    w._proc_pick("transition", args.transition)
    shot("3_ready.png")
    w._proc_load()
    accept()
    shot("4_fpl_loaded.png")
    faf = next((i for i, wp in enumerate(w._plan.waypoints) if wp.role == "faf"), None)
    if faf is not None:
        _set("FPLSTATE", 1)
        _set("FPLACTLEG", faf + 1)
        w._sync_engine_from_bridge()
    shot("5_fpl_active.png")
    _set("FPLSTATE", 0)
    _set("FPLACTLEG", 0)
    w._sync_engine_from_bridge()
    if args.refuse:
        trans, msg = args.refuse
        w._open_proc_page("approach")
        w._proc_set_airport(args.airport)
        w._proc_pick("proc", apr)
        w._proc_pick("transition", trans)
        w._proc_load()
        _set("FPLMSG", msg)
        w._on_fplmsg()
        shot("6_refused.png")
    if args.sid:
        ident, runway, trans = args.sid
        w._plan = fp_model.FlightPlan(waypoints=[KSBA.copy(), RZS.copy()])
        w._commit()
        accept()
        w._open_proc_page("departure")
        w._proc_pick("proc", index.find(args.airport, "sid", ident))
        w._proc_pick("runway", runway)
        w._proc_pick("transition", trans)
        shot("7_departure.png")

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
