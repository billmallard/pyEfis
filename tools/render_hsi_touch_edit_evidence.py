#!/usr/bin/env python3
#  SPDX-License-Identifier: GPL-2.0-or-later
"""Evidence renders for HSI touch-select HDG / CRS (pyEfis #309, TK2).

Renders the HSI at the Pi 5 panel's native size (45 x 39 cells of the
1920x1200, 200 x 110 grid = 432 x 425 px, the live Pi options) with
``touch_edit: true``, in each layout that shows the readouts:

- **rest, VLOC1**: the dim at-rest edit icon on HDG and on CRS.
- **HDG focused**: reached by a real synthetic tap on the HDG readout through
  ``EncoderController``, then two inner-knob clicks and one outer-ring click
  (HEADBUG 120 -> 132).
- **CRS focused, VLOC1**: a tap on CRS, then a push, which centres the CDI by
  setting NAV1CRS to VOR1BRG (45 -> 77).
- **rest, GPS**: CRS carries no icon, because it cannot be selected on GPS.

Plus the ``corners`` label fix: the plain source label before (drawn under the
HDG box) and after.

Every state is reached through the widget's own mouse and knob handling; the
script asserts the FIX values it expects, so a render that does not show the
behaviour fails instead of saving.

Writes ``sheet_1x.png`` (actual size) and ``focus_zoom3x.png`` (the readouts,
nearest-neighbour 3x) to the output directory.

    QT_QPA_PLATFORM=offscreen PYTHONPATH=src python3 tools/render_hsi_touch_edit_evidence.py OUTDIR
"""

import os
import sys
import time

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "src"))

from tools import render_instrument as ri  # noqa: E402  (installs the mock FIX db)

import pyavtools.fix as fix  # noqa: E402
from PyQt6.QtCore import QPoint, QRect, Qt, QTimer, qRound  # noqa: E402
from PyQt6.QtGui import QColor, QFont, QImage, QPainter  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QWidget  # noqa: E402

PANEL_W, PANEL_H, COLS, ROWS = 1920, 1200, 200, 110
HSI_W, HSI_H = round(45 * PANEL_W / COLS), round(39 * PANEL_H / ROWS)
LAYOUTS = ("top_panel", "corners", "split")
STATES = ("rest", "hdg", "crs", "gps")
NAMES = {"rest": "at rest, VLOC1", "hdg": "HDG focused (120 -> 132)",
         "crs": "CRS focused, push (45 -> 77)", "gps": "at rest, GPS"}


def _settle(app, n=30):
    for _ in range(n):
        app.processEvents()
        time.sleep(0.01)


class _Host(QWidget):
    """A minimal screen: owns the EncoderController the HSI finds by walking
    up its parents, exactly as on a real Screen."""

    def __init__(self):
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
        p.setColor(self.backgroundRole(), QColor(0, 0, 0))
        self.setPalette(p)

    def encoderChanged(self, value=0):
        self.encoder_controller.changed(value)


def _seed(navsrc):
    for key, val in (("HEAD", 87.0), ("HEADBUG", 120.0), ("COURSE", 45.0),
                     ("NAVSRC", float(navsrc)), ("NAVTYPE", 1.0),
                     ("NAV1CRS", 45.0), ("NAV2CRS", 200.0), ("GPSCRS", 70.0),
                     ("VOR1BRG", 77.0), ("VOR2BRG", 301.0)):
        hi = 3.0 if key in ("NAVSRC", "NAVTYPE") else 359.9
        fix.db.define_item(key, key, "float", 0.0, hi, "deg", 50000, "")
        fix.db.set_value(key, val)
        it = fix.db.get_item(key)
        it.bad = it.fail = it.old = False


def _expect(key, value):
    got = fix.db.get_item(key).value
    assert got == value, "%s is %r, expected %r" % (key, got, value)


def render(app, layout, state, old_label=False):
    from pyefis.instruments import edit_focus
    from pyefis.instruments.hsi import HSI

    _seed(2 if state == "gps" else 0)
    edit_focus.set_at_rest_hint(True)          # the default (TK1, AER-3922)
    host = _Host()
    host.resize(HSI_W, HSI_H)
    h = HSI(host, cdi_enabled=True, gsi_enabled=True,
            font_family="DejaVu Sans Condensed")
    if old_label:      # the label placement before this change, for comparison
        h._source_label_baseline = lambda fm: qRound(h.fontSize * 1.2)
    # Live Pi options (managed_MAP_CTL_TEST.yaml), minus the font family.
    for k, v in dict(bg_opacity=30, heading_bug_enabled=True, needle_width=2,
                     track_indicator_enabled=True, depth_rings=False,
                     shadow_enabled=True, center_symbol="aircraft",
                     readout_layout=layout, touch_edit=True).items():
        setattr(h, k, v)
    h.setGeometry(0, 0, HSI_W, HSI_H)
    host.instruments[0] = h
    host.show()
    _settle(app, 50)
    h.viewport().repaint()
    _settle(app)
    ctl = host.encoder_controller
    if state in ("hdg", "crs"):
        box = h._edit_rects[state][0]
        QTest.mouseClick(h.viewport(), Qt.MouseButton.LeftButton,
                         pos=box.center().toPoint())
        assert h._edit_field == state, "tap on %s did not focus it" % state
        if state == "hdg":
            ctl.changed(1)
            ctl.changed(1)
            ctl.outer_changed(1)
            _expect("HEADBUG", 132.0)
        else:
            ctl.button_changed(True)
            _expect("NAV1CRS", 77.0)
            _expect("COURSE", 45.0)            # never written directly
        _settle(app)
    if state == "gps":
        assert not h._field_editable("crs")
    img = host.grab().toImage()
    ctl.release_focus()
    host.close()
    edit_focus.set_at_rest_hint(False)
    return img, h


def main(outdir):
    os.makedirs(outdir, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    ri._load_fonts()
    ri._setup_fix()
    import pyefis.hmi as hmi
    if hmi.actions is None:
        hmi.initialize({})

    imgs, rects = {}, {}
    for lay in LAYOUTS:
        for s in STATES:
            imgs[(lay, s)], w = render(app, lay, s)
            rects[(lay, s)] = {f: r[0] for f, r in w._edit_rects.items()}
    before, _w = render(app, "corners", "rest", old_label=True)

    pad, label_h = 16, 22
    font = QFont("DejaVu Sans")
    font.setPixelSize(13)
    cols = len(STATES)
    sheet_w = pad + (cols + 1) * (HSI_W + pad)
    sheet_h = pad + len(LAYOUTS) * (label_h + HSI_H + pad)
    sheet = QImage(sheet_w, sheet_h, QImage.Format.Format_RGB32)
    sheet.fill(QColor(40, 40, 40))
    p = QPainter(sheet)
    p.setFont(font)
    p.setPen(QColor(230, 230, 230))
    for r, lay in enumerate(LAYOUTS):
        y = pad + r * (label_h + HSI_H + pad) + label_h
        for c, s in enumerate(STATES):
            x = pad + c * (HSI_W + pad)
            p.drawText(x, y - 6, "%s: %s" % (lay, NAMES[s]))
            p.drawImage(x, y, imgs[(lay, s)])
    x = pad + cols * (HSI_W + pad)
    y = pad + label_h
    p.drawText(x, y - 6, "corners, BEFORE: source label under HDG")
    p.drawImage(x, y, before)
    y += HSI_H + pad + label_h
    p.drawText(x, y - 6, "corners, AFTER: label below HDG")
    p.drawImage(x, y, imgs[("corners", "rest")])
    p.end()
    sheet.save(os.path.join(outdir, "sheet_1x.png"))

    # The readouts themselves, 3x nearest-neighbour: one strip per layout.
    z, m = 3, 14
    crops = []
    for lay in LAYOUTS:
        row = []
        for s in STATES:
            for f in ("hdg", "crs"):
                b = rects[(lay, s)][f].toAlignedRect().adjusted(-m, -m, m, m)
                b = b.intersected(QRect(0, 0, HSI_W, HSI_H))
                row.append(("%s %s" % (s, f.upper()), imgs[(lay, s)].copy(b)))
        crops.append((lay, row))
    cw = max(img.width() for _l, row in crops for _n, img in row) * z
    ch = max(img.height() for _l, row in crops for _n, img in row) * z
    zoom = QImage(pad + 8 * (cw + pad), pad + len(crops) * (label_h + ch + pad),
                  QImage.Format.Format_RGB32)
    zoom.fill(QColor(40, 40, 40))
    p = QPainter(zoom)
    p.setFont(font)
    p.setPen(QColor(230, 230, 230))
    for r, (lay, row) in enumerate(crops):
        y = pad + r * (label_h + ch + pad) + label_h
        for c, (name, img) in enumerate(row):
            x = pad + c * (cw + pad)
            p.drawText(x, y - 6, "%s: %s" % (lay, name))
            p.drawImage(x, y, img.scaled(img.width() * z, img.height() * z,
                                         Qt.AspectRatioMode.IgnoreAspectRatio,
                                         Qt.TransformationMode.FastTransformation))
    p.end()
    zoom.save(os.path.join(outdir, "focus_zoom3x.png"))
    print("hsi %dx%d, %d renders -> %s" % (HSI_W, HSI_H, len(imgs) + 1, outdir))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "hsi_touch_edit_evidence")
