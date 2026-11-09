"""Render AS_Trend_Tape in four IAS states for G74 / pyEfis #403.

Drives the IAS FIX item only (never the widget), with a hand-stepped clock,
then grabs the widget. Output: states.png beside this script, panels left to
right = accelerating 2.5 kt/s, steady IAS, decelerating 2.5 kt/s, IAS failed
(after the same deceleration).
"""
import os
import sys

_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path[:0] = [os.path.join(_ROOT, "src"), _ROOT]
import tests.mock_db.client
import tests.mock_db.scheduler
sys.modules["pyavtools.fix.client"] = tests.mock_db.client
sys.modules["pyavtools.scheduler"] = tests.mock_db.scheduler

from PyQt6.QtGui import QColor, QImage, QPainter
from PyQt6.QtWidgets import QApplication
import pyavtools.fix as fix

app = QApplication([])
fix.initialize({"main": {"FixServer": "localhost", "FixPort": "3490"}})
fix.db.define_item("IAS", "Indicated Airspeed", "float", 0, 1000, "knots", 2000, "")
from pyefis.instruments import vsi  # noqa: E402

W, H, GAP = 80, 400, 12


class Clock:
    t = 1000.0

    def __call__(self):
        return self.t


def panel(rate, steps, fail=False):
    item = fix.db.get_item("IAS")
    item.value = 100.0
    item.bad = item.old = item.fail = False
    w = vsi.AS_Trend_Tape()
    w._timer.stop()
    clock = Clock()
    w._clock = clock
    w.resize(W, H)
    w.show()
    app.processEvents()
    for _ in range(steps):
        clock.t += 0.1
        if rate:
            item.value = item.value + rate * 0.1
        else:
            w._sample()
    item.fail = fail
    app.processEvents()
    img = w.grab().toImage()
    w.close()
    return img


panels = [panel(2.5, 40), panel(0.0, 40), panel(-2.5, 40), panel(-2.5, 40, fail=True)]
out = QImage(len(panels) * W + (len(panels) - 1) * GAP, H, QImage.Format.Format_RGB32)
out.fill(QColor(64, 64, 64))
p = QPainter(out)
for i, img in enumerate(panels):
    p.drawImage(i * (W + GAP), 0, img)
p.end()
out.save(os.path.join(os.path.dirname(__file__), "states.png"))
print("wrote states.png")
