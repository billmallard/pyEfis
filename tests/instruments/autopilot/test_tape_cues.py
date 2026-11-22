#  SPDX-License-Identifier: GPL-2.0-or-later
"""Autopilot target cues on the tapes (AFC4, docs/ap_annunciator_widget_spec.md):
the IASSEL bug and box on the airspeed tape, the VSSEL bug on the VS tape and
the PFD VSI, and the ALTSEL box's capture look on the altimeter tape. Each is
drawn from reported state only and goes when that state goes old."""

import pytest
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QColor

from pyefis.instruments import airspeed, altimeter, edit_focus, vsi
from pyefis.instruments.airspeed import iassel
from pyefis.screens import screenbuilder_factory as factory
from tests.instruments.altimeter.test_altsel import _Host
from tests.instruments.autopilot.conftest import sent


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


def _ias_tape_on(qtbot, fix, host):
    """The tape on a screen stand-in with a real EncoderController."""
    item = fix.db.get_item("IAS")
    item.set_aux_value("Vne", 160)
    item.value = 90.4
    item.old = item.bad = item.fail = False
    w = airspeed.Airspeed_Tape(host)
    host.instruments[0] = w
    host.resize(80, 400)
    w.resize(80, 400)
    host.show()
    qtbot.waitExposed(host)
    host.encoder_controller.configure_inputs(None)
    return w


def _iassel_writes(fix):
    return [float(v) for _k, v in sent(fix, keys=("IASSEL",))]


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
    assert off == -1 and y == w.ias_box_zone().bottom() + 1


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


# -- TGT-IAS-004: touch and knob editable like the ALTSEL box ----------------

def test_ias_box_touch_focuses_and_knob_edits(ap_db, qtbot):
    """TGT-IAS-004 (Bill, AER-5808): a touch on the box takes the edit focus
    through the real EncoderController; inner ring 1 kt, outer 10 kt, every
    step written to the bus; push syncs to the current airspeed and ends the
    edit."""
    ap_db("APENG", True)
    ap_db("APVERT", "IAS")
    ap_db("IASSEL", 85.0)
    host = _Host()
    qtbot.addWidget(host)
    t = _ias_tape_on(qtbot, ap_db.fix, host)
    ctl = host.encoder_controller
    assert t in ctl._touch_instruments()
    ap_db.fix.db.clientthread.sendqueue.put.reset_mock()
    qtbot.mouseClick(t.viewport(), Qt.MouseButton.LeftButton,
                     pos=t.ias_box_zone().center().toPoint())
    assert ctl.focused_instrument() is t
    assert edit_focus.owner() is ctl
    ctl.changed(2)
    assert ap_db.fix.db.get_item("IASSEL").value == 87.0
    ctl.outer_changed(-1)
    assert ap_db.fix.db.get_item("IASSEL").value == 77.0
    ctl.button_changed(True)                   # push: sync, end the edit
    assert ap_db.fix.db.get_item("IASSEL").value == 90.0
    assert _iassel_writes(ap_db.fix) == [87.0, 77.0, 90.0]
    assert ctl.focused_instrument() is None
    assert edit_focus.owner() is None


def test_ias_box_not_editable_while_hidden(ap_db, qtbot):
    """TGT-IAS-004: no box, no edit. With IAS not reported (or the state old)
    a touch on the top of the tape takes no focus and writes nothing."""
    ap_db("APENG", True)
    ap_db("APVERT", "VS")
    ap_db("IASSEL", 85.0)
    host = _Host()
    qtbot.addWidget(host)
    t = _ias_tape_on(qtbot, ap_db.fix, host)
    ap_db.fix.db.clientthread.sendqueue.put.reset_mock()
    qtbot.mouseClick(t.viewport(), Qt.MouseButton.LeftButton,
                     pos=t.ias_box_zone().center().toPoint())
    assert host.encoder_controller.focused_instrument() is None
    assert t.enc_selectable() is False
    assert t.enc_select() is False
    assert t.enc_changed(1) is False
    assert _iassel_writes(ap_db.fix) == []


def test_ias_focus_released_when_ias_leaves(ap_db, qtbot):
    """TGT-IAS-004: the box held focus and IAS stopped being reported (a mode
    change, or the state went old): the edit ends with the box."""
    ap_db("APENG", True)
    ap_db("APVERT", "IAS")
    ap_db("IASSEL", 85.0)
    host = _Host()
    qtbot.addWidget(host)
    t = _ias_tape_on(qtbot, ap_db.fix, host)
    ctl = host.encoder_controller
    assert ctl.touch_focus(t) is True
    ap_db("APVERT", "ALT")
    assert ctl.focused_instrument() is None
    assert edit_focus.owner() is None
    assert t.enc_changed(1) is False


def test_ias_press_outside_the_box_releases(ap_db, qtbot):
    """TGT-IAS-004: only the box counts as the focused value."""
    ap_db("APVERT", "IAS")
    ap_db("IASSEL", 85.0)
    host = _Host()
    qtbot.addWidget(host)
    t = _ias_tape_on(qtbot, ap_db.fix, host)
    assert host.encoder_controller.touch_focus(t) is True
    vp = t.viewport()
    box_pt = vp.mapToGlobal(t.ias_box_zone().center().toPoint())
    mid_pt = vp.mapToGlobal(QPoint(t.width() // 2, t.height() // 2))
    assert t.edit_focus_hit(QPointF(box_pt)) is True
    assert t.edit_focus_hit(QPointF(mid_pt)) is False


@pytest.mark.parametrize("start,delta,expected", [
    (85.0, 1, 86.0),      # inner knob
    (85.0, -10, 75.0),    # outer ring
    (0.0, 1, 91.0),       # "not set": from the synced airspeed (90.4 -> 90)
    (5.0, -10, 1.0),      # never down to 0, which would unset the target
    (995.0, 10, 999.0),   # the key's max
])
def test_iassel_edit_rules(ap_db, qtbot, start, delta, expected):
    """TGT-IAS-004: the edit rules (iassel.IasSelEditor)."""
    ap_db("APVERT", "IAS")
    ap_db("IASSEL", start)
    t = _ias_tape(qtbot, ap_db.fix)
    ap_db.fix.db.get_item("IAS").value = 90.4
    assert t._iassel_editor.step(delta) is True
    assert ap_db.fix.db.get_item("IASSEL").value == expected


@pytest.mark.parametrize("flag", ["old", "bad", "fail"])
def test_iassel_no_airspeed_writes_nothing(ap_db, qtbot, flag):
    """TGT-IAS-004: with no usable airspeed, a push and a first step from "not
    set" write nothing; a step from a set target still works."""
    ap_db("APVERT", "IAS")
    ap_db("IASSEL", 0.0)
    t = _ias_tape(qtbot, ap_db.fix)
    ias = ap_db.fix.db.get_item("IAS")
    setattr(ias, flag, True)
    ap_db.fix.db.clientthread.sendqueue.put.reset_mock()
    assert t._iassel_editor.sync() is False
    assert t._iassel_editor.step(1) is False
    assert _iassel_writes(ap_db.fix) == []
    ap_db("IASSEL", 85.0)
    assert t._iassel_editor.step(1) is True
    assert ap_db.fix.db.get_item("IASSEL").value == 86.0


def test_ias_touch_edit_option(ap_db, qtbot):
    """TGT-IAS-004: touch_edit off leaves the box display only; the option
    reaches the tape through apply_options with the YAML shape."""
    from pyefis.screens import screenbuilder_options as opts
    ap_db("APVERT", "IAS")
    t = _ias_tape(qtbot, ap_db.fix)
    assert t.ias_box_editable()
    host = _Host()
    qtbot.addWidget(host)
    host.instruments[0] = t
    opts.apply_options(host, 0, {"type": "airspeed_tape",
                                 "options": {"touch_edit": False}})
    assert t.touch_edit is False
    assert not t.ias_box_editable()
    assert t.enc_select() is False
    assert iassel.FINE_STEP_KT == 1 and iassel.COARSE_STEP_KT == 10


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
