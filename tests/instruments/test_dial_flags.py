"""CERT1g (AER-6399): the round dials follow the tapes' flag convention.

The tapes read `fail`/`old` as a red X and XXX (CERT1a/b) and `bad` as an
amber frame and amber digits (CERT1c). The round `Airspeed` and `Altimeter`
dials used to draw needle and markings grey under `old` OR `bad`, and show the
red XXX only on `fail`: an expired key kept a frozen needle in grey, and a
suspect one looked the same as an expired one (Bill's ruling, packet AER-6303,
2026-11-22: the dials follow the tapes).

These tests grab each dial under every flag. On `dev` before CERT1g the `old`
dial drew a grey needle and no XXX, and the `bad` dial drew grey, not amber.
"""
import pytest

from pyefis.instruments import airspeed, altimeter

S = 300


def _clear(item):
    item.old = False
    item.bad = False
    item.fail = False


def _airspeed(fix):
    item = fix.db.get_item("IAS")
    _clear(item)
    item.value = 100
    w = airspeed.Airspeed()
    w.setAirspeed(100)
    return w, item


def _altimeter(fix):
    item = fix.db.get_item("ALT")
    _clear(item)
    item.value = 4500
    w = altimeter.Altimeter()
    w.setAltimeter(4500)
    return w, item


DIALS = {
    "airspeed": _airspeed,
    "altimeter": _altimeter,
}


def _is_amber(c):
    return c.red() > 200 and 130 < c.green() < 210 and c.blue() < 60


def _is_grey(c):
    # Qt.GlobalColor.gray is (160, 160, 164); antialiased edges against the
    # black face shade it darker, so take the neutral mid-greys.
    return (abs(c.red() - c.green()) < 12 and abs(c.green() - c.blue()) < 12
            and 90 < c.red() < 200)


def _is_red(c):
    return c.red() > 200 and c.green() < 60 and c.blue() < 60


def _is_white(c):
    return c.red() > 200 and c.green() > 200 and c.blue() > 200


def _ink(img, pred):
    return sum(pred(img.pixelColor(x, y))
               for y in range(img.height()) for x in range(img.width()))


def _centre_ink(img, pred):
    """Ink in the middle third, where the XXX and the needle hubs sit, and no
    scale marking does."""
    w, h = img.width(), img.height()
    return _ink(img.copy(w // 3, h // 3, w // 3, h // 3), pred)


def _left_ink(img, pred):
    """Ink in the left sixth: scale ticks and numerals only, clear of every
    needle at the test values. The airspeed's yellow arc blends to an amber
    shade where it meets the red, so callers compare against the live dial."""
    return _ink(img.copy(0, 0, img.width() // 6, img.height()), pred)


def _show(qtbot, name, fix):
    w, item = DIALS[name](fix)
    qtbot.addWidget(w)
    w.resize(S, S)
    w.show()
    qtbot.waitExposed(w)
    return w, item


def _grab(qtbot, w):
    qtbot.wait(20)
    return w.grab().toImage()


@pytest.mark.parametrize("name", sorted(DIALS))
def test_old_dial_reads_failed(fix, qtbot, name):
    """An expired (old) key is frozen at its last value: the dial draws the
    failed look (red XXX, no needle), the same as `fail`."""
    w, item = _show(qtbot, name, fix)
    live = _grab(qtbot, w)
    assert _centre_ink(live, _is_red) == 0, "control: a live dial has no XXX"

    item.fail = True
    failed = _grab(qtbot, w)
    assert _centre_ink(failed, _is_red) > 50, "control: fail draws the XXX"
    item.fail = False

    item.old = True
    old = _grab(qtbot, w)
    assert _centre_ink(old, _is_red) > 50, "an old dial must show the red XXX"
    assert old == failed, "an old dial must look exactly like a failed one"

    item.old = False
    back = _grab(qtbot, w)
    assert back == live, "the failed look must clear on recovery"


@pytest.mark.parametrize("name", sorted(DIALS))
def test_bad_dial_reads_amber(fix, qtbot, name):
    """A suspect (bad) key still shows its reading: needle and markings turn
    amber (the tape's suspect colour), never grey, and no XXX."""
    w, item = _show(qtbot, name, fix)
    live = _grab(qtbot, w)
    assert _centre_ink(live, _is_amber) == 0, "control: a live needle is not amber"
    assert _centre_ink(live, _is_white) > 20, "control: a live needle is white"

    item.bad = True
    bad = _grab(qtbot, w)
    assert _centre_ink(bad, _is_amber) > 20, "a bad dial's needle must be amber"
    assert (_left_ink(bad, _is_amber) - _left_ink(live, _is_amber) > 50
            and _left_ink(bad, _is_white) == 0), \
        "a bad dial's scale markings must be amber too"
    assert _centre_ink(bad, _is_white) == 0, "a bad needle must not stay white"
    # Only the needle area: antialiased edges of the airspeed's white flap
    # arc shade to grey on any dial, live or not.
    assert _centre_ink(bad, _is_grey) == 0, "a bad needle must not be grey"
    assert _centre_ink(bad, _is_red) == 0, "a bad dial must not show the XXX"

    item.bad = False
    back = _grab(qtbot, w)
    assert back == live, "the amber must clear on recovery"


@pytest.mark.parametrize("flag", ["fail", "old"])
@pytest.mark.parametrize("name", sorted(DIALS))
def test_fail_or_old_outranks_bad_on_the_dial(fix, qtbot, name, flag):
    """A failed or expired key that is also flagged bad still reads failed:
    only a merely suspect value draws in amber."""
    w, item = _show(qtbot, name, fix)
    item.fail = True
    failed = _grab(qtbot, w)
    item.fail = False

    item.bad = True
    setattr(item, flag, True)
    both = _grab(qtbot, w)
    assert both == failed, f"{flag} with bad must read failed, not amber"
    _clear(item)
