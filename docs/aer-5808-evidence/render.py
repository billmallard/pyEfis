#  SPDX-License-Identifier: GPL-2.0-or-later
"""Render the AFC4 evidence sheet offscreen (see README.md beside this file).

Drives the real widgets from an in-memory FIX database (tests/mock_db), one
row per autopilot state, and writes strip.png and tapes.png here.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path[:0] = [os.path.join(ROOT, "src"), ROOT]

import tests.mock_db.client  # noqa: E402
import tests.mock_db.scheduler  # noqa: E402
sys.modules["pyavtools.fix.client"] = tests.mock_db.client
sys.modules["pyavtools.scheduler"] = tests.mock_db.scheduler

from PyQt6.QtCore import Qt, QRectF  # noqa: E402
from PyQt6.QtGui import QColor, QFont, QImage, QPainter  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

import pyavtools.fix as fix  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)
fix.initialize({"main": {"FixServer": "localhost", "FixPort": "3490"}})

from tests.instruments.autopilot.conftest import AFC1_KEYS, INITIAL  # noqa: E402

for key, dtype, lo, hi, tol in AFC1_KEYS:
    fix.db.define_item(key, key, dtype, lo, hi, "", tol, "")
fix.db.define_item("IAS", "IAS", "float", 0, 2000.0, "knots", 2000,
                   "Min,Max,Vne,Vfe,Vno,Vs,Vs0")
fix.db.define_item("TAS", "TAS", "float", 0, 2000.0, "knots", 2000, "")
fix.db.define_item("VS", "VS", "float", -10000, 10000, "ft/min", 2000, "")
fix.db.define_item("ALT", "ALT", "float", -2000, 60000, "ft", 2000, "")
fix.db.define_item("ALTSEL", "ALTSEL", "int", -1000, 60000, "ft", 0, "")
fix.db.define_item("BARO", "BARO", "float", 0, 35, "inHg", 0, "")
ias = fix.db.get_item("IAS")
for aux, v in (("Vs0", 48), ("Vs", 55), ("Vfe", 85), ("Vno", 128), ("Vne", 160)):
    ias.set_aux_value(aux, v)


def put(key, value=None, old=False):
    item = fix.db.get_item(key)
    if value is not None:
        item.value = value
    item.old, item.bad, item.fail = old, False, False


def reset():
    for key, dtype, *_ in AFC1_KEYS:
        put(key, INITIAL[dtype])
    for key, v in (("IAS", 92.0), ("TAS", 98.0), ("VS", 480.0),
                   ("ALT", 7380.0), ("ALTSEL", 8500), ("BARO", 29.92)):
        put(key, v)


def flying():
    reset()
    for key, v in (("APENG", True), ("YDENG", True), ("APLAT", "HDG"),
                   ("APLATARM", "GPS"), ("APVERT", "VS"), ("APVERTARM", "ALT"),
                   ("VSSEL", 500), ("IASSEL", 90.0)):
        put(key, v)


class Clock:
    t = 1000.0

    def __call__(self):
        return self.t


from pyefis.instruments import airspeed, altimeter, vsi  # noqa: E402
from pyefis.instruments.autopilot import fma  # noqa: E402


def label(p, rect, text):
    f = QFont("DejaVu Sans")
    f.setPixelSize(14)
    p.setFont(f)
    p.setPen(QColor("#c0c0c0"))
    p.drawText(rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)


def strip_sheet(path):
    W, H, LW = 640, 40, 400
    rows = []
    clock = Clock()
    flying()
    w = fma.ModeAnnunciator(clock=clock)   # built on the reading: a baseline
    w.resize(W, H)

    def shot(caption):
        img = QImage(W, H, QImage.Format.Format_ARGB32)
        img.fill(QColor("#1d3a5f"))      # sky-blue ground under the strip
        # Children only, no palette background, so the strip composites over
        # the ground as it does over the attitude display.
        w.render(img, flags=type(w).RenderFlag.DrawChildren)
        rows.append((caption, img))

    shot("1 AP+YD, HDG (GPS armed), VS +500 (ALT armed)")
    put("APLAT", "GPS"); put("APLATARM", "")
    shot("2 GPS captured: boxed, flash ON phase (10 s)")
    clock.t += fma.BLINK_HALF_S
    shot("3 same, flash OFF phase (box stays)")
    clock.t = 1040.0                      # whole seconds: the flash ON phase
    put("APALTCAP", True)
    shot("4 altitude capture: ALT CAP boxed")
    put("APALTCAP", False); put("APVERT", "ALT"); put("APVERTARM", "")
    put("APALTREF", 8500); put("ALTSEL", 10500)
    clock.t = 1080.0
    shot("5 ALT hold 8500 (APALTREF), 10500 preselected")
    put("APALTREF", old=True)
    shot("5b same, APALTREF old: ALT, no number")
    put("APALTREF", old=False)
    put("APVERT", "IAS"); put("APVERTARM", "ALT"); clock.t = 1120.0
    shot("6 IAS 90 climb, ALT armed")
    put("APENG", False); put("APDISC", True); clock.t = 1160.0
    shot("7 AP disconnect: red AP flashing until acknowledged")
    put("APDISC", False); put("APENG", True)
    put("APLAT", old=True)
    shot("8 state key old while engaged: NO AP DATA amber")
    put("APLAT", old=False); put("APENG", False); put("APLAT", old=True)
    shot("9 state key old while off: NO AP DATA grey")
    sheet = QImage(LW + W + 20, len(rows) * (H + 10) + 10,
                   QImage.Format.Format_ARGB32)
    sheet.fill(QColor("#202020"))
    p = QPainter(sheet)
    for i, (caption, img) in enumerate(rows):
        y = 10 + i * (H + 10)
        label(p, QRectF(10, y, LW - 10, H), caption)
        p.drawImage(LW, y, img)
    p.end()
    sheet.save(path)


def tapes_sheet(path):
    flying()
    cols = []

    def grab(widget, w, h, caption):
        widget.resize(w, h)
        widget.show()
        app.processEvents()
        cols.append((caption, widget.grab().toImage()))
        widget.hide()

    put("APVERT", "IAS"); put("APVERTARM", "")
    grab(airspeed.Airspeed_Tape(), 90, 420, "IAS active")
    put("APVERT", "PIT"); put("APVERTARM", "IAS")
    grab(airspeed.Airspeed_Tape(), 90, 420, "IAS armed")
    put("APVERT", "IAS"); put("APVERTARM", "")
    editing = airspeed.Airspeed_Tape()
    editing._ias_focused = True          # the state a touch on the box leaves
    grab(editing, 90, 420, "IAS editing")
    put("APVERT", "VS"); put("APVERTARM", "ALT")
    grab(altimeter.Altimeter_Tape(dbkey="VS", maxalt=4000, majorDiv=500,
                                  minorDiv=100), 80, 420, "VS tape")
    grab(vsi.VSI_PFD(), 50, 420, "VSI_PFD")
    put("APALTCAP", True)
    grab(altimeter.Altimeter_Tape(dbkey="ALT"), 120, 420, "ALT CAP")
    put("APALTCAP", False)
    grab(altimeter.Altimeter_Tape(dbkey="ALT"), 120, 420, "ALTSEL plain")
    W = sum(img.width() for _, img in cols) + 20 * (len(cols) + 1)
    sheet = QImage(W, 470, QImage.Format.Format_ARGB32)
    sheet.fill(QColor("#1d3a5f"))
    p = QPainter(sheet)
    x = 20
    for caption, img in cols:
        p.drawImage(x, 40, img)
        label(p, QRectF(x - 10, 5, img.width() + 20, 30), caption)
        x += img.width() + 20
    p.end()
    sheet.save(path)


strip_sheet(os.path.join(HERE, "strip.png"))
tapes_sheet(os.path.join(HERE, "tapes.png"))
print("wrote strip.png, tapes.png")
