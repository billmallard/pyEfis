#!/usr/bin/env python3
#  SPDX-License-Identifier: GPL-2.0-or-later
"""Evidence renders for the one-button BRG tab (HSIBRG4, AER-5847; it
replaced the two-row tab of HSIBRG1, AER-5548).

Renders the HSI at the Pi 5 panel's native size (432 x 425 px, the live Pi
options, as tools/render_hsi_touch_edit_evidence.py) in `top_panel` with
both pointers available, the CDI on GPS, VLOC1 and VLOC2, and the tab
stepped through every state it offers there by real synthetic taps (GPS:
NONE, BRG 1, BRG 2, BOTH; VLOC1: NONE, BRG 2; VLOC2: NONE, BRG 1). A last
column per row is the `corners` layout, where the corner labels carry the
tap.

Every state is reached through the widget's own mouse handling, and the
script asserts the label, the pointers on and what each tap wrote to
BRGnSRC, so a render that does not show the behaviour fails instead of
saving. It also asserts the BRG tab is the source tab mirrored about the
panel's centre line, and prints both rectangles.

Writes ``sheet_1x.png`` and ``tabs_zoom3x.png`` (the source tab, the panel
and the BRG tab in one crop, nearest-neighbour 3x).

    QT_QPA_PLATFORM=offscreen PYTHONPATH=src python3 tools/render_hsi_bearing_evidence.py OUTDIR
"""

import os
import sys
import time

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "src"))

from tools import render_instrument as ri  # noqa: E402  (installs the mock FIX db)

import pyavtools.fix as fix  # noqa: E402
from PyQt6.QtCore import QPoint, QRect, Qt  # noqa: E402
from PyQt6.QtGui import QColor, QFont, QImage, QPainter  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QWidget  # noqa: E402

PANEL_W, PANEL_H, COLS, ROWS = 1920, 1200, 200, 110
HSI_W, HSI_H = round(45 * PANEL_W / COLS), round(39 * PANEL_H / ROWS)
CDI = {"GPS": 2.0, "VLOC1": 0.0, "VLOC2": 1.0}
#: The states the tab offers per CDI source, in tap order (HSIBRG4).
OFFERED = {"GPS": ("NONE", "BRG 1", "BRG 2", "BOTH"),
           "VLOC1": ("NONE", "BRG 2"),
           "VLOC2": ("NONE", "BRG 1")}
ON = {"NONE": (), "BRG 1": (1,), "BRG 2": (2,), "BOTH": (1, 2)}
COLS_PER_ROW = 5          # four tab states at most, then `corners`


def _settle(app, n=30):
    for _ in range(n):
        app.processEvents()
        time.sleep(0.01)


def _seed(navsrc):
    for key, val in (("HEAD", 87.0), ("HEADBUG", 120.0), ("COURSE", 70.0),
                     ("NAVSRC", navsrc), ("NAVTYPE", 0.0 if navsrc == 2 else 1.0),
                     ("CDI", -0.3), ("TOFROM", 1.0),
                     ("BRG1", 0.0), ("BRG2", 0.0),
                     ("BRG1SRC", 2.0), ("BRG2SRC", 0.0),
                     ("VOR1BRG", 40.0), ("VOR2BRG", 301.0), ("GPSBRG", 72.0)):
        hi = 3.0 if key in ("NAVSRC", "NAVTYPE", "BRG1SRC", "BRG2SRC",
                            "TOFROM") else 359.9
        lo = -1.0 if key == "CDI" else 0.0
        fix.db.define_item(key, key, "float", lo, hi, "deg", 50000, "")
        fix.db.set_value(key, val)
        it = fix.db.get_item(key)
        it.bad = it.fail = it.old = False


def _route_bearings():
    # The fix-gateway "select" stands in: BRGn follows its BRGnSRC.
    src = {0.0: "VOR1BRG", 1.0: "VOR2BRG", 2.0: "GPSBRG"}
    for n in (1, 2):
        sel = fix.db.get_item("BRG%dSRC" % n).value
        fix.db.set_value("BRG%d" % n, fix.db.get_item(src[sel]).value)


def _tap(h, rect):
    x, y, w, hh = rect
    QTest.mouseClick(h.viewport(), Qt.MouseButton.LeftButton,
                     pos=QPoint(int(x + w * 0.5), int(y + hh * 0.5)))


def render(app, cdi, layout, taps):
    """The HSI with both pointers available, the CDI on `cdi`, after `taps`
    taps on the BRG tab (top_panel) or on corner label 1 (corners)."""
    from pyefis.instruments.hsi import HSI

    _seed(CDI[cdi])
    host = QWidget()
    host.setStyleSheet("background: black")
    host.resize(HSI_W, HSI_H)
    h = HSI(host, cdi_enabled=True, gsi_enabled=True,
            font_family="DejaVu Sans Condensed")
    for k, v in dict(bg_opacity=30, heading_bug_enabled=True, needle_width=2,
                     track_indicator_enabled=True, depth_rings=False,
                     shadow_enabled=True, center_symbol="aircraft",
                     source_auto_color=True, readout_layout=layout,
                     bearing1_enabled=True, bearing2_enabled=True).items():
        setattr(h, k, v)
    h.setGeometry(0, 0, HSI_W, HSI_H)
    host.show()
    _settle(app, 50)
    h.viewport().repaint()
    _settle(app)
    assert h._bearing_tab_label() == "NONE", "a pointer was on before any tap"
    assert [st[0] for st in h._bearing_states()] == list(OFFERED[cdi])
    for _ in range(taps):
        if layout == "top_panel":
            rect = h._brg_tab_rect
        else:
            rect = next(r for r in (h._brg_label_rect[1], h._brg_label_rect[2])
                        if r is not None)
        _tap(h, rect)
        _route_bearings()
        h.viewport().repaint()
        _settle(app)
    label = OFFERED[cdi][taps % len(OFFERED[cdi])]
    assert h._bearing_tab_label() == label, (cdi, taps, h._bearing_tab_label())
    for n in (1, 2):
        assert h._brgOn[n] is (n in ON[label]), (cdi, label, n)
        if n in ON[label]:
            # Its VOR, never GPS, and never the CDI's own source.
            assert fix.db.get_item("BRG%dSRC" % n).value == n - 1
            assert n - 1 != CDI[cdi]
            assert h._bearing_visible(n)
            assert h._bearing_color(n) == QColor("#00ffff")
    img = host.grab().toImage()
    geo = None
    if layout == "top_panel":
        sx, sy, sw, sh = h._source_label_rect
        bx, by, bw, bh = h._brg_tab_rect
        centre = HSI_W / 2.0
        assert abs(bw - sw) < 1e-6 and abs(bh - sh) < 1e-6 and abs(by - sy) < 1e-6
        assert abs((bx + bw - centre) - (centre - sx)) < 1e-6
        geo = (h._source_label_rect, h._brg_tab_rect)
    host.close()
    return img, geo


def main(outdir):
    os.makedirs(outdir, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    ri._load_fonts()
    ri._setup_fix()
    import pyefis.hmi as hmi
    if hmi.actions is None:
        hmi.initialize({})

    imgs, geos = {}, {}
    for cdi in CDI:
        for taps, label in enumerate(OFFERED[cdi]):
            imgs[(cdi, label)], geos[(cdi, label)] = render(
                app, cdi, "top_panel", taps)
        imgs[(cdi, "corners")], _ = render(app, cdi, "corners", 0)

    pad, label_h = 16, 22
    font = QFont("DejaVu Sans")
    font.setPixelSize(13)
    sheet = QImage(pad + COLS_PER_ROW * (HSI_W + pad),
                   pad + len(CDI) * (label_h + HSI_H + pad),
                   QImage.Format.Format_RGB32)
    sheet.fill(QColor(40, 40, 40))
    p = QPainter(sheet)
    p.setFont(font)
    p.setPen(QColor(230, 230, 230))
    for r, cdi in enumerate(CDI):
        y = pad + r * (label_h + HSI_H + pad) + label_h
        cells = [(lbl, "tab %s" % lbl) for lbl in OFFERED[cdi]]
        cells += [None] * (COLS_PER_ROW - 1 - len(cells))
        cells.append(("corners", "corners, NONE"))
        for c, cell in enumerate(cells):
            if cell is None:
                continue
            x = pad + c * (HSI_W + pad)
            p.drawText(x, y - 6, "CDI %s: %s" % (cdi, cell[1]))
            p.drawImage(x, y, imgs[(cdi, cell[0])])
    p.end()
    sheet.save(os.path.join(outdir, "sheet_1x.png"))

    # Source tab, panel and BRG tab in one crop, 3x nearest-neighbour.
    z, m = 3, 6
    crops = []
    for cdi in CDI:
        for label in OFFERED[cdi]:
            (sx, sy, sw, sh), (bx, by, bw, bh) = geos[(cdi, label)]
            b = QRect(int(sx) - m, int(sy) - m * 3,
                      int(bx + bw - sx) + 2 * m, int(sh) + m * 6)
            b = b.intersected(QRect(0, 0, HSI_W, HSI_H))
            crops.append(("CDI %s: %s" % (cdi, label), imgs[(cdi, label)].copy(b)))
            print("CDI %-5s %-5s source tab x=%.2f y=%.2f w=%.2f h=%.2f | "
                  "BRG tab x=%.2f y=%.2f w=%.2f h=%.2f | insets from centre "
                  "%.2f / %.2f" % (cdi, label, sx, sy, sw, sh, bx, by, bw, bh,
                                   HSI_W / 2.0 - sx, bx + bw - HSI_W / 2.0))
    cw = max(i.width() for _n, i in crops) * z
    ch = max(i.height() for _n, i in crops) * z
    per_row = 2
    rows = (len(crops) + per_row - 1) // per_row
    zoom = QImage(pad + per_row * (cw + pad), pad + rows * (label_h + ch + pad),
                  QImage.Format.Format_RGB32)
    zoom.fill(QColor(40, 40, 40))
    p = QPainter(zoom)
    p.setFont(font)
    p.setPen(QColor(230, 230, 230))
    for i, (name, img) in enumerate(crops):
        x = pad + (i % per_row) * (cw + pad)
        y = pad + (i // per_row) * (label_h + ch + pad) + label_h
        p.drawText(x, y - 6, name)
        p.drawImage(x, y, img.scaled(img.width() * z, img.height() * z,
                                     Qt.AspectRatioMode.IgnoreAspectRatio,
                                     Qt.TransformationMode.FastTransformation))
    p.end()
    zoom.save(os.path.join(outdir, "tabs_zoom3x.png"))
    print("hsi %dx%d, %d renders -> %s" % (HSI_W, HSI_H, len(imgs), outdir))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "hsi_bearing_evidence")
