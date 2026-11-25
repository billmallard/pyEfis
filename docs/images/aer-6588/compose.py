#!/usr/bin/env python3
#  SPDX-License-Identifier: GPL-2.0-or-later
"""Compose the INS5 strips from two render_ins5_evidence.py output dirs.

    python3 compose.py OUT_DEV OUT_BRANCH DEST

One PNG per widget: a header row with the good frame (dev and branch are
byte-identical, which this script asserts), then one row per stale scene,
dev on the left and the branch on the right. The wind widget is upscaled
3x nearest-neighbour so its text can be read.
"""
import hashlib
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtCore import QRectF, Qt  # noqa: E402
from PyQt6.QtGui import QColor, QFont, QImage, QPainter  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

WIDGETS = {
    "wind": ["hwind_old"],
    "hsi": ["headbug_old", "headbug_fail", "gs_old"],
    "ai": ["track_old", "magvar_bad"],
    "map": ["lat_bad", "track_fail"],
    "mapcaution": ["alt_old"],
}
LABELS = {
    "hwind_old": "HWIND old", "headbug_old": "HEADBUG old",
    "headbug_fail": "HEADBUG fail", "gs_old": "GS old",
    "track_old": "TRACK old", "magvar_bad": "MAGVAR bad",
    "lat_bad": "LAT bad", "track_fail": "TRACK fail (ND)",
    "alt_old": "ALT old (caution mode)",
}
LABEL_H = 34
GAP = 12


def _sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _load(path, scale):
    img = QImage(path)
    if scale != 1:
        img = img.scaled(img.width() * scale, img.height() * scale,
                         Qt.AspectRatioMode.IgnoreAspectRatio,
                         Qt.TransformationMode.FastTransformation)
    return img


def compose(dev, branch, dest, widget):
    scale = 3 if widget == "wind" else 1
    good_dev = os.path.join(dev, "%s_good.png" % widget)
    good_br = os.path.join(branch, "%s_good.png" % widget)
    assert _sha(good_dev) == _sha(good_br), "%s good state differs" % widget
    good = _load(good_br, scale)
    cw, ch = good.width(), good.height()
    rows = WIDGETS[widget]
    W = 2 * cw + GAP
    H = (LABEL_H + ch + GAP) * (len(rows) + 1)
    out = QImage(W, H, QImage.Format.Format_RGB32)
    out.fill(QColor(24, 24, 24))
    p = QPainter(out)
    f = QFont("DejaVu Sans")
    f.setPixelSize(18)
    p.setFont(f)
    p.setPen(QColor(230, 230, 230))
    y = 0
    p.drawText(QRectF(4, y, W, LABEL_H), Qt.AlignmentFlag.AlignVCenter,
               "good source: dev and branch byte-identical")
    p.drawImage(0, y + LABEL_H, good)
    y += LABEL_H + ch + GAP
    for scene in rows:
        a = _load(os.path.join(dev, "%s_%s.png" % (widget, scene)), scale)
        b = _load(os.path.join(branch, "%s_%s.png" % (widget, scene)), scale)
        p.drawText(QRectF(4, y, cw, LABEL_H), Qt.AlignmentFlag.AlignVCenter,
                   "%s: dev" % LABELS[scene])
        p.drawText(QRectF(cw + GAP + 4, y, cw, LABEL_H),
                   Qt.AlignmentFlag.AlignVCenter,
                   "%s: branch" % LABELS[scene])
        p.drawImage(0, y + LABEL_H, a)
        p.drawImage(cw + GAP, y + LABEL_H, b)
        y += LABEL_H + ch + GAP
    p.end()
    path = os.path.join(dest, "%s_strip.png" % widget)
    out.save(path)
    print(_sha(path)[:12], path)


def main():
    dev, branch, dest = sys.argv[1:4]
    app = QApplication.instance() or QApplication(sys.argv[:1])  # noqa: F841
    os.makedirs(dest, exist_ok=True)
    for widget in WIDGETS:
        compose(dev, branch, dest, widget)


if __name__ == "__main__":
    main()
