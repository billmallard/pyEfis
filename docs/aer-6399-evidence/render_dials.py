"""Render the round airspeed and altimeter dials under each flag (CERT1g).

Run from the repo root through pytest, so the root conftest's in-memory FIX
database is used (see README.md beside this file):

    OUT=<dir> python3 -m pytest -p no:cacheprovider --no-cov -q \
        docs/aer-6399-evidence/render_dials.py

Writes <dir>/dials.png: four columns (live, bad, old, fail), the airspeed dial
above the altimeter dial in each, on a black panel.
"""
import os

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QImage, QPainter
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from pyefis.instruments import airspeed, altimeter

DIAL = 240
LABEL_H = 28
STATES = ("live", "bad", "old", "fail")


def test_render(fix, qtbot):
    out = os.environ["OUT"]
    os.makedirs(out, exist_ok=True)
    keys = {"IAS": 112, "ALT": 4520}
    for k, v in keys.items():
        item = fix.db.get_item(k)
        item.value = v
        item.old = item.bad = item.fail = False

    panel = QWidget()
    panel.setStyleSheet("background-color: black;")
    panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    lay = QVBoxLayout(panel)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(8)
    asi = airspeed.Airspeed(panel)
    asi.setAirspeed(keys["IAS"])
    alt = altimeter.Altimeter(panel)
    alt.setAltimeter(keys["ALT"])
    for w in (asi, alt):
        w.setFixedSize(DIAL, DIAL)
        lay.addWidget(w)
    qtbot.addWidget(panel)
    panel.show()
    qtbot.waitExposed(panel)

    cols = []
    for state in STATES:
        for k in keys:
            item = fix.db.get_item(k)
            item.old = item.bad = item.fail = False
            if state != "live":
                setattr(item, state, True)
        qtbot.wait(50)
        cols.append(panel.grab().toImage())

    cw, ch = cols[0].width(), cols[0].height()
    sheet = QImage(cw * len(cols) + 8 * (len(cols) - 1), ch + LABEL_H,
                   QImage.Format.Format_RGB32)
    sheet.fill(QColor(Qt.GlobalColor.black))
    p = QPainter(sheet)
    f = QFont("DejaVu Sans")
    f.setPixelSize(18)
    p.setFont(f)
    p.setPen(QColor(Qt.GlobalColor.white))
    for i, (state, img) in enumerate(zip(STATES, cols)):
        x = i * (cw + 8)
        p.drawText(x, 0, cw, LABEL_H, Qt.AlignmentFlag.AlignCenter, state)
        p.drawImage(x, LABEL_H, img)
    p.end()
    assert sheet.save(os.path.join(out, "dials.png"))
