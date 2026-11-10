"""CERT1a (AER-5178): a failed airspeed, altitude or VSI tape is unmistakable.

Before this change a failed tape kept drawing its scale numbers, coloured bands
and trend vector and showed the failure only as a small red XXX in the readout
box (pyEfis #411's "fixgw stopped 6 s" frame). These tests render the real
paintEvent and assert, for each tape, that a failed tape draws a red X corner to
corner, that the scale under it is blanked, and that both clear on recovery.

CERT1b (AER-5269): an expired key (`old`: its time-to-live ran out while
fix-gateway kept running, the likeliest field failure) gets the same look, and
a suspect key (`bad`) keeps its scale inside an amber frame. On `dev` before
CERT1b an old tape blanked only its readout digits and kept drawing its scale,
bands and trend at the frozen value, and a bad tape showed no cue at all.
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


def _is_amber(c):
    return c.red() > 200 and 130 < c.green() < 210 and c.blue() < 60


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


def _frame_amber_fraction(w, img):
    """Share of sample points on the four edges of the X region (2 px in)
    that are amber."""
    x0, y0, x1, y1 = _x_region(w, img)
    pts = []
    for i in range(1, 20):
        t = i / 20.0
        x = int(x0 + (x1 - x0) * t)
        y = int(y0 + (y1 - y0) * t)
        pts += [(x0 + 1, y), (x1 - 2, y), (x, y0 + 1), (x, y1 - 2)]
    return sum(_is_amber(img.pixelColor(x, y)) for x, y in pts) / len(pts)


def _readout_shows_failed(w):
    """The tape's own readout carries the failed annunciation (red XXX)."""
    if isinstance(w, vsi.Alt_Trend_Tape):
        return w.vstext.toPlainText() == "XXX"
    if isinstance(w, vsi.VSI_PFD):
        return True  # no readout of its own
    return w.numerical_display.fail


@pytest.mark.parametrize("flag", ["fail", "old"])
@pytest.mark.parametrize("name", sorted(TAPES))
def test_failed_tape_draws_red_x_and_blanks_scale(fix, qtbot, name, flag):
    w, item = TAPES[name](fix)
    _show(qtbot, w)

    live = _grab(qtbot, w)
    assert _diagonal_red_fraction(w, live) < 0.5, "live tape already shows an X"
    assert _scale_ink_count(w, live) > 0, "control: the live scale draws ink"

    setattr(item, flag, True)
    failed = _grab(qtbot, w)
    assert _diagonal_red_fraction(w, failed) > 0.9, \
        "a %s tape must carry a red X corner to corner" % flag
    assert _scale_ink_count(w, failed) == 0, \
        "the scale under a %s tape must be blanked" % flag
    assert _readout_shows_failed(w), "the readout must show the red XXX"

    setattr(item, flag, False)
    back = _grab(qtbot, w)
    assert _diagonal_red_fraction(w, back) < 0.5, "the X must clear on recovery"
    assert _scale_ink_count(w, back) > 0, "the scale must return on recovery"


@pytest.mark.parametrize("name", sorted(TAPES))
def test_bad_tape_keeps_scale_inside_amber_frame(fix, qtbot, name):
    """CERT1b: suspect is not absent. A bad tape keeps its scale, carries an
    amber frame and no red X, and the frame clears on recovery."""
    w, item = TAPES[name](fix)
    _show(qtbot, w)

    live = _grab(qtbot, w)
    assert _frame_amber_fraction(w, live) < 0.2, "live tape already framed"

    item.bad = True
    bad = _grab(qtbot, w)
    assert _frame_amber_fraction(w, bad) > 0.9, \
        "a bad tape must carry an amber frame"
    assert _diagonal_red_fraction(w, bad) < 0.5, "a bad tape is not a red X"
    assert _scale_ink_count(w, bad) > 0, "a bad tape keeps its scale"

    item.bad = False
    back = _grab(qtbot, w)
    assert _frame_amber_fraction(w, back) < 0.2, "the frame must clear"


def test_fail_or_old_outranks_bad(fix, qtbot):
    """A key both expired and suspect shows the X, not the amber frame."""
    w, item = _airspeed(fix)
    _show(qtbot, w)
    item.bad = True
    item.old = True
    img = _grab(qtbot, w)
    assert _diagonal_red_fraction(w, img) > 0.9
    assert _frame_amber_fraction(w, img) < 0.2


def test_vsi_pfd_bad_dot_is_amber(fix, qtbot):
    """VSI_PFD keeps its dot under a bad VS, amber rather than magenta."""
    w, item = _vsi_pfd(fix)
    _show(qtbot, w)
    item.bad = True
    img = _grab(qtbot, w)
    magenta = sum(1 for y in range(img.height()) for x in range(img.width())
                  if (lambda c: c.red() > 200 and c.blue() > 200
                      and c.green() < 60)(img.pixelColor(x, y)))
    inner_amber = sum(_is_amber(img.pixelColor(x, y))
                      for y in range(8, img.height() - 8)
                      for x in range(8, img.width() - 8))
    assert magenta == 0, "the dot must not stay magenta under a bad VS"
    assert inner_amber > 20, "the dot must be drawn amber"


@pytest.mark.parametrize("ias_flag", ["fail", "old"])
def test_tas_blanks_under_failed_or_old_ias(fix, qtbot, ias_flag):
    """CERT1b: no TAS number beside a failed or expired IAS (same pitot)."""
    for k in ("IAS", "TAS"):
        _clear(fix.db.get_item(k))
    fix.db.get_item("IAS").value = 100
    fix.db.get_item("TAS").value = 108
    w = airspeed.Airspeed_Tape(show_tas=True, show_trend=False)
    _show(qtbot, w)
    assert w.tas_text() == "108", "control: a live TAS reads"
    setattr(fix.db.get_item("IAS"), ias_flag, True)
    assert w.tas_text() == "---"
    setattr(fix.db.get_item("IAS"), ias_flag, False)
    assert w.tas_text() == "108"


def test_tas_stays_live_under_bad_ias(fix, qtbot):
    """The ruling blanks TAS under a failed or expired IAS only; a suspect IAS
    keeps its TAS (it is flagged on its own key if it is suspect too)."""
    for k in ("IAS", "TAS"):
        _clear(fix.db.get_item(k))
    fix.db.get_item("TAS").value = 108
    w = airspeed.Airspeed_Tape(show_tas=True, show_trend=False)
    _show(qtbot, w)
    fix.db.get_item("IAS").bad = True
    assert w.tas_text() == "108"


def test_tas_flag_change_repaints(fix, qtbot, monkeypatch):
    """A TAS flag change repaints the tape (it used to wait for a value)."""
    for k in ("IAS", "TAS"):
        _clear(fix.db.get_item(k))
    w = airspeed.Airspeed_Tape(show_tas=True, show_trend=False)
    _show(qtbot, w)
    hits = []
    monkeypatch.setattr(w.viewport(), "update", lambda *a: hits.append(1))
    fix.db.get_item("TAS").old = True
    assert hits, "a TAS flag change must repaint the TAS box"


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


@pytest.mark.parametrize("flag", ["fail", "bad", "old"])
def test_vsi_tape_flag_change_is_not_rate_limited(fix, qtbot, flag):
    """A quality-flag change refreshes the readout even inside the
    update_period window. Rate-limited, the Beelink capture showed the readout
    stuck at XXX 4 s after fix-gateway recovered, with VS steady at 0."""
    item = fix.db.get_item("VS")
    _clear(item)
    item.value = 0
    w = vsi.Alt_Trend_Tape()
    w.myparent = _parent(update_period=60)   # one redraw a minute at most
    _show(qtbot, w)
    assert w.vstext.toPlainText() == "0"
    setattr(item, flag, True)
    assert w.vstext.toPlainText() == ("" if flag == "bad" else "XXX")
    setattr(item, flag, False)
    assert w.vstext.toPlainText() == "0"
