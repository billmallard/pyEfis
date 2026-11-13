#!/usr/bin/env python3
#  SPDX-License-Identifier: GPL-2.0-or-later
"""Evidence renders for cyan, opt-in bearing pointers and the BRG tab
(HSIBRG1, AER-5548).

Renders the HSI at the Pi 5 panel's native size (432 x 425 px, the live Pi
options, as tools/render_hsi_touch_edit_evidence.py) in `top_panel`, with the
CDI on GPS and on VLOC1, and the bearing pointers stepped through the BRG tab
by real synthetic taps:

- **one pointer available**: Off (the default), then one tap, then the last
  source, so the tab shows `BRG OFF`, `BRG1 VOR1` and the end of the cycle.
- **both available**: pointer 1 and pointer 2 each tapped on, two rows.
- **corners**: no top panel, so the corner labels carry `1 OFF` and the tap.

Every state is reached through the widget's own mouse handling; the script
asserts what each tap must have written, so a render that does not show the
behaviour fails instead of saving.

Writes ``sheet_1x.png`` and ``tab_zoom3x.png`` (the tab, nearest-neighbour 3x).

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
CDI = {"GPS": 2.0, "VLOC1": 0.0}
# (name, layout, pointers available, taps as (pointer, count))
STATES = (
    ("BRG off (default)", "top_panel", (1,), ()),
    ("BRG1 one tap", "top_panel", (1,), ((1, 1),)),
    ("BRG1 two taps", "top_panel", (1,), ((1, 2),)),
    ("BRG1 + BRG2 on", "top_panel", (1, 2), ((1, 1), (2, 2))),
    ("corners, BRG off", "corners", (1, 2), ()),
)


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


def render(app, cdi, layout, pointers, taps):
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
                     source_auto_color=True, readout_layout=layout).items():
        setattr(h, k, v)
    for n in pointers:
        setattr(h, "bearing%d_enabled" % n, True)
    h.setGeometry(0, 0, HSI_W, HSI_H)
    host.show()
    _settle(app, 50)
    h.viewport().repaint()
    _settle(app)
    assert not any(h._brgOn.values()), "a pointer was on before any tap"
    for n, count in taps:
        for _ in range(count):
            rects = h._brg_tab_rects if layout == "top_panel" else h._brg_label_rect
            _tap(h, rects[n])
            _route_bearings()
            h.viewport().repaint()
            _settle(app)
        cycle = h._bearing_cycle()
        assert CDI[cdi] not in cycle
        want = cycle[count - 1]
        got = fix.db.get_item("BRG%dSRC" % n).value
        assert h._brgOn[n] and got == want, (cdi, n, count, got, want)
    for n in (1, 2):
        if h._bearing_visible(n):
            assert h._bearing_color(n) == QColor("#00ffff")
    img = host.grab().toImage()
    tab = dict(h._brg_tab_rects)
    host.close()
    return img, tab


def main(outdir):
    os.makedirs(outdir, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    ri._load_fonts()
    ri._setup_fix()
    import pyefis.hmi as hmi
    if hmi.actions is None:
        hmi.initialize({})

    imgs, tabs = {}, {}
    for cdi in CDI:
        for name, layout, pointers, taps in STATES:
            imgs[(cdi, name)], tabs[(cdi, name)] = render(
                app, cdi, layout, pointers, taps)

    pad, label_h = 16, 22
    font = QFont("DejaVu Sans")
    font.setPixelSize(13)
    sheet = QImage(pad + len(STATES) * (HSI_W + pad),
                   pad + len(CDI) * (label_h + HSI_H + pad),
                   QImage.Format.Format_RGB32)
    sheet.fill(QColor(40, 40, 40))
    p = QPainter(sheet)
    p.setFont(font)
    p.setPen(QColor(230, 230, 230))
    for r, cdi in enumerate(CDI):
        y = pad + r * (label_h + HSI_H + pad) + label_h
        for c, (name, *_rest) in enumerate(STATES):
            x = pad + c * (HSI_W + pad)
            p.drawText(x, y - 6, "CDI %s: %s" % (cdi, name))
            p.drawImage(x, y, imgs[(cdi, name)])
    p.end()
    sheet.save(os.path.join(outdir, "sheet_1x.png"))

    # The BRG tab, 3x nearest-neighbour, every top_panel state.
    z, m = 3, 10
    crops = []
    for cdi in CDI:
        for name, layout, *_rest in STATES:
            if layout != "top_panel":
                continue
            rs = tabs[(cdi, name)].values()
            x0 = min(r[0] for r in rs) - m * 4
            y0 = min(r[1] for r in rs) - m
            x1 = max(r[0] + r[2] for r in rs) + m
            y1 = max(r[1] + r[3] for r in rs) + m
            b = QRect(int(x0), int(y0), int(x1 - x0), int(y1 - y0))
            b = b.intersected(QRect(0, 0, HSI_W, HSI_H))
            crops.append(("CDI %s: %s" % (cdi, name), imgs[(cdi, name)].copy(b)))
    cw = max(i.width() for _n, i in crops) * z
    ch = max(i.height() for _n, i in crops) * z
    per_row = 4
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
    zoom.save(os.path.join(outdir, "tab_zoom3x.png"))
    print("hsi %dx%d, %d renders -> %s" % (HSI_W, HSI_H, len(imgs), outdir))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "hsi_bearing_evidence")
