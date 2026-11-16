#  SPDX-License-Identifier: GPL-2.0-or-later
"""Autopilot target cues on the tapes (AFC4, docs/ap_annunciator_widget_spec.md):
the IASSEL bug and box on the airspeed tape, the VSSEL bug on the VS tape and
the PFD VSI, and the ALTSEL box's capture look on the altimeter tape. Each is
drawn from reported state only and goes when that state goes old."""

import pytest
from PyQt6.QtGui import QColor

from pyefis.instruments import airspeed, altimeter, vsi
from pyefis.screens import screenbuilder_factory as factory


def _ias_tape(qtbot, fix):
    item = fix.db.get_item("IAS")
    item.set_aux_value("Vne", 160)
    item.value = 90.0
    item.old = item.bad = item.fail = False
    w = airspeed.Airspeed_Tape()
    qtbot.addWidget(w)
    w.resize(80, 400)
    w.show()
    qtbot.waitExposed(w)
    return w


def _vs_tape(qtbot, fix, **kw):
    fix.db.define_item("VS", "VS", "float", -10000, 10000, "ft/min", 2000, "")
    item = fix.db.get_item("VS")
    item.value = 300.0
    item.old = item.bad = item.fail = False
    w = altimeter.Altimeter_Tape(dbkey="VS", maxalt=4000, majorDiv=500,
                                 minorDiv=100, **kw)
    qtbot.addWidget(w)
    w.resize(80, 400)
    w.show()
    qtbot.waitExposed(w)
    return w


def _alt_tape(qtbot, fix):
    fix.db.define_item("ALT", "ALT", "float", -2000, 60000, "ft", 2000, "")
    fix.db.define_item("ALTSEL", "ALTSEL", "int", -1000, 60000, "ft", 0, "")
    for key, v in (("ALT", 4200.0), ("ALTSEL", 4500)):
        item = fix.db.get_item(key)
        item.value = v
        item.old = item.bad = item.fail = False
    w = altimeter.Altimeter_Tape(dbkey="ALT")
    qtbot.addWidget(w)
    w.resize(140, 520)
    w.show()
    qtbot.waitExposed(w)
    return w


# -- TGT-IAS-001..003 ---------------------------------------------------------

@pytest.mark.parametrize("vert,arm,shown,active", [
    ("IAS", "", True, True),
    ("PIT", "IAS", True, False),
    ("VS", "ALT", False, False),
    ("", "", False, False),
])
def test_ias_target_shown_while_ias_active_or_armed(
        ap_db, qtbot, vert, arm, shown, active):
    """TGT-IAS-001, TGT-IAS-002: box and bug only while IAS is the active or an
    armed vertical mode; the box accent says which."""
    ap_db("APENG", True)
    ap_db("APVERT", vert)
    ap_db("APVERTARM", arm)
    ap_db("IASSEL", 85.0)
    w = _ias_tape(qtbot, ap_db.fix)
    assert w.ias_target_shown() is shown
    assert w.ias_target_active() is active
    assert (w.ias_bug_y() is not None) is shown
    if shown:
        assert w.ias_box_text() == "85"


def test_ias_bug_sits_on_the_target_speed(ap_db, qtbot):
    """TGT-IAS-001: the bug's apex is on the IASSEL tick, like the read pointer
    on the current speed: at the current speed it is at mid-tape."""
    ap_db("APVERT", "IAS")
    w = _ias_tape(qtbot, ap_db.fix)
    ap_db("IASSEL", 90.0)
    y, off = w.ias_bug_y()
    assert off == 0
    assert abs(y - w.height() / 2) <= 2
    ap_db("IASSEL", 100.0)
    y2, _ = w.ias_bug_y()
    assert abs((y - y2) - 10 * w.pph) <= 2      # 10 kt faster is higher


def test_ias_bug_pegs_off_scale(ap_db, qtbot):
    """TGT-IAS-001: a target off the visible tape pegs at the edge."""
    ap_db("APVERT", "IAS")
    ap_db("IASSEL", 400.0)
    w = _ias_tape(qtbot, ap_db.fix)
    y, off = w.ias_bug_y()
    assert off == -1 and y == w.ias_box_rect().bottom() + 1


def test_ias_unset_target_shows_dashes_and_no_bug(ap_db, qtbot):
    """TGT-IAS-001: IASSEL 0 is "not set" (AFC1): dashes, no bug."""
    ap_db("APVERT", "IAS")
    ap_db("IASSEL", 0.0)
    w = _ias_tape(qtbot, ap_db.fix)
    assert w.ias_target_shown()
    assert w.ias_box_text() == "---"
    assert w.ias_bug_y() is None


@pytest.mark.parametrize("flag", ["old", "bad", "fail"])
def test_ias_target_goes_with_stale_state(ap_db, qtbot, flag):
    """TGT-IAS-003: an old, bad or failed autopilot state removes box and bug."""
    ap_db("APVERT", "IAS")
    ap_db("IASSEL", 85.0)
    w = _ias_tape(qtbot, ap_db.fix)
    ap_db("APVERT", **{flag: True})
    assert not w.ias_target_shown()
    assert w.ias_bug_y() is None


def test_ias_target_option_off_and_missing_keys(fix, qtbot):
    """TGT-IAS-003: the tape builds on a gateway with no autopilot keys and
    shows nothing; ias_bug off hides it."""
    w = _ias_tape(qtbot, fix)
    assert not w.ias_target_shown()
    w.ias_bug = False
    assert not w.ias_target_shown()


def test_ias_box_pixels_appear_and_go(ap_db, qtbot):
    """TGT-IAS-001, TGT-IAS-003: the box is painted (a green border while IAS
    is active) and gone once the state goes old."""
    ap_db("APVERT", "IAS")
    ap_db("IASSEL", 85.0)
    w = _ias_tape(qtbot, ap_db.fix)

    def greens():
        img = w.grab().toImage()
        r = w.ias_box_rect()
        return sum(img.pixelColor(x, y).green() > 200
                   and img.pixelColor(x, y).red() < 80
                   and img.pixelColor(x, y).blue() < 80
                   for x in range(int(r.width())) for y in range(int(r.height())))

    assert greens() > 0
    ap_db("APVERT", old=True)
    assert greens() == 0


# -- TGT-VS-001 ---------------------------------------------------------------

@pytest.mark.parametrize("vert,shown", [("VS", True), ("ALT", False),
                                        ("PIT", False)])
def test_vs_tape_bug_only_while_vs_active(ap_db, qtbot, vert, shown):
    """TGT-VS-001: the VSSEL bug on a VS tape while VS is the active mode."""
    ap_db("APVERT", vert)
    ap_db("APVERTARM", "VS")       # armed is not enough
    ap_db("VSSEL", 300)
    w = _vs_tape(qtbot, ap_db.fix)
    placed = w.vs_bug_y()
    assert (placed is not None) is shown
    if shown:
        # the bug is on the read pointer: VS is 300, the target is 300
        assert abs(placed[0] - w.height() / 2) <= 3


@pytest.mark.parametrize("flag", ["old", "bad", "fail"])
def test_vs_tape_bug_goes_with_stale_state(ap_db, qtbot, flag):
    """TGT-VS-001: stale autopilot state, no bug."""
    ap_db("APVERT", "VS")
    ap_db("VSSEL", 300)
    w = _vs_tape(qtbot, ap_db.fix)
    ap_db("APLAT", **{flag: True})
    assert w.vs_bug_y() is None


def test_vs_bug_defaults_follow_the_key(ap_db, qtbot):
    """TGT-VS-001: on by default for a VS tape, off for an ALT tape; the
    builder forwards the option."""
    ap_db("APVERT", "VS")
    ap_db("VSSEL", 300)
    assert _vs_tape(qtbot, ap_db.fix).vs_bug is True
    assert _vs_tape(qtbot, ap_db.fix, vs_bug=False).vs_bug_y() is None
    assert _alt_tape(qtbot, ap_db.fix).vs_bug is False
    built = factory.build_altimeter_tape(
        None, {"options": {"dbkey": "VS", "vs_bug": False}})
    qtbot.addWidget(built)
    assert built.vs_bug is False


def test_vsi_pfd_bug_only_while_vs_active(ap_db, qtbot):
    """TGT-VS-001: the PFD VSI carries the same bug, same gating."""
    fix = ap_db.fix
    fix.db.define_item("VS", "VS", "float", -10000, 10000, "ft/min", 2000, "")
    item = fix.db.get_item("VS")
    item.value = 0.0
    item.old = item.bad = item.fail = False
    ap_db("APVERT", "VS")
    ap_db("VSSEL", 1000)
    w = vsi.VSI_PFD()
    qtbot.addWidget(w)
    w.resize(40, 300)
    w.show()
    qtbot.waitExposed(w)
    y = w.vs_bug_y()
    assert y is not None and y == pytest.approx(w.scale_y(1000))
    assert y < w.height() / 2          # a climb is above the zero line
    ap_db("APVERT", "ALT")
    assert w.vs_bug_y() is None
    ap_db("APVERT", "VS", old=True)
    assert w.vs_bug_y() is None
    w.grab()                           # paints with and without the bug


# -- AL-CAP-001 ---------------------------------------------------------------

def test_altsel_box_changes_look_while_capturing(ap_db, qtbot):
    """AL-CAP-001: while APALTCAP is set the ALTSEL box border is the capture
    colour; it reverts when capture ends or the state goes old."""
    ap_db("APVERT", "VS")
    w = _alt_tape(qtbot, ap_db.fix)
    box = w.altsel_display
    assert not box.capture_look()
    ap_db("APALTCAP", True)
    assert box.capturing and box.capture_look()
    assert box.border_color() == QColor("#00ff00")
    ap_db("APALTCAP", old=True)
    assert not box.capture_look()
    ap_db("APALTCAP", False, old=False)
    assert not box.capture_look()


def test_deviation_alert_outranks_the_capture_look(ap_db, qtbot):
    """AL-CAP-001 with EFIS-ALTSEL-006: the gateway's deviation alert (amber)
    wins over the capture look."""
    ap_db("APALTCAP", True)
    w = _alt_tape(qtbot, ap_db.fix)
    ap_db.fix.db.get_item("ALTSEL").annunciate = True
    box = w.altsel_display
    assert not box.capture_look()
    assert box.border_color() == QColor("#ffb000")
