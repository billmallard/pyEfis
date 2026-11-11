"""Render a bound fuel bar, an unbound one and a failed-sensor one side by
side (AER-5390). Run from the repo root:

    QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. python3 docs/images/aer-5390/render.py
"""
import os
import sys

import tests.mock_db.client
import tests.mock_db.scheduler

sys.modules["pyavtools.fix.client"] = tests.mock_db.client
sys.modules["pyavtools.scheduler"] = tests.mock_db.scheduler

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtWidgets import QApplication

import pyavtools.fix as fix
import pyefis.hmi as hmi
from pyefis.instruments import gauges

app = QApplication([])
hmi.initialize({})
fix.initialize({"main": {"FixServer": "localhost", "FixPort": "3490"}})
for key, value, failed in (("FUELQ1", 18.0, False), ("FUELQ2", 11.0, True)):
    fix.db.define_item(key, key, "float", 0, 25, "gal", 50000,
                       "Min,Max,lowWarn,lowAlarm")
    fix.db.set_value(key, value)
    item = fix.db.get_item(key)
    item.old = item.bad = False
    item.fail = failed
    item.set_aux_value("lowAlarm", 2)
    item.set_aux_value("lowWarn", 5)

W, H = 120, 300
panels = []
for name, key in (("L MAIN", "FUELQ1"), ("L TIP", None), ("R MAIN", "FUELQ2")):
    bar = gauges.VerticalBar(min_size=False)
    bar.name = name
    if key is None:
        bar.setUnbound()
    else:
        bar.setDbkey(key)
    bar.resize(W, H)
    panels.append(bar.grab().toImage())

scale = 2
out = QImage(W * len(panels) * scale, H * scale, QImage.Format.Format_RGB32)
out.fill(Qt.GlobalColor.black)
p = QPainter(out)
for i, img in enumerate(panels):
    p.drawImage(i * W * scale, 0, img.scaled(W * scale, H * scale,
                transformMode=Qt.TransformationMode.FastTransformation))
p.end()
path = os.path.join(os.path.dirname(__file__), "bound_unbound_failed.png")
out.save(path)
print(path)
