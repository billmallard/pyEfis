#!/usr/bin/env python3
#  SPDX-License-Identifier: GPL-2.0-or-later
"""Evidence renders for the touch-select + knob-edit visual language (pyEfis #308).

Renders, at the Pi 5 panel's native pixel size (1920x1200 on a 200x110 grid):

1. A baro ``numeric_display`` (12 x 4 grid cells = 115 x 44 px) in three
   states, over black and over a sky colour: at rest with no hint, at rest
   with the dim hint (``editIconAtRest: true``), and focused. The focused
   state is reached by a real synthetic touch through ``EncoderController``,
   not by setting a flag.
2. The HSI (45 x 39 cells = 432 x 425 px, the live Pi options) with the same
   marks drawn on its HDG readout, in the live ``top_panel`` layout and in the
   ``corners`` layout, where the HDG box border is itself cyan. This is the
   colour-clash check. HSI wiring is TK2 (#309); here the marks are drawn by a
   subclass, through the same helper TK2 will call.

Writes ``sheet_1x.png`` (everything at actual size) and ``baro_zoom4x.png``
(the baro states, nearest-neighbour 4x) to the output directory.

    QT_QPA_PLATFORM=offscreen PYTHONPATH=src python3 tools/render_edit_focus_evidence.py OUTDIR
"""

import os
import sys
import time

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "src"))

from tools import render_instrument as ri  # noqa: E402  (installs the mock FIX db)

import pyavtools.fix as fix  # noqa: E402
from PyQt6.QtCore import QPoint, QRectF, Qt, QTimer  # noqa: E402
from PyQt6.QtGui import QColor, QFont, QImage, QPainter  # noqa: E402
from PyQt6.QtWidgets import QApplication, QWidget  # noqa: E402

PANEL_W, PANEL_H, COLS, ROWS = 1920, 1200, 200, 110
CELL_W, CELL_H = PANEL_W / COLS, PANEL_H / ROWS
BARO_W, BARO_H = round(12 * CELL_W), round(4 * CELL_H)
HSI_W, HSI_H = round(45 * CELL_W), round(39 * CELL_H)
SKY = QColor(150, 190, 235)


def _settle(app, n=30):
    for _ in range(n):
        app.processEvents()
        time.sleep(0.01)


class _Host(QWidget):
    """A minimal screen: owns an EncoderController the gauge finds by walking
    up its parents, exactly as on a real Screen."""

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


def render_baro(app, state, bg):
    from pyefis.instruments import edit_focus
    from pyefis.instruments.gauges import numeric
    edit_focus.set_at_rest_hint(state == "hint")
    host = _Host(bg)
    host.resize(BARO_W, BARO_H)
    g = numeric.NumericDisplay(host, font_family="DejaVu Sans Condensed")
    g.setDbkey("BARO")
    # The stock svs.yaml baro box options.
    g.font_mask = "XXXXXX"
    g.decimal_places = 2
    g.clipping = True
    g.encoder_set_real_time = True
    g.encoder_multiplier = 0.01
    g.touch_edit = True
    g.setupGauge()
    g.setGeometry(0, 0, BARO_W, BARO_H)
    host.instruments[0] = g
    host.show()
    _settle(app)
    if state == "focused":
        from PyQt6.QtTest import QTest
        QTest.mouseClick(g, Qt.MouseButton.LeftButton, pos=QPoint(BARO_W // 2, BARO_H // 2))
        assert g.encoder_selected, "touch did not focus the gauge"
        _settle(app)
    img = host.grab().toImage()
    host.encoder_controller.release_focus()
    host.close()
    edit_focus.set_at_rest_hint(False)
    return img


def render_hsi(app, layout, state):
    from pyefis.instruments import edit_focus
    from pyefis.instruments.hsi import HSI

    class MarkedHSI(HSI):
        def _draw_readout_panel(self, c, x, y, w, h, orientation, segments):
            super()._draw_readout_panel(c, x, y, w, h, orientation, segments)
            if segments and segments[0][0] == "HDG" and orientation == "h":
                cell = QRectF(x, y, w / len(segments), h)
                # Inside a sectioned panel the ring must fit the cell.
                edit_focus.draw_edit_marks(
                    c, edit_focus.inset_for_marks(cell), state == "focused")

        def _draw_readout_box(self, c, ax, ay, anchor, label, value, color):
            super()._draw_readout_box(c, ax, ay, anchor, label, value, color)
            if label == "HDG":
                bw, bh = self.fontSize * 3.6, self.fontSize * 2.4
                x = ax if anchor[0] == "l" else (ax - bw if anchor[0] == "r" else ax - bw / 2)
                y = ay if anchor[1] == "t" else (ay - bh if anchor[1] == "b" else ay - bh / 2)
                # A free-standing box: the ring goes OUTSIDE its cyan border.
                edit_focus.draw_edit_marks(c, QRectF(x, y, bw, bh), state == "focused")

    edit_focus.set_at_rest_hint(state == "hint")
    host = QWidget()
    host.setAutoFillBackground(True)
    pal = host.palette()
    pal.setColor(host.backgroundRole(), QColor(0, 0, 0))
    host.setPalette(pal)
    host.resize(HSI_W, HSI_H)
    h = MarkedHSI(host, cdi_enabled=True, gsi_enabled=True, font_family="DejaVu Sans Condensed")
    # Live Pi options (managed_MAP_CTL_TEST.yaml), minus the font family.
    for k, v in dict(bg_opacity=30, heading_bug_enabled=True, needle_width=2,
                     track_indicator_enabled=True, depth_rings=False,
                     shadow_enabled=True, center_symbol="aircraft",
                     readout_layout=layout).items():
        setattr(h, k, v)
    h.setGeometry(0, 0, HSI_W, HSI_H)
    host.show()
    _settle(app, 50)
    img = host.grab().toImage()
    host.close()
    edit_focus.set_at_rest_hint(False)
    return img


def main(outdir):
    os.makedirs(outdir, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    ri._load_fonts()
    ri._setup_fix()
    import pyefis.hmi as hmi
    if hmi.actions is None:
        hmi.initialize({})
    for key, val in (("BARO", 29.92), ("HEAD", 87.0), ("HEADBUG", 120.0),
                     ("COURSE", 70.0), ("NAVSRC", 2.0)):
        it = fix.db.get_item(key)
        fix.db.set_value(key, val)
        it.bad = it.fail = it.old = False

    states = ["rest", "hint", "focused"]
    baro = {(s, bgname): render_baro(app, s, bg)
            for s in states for bgname, bg in (("black", QColor(0, 0, 0)), ("sky", SKY))}
    hsi = {(lay, s): render_hsi(app, lay, s)
           for lay in ("top_panel", "corners") for s in ("hint", "focused")}

    pad, label_h = 16, 22
    font = QFont("DejaVu Sans")
    font.setPixelSize(13)

    # 1:1 sheet.
    col_w = max(BARO_W, 200)
    baro_block_w = len(states) * (col_w + pad)
    sheet_w = max(baro_block_w, 4 * (HSI_W + pad)) + pad
    sheet_h = pad + label_h + 2 * (BARO_H + pad) + label_h + HSI_H + label_h + pad
    sheet = QImage(sheet_w, sheet_h, QImage.Format.Format_RGB32)
    sheet.fill(QColor(40, 40, 40))
    p = QPainter(sheet)
    p.setFont(font)
    p.setPen(QColor(230, 230, 230))
    names = {"rest": "at rest, no hint", "hint": "at rest, dim hint", "focused": "focused (touched)"}
    y0 = pad + label_h
    for i, s in enumerate(states):
        x = pad + i * (col_w + pad)
        p.drawText(x, y0 - 6, names[s])
        p.drawImage(x, y0, baro[(s, "black")])
        p.drawImage(x, y0 + BARO_H + pad, baro[(s, "sky")])
    y1 = y0 + 2 * (BARO_H + pad) + label_h
    for i, key in enumerate([("top_panel", "hint"), ("top_panel", "focused"),
                             ("corners", "hint"), ("corners", "focused")]):
        x = pad + i * (HSI_W + pad)
        p.drawText(x, y1 - 6, "HSI %s, HDG %s" % (key[0], "hint" if key[1] == "hint" else "focused"))
        p.drawImage(x, y1, hsi[key])
    p.end()
    sheet.save(os.path.join(outdir, "sheet_1x.png"))

    # Baro states, 4x nearest-neighbour.
    z = 4
    zw, zh = BARO_W * z, BARO_H * z
    zoom = QImage(len(states) * (zw + pad) + pad, 2 * (zh + pad) + pad + label_h,
                  QImage.Format.Format_RGB32)
    zoom.fill(QColor(40, 40, 40))
    p = QPainter(zoom)
    p.setFont(font)
    p.setPen(QColor(230, 230, 230))
    for i, s in enumerate(states):
        x = pad + i * (zw + pad)
        p.drawText(x, pad + label_h - 6, names[s] + " (4x)")
        for j, bgname in enumerate(("black", "sky")):
            src = baro[(s, bgname)].scaled(zw, zh, Qt.AspectRatioMode.IgnoreAspectRatio,
                                           Qt.TransformationMode.FastTransformation)
            p.drawImage(x, pad + label_h + j * (zh + pad), src)
    p.end()
    zoom.save(os.path.join(outdir, "baro_zoom4x.png"))
    for s in states:
        baro[(s, "black")].save(os.path.join(outdir, "baro_%s_1x.png" % s))
    print("baro %dx%d, hsi %dx%d -> %s" % (BARO_W, BARO_H, HSI_W, HSI_H, outdir))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "edit_focus_evidence")
