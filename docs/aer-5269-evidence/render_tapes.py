"""CERT1b (AER-5269) offscreen renders of the four tapes (airspeed with its TAS
box, altitude, VSI trend tape, VSI_PFD) with IAS, ALT and VS live, expired
(old), suspect (bad) or failed. TAS stays live in every strip, so the TAS box
shows the CERT1b rule. No gateway: uses tests/mock_db. Adapted from
docs/aer-5178-evidence/render_tape_variants.py.

  render_tapes.py strip <live|old|bad|fail> <out.png>
  render_tapes.py sheet <out.png> <png> <caption> [<png> <caption> ...]

Run with PYTHONPATH=src:. and QT_QPA_PLATFORM=offscreen from a pyEfis tree:
a dev tree for the before, the branch for the after. The script prints the
path of the widget module it imported, as provenance.
"""
import sys

import tests.mock_db.client
import tests.mock_db.scheduler
sys.modules["pyavtools.fix.client"] = tests.mock_db.client
sys.modules["pyavtools.scheduler"] = tests.mock_db.scheduler

from unittest import mock
from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QColor, QFont, QImage, QPainter
from PyQt6.QtWidgets import QApplication

app = QApplication(sys.argv)
BG = QColor(51, 51, 51)
# Tape sizes as on the Beelink PFD (1920x1080, see docs/aer-5031-evidence).
SIZES = {"asi": (120, 590), "alt": (115, 590), "vsi": (65, 400),
         "vsi_pfd": (50, 400)}


def strip(mode, out):
    # The test suite's FIX db (conftest.py `fix` fixture) defines IAS, ALT, VS
    # and friends with their aux values; reuse it rather than copy it.
    import conftest
    fx = conftest.fix
    fn = getattr(fx, "_get_wrapped_function", None)
    fn = fn() if fn else getattr(fx, "__pytest_wrapped__").obj
    fix = next(fn())
    from pyefis.instruments import airspeed, altimeter, vsi
    print("widgets from", airspeed.__file__)
    ias = fix.db.get_item("IAS")
    for k, v in (("Vs0", 50), ("Vs", 55), ("Vfe", 85), ("Vno", 130), ("Vne", 150)):
        ias.set_aux_value(k, v)
    for k, v in (("IAS", 110), ("TAS", 115), ("ALT", 4510), ("VS", 500)):
        it = fix.db.get_item(k)
        it.value = v
        it.old = it.bad = it.fail = False
    a = airspeed.Airspeed_Tape(font_percent=None)
    b = altimeter.Altimeter_Tape(show_trend=False)
    c = vsi.Alt_Trend_Tape()
    c.myparent = mock.Mock(get_config_item=mock.Mock(return_value=0))
    d = vsi.VSI_PFD()
    widgets = [(a, SIZES["asi"]), (b, SIZES["alt"]), (c, SIZES["vsi"]),
               (d, SIZES["vsi_pfd"])]
    for w, (ww, hh) in widgets:
        w.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        w.resize(ww, hh)
        w.show()
    for _ in range(5):
        app.processEvents()
    if mode != "live":
        for k in ("IAS", "ALT", "VS"):
            setattr(fix.db.get_item(k), mode, True)
        for _ in range(5):
            app.processEvents()
    gap = 30
    img = QImage(sum(s[0] for _, s in widgets) + gap * 5, 620,
                 QImage.Format.Format_RGB32)
    img.fill(BG)
    p = QPainter(img)
    x = gap
    for w, (ww, hh) in widgets:
        w.repaint()
        app.processEvents()
        p.drawImage(x, (620 - hh) // 2, w.grab().toImage())
        x += ww + gap
    p.end()
    img.save(out)


def sheet(out, pairs):
    imgs = [(QImage(f), cap) for f, cap in pairs]
    cap_h = 34
    W = sum(i.width() for i, _ in imgs) + 20 * (len(imgs) + 1)
    H = max(i.height() for i, _ in imgs) + cap_h + 20
    s = QImage(W, H, QImage.Format.Format_RGB32)
    s.fill(QColor(20, 20, 20))
    p = QPainter(s)
    f = QFont("DejaVu Sans")
    f.setPixelSize(18)
    p.setFont(f)
    p.setPen(QColor(Qt.GlobalColor.white))
    x = 20
    for i, cap in imgs:
        p.drawText(QRectF(x, 6, i.width(), cap_h - 6),
                   int(Qt.AlignmentFlag.AlignCenter), cap)
        p.drawImage(x, cap_h, i)
        x += i.width() + 20
    p.end()
    s.save(out)


if __name__ == "__main__":
    if sys.argv[1] == "strip":
        strip(sys.argv[2], sys.argv[3])
    else:
        rest = sys.argv[3:]
        sheet(sys.argv[2], list(zip(rest[0::2], rest[1::2])))
