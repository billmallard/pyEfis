"""Compare the dev and branch strip frames pixel for pixel, and build one
strip image per bench: a row per pose, columns svs | symbology | none, each
cell the branch frame (the dev frame is identical wherever the table says
0 differing pixels).

    python compare_strips.py <out-dir> <strip.png> [<label>]
"""
import os
import sys
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter

POSES = tuple(os.environ.get("STRIP_POSES",
                             "coastal mountains approach final").split())
MODES = tuple(os.environ.get("STRIP_MODES", "svs symbology none").split())
SCALE = 0.5


def load(path):
    img = QImage(str(path))
    return None if img.isNull() else img.convertToFormat(
        QImage.Format.Format_RGB32)


def differing_pixels(a, b):
    if a.size() != b.size():
        return -1
    pa, pb = a.constBits(), b.constBits()
    pa.setsize(a.sizeInBytes())
    pb.setsize(b.sizeInBytes())
    ra, rb = bytes(pa), bytes(pb)
    if ra == rb:
        return 0
    return sum(1 for i in range(0, len(ra), 4) if ra[i:i + 3] != rb[i:i + 3])


def main(out, strip, label=""):
    out = Path(out)
    app = QGuiApplication.instance() or QGuiApplication([])  # noqa: F841
    rows, failed = [], False
    for pose in POSES:
        for mode in MODES:
            d = load(out / "dev" / f"{pose}-{mode}.png")
            b = load(out / "branch" / f"{pose}-{mode}.png")
            if d is None or b is None:
                n = "missing"
                failed = True
            else:
                n = differing_pixels(d, b)
                failed |= n != 0
            rows.append((pose, mode, n, b))
            print(f"{pose:10s} {mode:10s} differing pixels: {n}")

    cell = next(b for *_, b in rows if b is not None)
    cw, ch = int(cell.width() * SCALE), int(cell.height() * SCALE)
    head = 28
    img = QImage(cw * len(MODES), head + ch * len(POSES),
                 QImage.Format.Format_RGB32)
    img.fill(QColor(20, 20, 20))
    p = QPainter(img)
    p.setFont(QFont("DejaVu Sans", 11))
    p.setPen(QColor(230, 230, 230))
    for i, mode in enumerate(MODES):
        p.drawText(i * cw + 6, 19, f"{label} {mode}".strip())
    for k, (pose, mode, n, b) in enumerate(rows):
        r, c = divmod(k, len(MODES))
        x, y = c * cw, head + r * ch
        if b is not None:
            p.drawImage(x, y, b.scaled(
                cw, ch, Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
        p.fillRect(x, y + ch - 22, cw, 22, QColor(0, 0, 0, 170))
        p.drawText(x + 6, y + ch - 6, f"{pose}: dev vs branch differ by {n} px")
    p.end()
    img.save(str(strip))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
