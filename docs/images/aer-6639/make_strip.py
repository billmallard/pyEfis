"""Tile the AER-6639 bench frames: one row per run, one column per moment.

    python make_strip.py <frames-dir> <out-dir>

<frames-dir> holds exp3-hdg/, exp3-baro/ (dev) and fix-hdg/, fix-baro/
(the fix), each as written by touch_after_screenshot.sh."""
import os
import sys

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter

COLS = [("after_usr1_7s", "after SIGUSR1"), ("touched", "touched +1.5 s"),
        ("timed_out", "+13.5 s (focus timed out)")]
W, H, LABEL = 640, 360, 28


def strip(frames, rows, out):
    img = QImage(W * len(COLS), (H + LABEL) * len(rows),
                 QImage.Format.Format_RGB32)
    img.fill(QColor(0, 0, 0))
    p = QPainter(img)
    f = QFont()
    f.setPixelSize(18)
    p.setFont(f)
    for r, (run, title) in enumerate(rows):
        for c, (name, col) in enumerate(COLS):
            x, y = c * W, r * (H + LABEL)
            src = QImage(os.path.join(frames, run, name + ".png"))
            p.drawImage(QRectF(x, y + LABEL, W, H), src)
            p.setPen(QColor(255, 255, 255))
            p.drawText(QRectF(x + 6, y, W - 12, LABEL),
                       int(Qt.AlignmentFlag.AlignVCenter), "%s: %s" % (title, col))
    p.end()
    img.save(out)


if __name__ == "__main__":
    app = QGuiApplication(sys.argv[:1])
    frames, out = sys.argv[1], sys.argv[2]
    strip(frames, [("exp3-hdg", "dev"), ("fix-hdg", "fix")],
          os.path.join(out, "hdg_touch_dev_vs_fix.png"))
    strip(frames, [("exp3-baro", "dev"), ("fix-baro", "fix")],
          os.path.join(out, "baro_touch_dev_vs_fix.png"))
