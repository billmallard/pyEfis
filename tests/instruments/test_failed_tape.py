"""CERT1a (AER-5178): a failed airspeed, altitude or VSI tape is unmistakable.

Before this change a failed tape kept drawing its scale numbers, coloured bands
and trend vector and showed the failure only as a small red XXX in the readout
box (pyEfis #411's "fixgw stopped 6 s" frame). These tests render the real
paintEvent and assert, for each tape, that a failed tape draws a red X corner to
corner, that the scale under it is blanked, and that both clear on recovery.
"""
from unittest import mock

import pytest
from PyQt6.QtGui import QColor

from pyefis.instruments import airspeed, altimeter, helpers, vsi

W, H = 120, 400


def _clear(item):
    item.old = False
    item.bad = False
    item.fail = False


def _parent(update_period=0):
    parent = mock.Mock()
    parent.get_config_item = mock.Mock(return_value=update_period)
    return parent


def _airspeed(fix):
    for k in ("IAS", "TAS"):
        _clear(fix.db.get_item(k))
    fix.db.get_item("IAS").value = 100
    w = airspeed.Airspeed_Tape(show_tas=False, show_trend=False)
    return w, fix.db.get_item("IAS")


def _altimeter(fix):
    _clear(fix.db.get_item("ALT"))
    fix.db.get_item("ALT").value = 4500
    w = altimeter.Altimeter_Tape(show_trend=False, show_baro=False,
                                 alt_bug_enabled=False)
    return w, fix.db.get_item("ALT")


def _vsi_tape(fix):
    _clear(fix.db.get_item("VS"))
    fix.db.get_item("VS").value = 500
    w = vsi.Alt_Trend_Tape()
    w.myparent = _parent()
    return w, fix.db.get_item("VS")


def _vsi_pfd(fix):
    _clear(fix.db.get_item("VS"))
    fix.db.get_item("VS").value = 500
    return vsi.VSI_PFD(), fix.db.get_item("VS")


TAPES = {
    "airspeed": _airspeed,
    "altimeter": _altimeter,
    "vsi_tape": _vsi_tape,
    "vsi_pfd": _vsi_pfd,
}


def _show(qtbot, w):
    qtbot.addWidget(w)
    w.resize(W, H)
    w.show()
    qtbot.waitExposed(w)


def _grab(qtbot, w):
    qtbot.wait(20)
    target = w.viewport() if hasattr(w, "viewport") else w
    return target.grab().toImage()


def _is_red(c):
    return c.red() > 200 and c.green() < 60 and c.blue() < 60


def _is_scale_ink(c):
    """White tick/label ink or a green/yellow band: anything that reads as a
    live scale."""
    white = c.red() > 150 and c.green() > 150 and c.blue() > 150
    green = c.green() > 100 and c.green() > c.red() + 40 and c.blue() < 80
    return white or green


def _x_region(w, img):
    """The rect the X spans, in image pixels."""
    if isinstance(w, vsi.Alt_Trend_Tape):
        return (0, int(w.top_margin) + 1,
                img.width() - w.RIGHT_MARGIN, img.height())
    return (0, 0, img.width(), img.height())


def _diagonal_red_fraction(w, img):
    x0, y0, x1, y1 = _x_region(w, img)
    hits = total = 0
    for i in range(1, 20):
        t = i / 20.0
        for (ax, ay, bx, by) in ((x0, y0, x1, y1), (x0, y1, x1, y0)):
            x = int(ax + (bx - ax) * t)
            y = int(ay + (by - ay) * t)
            x = min(max(x, 0), img.width() - 1)
            y = min(max(y, 0), img.height() - 1)
            total += 1
            hits += _is_red(img.pixelColor(x, y))
    return hits / total


def _scale_ink_count(w, img):
    x0, y0, x1, y1 = _x_region(w, img)
    return sum(_is_scale_ink(img.pixelColor(x, y))
               for y in range(y0, y1, 2) for x in range(x0, x1, 2))


@pytest.mark.parametrize("name", sorted(TAPES))
def test_failed_tape_draws_red_x_and_blanks_scale(fix, qtbot, name):
    w, item = TAPES[name](fix)
    _show(qtbot, w)

    live = _grab(qtbot, w)
    assert _diagonal_red_fraction(w, live) < 0.5, "live tape already shows an X"
    assert _scale_ink_count(w, live) > 0, "control: the live scale draws ink"

    item.fail = True
    failed = _grab(qtbot, w)
    assert _diagonal_red_fraction(w, failed) > 0.9, \
        "a failed tape must carry a red X corner to corner"
    assert _scale_ink_count(w, failed) == 0, \
        "the scale under a failed tape must be blanked"

    item.fail = False
    back = _grab(qtbot, w)
    assert _diagonal_red_fraction(w, back) < 0.5, "the X must clear on recovery"
    assert _scale_ink_count(w, back) > 0, "the scale must return on recovery"


def test_failed_vsi_tape_keeps_its_header(fix, qtbot):
    """The trend tape keeps the "VSI" label and its red XXX readout above the X."""
    w, item = _vsi_tape(fix)
    _show(qtbot, w)
    item.fail = True
    img = _grab(qtbot, w)
    header = [img.pixelColor(x, y)
              for y in range(0, int(w.top_margin))
              for x in range(img.width())]
    assert any(_is_red(c) for c in header), "the red XXX readout is gone"
    # No scale label may peek out under the header (the top graduation label
    # straddles top_margin, so a crop at top_margin would leave half of it).
    shown = sorted(t.toPlainText() for t in w.scene.items()
                   if hasattr(t, "toPlainText") and t.isVisible())
    assert shown == ["VSI", "XXX"], shown


def test_failed_tape_x_stays_inside_rect(qtbot):
    """The stroke is inset, so no X pixel lands outside the rect it is given."""
    from PyQt6.QtGui import QImage, QPainter
    from PyQt6.QtCore import QRectF
    img = QImage(100, 300, QImage.Format.Format_ARGB32)
    img.fill(QColor(0, 0, 0, 0))
    p = QPainter(img)
    helpers.draw_failed_tape_x(p, QRectF(20, 50, 60, 200))
    p.end()
    for y in range(img.height()):
        for x in range(img.width()):
            if img.pixelColor(x, y).alpha():
                assert 20 <= x < 80 and 50 <= y < 250, (x, y)
