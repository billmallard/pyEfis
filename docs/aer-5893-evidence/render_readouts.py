"""Render the airspeed, altimeter and VSI tapes live and under `bad` (CERT1c).

Run from the repo root through pytest, so the root conftest's in-memory FIX
database is used (see README.md beside this file):

    OUT=<dir> python3 -m pytest -p no:cacheprovider --no-cov -q \
        docs/aer-5893-evidence/render_readouts.py

Writes <dir>/live.png and <dir>/bad.png: the three tapes side by side on a
black panel at 2x, nearest-neighbour.
"""
import os
from unittest import mock

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QWidget

from pyefis.instruments import airspeed, altimeter, vsi

TAPE_W, TAPE_H = 100, 400


def test_render(fix, qtbot):
    out = os.environ["OUT"]
    os.makedirs(out, exist_ok=True)
    keys = {"IAS": 112, "ALT": 4520, "VS": 500}
    for k, v in keys.items():
        item = fix.db.get_item(k)
        item.value = v
        item.old = item.bad = item.fail = False
    tas = fix.db.get_item("TAS")
    tas.old = tas.bad = tas.fail = False

    panel = QWidget()
    panel.setStyleSheet("background-color: black;")
    panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    lay = QHBoxLayout(panel)
    lay.setSpacing(12)
    asi = airspeed.Airspeed_Tape(panel, show_tas=False, show_trend=False)
    alt = altimeter.Altimeter_Tape(panel, show_trend=False, show_baro=False,
                                   alt_bug_enabled=False)
    vs = vsi.Alt_Trend_Tape(panel)
    parent = mock.Mock()
    parent.get_config_item = mock.Mock(return_value=0)
    vs.myparent = parent
    for w in (asi, alt, vs):
        w.setFixedSize(TAPE_W, TAPE_H)
        lay.addWidget(w)
    qtbot.addWidget(panel)
    panel.show()
    qtbot.waitExposed(panel)

    def grab(name):
        qtbot.wait(50)
        img = panel.grab().toImage()
        img = img.scaled(img.width() * 2, img.height() * 2,
                         transformMode=Qt.TransformationMode.FastTransformation)
        assert img.save(os.path.join(out, name + ".png"))

    grab("live")
    for k in keys:
        fix.db.get_item(k).bad = True
    grab("bad")
