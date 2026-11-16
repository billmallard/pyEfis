#  SPDX-License-Identifier: GPL-2.0-or-later
"""Capture sheet for the autopilot_panel (AFC3, AER-5807).

Renders the real widget, both layouts, in a fixed set of reported states, on
an in-memory FIX database (tests/mock_db, no gateway). Run from the repo root:

    QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. python3 \
        docs/aer-5807-evidence/make_sheet.py --out docs/aer-5807-evidence
"""

import argparse
import os
import platform
import sys

import tests.mock_db.client
import tests.mock_db.scheduler

sys.modules["pyavtools.fix.client"] = tests.mock_db.client
sys.modules["pyavtools.scheduler"] = tests.mock_db.scheduler

from PyQt6.QtCore import QRect, Qt                      # noqa: E402
from PyQt6.QtGui import QColor, QFont, QImage, QPainter  # noqa: E402
from PyQt6.QtWidgets import QApplication                 # noqa: E402

import pyavtools.fix as fix                              # noqa: E402

KEYS = {
    "VSSEL": ("int", -30000, 30000, 0, 0),
    "IASSEL": ("float", 0.0, 999.9, 0.0, 0),
    "APCMD": ("str", None, None, "", 0),
    "APCMDSEQ": ("int", 0, 2147483647, 0, 0),
    "APENG": ("bool", None, None, False, 2000),
    "FDENG": ("bool", None, None, False, 2000),
    "YDENG": ("bool", None, None, False, 2000),
    "APLAT": ("str", None, None, "", 2000),
    "APLATARM": ("str", None, None, "", 2000),
    "APVERT": ("str", None, None, "", 2000),
    "APVERTARM": ("str", None, None, "", 2000),
    "APALTCAP": ("bool", None, None, False, 2000),
    "APCAPS": ("str", None, None, "", 2000),
    "APMSG": ("str", None, None, "", 2000),
    "HEADBUG": ("float", 0.0, 359.9, 0.0, 0),
    "ALTSEL": ("int", -1000, 60000, 0, 0),
    "HEAD": ("float", 0.0, 359.9, 0.0, 0),
    "VS": ("float", -30000, 30000, 0.0, 0),
    "IAS": ("float", 0.0, 999.0, 0.0, 0),
    "ALT": ("float", -2000, 60000, 0.0, 0),
}
CAPS = "AP,FD,YD,LVL,HDG,NAV,APR,IAS,VNAV,VS,ALT,DISC"
BASE = dict(APENG=False, FDENG=False, YDENG=False, APLAT="", APLATARM="",
            APVERT="", APVERTARM="", APALTCAP=False, APCAPS=CAPS, APMSG="",
            HEADBUG=270.0, VSSEL=500, IASSEL=0.0, ALTSEL=8500, HEAD=268.0,
            VS=0.0, IAS=112.0, ALT=6020.0)

# (caption, values, extra) -- extra: "press:<KEY>[:<seconds>]" or "stale".
SCENES = [
    ("1 all off: autopilot idle, every mode available", {}, None),
    ("2 AP + FD + YD on, HDG and VS active, ALT armed, NAV armed",
     dict(APENG=True, FDENG=True, YDENG=True, APLAT="HDG", APLATARM="GPS",
          APVERT="VS", APVERTARM="ALT"), None),
    ("3 coupled ILS: LOC (NAV) and GS (APR) active, IAS box set",
     dict(APENG=True, FDENG=True, YDENG=True, APLAT="LOC", APVERT="GS",
          IASSEL=90.0), None),
    ("4 IAS climb: IAS active (box accented), ALT armed",
     dict(APENG=True, FDENG=True, APLAT="HDG", APVERT="IAS",
          APVERTARM="ALT", IASSEL=95.0), None),
    ("5 LVL engaged", dict(APENG=True, FDENG=True, APLAT="LVL",
                           APVERT="LVL"), None),
    ("6 NAV pressed 0.3 s ago, no change yet: pending (border flash on)",
     dict(APENG=True, FDENG=True, APLAT="HDG", APVERT="ALT"), "press:NAV:0.1"),
    ("7 NAV not taken after 2 s: amber + APMSG",
     dict(APENG=True, FDENG=True, APLAT="HDG", APVERT="ALT",
          APMSG="NAV: NO NAV SOURCE"), "press:NAV:2.2"),
    ("8 partial source: APCAPS lacks APR, YD, VNAV, IAS (greyed, not hidden)",
     dict(APENG=True, APLAT="HDG", APVERT="ALT",
          APCAPS="AP,FD,LVL,HDG,NAV,VS,ALT,DISC"), None),
    ("9 state keys old: NO AUTOPILOT DATA", dict(APENG=True, APLAT="HDG"),
     "stale"),
]


def define():
    fix.initialize({"main": {"FixServer": "localhost", "FixPort": "3490"}})
    for key, (dtype, lo, hi, initial, tol) in KEYS.items():
        fix.db.define_item(key, key, dtype, lo, hi, "", tol, "")
        fix.db.set_value(key, initial)
        item = fix.db.get_item(key)
        item.old = item.bad = item.fail = False


def render(layout, size, values, extra):
    from pyefis.instruments import autopilot as ap
    for k, v in dict(BASE, **values).items():
        fix.db.set_value(k, v)
    for k in KEYS:
        fix.db.get_item(k).old = False
    w = ap.AutopilotPanel(None, font_family="DejaVu Sans")
    w.setPanelLayout(layout)
    clock = [100.0]
    w._clock = lambda: clock[0]
    w.resize(*size)
    if extra and extra.startswith("press:"):
        parts = extra.split(":")
        w.press(parts[1])
        clock[0] += float(parts[2])
    if extra == "stale":
        fix.db.get_item("APLAT").old = True
    img = QImage(w.size(), QImage.Format.Format_ARGB32)
    img.fill(QColor(0, 0, 0))
    w.render(img)
    w._timer.stop()
    w.deleteLater()
    return img


def sheet(layout, size, out):
    cap_h = 26
    pad = 12
    imgs = [(c, render(layout, size, v, e)) for c, v, e in SCENES]
    W = size[0] + 2 * pad
    H = sum(i.height() + cap_h + pad for _, i in imgs) + pad + 30
    page = QImage(W, H, QImage.Format.Format_ARGB32)
    page.fill(QColor(40, 40, 40))
    p = QPainter(page)
    f = QFont("DejaVu Sans")
    f.setPixelSize(15)
    p.setFont(f)
    p.setPen(QColor(230, 230, 230))
    stamp = "autopilot_panel layout=%s %dx%d  host=%s  rev=%s" % (
        layout, size[0], size[1], platform.node(),
        os.environ.get("SHEET_REV", "?"))
    p.drawText(QRect(pad, 4, W - 2 * pad, 24), Qt.AlignmentFlag.AlignLeft, stamp)
    y = 30
    for cap, img in imgs:
        p.drawText(QRect(pad, y, W - 2 * pad, cap_h),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   cap)
        y += cap_h
        p.drawImage(pad, y, img)
        y += img.height() + pad
    p.end()
    page.save(out)
    print(out)


def main():
    ap_ = argparse.ArgumentParser()
    ap_.add_argument("--out", default=".")
    args = ap_.parse_args()
    app = QApplication.instance() or QApplication(sys.argv)  # noqa: F841
    define()
    sheet("full", (640, 260), os.path.join(args.out, "sheet_full.png"))
    sheet("compact", (900, 110), os.path.join(args.out, "sheet_compact.png"))


if __name__ == "__main__":
    main()
