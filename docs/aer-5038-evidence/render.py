"""Render a VerticalBar in Normal and Normalize mode, 3x nearest-neighbour.

Run from the repo root:
    QT_QPA_PLATFORM=offscreen PYTHONPATH=src python docs/aer-5038-evidence/render.py
Writes normalize_after.png next to this file. For the "before" image, run
the same command on dev before the fix (d9028b7e^) with OUT=normalize_before.png.
"""
import os
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtCore import Qt

app = QApplication([])
from pyefis.instruments.gauges.verticalBar import VerticalBar


def grab(normalize):
    w = VerticalBar()
    w.name = "EGT1"
    w.units = "F"
    w.lowRange, w.highRange = 1000, 1600
    w.normalize_range = 400
    w._value = 1350
    w.resize(80, 240)
    w.setColors()
    w.show()
    app.processEvents()
    w.resizeEvent(None)
    if normalize:
        w.setNormalizeMode(True)
    return w.grab().toImage()


normal, norm = grab(False), grab(True)
gap = 10
out = QImage(normal.width() * 2 + gap, normal.height(), QImage.Format.Format_RGB32)
out.fill(Qt.GlobalColor.darkGray)
p = QPainter(out)
p.drawImage(0, 0, normal)
p.drawImage(normal.width() + gap, 0, norm)
p.end()
out = out.scaled(out.width() * 3, out.height() * 3,
                 transformMode=Qt.TransformationMode.FastTransformation)
here = os.path.dirname(os.path.abspath(__file__))
out.save(os.path.join(here, os.environ.get("OUT", "normalize_after.png")))
