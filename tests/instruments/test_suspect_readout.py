"""CERT1c (AER-5893): a suspect (bad) readout shows its value, in amber.

CERT1b framed a bad tape in amber and kept its scale ("suspect is not absent"),
but the readout box inside the frame still blanked its digits, so the pilot saw
a live scale beside an empty box. These tests grab each tape's readout and
assert that under `bad` it carries amber digit ink and no white digit ink, and
that the digits return to white on recovery. On `dev` before CERT1c the bad
readout drew no digit ink at all.
"""
from unittest import mock

import pytest

from pyefis.instruments import airspeed, altimeter, vsi

W, H = 120, 400


def _clear(item):
    item.old = False
    item.bad = False
    item.fail = False


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
    parent = mock.Mock()
    parent.get_config_item = mock.Mock(return_value=0)
    w.myparent = parent
    return w, fix.db.get_item("VS")


TAPES = {
    "airspeed": _airspeed,
    "altimeter": _altimeter,
    "vsi_tape": _vsi_tape,
}


def _is_amber(c):
    return c.red() > 200 and 130 < c.green() < 210 and c.blue() < 60


def _is_white(c):
    return c.red() > 200 and c.green() > 200 and c.blue() > 200


def _readout_image(qtbot, w):
    """The readout box alone: the NumericalDisplay on the airspeed and
    altitude tapes, the header strip above the scale on the VSI tape (the
    suspect frame starts below it, at top_margin)."""
    qtbot.wait(20)
    if isinstance(w, vsi.Alt_Trend_Tape):
        img = w.viewport().grab().toImage()
        # Skip the text item's top quarter (document margin): the white "VSI"
        # label above overlaps it by a few rows.
        th = w.vstext.boundingRect().height()
        return img.copy(0, int(w.vstext.y() + th * 0.25), img.width(),
                        int(th * 0.75))
    nd = w.numerical_display
    # The panel interior only: its white border, and whatever the grab puts
    # outside the rounded corners, are not digits.
    r = nd.readout_rect.adjusted(4, 4, -4, -4).toRect()
    return nd.grab().toImage().copy(r)


def _ink(img, pred):
    return sum(pred(img.pixelColor(x, y))
               for y in range(img.height()) for x in range(img.width()))


@pytest.mark.parametrize("name", sorted(TAPES))
def test_bad_readout_shows_value_in_amber(fix, qtbot, name):
    w, item = TAPES[name](fix)
    qtbot.addWidget(w)
    w.resize(W, H)
    w.show()
    qtbot.waitExposed(w)

    live = _readout_image(qtbot, w)
    assert _ink(live, _is_white) > 20, "control: the live readout draws digits"
    assert _ink(live, _is_amber) == 0, "control: live digits are not amber"

    item.bad = True
    bad = _readout_image(qtbot, w)
    assert _ink(bad, _is_amber) > 20, \
        "a bad readout must still show its value, in amber"
    assert _ink(bad, _is_white) == 0, \
        "a bad readout's digits must not stay white"

    item.bad = False
    back = _readout_image(qtbot, w)
    assert _ink(back, _is_amber) == 0, "the amber must clear on recovery"
    assert _ink(back, _is_white) > 20, "white digits must return on recovery"


@pytest.mark.parametrize("flag", ["fail", "old"])
@pytest.mark.parametrize("name", sorted(TAPES))
def test_fail_or_old_outranks_bad_in_the_readout(fix, qtbot, name, flag):
    """A failed or expired key still shows no number (the XXX), even if it is
    also flagged bad: only a merely suspect value reads in amber."""
    w, item = TAPES[name](fix)
    qtbot.addWidget(w)
    w.resize(W, H)
    w.show()
    qtbot.waitExposed(w)
    item.bad = True
    setattr(item, flag, True)
    if isinstance(w, vsi.Alt_Trend_Tape):
        assert w.vstext.toPlainText() == "XXX"
    else:
        # The tapes raise the readout's XXX for an old key too (CERT1b).
        assert w.numerical_display.fail
    setattr(item, flag, False)
    _clear(item)
