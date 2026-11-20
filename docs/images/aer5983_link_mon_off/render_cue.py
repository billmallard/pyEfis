#!/usr/bin/env python3
"""Render the proposed LINK MON OFF cue (AER-5983) over a composed PFD.

Uses the real non-GL attitude indicator and tapes on the mock FIX database,
then the real fix_watchdog cue widget over them, at 800x480 and 1024x600.
Run from the repo root:  QT_QPA_PLATFORM=offscreen python <this file>
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "src"), os.path.join(ROOT, "tools")]

import render_instrument as ri  # noqa: E402  (installs the mock FIX db)
from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication, QWidget  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)
ri._load_fonts()
ri._setup_fix()

from pyefis import fix_watchdog, kiosk  # noqa: E402
from pyefis.instruments.ai.ai_widget import AI  # noqa: E402
from pyefis.instruments.airspeed import Airspeed_Tape  # noqa: E402
from pyefis.instruments.altimeter import Altimeter_Tape  # noqa: E402


def compose(w, h, demo):
    win = QWidget()
    win.setStyleSheet("background: black")
    win.resize(w, h)
    ai = AI(win)
    ai.setGeometry(0, 0, w, h)
    tw = int(w * 0.12)
    asi = Airspeed_Tape(win)
    asi.setGeometry(int(w * 0.05), int(h * 0.15), tw, int(h * 0.7))
    alt = Altimeter_Tape(win)
    alt.setGeometry(w - int(w * 0.05) - tw, int(h * 0.15), tw, int(h * 0.7))
    if demo:
        class Live:  # a DEMO marking that is lit, to show the two never overlap
            value, old, bad, fail = True, False, False, False
            def __getattr__(self, name):
                return type("S", (), {"__getitem__": lambda s, k: s,
                                      "connect": lambda s, f: None})()
        kiosk.DemoMarking(win, Live())
    fix_watchdog.show_off_cue(win, fix_watchdog.OFF_NO_PING_KEY)
    win.show()
    for _ in range(5):
        app.processEvents()
    return win.grab()


for (w, h) in ((800, 480), (1024, 600)):
    compose(w, h, False).save(os.path.join(HERE, "pfd_%dx%d.png" % (w, h)))
compose(800, 480, True).save(os.path.join(HERE, "pfd_800x480_with_demo.png"))
img = compose(800, 480, False)
crop = img.copy(250, 0, 300, 70)
crop.scaled(900, 210, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation).save(
    os.path.join(HERE, "cue_crop_3x.png"))
print("wrote", sorted(f for f in os.listdir(HERE) if f.endswith(".png")))
