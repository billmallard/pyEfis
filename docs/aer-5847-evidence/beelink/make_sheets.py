"""Crop the Beelink frames into beelink_hsi_sheet.png and
beelink_tabs_zoom3x.png (AER-5847). Run from the repo root."""
import os
from PyQt6.QtGui import QGuiApplication, QImage, QPainter, QColor, QFont
from PyQt6.QtCore import QRect, Qt

E = "docs/aer-5847-evidence/beelink"
OUT = "docs/aer-5847-evidence"
CAP = {
    "gps_0_none": "GPS: NONE", "gps_1_brg1": "GPS: tap -> BRG 1",
    "gps_2_brg2": "GPS: tap -> BRG 2", "gps_3_both": "GPS: tap -> BOTH",
    "vloc1_drop_both_to_brg2": "NAVSRC -> VLOC1: BOTH drops to BRG 2",
    "vloc1_0_none": "VLOC1: tap -> NONE", "vloc1_1_brg2": "VLOC1: tap -> BRG 2",
    "vloc1_2_none_again": "VLOC1: tap -> NONE",
    "vloc2_drop_brg2_to_none": "BRG 2 on, NAVSRC -> VLOC2: NONE",
    "vloc2_1_brg1": "VLOC2: tap -> BRG 1", "vloc2_2_none_again": "VLOC2: tap -> NONE",
}
app = QGuiApplication([])
font = QFont("DejaVu Sans")
font.setPixelSize(13)
pad, lh = 12, 22

hsi = QRect(440, 640, 380, 400)
cols = 4
rows = (len(CAP) + cols - 1) // cols
sheet = QImage(pad + cols * (hsi.width() + pad), pad + rows * (lh + hsi.height() + pad),
               QImage.Format.Format_RGB32)
sheet.fill(QColor(40, 40, 40))
p = QPainter(sheet)
p.setFont(font)
p.setPen(QColor(230, 230, 230))
for i, (n, cap) in enumerate(CAP.items()):
    x = pad + (i % cols) * (hsi.width() + pad)
    y = pad + (i // cols) * (lh + hsi.height() + pad) + lh
    p.drawText(x, y - 6, cap)
    p.drawImage(x, y, QImage(os.path.join(E, n + "_glass.png")).copy(hsi))
p.end()
sheet.save(os.path.join(OUT, "beelink_hsi_sheet.png"))

tabs, z = QRect(468, 648, 322, 44), 3
pick = ["gps_0_none", "gps_1_brg1", "gps_2_brg2", "gps_3_both", "vloc1_1_brg2", "vloc2_1_brg1"]
zw, zh = tabs.width() * z, tabs.height() * z
zm = QImage(pad + 2 * (zw + pad), pad + 3 * (lh + zh + pad), QImage.Format.Format_RGB32)
zm.fill(QColor(40, 40, 40))
p = QPainter(zm)
p.setFont(font)
p.setPen(QColor(230, 230, 230))
for i, n in enumerate(pick):
    img = QImage(os.path.join(E, n + "_glass.png")).copy(tabs).scaled(
        zw, zh, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.FastTransformation)
    x = pad + (i % 2) * (zw + pad)
    y = pad + (i // 2) * (lh + zh + pad) + lh
    p.drawText(x, y - 6, CAP[n] + " (3x)")
    p.drawImage(x, y, img)
p.end()
zm.save(os.path.join(OUT, "beelink_tabs_zoom3x.png"))

# The two tab fills on the glass, measured on gps_3_both (both filled).
img = QImage(os.path.join(E, "gps_3_both_glass.png"))
mag = lambda c: c.red() > 200 and c.blue() > 200 and c.green() < 80
cyan = lambda c: c.green() > 200 and c.blue() > 200 and c.red() < 80
def xs(f): v = [x for x in range(440, 820) if f(QColor(img.pixel(x, 669)))]; return min(v), max(v)
def ys(f, x): v = [y for y in range(640, 700) if f(QColor(img.pixel(x, y)))]; return min(v), max(v)
s, b = xs(mag), xs(cyan)
centre = (s[1] + b[0]) / 2.0
print("source fill x %d-%d (%d px), y %d-%d | BRG fill x %d-%d (%d px), y %d-%d | "
      "outer insets from the panel centre %.1f / %.1f" % (
          s[0], s[1], s[1] - s[0] + 1, *ys(mag, s[0] + 5), b[0], b[1], b[1] - b[0] + 1,
          *ys(cyan, b[1] - 5), centre - s[0], b[1] - centre))
