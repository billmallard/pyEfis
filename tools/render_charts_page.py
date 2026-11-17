#!/usr/bin/env python3
#  SPDX-License-Identifier: GPL-2.0-or-later
"""Renders of the Charts page (PA12, pyEfis #241, AER-1611).

Draws the real ``flight_plan`` widget -- its own paint path, not a drawing of
it -- at the Beelink's Flight Plan tab size (649 x 993 px on a 21.5 in
1920 x 1080 panel), with ``font_percent`` 0.8 as the bench serves it, the
same set-up as ``tools/render_proc_page.py``. The route is RZS then KSBA,
the approach is loaded through the real PROC page calls, and the engine is
played by hand (a commit is accepted by writing ``FPLLDSEQ``). Every tap is
the real callback a finger reaches.

Writes, to OUTDIR:

1. ``1_fpl_charts_key.png`` -- the FPL page with the approach loaded and
   the CHARTS soft key.
2. ``2_plate.png`` -- one tap on CHARTS: the approach's plate.
3. ``3_zoomed.png`` -- ZOOM + twice, dragged to the plan view's IAF.
4. ``4_list.png`` -- LIST: the airport's charts, the diagram first.
5. ``5_diagram.png`` -- the airport diagram, tapped from the list.
6. ``sheet.png`` -- all of them side by side at 1:1.

    QT_QPA_PLATFORM=offscreen PYTHONPATH=src python3 tools/render_charts_page.py OUTDIR \\
        --procedures procedures.sqlite --plates plates-ksba-2611.sqlite
"""

import argparse
import os
import sys
import time
from types import SimpleNamespace

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "src"))

from tools import render_proc_page as rp  # noqa: E402  (installs the mock FIX db)

import pyavtools.fix as fix  # noqa: E402
from PyQt6.QtCore import QPointF  # noqa: E402
from PyQt6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from pyefis.flightplan import fixbridge  # noqa: E402
from pyefis.flightplan import model as fp_model  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("outdir")
    ap.add_argument("--procedures", required=True, help="procedures.sqlite")
    ap.add_argument("--plates", required=True, help="plates pack, or a directory of them")
    ap.add_argument("--airport", default="KSBA")
    ap.add_argument("--approach", default="I07", help="approach ident as the pack codes it")
    ap.add_argument("--transition", default="VECTORS")
    ap.add_argument("--pan", nargs=2, type=float, default=(0.33, 0.27), metavar=("X", "Y"),
                    help="page point (fractions of the page) to centre the zoomed view on")
    args = ap.parse_args(argv)
    os.makedirs(args.outdir, exist_ok=True)

    app = QApplication.instance() or QApplication(sys.argv)
    fix.initialize({"main": {"FixServer": "localhost", "FixPort": "3490"}})
    for key, dtype, blank in fixbridge.route_key_specs():
        rp._define(key, dtype, blank)
    for key, dtype in rp._ENGINE.items():
        rp._define(key, dtype, rp._BLANK[dtype])
    rp._set("MAGVAR", -11.6)
    rp._set("FPLINTEG", True)

    from pyefis.instruments import flight_plan
    w = flight_plan.FlightPlan(None, font_percent=0.8)   # the bench's option
    w.procedures_db_path = args.procedures
    w.plates_path = args.plates
    w.parent = SimpleNamespace(parent=rp.BEELINK)
    w.resize(rp.PANE_W, rp.PANE_H)
    w._plan = fp_model.FlightPlan(waypoints=[rp.RZS.copy(), rp.KSBA.copy()])
    w._commit()

    def accept():
        rp._set("FPLLDSEQ", int(fix.db.get_item("FPLSEQ").value))
        w._on_bridge_change()

    def tap(callback):
        w.grab()
        assert any(t[4] == callback for t in w._tap_targets), "not on screen"
        callback()

    accept()
    apr = w._ensure_procedure_index().find(args.airport, "approach", args.approach)
    if apr is None:
        sys.exit(f"no approach {args.approach} at {args.airport} in {args.procedures}")
    w._open_proc_page("approach")
    w._proc_set_airport(args.airport)
    w._proc_pick("proc", apr)
    w._proc_pick("transition", args.transition)
    w._proc_load()
    accept()

    out = []
    shot = lambda name: out.append(rp._grab(app, w, os.path.join(args.outdir, name)))  # noqa: E731
    shot("1_fpl_charts_key.png")
    tap(w._footer_charts)
    if w._charts["plate"] is None:
        sys.exit(f"no single plate for {args.approach}: {w._charts['message']}")
    shot("2_plate.png")
    w.grab()
    w._charts_zoom(2)
    w._charts["centre"] = tuple(args.pan)
    shot("3_zoomed.png")
    tap(w._charts_list)
    shot("4_list.png")
    first_row = next(t[4] for t, kind in zip(w._tap_targets, w._tap_kinds) if kind == "row")
    first_row()
    if w._charts["plate"].chart_code != "APD":
        sys.exit(f"the first chart listed is {w._charts['plate'].chart_name}, not the diagram")
    shot("5_diagram.png")

    gap = 16
    sheet = QImage(rp.PANE_W * len(out) + gap * (len(out) - 1), rp.PANE_H,
                   QImage.Format.Format_RGB32)
    sheet.fill(QColor("#404040"))
    p = QPainter(sheet)
    for n, img in enumerate(out):
        p.drawImage(QPointF(n * (rp.PANE_W + gap), 0), img)
    p.end()
    sheet.save(os.path.join(args.outdir, "sheet.png"))
    print("wrote", args.outdir)


if __name__ == "__main__":
    main()
