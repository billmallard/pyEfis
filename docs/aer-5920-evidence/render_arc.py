"""HSIARC1 (AER-5920) offscreen renders of the arc HSI at headings 120, 123
and 127.5, heading live, CDI/GSI absent, COURSE valid. No gateway: uses
tests/mock_db. Adapted from docs/aer-5894-evidence/render_hsi.py.

  render_arc.py row <out.png>                      # one row, the tree on PYTHONPATH
  render_arc.py sheet <before.png> <after.png> <out.png>

Run with PYTHONPATH=src:. and QT_QPA_PLATFORM=offscreen from a pyEfis tree:
a dev tree for the before row, the branch for the after row. `row` prints the
path of the widget module it imported, as provenance.
"""
import sys

import tests.mock_db.client
import tests.mock_db.scheduler
sys.modules["pyavtools.fix.client"] = tests.mock_db.client
sys.modules["pyavtools.scheduler"] = tests.mock_db.scheduler

from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QColor, QFont, QImage, QPainter
from PyQt6.QtWidgets import QApplication

app = QApplication(sys.argv)
BG = QColor(51, 51, 51)
SIZE = (340, 405)        # the HSI's box on the Beelink PFD (1920x1080)
HEADINGS = (120.0, 123.0, 127.5)
PAD, CAP = 16, 28


def _fix():
    import conftest
    fx = conftest.fix
    fn = getattr(fx, "_get_wrapped_function", None)
    fn = fn() if fn else getattr(fx, "__pytest_wrapped__").obj
    return next(fn())


def render(heading):
    from pyefis.instruments import hsi
    w = hsi.HSI(cdi_enabled=False, gsi_enabled=False)
    w.orientation = "arc"
    w.resize(*SIZE)
    w.show()
    app.processEvents()
    w._CourseOld = w._CourseBad = w._CourseFail = False
    for f in ("Old", "Bad", "Fail"):
        setattr(w, "_Head" + f, False)
    w.setHeading(heading)
    app.processEvents()
    img = QImage(SIZE[0], SIZE[1], QImage.Format.Format_ARGB32)
    img.fill(BG)
    w.viewport().render(img)
    w.hide()
    return img


def _caption(p, x, y, w, text):
    f = QFont("DejaVu Sans")
    f.setPixelSize(18)
    p.setFont(f)
    p.setPen(QColor(255, 255, 255))
    p.drawText(QRectF(x, y, w, CAP), int(Qt.AlignmentFlag.AlignCenter), text)


def row(out):
    _fix()
    from pyefis.instruments import hsi
    print("widget module:", hsi.__file__)
    W = len(HEADINGS) * SIZE[0] + (len(HEADINGS) - 1) * PAD
    sheet = QImage(W, SIZE[1] + CAP, QImage.Format.Format_ARGB32)
    sheet.fill(QColor(0, 0, 0))
    p = QPainter(sheet)
    for i, h in enumerate(HEADINGS):
        x = i * (SIZE[0] + PAD)
        _caption(p, x, 0, SIZE[0], "heading %g" % h)
        p.drawImage(x, CAP, render(h))
    p.end()
    sheet.save(out)


def sheet(before, after, out):
    rows = [(QImage(before), "before (dev)"), (QImage(after), "after (HSIARC1)")]
    W = rows[0][0].width()
    H = sum(r.height() + CAP for r, _ in rows) + PAD
    img = QImage(W, H, QImage.Format.Format_ARGB32)
    img.fill(QColor(0, 0, 0))
    p = QPainter(img)
    y = 0
    for r, label in rows:
        _caption(p, 0, y, W, label)
        p.drawImage(0, y + CAP, r)
        y += r.height() + CAP + PAD
    p.end()
    img.save(out)


if __name__ == "__main__":
    if sys.argv[1] == "row":
        row(sys.argv[2])
    else:
        sheet(*sys.argv[2:5])
