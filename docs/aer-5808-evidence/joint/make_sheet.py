#  SPDX-License-Identifier: GPL-2.0-or-later
"""AER-5808: contact sheet and top-band zoom from the joint frames (README.md).

Usage: python make_sheet.py <dir with the joint PNGs and .json sidecars>
"""
import json
import os
import sys

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QImage, QPainter
from PyQt6.QtWidgets import QApplication

app = QApplication(sys.argv)
D = sys.argv[1]
SCENES = ["ksba_final", "mtn_climb", "bank_turn", "ksba_disc"]
STYLES = ["single_cue", "cross_pointer"]
S, CAP, PAD = 0.5, 34, 10
W, H = int(1248 * S), int(1200 * S)


def font(px):
    f = QFont("DejaVu Sans")
    f.setPixelSize(px)
    return f


sheet = QImage(PAD + len(STYLES) * (W + PAD),
               PAD + len(SCENES) * (H + CAP + PAD), QImage.Format.Format_RGB32)
sheet.fill(QColor("#202020"))
p = QPainter(sheet)
p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
for r, sc in enumerate(SCENES):
    for c, st in enumerate(STYLES):
        img = QImage(os.path.join(D, f"{sc}_{st}.png"))
        cap = json.load(open(os.path.join(D, f"{sc}_{st}.png.json")))["caption"]
        x, y = PAD + c * (W + PAD), PAD + r * (H + CAP + PAD)
        p.setFont(font(15))
        p.setPen(QColor("#d0d0d0"))
        p.drawText(QRectF(x, y, W, CAP), Qt.AlignmentFlag.AlignVCenter,
                   f"{cap}  [{st}]")
        p.drawImage(QRectF(x, y + CAP, W, H), img)
p.end()
sheet.save(os.path.join(D, "contact.png"))

# Top band at full size (1:1): the strip, the bank scale and the FD cue.
BAND = (100, 0, 1048, 280)
zoom = QImage(PAD + len(STYLES) * (BAND[2] + PAD), PAD + 2 * (BAND[3] + PAD),
              QImage.Format.Format_RGB32)
zoom.fill(QColor("#202020"))
p = QPainter(zoom)
for r, sc in enumerate(["mtn_climb", "ksba_final"]):
    for c, st in enumerate(STYLES):
        img = QImage(os.path.join(D, f"{sc}_{st}.png")).copy(*BAND)
        p.drawImage(PAD + c * (BAND[2] + PAD), PAD + r * (BAND[3] + PAD), img)
p.end()
zoom.save(os.path.join(D, "top_band.png"))
print("wrote contact.png, top_band.png")
