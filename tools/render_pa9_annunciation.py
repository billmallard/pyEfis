#!/usr/bin/env python3
#  SPDX-License-Identifier: GPL-2.0-or-later
"""Renders of the loaded procedure's type and AIRAC cycle, current and
expired (PA9, pyEfis #240, AER-1608).

Draws the real ``flight_plan`` and ``nav_status`` widgets -- their own paint
paths -- at the Beelink's Flight Plan tab geometry (the FPL pane 649 x 993 px
with ``font_percent`` 0.8, as ``render_proc_page.py`` does; the chip at the
width of the screen's left half). The approach comes from the procedures pack
given, through the real PROC page calls and the real FIX bridge into the
in-memory mock FIX db, and the chip reads the keys that bridge wrote. The
engine outputs (state, phase, waypoints, FPLTURN) are set by hand.

"Current" and "expired" differ only in the UTC date the AIRAC check is given:
the day after the pack's cycle took effect, and the day it expired. Nothing
else changes, and the expired approach is loaded exactly as the current one.

Writes, to OUTDIR:

1. ``1_fpl_current.png`` / ``2_fpl_expired.png`` -- the FPL page after Load.
2. ``3_preview_expired.png`` -- the PROC page preview, before Load.
3. ``4_chip.png`` -- the chip, top to bottom: current; expired; expired with
   ``FPLTURN`` R.
4. ``sheet.png`` -- 1-3 side by side at 1:1, the chip strip under them.

    QT_QPA_PLATFORM=offscreen PYTHONPATH=src python3 tools/render_pa9_annunciation.py OUTDIR \\
        --procedures /data/makerplane-data/procedures/current/procedures.sqlite \\
        --approach I07 --transition GOLET
"""

import argparse
import datetime as dt
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "src"))

from tools import render_proc_page as rp  # noqa: E402  (installs the mock FIX db)

import pyavtools.fix as fix  # noqa: E402
from PyQt6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from pyefis.flightplan import airac  # noqa: E402
from pyefis.flightplan import fixbridge  # noqa: E402
from pyefis.flightplan import model as fp_model  # noqa: E402
from pyefis.flightplan import procedures  # noqa: E402

CHIP_W, CHIP_H = 960, 64


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("outdir")
    ap.add_argument("--procedures", required=True, help="procedures.sqlite")
    ap.add_argument("--airport", default="KSBA")
    ap.add_argument("--approach", default="I07", help="approach ident as the pack codes it")
    ap.add_argument("--transition", default="GOLET")
    ap.add_argument("--magvar", type=float, default=-11.6)
    args = ap.parse_args(argv)
    os.makedirs(args.outdir, exist_ok=True)

    app = QApplication.instance() or QApplication(sys.argv)
    fix.initialize({"main": {"FixServer": "localhost", "FixPort": "3490"}})
    for key, dtype, blank in fixbridge.route_key_specs():
        rp._define(key, dtype, blank)
    for key, dtype in rp._ENGINE.items():
        rp._define(key, dtype, rp._BLANK[dtype])
    rp._define("FPLTURN", "str", "")
    rp._set("MAGVAR", args.magvar)
    rp._set("FPLINTEG", True)

    index = procedures.ProcedureIndex(args.procedures)
    apr = index.find(args.airport, "approach", args.approach)
    if apr is None:
        sys.exit(f"no approach {args.approach} at {args.airport} in {args.procedures}")
    start = airac.effective(apr.cycle)
    if start is None:
        sys.exit(f"pack cycle {apr.cycle!r} is not an AIRAC ident")
    current, expired = start + dt.timedelta(days=1), airac.expires(apr.cycle)
    print(f"cycle {apr.cycle}: current on {current}, expired on {expired}")

    from pyefis.instruments import flight_plan, nav_status
    w = flight_plan.FlightPlan(None, font_percent=0.8)   # the bench's option
    w.procedures_db_path = args.procedures
    w.parent = rp.SimpleNamespace(parent=rp.BEELINK)
    w.resize(rp.PANE_W, rp.PANE_H)
    w._plan = fp_model.FlightPlan(waypoints=[rp.RZS.copy(), rp.KSBA.copy()])
    w._commit()

    def accept():
        rp._set("FPLLDSEQ", int(fix.db.get_item("FPLSEQ").value))
        w._on_bridge_change()

    def on(day):
        airac.utc_today = lambda: day

    accept()
    out = []
    shot = lambda name: out.append(rp._grab(app, w, os.path.join(args.outdir, name)))  # noqa: E731

    on(expired)
    w._open_proc_page("approach")
    w._proc_set_airport(args.airport)
    w._proc_pick("proc", apr)
    w._proc_pick("transition", args.transition)
    preview = rp._grab(app, w, os.path.join(args.outdir, "3_preview_expired.png"))
    w._proc_load()
    accept()
    assert any(s.kind == "approach" for s in w._plan.segments), "the expired approach did not load"
    on(current)
    shot("1_fpl_current.png")
    on(expired)
    shot("2_fpl_expired.png")
    out.append(preview)

    # The chip, on the keys the bridge just wrote plus a hand-set leg.
    faf = next((wp for wp in w._plan.waypoints if wp.role == "faf"), None)
    rp._set("FPLSTATE", 1)
    rp._set("FPLPHASE", "TERM")
    rp._set("WPFROM", "GOLET")
    rp._set("WPNAME", faf.id if faf else "____")
    rp._set("WPNEXT", "RW07")
    rp._set("WPDIS", 8.4)
    rp._set("WPETE", 312)
    chips = []

    def chip_shot():
        c = nav_status.NavStatus()
        c.resize(CHIP_W, CHIP_H)
        c.update()
        for _ in range(10):
            app.processEvents()
        chips.append(c.grab().toImage())

    on(current)
    chip_shot()
    on(expired)
    chip_shot()
    rp._set("FPLTURN", "R")
    chip_shot()

    gap = 8
    strip = QImage(CHIP_W, CHIP_H * len(chips) + gap * (len(chips) - 1), QImage.Format.Format_RGB32)
    strip.fill(QColor("#404040"))
    p = QPainter(strip)
    for n, img in enumerate(chips):
        p.drawImage(0, n * (CHIP_H + gap), img)
    p.end()
    strip.save(os.path.join(args.outdir, "4_chip.png"))

    gap = 16
    width = rp.PANE_W * len(out) + gap * (len(out) - 1)
    sheet = QImage(width, rp.PANE_H + gap + strip.height(), QImage.Format.Format_RGB32)
    sheet.fill(QColor("#404040"))
    p = QPainter(sheet)
    for n, img in enumerate(out):
        p.drawImage(n * (rp.PANE_W + gap), 0, img)
    p.drawImage(0, rp.PANE_H + gap, strip)
    p.end()
    sheet.save(os.path.join(args.outdir, "sheet.png"))
    print("wrote", args.outdir)


if __name__ == "__main__":
    main()
