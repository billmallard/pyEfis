#!/usr/bin/env python3
#  SPDX-License-Identifier: GPL-2.0-or-later
"""Evidence renders for the altimeter tape baro setting box (pyEfis #311).

Renders the stock ALT tape (``includes/ahrs/svs.yaml``: 15 x 110 cells,
``font_percent: 0.24``, ``majorDiv: 100``, ``font_scale: 1.1``) at the Pi 5
panel's native pixel size (1920x1200 on a 200 x 110 grid = 144 x 1200 px),
over a sky colour standing in for the SVS behind the transparent tape.

States, left to right: inHg at rest (dim edit icon), inHg focused, hPa focused
after 3 inner-knob steps, the knob-walk highlight, and BARO failed. Focus is
reached by a real synthetic touch on the box through ``EncoderController``,
and the knob steps go through the controller too, not by setting flags.

Writes ``tape_full_1x.png`` (one whole tape, actual size), ``sheet_1x.png``
(the bottom of each tape, actual size) and ``sheet_zoom3x.png`` (the same,
nearest-neighbour 3x) to the output directory.

    QT_QPA_PLATFORM=offscreen PYTHONPATH=src python3 tools/render_baro_box_evidence.py OUTDIR
"""

import os
import sys
import time

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "src"))

from tools import render_instrument as ri  # noqa: E402  (installs the mock FIX db)

import pyavtools.fix as fix  # noqa: E402
from PyQt6.QtCore import QRect, Qt, QTimer  # noqa: E402
from PyQt6.QtGui import QColor, QFont, QImage, QPainter  # noqa: E402
from PyQt6.QtWidgets import QApplication, QWidget  # noqa: E402

PANEL_W, PANEL_H, COLS, ROWS = 1920, 1200, 200, 110
TAPE_W, TAPE_H = round(15 * PANEL_W / COLS), round(110 * PANEL_H / ROWS)
CROP_H = 220
SKY = QColor(150, 190, 235)


def _settle(app, n=30):
    for _ in range(n):
        app.processEvents()
        time.sleep(0.01)


class _Host(QWidget):
    """A minimal screen owning an EncoderController, found by the tape by
    walking up its parents exactly as on a real Screen."""

    def __init__(self, bg):
        super().__init__()
        from pyefis.screens.screenbuilder_encoder import EncoderController
        self.instruments = {}
        self.encoder_list = []
        self.encoder_list_sorted = []
        self.encoder_current_selection = None
        self.encoder_timeout = 600_000          # do not time out mid-render
        self.encoder_timestamp = 0
        self.encoder_control = False
        self.encoder_timer = QTimer(self)
        self.encoder = None
        self.encoder_button = None
        self.encoder_controller = EncoderController(self)
        self.setAutoFillBackground(True)
        p = self.palette()
        p.setColor(self.backgroundRole(), bg)
        self.setPalette(p)

    def encoderChanged(self, value=0):
        self.encoder_controller.changed(value)


def render_tape(app, state):
    from PyQt6.QtTest import QTest
    import pyefis.hmi as hmi
    from pyefis.instruments import altimeter, edit_focus
    from pyefis.screens import screenbuilder_options

    item = fix.db.get_item("BARO")
    fix.db.set_value("BARO", 29.92)
    item.bad = item.fail = item.old = False
    if state == "fail":
        item.fail = True
    edit_focus.set_at_rest_hint(True)          # the shipped default
    host = _Host(SKY)
    host.resize(TAPE_W, TAPE_H)
    t = altimeter.Altimeter_Tape(host, font_percent=0.24, majorDiv=100,
                                 font_scale=1.1,
                                 font_family="DejaVu Sans Condensed")
    t.setGeometry(0, 0, TAPE_W, TAPE_H)
    host.instruments[0] = t
    screenbuilder_options.configure_tape_baro(host)
    if state == "walk":
        host.encoder_list_sorted = [0]
        host.encoder_current_selection = 0
    host.encoder_controller.configure_inputs(fix)
    if state.startswith("hpa"):
        hmi.actions.trigger("Set Instrument Units", "Pressure:hPa")
    host.show()
    _settle(app)
    ctl = host.encoder_controller
    if state in ("focused", "hpa"):
        QTest.mouseClick(t.viewport(), Qt.MouseButton.LeftButton,
                         pos=t.baro_box_rect().center().toPoint())
        assert t.encoder_selected, "touch did not focus the baro box"
    if state == "hpa":
        for _ in range(3):
            ctl.changed(1)
        assert t.baro_text()[0] == "1016", t.baro_text()
    if state == "walk":
        ctl.changed(1)
        assert t._baro_walk
    _settle(app)
    img = host.grab().toImage()
    ctl.release_focus()
    if state.startswith("hpa"):
        hmi.actions.trigger("Set Instrument Units", "Pressure:inHg")
    host.close()
    item.fail = False
    return img


def main(outdir):
    os.makedirs(outdir, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    ri._load_fonts()
    ri._setup_fix()
    import pyefis.hmi as hmi
    if hmi.actions is None:
        hmi.initialize({})
    fix.db.set_value("ALT", 3500.0)
    alt = fix.db.get_item("ALT")
    alt.bad = alt.fail = alt.old = False

    states = [("hint", "inHg, at rest (dim icon)"),
              ("focused", "inHg, touched"),
              ("hpa", "hPa, touched, +3 steps"),
              ("walk", "knob walk"),
              ("fail", "BARO failed")]
    imgs = {s: render_tape(app, s) for s, _ in states}
    imgs["focused"].save(os.path.join(outdir, "tape_full_1x.png"))

    pad, label_h = 16, 22
    font = QFont("DejaVu Sans")
    font.setPixelSize(12)
    col_w = max(TAPE_W, 150)

    def sheet(scale):
        cw, ch = TAPE_W * scale, CROP_H * scale
        colw = max(cw, col_w)
        img = QImage(len(states) * (colw + pad) + pad, ch + 2 * pad + label_h,
                     QImage.Format.Format_RGB32)
        img.fill(QColor(40, 40, 40))
        p = QPainter(img)
        p.setFont(font)
        p.setPen(QColor(230, 230, 230))
        for i, (s, label) in enumerate(states):
            x = pad + i * (colw + pad)
            p.drawText(x, pad + label_h - 6, label)
            crop = imgs[s].copy(QRect(0, TAPE_H - CROP_H, TAPE_W, CROP_H))
            if scale != 1:
                crop = crop.scaled(cw, ch, Qt.AspectRatioMode.IgnoreAspectRatio,
                                   Qt.TransformationMode.FastTransformation)
            p.drawImage(x, pad + label_h, crop)
        p.end()
        return img

    sheet(1).save(os.path.join(outdir, "sheet_1x.png"))
    sheet(3).save(os.path.join(outdir, "sheet_zoom3x.png"))
    print("tape %dx%d -> %s" % (TAPE_W, TAPE_H, outdir))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "baro_box_evidence")
