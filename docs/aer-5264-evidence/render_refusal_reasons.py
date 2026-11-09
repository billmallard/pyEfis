#!/usr/bin/env python3
#  SPDX-License-Identifier: GPL-2.0-or-later
"""Renders the FPL page's refusal strip for several engine FPLMSG codes
(G61a, AER-5264), the way docs/aer-5089-evidence/render_refused_commit.py
renders the strip itself.

The flown plan KSBA GVO REYES KSMX is loaded (FPLLDSEQ = FPLSEQ = 1). A
second display then commits a route with an RF leg at RFFIX (FPLSEQ 2) and
the engine answers each code below on FPLMSG, leaving FPLLDSEQ at 1. The
codes are the exact strings fix-gateway's engine writes for that route.

    QT_QPA_PLATFORM=offscreen PYTHONPATH=src:.:tools \\
        python3 docs/aer-5264-evidence/render_refusal_reasons.py <out_dir> [prefix]

Writes <prefix><name>.png (the whole page) for each case, and
<prefix>strips_x2.png: every case's strip region stacked, 2x nearest-neighbour.
"""

import os
import sys

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QImage, QPainter
from PyQt6.QtWidgets import QApplication

# The in-memory FIX client the test suite uses (conftest.py): no gateway.
import tests.mock_db.client
import tests.mock_db.scheduler
sys.modules["pyavtools.fix.client"] = tests.mock_db.client
sys.modules["pyavtools.scheduler"] = tests.mock_db.scheduler
import pyavtools.fix as fix  # noqa: E402

from pyefis.flightplan import fixbridge  # noqa: E402
from pyefis.flightplan import model as fp_model  # noqa: E402
from pyefis.instruments import flight_plan  # noqa: E402

W, H = 650, 1000   # about the Flight Plan tab's pane on the Beelink PFD screen
STRIP_TOP, STRIP_H = 840, 100

# (file name, FPLMSG, open the draft?)
CASES = [
    ("badturn", "BADTURN RF RFFIX", False),
    ("badturn_draft", "BADTURN RF RFFIX", True),
    ("unsupp", "UNSUPP FC RFFIX", False),
    ("segent", "SEGENT S4 RFFIX", False),
    ("unknown", "NEWCODE RF RFFIX", False),
]


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


def render(msg, draft):
    """The page after the engine answers *msg* to the refused commit."""
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
    fix.db.set_value("FPLMSG", msg)
    QApplication.processEvents()
    if draft:
        w._reopen_draft()
    img = QImage(W, H, QImage.Format.Format_RGB32)
    w._paint(img)
    w.deleteLater()
    return img


def main():
    out_dir = sys.argv[1]
    prefix = sys.argv[2] if len(sys.argv) > 2 else ""
    app = QApplication.instance() or QApplication([])
    try:
        from evidence_sidecar import write_sidecar
    except ImportError:
        write_sidecar = None

    label_h = 22
    sheet = QImage(W * 2, len(CASES) * (STRIP_H * 2 + label_h), QImage.Format.Format_RGB32)
    sheet.fill(QColor("#000000"))
    p = QPainter(sheet)
    f = QFont()
    f.setPixelSize(15)
    p.setFont(f)
    y = 0
    for name, msg, draft in CASES:
        img = render(msg, draft)
        path = os.path.join(out_dir, f"{prefix}{name}.png")
        img.save(path)
        if write_sidecar:
            write_sidecar(path)
        print(path)
        p.setPen(QColor("#c0c0c0"))
        p.drawText(6, y, W * 2 - 12, label_h, Qt.AlignmentFlag.AlignVCenter,
                   f"FPLMSG = {msg}" + ("   (after Edit draft)" if draft else ""))
        strip = img.copy(0, STRIP_TOP, W, STRIP_H).scaled(
            W * 2, STRIP_H * 2, transformMode=Qt.TransformationMode.FastTransformation)
        p.drawImage(0, y + label_h, strip)
        y += label_h + STRIP_H * 2
    p.end()
    path = os.path.join(out_dir, f"{prefix}strips_x2.png")
    sheet.save(path)
    if write_sidecar:
        write_sidecar(path)
    print(path)
    app.processEvents()


if __name__ == "__main__":
    main()
