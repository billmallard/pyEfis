#  SPDX-License-Identifier: GPL-2.0-or-later
"""AFC5 evidence renders: flight director bars on the attitude indicator.

    QT_QPA_PLATFORM=offscreen python3 docs/aer-6052-evidence/render.py

Writes, beside this file:

- ``styles.png``: both styles (rows) for four commands (columns), on the
  classic and the garmin aircraft symbol.
- ``replay.png``: the real AFC2 X-Plane flight (sim-bench session
  bf3a33402db4) replayed into the real widget, one frame per moment, both
  styles. The bus is tests/instruments/ai/data/afc2_bf3a33402db4_fd_bus.csv.gz.

Offscreen (QPainter on a QImage), mock FIX database, no SVS terrain: not a GL
capture and not the live glass.
"""

import csv
import gzip
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path[:0] = [os.path.join(ROOT, "src"), ROOT]

import tests.mock_db.client  # noqa: E402
import tests.mock_db.scheduler  # noqa: E402

sys.modules["pyavtools.fix.client"] = tests.mock_db.client
sys.modules["pyavtools.scheduler"] = tests.mock_db.scheduler

from PyQt6.QtCore import QRectF, Qt  # noqa: E402
from PyQt6.QtGui import QColor, QFont, QImage, QPainter  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

import pyavtools.fix as fix  # noqa: E402

W, H = 400, 300
CAP = 40
FLIGHT = os.path.join(ROOT, "tests/instruments/ai/data/"
                            "afc2_bf3a33402db4_fd_bus.csv.gz")

app = QApplication.instance() or QApplication(sys.argv)
fix.initialize({"main": {"FixServer": "localhost", "FixPort": "3490"}})
for key, dtype, lo, hi in (("PITCH", "float", -90, 90),
                           ("ROLL", "float", -180, 180),
                           ("ALAT", "float", -1, 1), ("TAS", "float", 0, 500),
                           ("FDENG", "bool", 0, 1),
                           ("FDPITCH", "float", -90, 90),
                           ("FDROLL", "float", -180, 180),
                           ("APLAT", "str", None, None),
                           ("APVERT", "str", None, None),
                           ("APLATARM", "str", None, None),
                           ("APVERTARM", "str", None, None)):
    fix.db.define_item(key, key, dtype, lo, hi, "", 1000, "")

from pyefis.instruments.ai import AI  # noqa: E402


def put(key, value, old=False):
    fix.db.set_value(key, value)
    item = fix.db.get_item(key)
    item.old, item.bad, item.fail = old, False, False


def widget(style, symbol="classic"):
    w = AI()
    w.fd_style = style
    w.aircraft_symbol = symbol
    w.resize(W, H)
    w.show()
    app.processEvents()
    return w


def frame(w):
    w.redraw()
    app.processEvents()
    return w.grab().toImage()


def sheet(cells, cols, path):
    rows = (len(cells) + cols - 1) // cols
    img = QImage(cols * W, rows * (H + CAP), QImage.Format.Format_RGB32)
    img.fill(QColor(24, 24, 24))
    p = QPainter(img)
    f = QFont("DejaVu Sans")
    f.setPixelSize(13)
    p.setFont(f)
    for i, (cap, im) in enumerate(cells):
        x, y = (i % cols) * W, (i // cols) * (H + CAP)
        p.drawImage(x, y + CAP, im)
        p.setPen(QColor(Qt.GlobalColor.white))
        p.drawText(QRectF(x + 6, y + 2, W - 12, CAP - 4),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                   | Qt.TextFlag.TextWordWrap, cap)
    p.end()
    img.save(path)
    print("wrote", path)


def styles():
    for key, value in (("ALAT", 0.0), ("TAS", 110.0), ("FDENG", True)):
        put(key, value)
    commands = [
        ("satisfied: pitch 2, roll 0, command 2/0", 2.0, 0.0, 2.0, 0.0),
        ("climb: command pitch +6 from 0", 0.0, 0.0, 6.0, 0.0),
        ("turn: command right bank 20 from level", 0.0, 0.0, 0.0, 20.0),
        ("both: command 4 up, 15 left from 0/10 right", 0.0, 10.0, 4.0, -15.0),
    ]
    cells = []
    for style, symbol in (("single_cue", "classic"), ("cross_pointer", "classic"),
                          ("single_cue", "garmin"), ("cross_pointer", "garmin")):
        w = widget(style, symbol)
        for cap, pitch, roll, fdp, fdr in commands:
            for key, value in (("PITCH", pitch), ("ROLL", roll),
                               ("FDPITCH", fdp), ("FDROLL", fdr)):
                put(key, value)
            cells.append((f"{style} / {symbol}: {cap}", frame(w)))
        w.close()
    sheet(cells, 4, os.path.join(HERE, "styles.png"))


MOMENTS = [
    (6.0, "FD off: the AP is not yet coupled"),
    (26.0, "HDG"),
    (44.0, "VS engaged, ALT armed: command pitch up"),
    (70.0, "VS climb"),
    (97.5, "ALT captured"),
    (147.0, "NAV (GPS) captured"),
    (177.5, "AP disconnected, FD still on"),
    (179.8, "X-Plane stopped sending: keys old, bars removed"),
]


def replay():
    rows = []
    with gzip.open(FLIGHT, "rt") as fh:
        for r in csv.DictReader(fh):
            rows.append((float(r["t_s"]), r["key"], r["value"], r["flags"]))
    cells = {s: [] for s in ("single_cue", "cross_pointer")}
    for style in cells:
        put("ALAT", 0.0)
        put("TAS", 110.0)
        w = widget(style, "classic")
        state = {}
        todo = list(MOMENTS)
        for t, key, value, flags in rows:
            while todo and t >= todo[0][0]:
                mt, what = todo.pop(0)
                cap = (f"{style} t={mt:.1f}s {what} | "
                       f"{state.get('APLAT', '')}/{state.get('APVERT', '')} "
                       f"FD {state.get('FDPITCH', '?')}/{state.get('FDROLL', '?')} "
                       f"att {state.get('PITCH', '?')}/{state.get('ROLL', '?')}")
                cells[style].append((cap, frame(w)))
            item = fix.db.get_item(key)
            v = (value == "True" if item.dtype is bool
                 else float(value) if item.dtype is float else value)
            fix.db.set_value(key, v)
            item.old, item.bad, item.fail = (flags[i] == "1" for i in (1, 2, 3))
            state[key] = (value[:5] if item.dtype is float else value) + \
                ("(old)" if flags[1] == "1" else "")
        # Moments after the last logged row: nothing more arrived.
        for mt, what in todo:
            cells[style].append((f"{style} t={mt:.1f}s {what} | last: "
                                 f"FD {state.get('FDPITCH')} att "
                                 f"{state.get('PITCH')}", frame(w)))
        w.close()
    # Two rows: one per style.
    sheet(cells["single_cue"] + cells["cross_pointer"], len(MOMENTS),
          os.path.join(HERE, "replay.png"))


styles()
replay()
