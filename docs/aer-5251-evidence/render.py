"""Evidence renders for pyEfis #319 / AER-5251.

Paints the attitude widget (SVS off) at horizon_position 68 and 1248x1200,
banked, on a black view background (what the live display shows past the
sky/ground rectangles), and writes one PNG per bank. Run through pytest so
the repo's mock FIX database fixture is available:

  OUT_TAG=before QT_QPA_PLATFORM=offscreen PYTHONPATH=src \
      python -m pytest docs/aer-5251-evidence/render.py --no-cov -q
"""
import os

import pytest
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import QApplication

from pyefis.instruments import ai

_HERE = os.path.dirname(os.path.abspath(__file__))


@pytest.mark.parametrize("bank", [30, -30, 60])
def test_render(fix, qtbot, bank):
    QApplication.instance() or QApplication([])
    for key in ("PITCH", "ROLL", "ALAT", "TAS"):
        item = fix.db.get_item(key)
        item.old = item.bad = item.fail = False
    widget = ai.AI()
    qtbot.addWidget(widget)
    widget.horizon_position = 68
    widget.resize(1248, 1200)
    widget.show()
    qtbot.waitExposed(widget)
    widget.setBackgroundBrush(QBrush(QColor(0, 0, 0)))
    widget._pitchAngle = 0.0
    widget._rollAngle = bank
    widget.redraw()
    tag = os.environ.get("OUT_TAG", "out")
    img = widget.viewport().grab().toImage()
    img.save(os.path.join(_HERE, f"{tag}_hp68_bank{bank:+d}.png"))
