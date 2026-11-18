"""CERT1e (AER-5894) offscreen renders of the HSI with HEAD live, expired (old),
suspect (bad) or failed, on the rose and the arc. CDI and GSI are absent and
COURSE is valid, so the compass numerals show whenever the heading is valid: the
bench panel's COURSE is invalid, which hides them in every bench frame. No
gateway: uses tests/mock_db. Adapted from docs/aer-5269-evidence/render_tapes.py.

  render_hsi.py strip <out.png>          # rose row over arc row, live/old/bad/fail

Run with PYTHONPATH=src:. and QT_QPA_PLATFORM=offscreen from a pyEfis tree:
a dev tree for the before, the branch for the after. The script prints the
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
MODES = ("live", "old", "bad", "fail")


def _fix():
    import conftest
    fx = conftest.fix
    fn = getattr(fx, "_get_wrapped_function", None)
    fn = fn() if fn else getattr(fx, "__pytest_wrapped__").obj
    return next(fn())


def render(fix, orientation, mode):
    from pyefis.instruments import hsi
    w = hsi.HSI(cdi_enabled=False, gsi_enabled=False)
    w.heading_bug_enabled = True
    w.orientation = orientation
    w.resize(*SIZE)
    w.show()
    app.processEvents()
    w._CourseOld = w._CourseBad = w._CourseFail = False
    for f in ("Old", "Bad", "Fail"):
        setattr(w, "_Head" + f, False)
    w.setHeading(90.0)
    w._hdgBug = 0.0 if orientation != "arc" else 120.0
    if mode != "live":
        getattr(w, "setHead" + mode.capitalize())(True)
    app.processEvents()
    img = QImage(SIZE[0], SIZE[1], QImage.Format.Format_ARGB32)
    img.fill(BG)
    w.viewport().render(img)
    w.hide()
    return img


def strip(out):
    fix = _fix()
    from pyefis.instruments import hsi
    print("widget module:", hsi.__file__)
    pad, cap = 16, 28
    W = len(MODES) * SIZE[0] + (len(MODES) - 1) * pad
    H = 2 * (SIZE[1] + cap) + pad
    sheet = QImage(W, H, QImage.Format.Format_ARGB32)
    sheet.fill(QColor(0, 0, 0))
    p = QPainter(sheet)
    f = QFont("DejaVu Sans")
    f.setPixelSize(18)
    p.setFont(f)
    p.setPen(QColor(255, 255, 255))
    for r, orientation in enumerate(("heading_up", "arc")):
        y = r * (SIZE[1] + cap + pad)
        for i, mode in enumerate(MODES):
            x = i * (SIZE[0] + pad)
            p.drawText(QRectF(x, y, SIZE[0], cap),
                       int(Qt.AlignmentFlag.AlignCenter),
                       "%s, HEAD %s" % ("rose" if orientation != "arc" else "arc", mode))
            p.drawImage(x, y + cap, render(fix, orientation, mode))
    p.end()
    sheet.save(out)
    print("wrote", out)


if __name__ == "__main__":
    if sys.argv[1] == "strip":
        strip(sys.argv[2])
