"""CERT1f (AER-6134) offscreen renders of the HSI with HEAD valid and one nav
fault at a time: CDI failed, GSI failed, COURSE bad, COURSE failed. HEAD failed
is the last column, for contrast. CDI and GSI are enabled, so each fault drops
its own symbols. No gateway: uses tests/mock_db. Adapted from
docs/aer-5894-evidence/render_hsi.py.

  render_hsi.py strip <out.png>    # rose row over arc row, one column per case

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
CASES = (
    ("all valid", None),
    ("CDI fail", "setCdiFail"),
    ("GSI fail", "setGsiFail"),
    ("COURSE bad", "setCourseBad"),
    ("COURSE fail", "setCourseFail"),
    ("HEAD fail", "setHeadFail"),
)


def _fix():
    import conftest
    fx = conftest.fix
    fn = getattr(fx, "_get_wrapped_function", None)
    fn = fn() if fn else getattr(fx, "__pytest_wrapped__").obj
    return next(fn())


def render(fix, orientation, setter):
    from pyefis.instruments import hsi
    w = hsi.HSI(cdi_enabled=True, gsi_enabled=True)
    w.orientation = orientation
    w.resize(*SIZE)
    w.show()
    app.processEvents()
    for k in ("Course", "Cdi", "Gsi", "Head"):
        for f in ("Old", "Bad", "Fail"):
            setattr(w, "_%s%s" % (k, f), False)
    w.setHeading(90.0)
    w.setCoursePointer(120.0)
    w.setCdi(0.5)
    w.setGsi(-0.5)
    w.changeFail()
    if setter:
        getattr(w, setter)(True)
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
    W = len(CASES) * SIZE[0] + (len(CASES) - 1) * pad
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
        for i, (label, setter) in enumerate(CASES):
            x = i * (SIZE[0] + pad)
            p.drawText(QRectF(x, y, SIZE[0], cap),
                       int(Qt.AlignmentFlag.AlignCenter),
                       "%s, %s" % ("rose" if orientation != "arc" else "arc", label))
            p.drawImage(x, y + cap, render(fix, orientation, setter))
    p.end()
    sheet.save(out)
    print("wrote", out)


if __name__ == "__main__":
    if sys.argv[1] == "strip":
        strip(sys.argv[2])
