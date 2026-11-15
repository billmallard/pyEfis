"""Render a VerticalBar whose highlight key is valid, then old (CERT2c, AER-5319).

Run from this repo's root; point PYTHONPATH's first entry at the src of the
checkout to render (this branch, or a dev worktree for the "before" image):
  QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. python3 docs/images/cert2c/render.py after.png
  QT_QPA_PLATFORM=offscreen PYTHONPATH=<dev>/src:. python3 docs/images/cert2c/render.py before.png
Left half: EGTMAX1 valid. Right half: EGTMAX1 old. 2x nearest-neighbour.
"""
import sys

import tests.mock_db.client
import tests.mock_db.scheduler

sys.modules["pyavtools.fix.client"] = tests.mock_db.client
sys.modules["pyavtools.scheduler"] = tests.mock_db.scheduler

from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtWidgets import QApplication

import pyavtools.fix as fix

app = QApplication([])
fix.initialize({"main": {"FixServer": "localhost", "FixPort": "3490"}})
from pyefis.instruments import gauges  # noqa: E402


def item(key):
    fix.db.define_item(key, key, "float", 0, 1000, "degF", 50000, "")
    i = fix.db.get_item(key)
    i.bad = i.fail = i.old = False
    i.value = 1350.0
    return i


bar, hl = item("EGT1"), item("EGTMAX1")
w = gauges.VerticalBar()
w.name = "EGT1"
w.highlight_key = "EGTMAX1"
w.setDbkey("EGT1")
w.resize(90, 300)
w.show()
frames = [w.grab()]
hl.old = True
frames.append(w.grab())
out = QImage(2 * 90 * 2, 300 * 2, QImage.Format.Format_RGB32)
p = QPainter(out)
for n, f in enumerate(frames):
    p.drawImage(n * 180, 0, f.toImage().scaled(180, 600))
p.end()
out.save(sys.argv[1])
