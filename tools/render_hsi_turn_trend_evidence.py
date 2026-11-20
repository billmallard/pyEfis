#!/usr/bin/env python3
#  SPDX-License-Identifier: GPL-2.0-or-later
"""Evidence renders for the HSI turn-rate trend (ATT1b, AER-6076).

Renders the HSI at the Pi 5 panel's native size (432 x 425 px, the live Pi
options, as tools/render_hsi_bearing_evidence.py) at ROT = -3, -1.5, 0, +3
and +5 deg/s, in the `top_panel`, `corners` and `arc` presentations, plus
one column with ROT failed. Standard rate (3 deg/s) must end on the 18-deg
mark; 5 deg/s is past the 4 deg/s cap, so it stops at 24 deg with an
arrowhead. The script asserts the trend's shown state and length per cell,
so a render that does not show the behaviour fails instead of saving.

Writes ``sheet_1x.png``, ``top_zoom3x.png`` (the band above the rose,
nearest-neighbour 3x, for the standard-rate cells) and ``turn_rate_trend.png``
(the Pilot's Guide picture, docs/images/hsi/).

    QT_QPA_PLATFORM=offscreen PYTHONPATH=src python3 tools/render_hsi_turn_trend_evidence.py OUTDIR
"""

import os
import sys
import time

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "src"))

from tools import render_instrument as ri  # noqa: E402  (installs the mock FIX db)

import pyavtools.fix as fix  # noqa: E402
from PyQt6.QtCore import QRect  # noqa: E402
from PyQt6.QtGui import QColor, QFont, QImage, QPainter  # noqa: E402
from PyQt6.QtWidgets import QApplication, QWidget  # noqa: E402

PANEL_W, PANEL_H, COLS, ROWS = 1920, 1200, 200, 110
HSI_W, HSI_H = round(45 * PANEL_W / COLS), round(39 * PANEL_H / ROWS)
RATES = (-3.0, -1.5, 0.0, 3.0, 5.0, "fail")
VIEWS = (("top_panel", "heading_up"), ("corners", "heading_up"),
         ("top_panel", "arc"))


def _settle(app, n=30):
    for _ in range(n):
        app.processEvents()
        time.sleep(0.01)


def _seed(rot):
    for key, val in (("HEAD", 87.0), ("HEADBUG", 120.0), ("COURSE", 70.0),
                     ("NAVSRC", 2.0), ("NAVTYPE", 0.0), ("CDI", -0.3),
                     ("CDIV", 1.0), ("GSV", 0.0), ("TOFROM", 1.0),
                     ("TRACKM", 92.0), ("GS", 110.0),
                     ("ROT", 0.0 if rot == "fail" else rot)):
        lo, hi = {"CDI": (-1.0, 1.0), "ROT": (-3000.0, 3000.0),
                  "NAVSRC": (0.0, 3.0), "NAVTYPE": (0.0, 3.0),
                  "CDIV": (0.0, 1.0), "GSV": (0.0, 1.0), "TOFROM": (0.0, 2.0),
                  "GS": (0.0, 999.0)}.get(key, (0.0, 359.9))
        fix.db.define_item(key, key, "float", lo, hi, "", 50000, "")
        fix.db.set_value(key, val)
        it = fix.db.get_item(key)
        it.bad = it.old = False
        it.fail = key == "ROT" and rot == "fail"


def render(app, rot, layout, orientation):
    from pyefis.instruments.hsi import HSI

    _seed(rot)
    host = QWidget()
    host.setStyleSheet("background: black")
    host.resize(HSI_W, HSI_H)
    h = HSI(host, cdi_enabled=True, gsi_enabled=False,
            font_family="DejaVu Sans Condensed")
    for k, v in dict(bg_opacity=30, heading_bug_enabled=True, needle_width=2,
                     track_indicator_enabled=True, track_min_speed=20,
                     depth_rings=False, shadow_enabled=True,
                     center_symbol="aircraft", source_auto_color=True,
                     readout_layout=layout, orientation=orientation).items():
        setattr(h, k, v)
    h.setGeometry(0, 0, HSI_W, HSI_H)
    host.show()
    _settle(app, 50)
    h.viewport().repaint()
    _settle(app)
    assert not h._nav_flag_shown(), "a NAV flag would mislead the picture"
    if rot == "fail":
        assert not h._turn_trend_shown()
    else:
        assert h._turn_trend_shown()
        d, capped = h._turn_trend_deg()
        assert abs(d - max(-24.0, min(24.0, rot * 6.0))) < 1e-9, (rot, d)
        assert capped is (abs(rot) > 4.0)
    img = host.grab().toImage()
    top = None
    if orientation == "arc":
        cx, top_y, _own, half_w, _sag = h._arc_params()
        top = QRect(int(cx - half_w * 0.5), int(top_y - h.fontSize * 1.6),
                    int(half_w), int(h.fontSize * 3.0))
    else:
        rt = h._turn_trend_rose_radius()
        top = QRect(int(h.cx - rt * 0.5), int(h.cy - rt - h.fontSize * 1.2),
                    int(rt), int(h.fontSize * 3.0))
    host.close()
    return img, top


def main(outdir):
    os.makedirs(outdir, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    ri._load_fonts()
    ri._setup_fix()
    import pyefis.hmi as hmi
    if hmi.actions is None:
        hmi.initialize({})

    imgs = {}
    for view in VIEWS:
        for rot in RATES:
            imgs[(view, rot)] = render(app, rot, *view)

    pad, label_h = 16, 22
    font = QFont("DejaVu Sans")
    font.setPixelSize(13)
    sheet = QImage(pad + len(RATES) * (HSI_W + pad),
                   pad + len(VIEWS) * (label_h + HSI_H + pad),
                   QImage.Format.Format_RGB32)
    sheet.fill(QColor(40, 40, 40))
    p = QPainter(sheet)
    p.setFont(font)
    p.setPen(QColor(230, 230, 230))
    for r, view in enumerate(VIEWS):
        y = pad + r * (label_h + HSI_H + pad) + label_h
        for c, rot in enumerate(RATES):
            x = pad + c * (HSI_W + pad)
            what = "ROT failed" if rot == "fail" else "ROT %+.1f deg/s" % rot
            name = view[1] if view[1] == "arc" else view[0]
            p.drawText(x, y - 6, "%s: %s" % (name, what))
            p.drawImage(x, y, imgs[(view, rot)][0])
    p.end()
    sheet.save(os.path.join(outdir, "sheet_1x.png"))

    z = 3
    crops = []
    for view in VIEWS:
        for rot in (-3.0, 3.0):
            img, box = imgs[(view, rot)]
            name = view[1] if view[1] == "arc" else view[0]
            crops.append(("%s ROT %+.0f" % (name, rot), img.copy(box)))
    cw = max(i.width() for _n, i in crops) * z
    ch = max(i.height() for _n, i in crops) * z
    zoom = QImage(pad + 2 * (cw + pad), pad + len(VIEWS) * (label_h + ch + pad),
                  QImage.Format.Format_RGB32)
    zoom.fill(QColor(40, 40, 40))
    p = QPainter(zoom)
    p.setFont(font)
    p.setPen(QColor(230, 230, 230))
    for i, (name, img) in enumerate(crops):
        r, c = divmod(i, 2)
        x = pad + c * (cw + pad)
        y = pad + r * (label_h + ch + pad) + label_h
        p.drawText(x, y - 6, name + " (3x nearest)")
        p.drawImage(x, y, img.scaled(img.width() * z, img.height() * z))
    p.end()
    zoom.save(os.path.join(outdir, "top_zoom3x.png"))

    # The Pilot's Guide picture (docs/images/hsi/turn_rate_trend.png):
    # standard rate left and right on the rose, and right in the arc view.
    cells = [(VIEWS[0], -3.0, "Rose: standard rate left"),
             (VIEWS[1], 3.0, "Rose (corners): standard rate right"),
             (VIEWS[2], 3.0, "Arc view: standard rate right")]
    guide = QImage(pad + len(cells) * (HSI_W + pad), pad + label_h + HSI_H + pad,
                   QImage.Format.Format_RGB32)
    guide.fill(QColor(40, 40, 40))
    p = QPainter(guide)
    p.setFont(font)
    p.setPen(QColor(230, 230, 230))
    for c, (view, rot, name) in enumerate(cells):
        x = pad + c * (HSI_W + pad)
        p.drawText(x, pad + label_h - 6, name)
        p.drawImage(x, pad + label_h, imgs[(view, rot)][0])
    p.end()
    guide.save(os.path.join(outdir, "turn_rate_trend.png"))
    print("wrote", outdir)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
