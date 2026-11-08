#!/usr/bin/env python3
#  SPDX-License-Identifier: GPL-2.0-or-later
"""Renders the FPL page around a refused route commit (G61, pyEfis #380).

The engine is played by hand, as in tests/instruments/flight_plan/
test_refused_commit.py: the flown plan is loaded (FPLLDSEQ = FPLSEQ = 1),
then a second display commits a route with an RF leg and no turn direction
(FPLSEQ 2) and the engine answers BADTURN on FPLMSG, leaving FPLLDSEQ at 1.

    QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. \\
        python3 docs/aer-5089-evidence/render_refused_commit.py <out_dir> [prefix]

Writes <prefix>refused.png (the page after the refusal) and, when the code
has a draft to open, <prefix>draft.png (after Edit draft).
"""

import os
import sys

from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication

# The in-memory FIX client the test suite uses (conftest.py): no gateway.
import tests.mock_db.client
import tests.mock_db.scheduler
sys.modules["pyavtools.fix.client"] = tests.mock_db.client
sys.modules["pyavtools.scheduler"] = tests.mock_db.scheduler
import pyavtools.fix as fix  # noqa: E402

from pyefis.flightplan import fixbridge
from pyefis.flightplan import model as fp_model
from pyefis.instruments import flight_plan

W, H = 650, 1000   # about the Flight Plan tab's pane on the Beelink PFD screen


def define(key, dtype, value):
    bounds = {"float": (-1e9, 1e9), "int": (-1_000_000, 1_000_000)}.get(dtype, (None, None))
    fix.db.define_item(key, key, dtype, bounds[0], bounds[1], "", 0, "")
    fix.db.set_value(key, value)
    fix.db.get_item(key).bad = False
    fix.db.get_item(key).fail = False


def bus():
    fix.initialize({"main": {"FixServer": "localhost", "FixPort": "3490"}})
    for key, dtype, blank in fixbridge.route_key_specs():
        define(key, dtype, blank)
    for key in ("FPLSTATE", "FPLACTLEG", "FPLAPR", "FPLTF", "WPETE", "FPLREMETE",
                "GPSSRC", "FPLACTSEG", "FPLLDSEQ"):
        define(key, "int", 0)
    for key in ("CDISCALE", "FPLCRS", "FPLXTK", "FPLCDI", "FPLFRLAT", "FPLFRLON",
                "WPLAT", "WPLON", "WPDIS", "FPLREMDIS", "FPLSEGREM"):
        define(key, "float", 0.0)
    for key in ("FPLPHASE", "WPNAME", "WPFROM", "WPNEXT"):
        define(key, "str", "")
    define("FPLINTEG", "bool", True)
    define("FPLALERT", "bool", False)


def wp(ident, lat, lon, **kw):
    return fp_model.Waypoint(id=ident, type="fix", lat=lat, lon=lon, **kw)


def main():
    out_dir = sys.argv[1]
    prefix = sys.argv[2] if len(sys.argv) > 2 else ""
    app = QApplication.instance() or QApplication([])
    bus()
    other = fixbridge.FixBridge(fix)
    flown = fp_model.FlightPlan(name="KSBA-KSMX", waypoints=[
        fp_model.Waypoint(id="KSBA", type="airport", lat=34.4262, lon=-119.8404),
        wp("GVO", 34.5314, -120.0911), wp("REYES", 34.70, -120.25),
        fp_model.Waypoint(id="KSMX", type="airport", lat=34.8989, lon=-120.4576)])
    other.publish(flown)
    fix.db.set_value("FPLLDSEQ", 1)
    fix.db.set_value("FPLSTATE", 1)
    fix.db.set_value("FPLACTLEG", 2)
    fix.db.set_value("FPLREMDIS", 42.0)
    fix.db.set_value("FPLREMETE", 1500)

    w = flight_plan.FlightPlan(None)
    w.resize(W, H)
    refused = fp_model.FlightPlan(name="KSBA-KSMX", waypoints=list(flown.waypoints[:3]) + [
        wp("RFFIX", 34.80, -120.30, pt="RF", ctr_lat=34.75, ctr_lon=-120.35, turn=""),
        flown.waypoints[3]])
    other.publish(refused)
    fix.db.set_value("FPLMSG", "BADTURN 4")
    app.processEvents()

    def save(name):
        img = QImage(W, H, QImage.Format.Format_RGB32)
        w._paint(img)
        path = os.path.join(out_dir, prefix + name)
        img.save(path)
        print(path)

    save("refused.png")
    if hasattr(w, "_reopen_draft"):
        w._reopen_draft()
        save("draft.png")


if __name__ == "__main__":
    main()
