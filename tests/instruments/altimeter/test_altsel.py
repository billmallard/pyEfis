#  SPDX-License-Identifier: GPL-2.0-or-later
"""Selected-altitude (ALTSEL) box and bug on the altimeter tape (pyEfis #310).

Inner knob 100 ft, outer ring 1000 ft, push syncs to the current altitude
rounded to 100 ft, clamped to the key's min/max; no value -> dashes and no
bug, but touch-to-set still works. Writes are asserted on the bytes queued to
fix-gateway, not on the local item (a local-only set never reaches the bus).
"""

import pytest
from PyQt6.QtCore import QPoint, QPointF, QTimer, Qt
from PyQt6.QtWidgets import QWidget

from pyefis.instruments import altimeter, edit_focus
from pyefis.instruments.altimeter import altsel
from pyefis.instruments.helpers import bugs
from pyefis.screens.screenbuilder_encoder import EncoderController


@pytest.fixture(autouse=True)
def _clean_registry():
    edit_focus.set_at_rest_hint(False)
    yield
    owner = edit_focus.owner()
    if owner is not None:
        owner.release_focus()
    edit_focus.set_at_rest_hint(False)


def _define(fix, key, dtype, lo, hi, value):
    fix.db.define_item(key, key, dtype, lo, hi, "ft", 50000, "")
    fix.db.set_value(key, value)
    item = fix.db.get_item(key)
    item.old = False
    item.bad = False
    item.fail = False
    return item


@pytest.fixture
def alt_db(fix):
    alt = _define(fix, "ALT", "float", -2000, 60000, 4130.0)
    sel = _define(fix, "ALTSEL", "int", -1000, 60000, 4500)
    fix.db.clientthread.sendqueue.put.reset_mock()
    return fix, alt, sel


def _sent(fix):
    """The ALTSEL values queued to fix-gateway, in order."""
    out = []
    for call in fix.db.clientthread.sendqueue.put.call_args_list:
        line = call.args[0].decode()
        key, value, flags = line.strip().split(";")
        if key == "ALTSEL":
            out.append((int(float(value)), flags))
    return out


class _Host(QWidget):
    """A screen stand-in: the attributes EncoderController reads, and a real
    widget so the tape's box can find ``encoder_controller`` up its parents."""

    def __init__(self, timeout=10_000):
        super().__init__()
        self.instruments = {}
        self.encoder_list = []
        self.encoder_list_sorted = []
        self.encoder_current_selection = None
        self.encoder_timeout = timeout
        self.encoder_timestamp = 0
        self.encoder_control = False
        self.encoder_timer = QTimer()
        self.encoder = None
        self.encoder_button = None
        self.encoder_controller = EncoderController(self)

    def encoderChanged(self, value=0):
        self.encoder_controller.changed(value)


def _tape(qtbot, host=None, **kwargs):
    parent = host
    w = altimeter.Altimeter_Tape(parent, **kwargs)
    if host is None:
        qtbot.addWidget(w)
        w.resize(140, 520)
        w.show()
        qtbot.waitExposed(w)
    else:
        host.instruments[0] = w
        host.resize(140, 520)
        w.resize(140, 520)
        host.show()
        qtbot.waitExposed(host)
    return w


def _focus(tape):
    tape.enc_highlight(True)
    assert tape.enc_select() is True


# --- the edit rules ----------------------------------------------------------

def test_inner_steps_100_outer_steps_1000(alt_db, qtbot):
    fix, _alt, sel = alt_db
    t = _tape(qtbot)
    _focus(t)
    assert t.enc_changed(1) is True
    assert sel.value == 4600
    t.enc_changed(-3)
    assert sel.value == 4300
    assert t.enc_outer_changed(2) is True
    assert sel.value == 6300
    t.enc_outer_changed(-1)
    assert sel.value == 5300
    assert [v for v, _ in _sent(fix)] == [4600, 4300, 6300, 5300]


def test_clamped_to_the_key_limits(alt_db, qtbot):
    fix, _alt, sel = alt_db
    t = _tape(qtbot)
    _focus(t)
    sel.value = 59500
    t.enc_outer_changed(3)
    assert sel.value == 60000
    sel.value = -500
    t.enc_outer_changed(-1)
    assert sel.value == -1000
    assert _sent(fix)[-1][0] == -1000


@pytest.mark.parametrize("alt, expected", [
    (4130.0, 4100), (4149.9, 4100), (4150.0, 4200), (4199.0, 4200),
    (-149.0, -100), (-150.0, -200), (61234.0, 60000),
])
def test_push_syncs_to_current_altitude_rounded_to_100(alt_db, qtbot, alt, expected):
    fix, alt_item, sel = alt_db
    t = _tape(qtbot)
    _focus(t)
    alt_item.value = alt
    keep = t.enc_clicked()
    assert keep is False                      # sync ends the edit
    assert sel.value == expected
    assert _sent(fix)[-1][0] == expected


def test_push_with_invalid_altitude_writes_nothing_and_keeps_focus(alt_db, qtbot):
    fix, alt_item, sel = alt_db
    t = _tape(qtbot)
    _focus(t)
    alt_item.fail = True
    assert t.enc_clicked() is True
    assert sel.value == 4500
    assert _sent(fix) == []


def test_round_to_step_halves_away_from_zero():
    assert altsel.round_to_step(2950) == 3000
    assert altsel.round_to_step(3050) == 3100
    assert altsel.round_to_step(-50) == -100
    assert altsel.round_to_step(49) == 0


# --- no value ----------------------------------------------------------------

def test_no_value_shows_dashes_no_bug_and_touch_still_sets(alt_db, qtbot):
    fix, _alt, sel = alt_db
    sel.fail = True
    sel.bad = True
    t = _tape(qtbot)
    assert t.altsel_display.text() == altsel.DASHES
    assert t.alt_bug_y() is None
    assert t.touch_edit is True
    _focus(t)
    t.enc_changed(1)                          # from the synced 4100
    assert sel.value == 4200
    assert sel.fail is False and sel.bad is False
    assert _sent(fix) == [(4200, "0000")]     # written good, not failed
    assert t.altsel_display.text() == "4200"
    assert t.alt_bug_y() is not None


def test_missing_key_builds_shows_dashes_and_is_not_touchable(fix, qtbot):
    _define(fix, "ALT", "float", -2000, 60000, 4130.0)
    t = _tape(qtbot, show_baro=False)         # no ALTSEL in the database
    assert t.altsel_display.text() == altsel.DASHES
    assert t.alt_bug_y() is None
    assert t._altsel_touchable() is False
    assert t.touch_edit is False
    assert t.enc_selectable() is False
    assert t.enc_select() is False


def test_degraded_value_draws_grey(alt_db, qtbot):
    _fix, _alt, sel = alt_db
    t = _tape(qtbot)
    sel.old = True
    assert t._altsel.state == bugs.STATE_DEGRADED
    assert t._altsel.color() == bugs.BUG_DEGRADED_COLOR
    assert t.alt_bug_y() is not None


# --- the bug -----------------------------------------------------------------

def _tick_y(tape, alt):
    return tape.mapFromScene(QPointF(0, tape.y_offset(alt + tape.maxalt))).y()


def test_bug_sits_on_the_selected_altitude_tick(alt_db, qtbot):
    _fix, _alt, sel = alt_db
    t = _tape(qtbot)
    y, off = t.alt_bug_y()
    assert off == 0
    assert y == pytest.approx(_tick_y(t, 4500))
    assert y < t.viewport().height() / 2      # above the read pointer


def test_bug_off_tape_pegs_at_the_edge(alt_db, qtbot):
    _fix, _alt, sel = alt_db
    t = _tape(qtbot)
    sel.value = 9000                          # far above the visible span
    y, off = t.alt_bug_y()
    assert off == -1
    assert y == t.altsel_display.geometry().bottom() + 1
    sel.value = 1000                          # far below
    y, off = t.alt_bug_y()
    assert off == 1
    bottom = t._baro_zone().top() if t.baro_shown() else t.viewport().height()
    assert y == bottom                        # above the baro box when shown


def test_clamp_to_span():
    assert bugs.clamp_to_span(5, 0, 10) == (5, 0)
    assert bugs.clamp_to_span(-3, 0, 10) == (0, -1)
    assert bugs.clamp_to_span(12, 0, 10) == (10, 1)


def test_bug_follows_the_tape_units(alt_db, qtbot):
    _fix, _alt, sel = alt_db
    t = _tape(qtbot)
    t.conversionFunction = lambda x: x / 3.28084
    t.setAltimeter(4130.0)
    y, off = t.alt_bug_y()
    assert y == pytest.approx(_tick_y(t, 4500 / 3.28084))
    assert t.altsel_display.text() == str(round(4500 / 3.28084))


# --- option defaults ---------------------------------------------------------

def test_box_and_bug_default_on_for_alt_off_for_vs(fix, qtbot):
    assert altimeter.Altimeter_Tape(dbkey="ALT").altsel_box is True
    vs = altimeter.Altimeter_Tape(dbkey="VS")
    assert vs.altsel_box is False
    assert vs._bug_on() is False
    assert vs.touch_edit is False
    forced = altimeter.Altimeter_Tape(dbkey="VS", altsel_box=True)
    assert forced.altsel_box is True


def test_bug_can_be_turned_off_alone(alt_db, qtbot):
    t = _tape(qtbot, alt_bug_enabled=False)
    assert t.altsel_display is not None
    assert t.alt_bug_y() is None


def test_build_altimeter_tape_forwards_altsel_options(monkeypatch):
    from pyefis.screens import screenbuilder_factory as sf
    seen = {}
    monkeypatch.setattr(sf.altimeter, "Altimeter_Tape",
                        lambda screen, **kw: seen.update(kw) or object())
    sf.build_altimeter_tape(None, {"options": {
        "altsel_box": False, "alt_bug_enabled": True,
        "alt_bug_color": "#ff00ff", "alt_bug_dbkey": "ALTSEL2"}})
    assert seen["altsel_box"] is False
    assert seen["alt_bug_enabled"] is True
    assert seen["alt_bug_color"] == "#ff00ff"
    assert seen["alt_bug_dbkey"] == "ALTSEL2"


# --- touch focus through the real EncoderController --------------------------

def test_touch_on_box_focuses_tape_and_knob_edits(alt_db, qtbot):
    fix, _alt, sel = alt_db
    host = _Host()
    qtbot.addWidget(host)
    t = _tape(qtbot, host)
    ctl = host.encoder_controller
    ctl.configure_inputs(None)
    assert t in ctl._touch_instruments()
    qtbot.mouseClick(t.altsel_display, Qt.MouseButton.LeftButton,
                     pos=t.altsel_display.rect().center())
    assert ctl.focused_instrument() is t
    assert t.altsel_display.focused is True
    assert edit_focus.owner() is ctl
    ctl.changed(2)
    assert sel.value == 4700
    ctl.outer_changed(1)
    assert sel.value == 5700
    ctl.button_changed(True)                  # push: sync, end the edit
    assert sel.value == 4100
    assert ctl.focused_instrument() is None
    assert t.altsel_display.focused is False
    assert edit_focus.owner() is None


def test_press_on_the_tape_outside_the_box_releases(alt_db, qtbot):
    _fix, _alt, _sel = alt_db
    host = _Host()
    qtbot.addWidget(host)
    t = _tape(qtbot, host)
    host.encoder_controller.configure_inputs(None)
    assert host.encoder_controller.touch_focus(t) is True
    box_pt = t.altsel_display.mapToGlobal(t.altsel_display.rect().center())
    tape_pt = t.mapToGlobal(QPoint(t.width() // 2, t.height() // 2))
    assert t.edit_focus_hit(QPointF(box_pt)) is True
    assert t.edit_focus_hit(QPointF(tape_pt)) is False
    qtbot.mouseClick(t.viewport(), Qt.MouseButton.LeftButton,
                     pos=QPoint(t.width() // 2, t.height() // 2))
    assert host.encoder_controller.focused_instrument() is None
    assert t.altsel_display.focused is False


def test_timeout_clears_focus(alt_db, qtbot):
    host = _Host(timeout=50)
    qtbot.addWidget(host)
    t = _tape(qtbot, host)
    host.encoder_controller.configure_inputs(None)
    host.encoder_controller.touch_focus(t)
    assert t.altsel_display.focused is True
    qtbot.waitUntil(lambda: host.encoder_control is False, timeout=2000)
    assert t.altsel_display.focused is False
    assert edit_focus.owner() is None


# --- one tape, two boxes: ALTSEL (#310) and baro (#311) -----------------------

def _baro_click(qtbot, t):
    z = t._baro_zone()
    qtbot.mouseClick(t.viewport(), Qt.MouseButton.LeftButton,
                     pos=QPoint(int(z.center().x()), int(z.center().y())))


def test_each_box_takes_its_own_focus_and_knob(alt_db, qtbot):
    fix, _alt, sel = alt_db
    baro = fix.db.get_item("BARO")
    host = _Host()
    qtbot.addWidget(host)
    t = _tape(qtbot, host)
    assert t.baro_shown(), "fixture needs BARO for this test"
    ctl = host.encoder_controller
    ctl.configure_inputs(None)
    b0 = baro.value

    qtbot.mouseClick(t.altsel_display, Qt.MouseButton.LeftButton,
                     pos=t.altsel_display.rect().center())
    assert t._edit_box == "altsel"
    assert t.altsel_display.focused and not t.encoder_selected
    ctl.changed(1)
    assert sel.value == 4600 and baro.value == b0

    _baro_click(qtbot, t)                     # touch moves to the baro box
    assert ctl.focused_instrument() is t
    assert t._edit_box == "baro"
    assert t.encoder_selected and not t.altsel_display.focused
    ctl.changed(1)
    assert sel.value == 4600                  # ALTSEL untouched
    assert baro.value == pytest.approx(round(b0, 2) + 0.01)

    qtbot.mouseClick(t.altsel_display, Qt.MouseButton.LeftButton,
                     pos=t.altsel_display.rect().center())
    assert t._edit_box == "altsel" and not t.encoder_selected
    ctl.outer_changed(1)
    assert sel.value == 5600


def test_focus_hit_counts_only_the_focused_box(alt_db, qtbot):
    host = _Host()
    qtbot.addWidget(host)
    t = _tape(qtbot, host)
    host.encoder_controller.configure_inputs(None)
    t._touch_box("altsel")
    z = t._baro_zone()
    baro_pt = QPointF(t.viewport().mapToGlobal(z.center().toPoint()))
    box_pt = QPointF(t.altsel_display.mapToGlobal(
        t.altsel_display.rect().center()))
    assert t.edit_focus_hit(box_pt) is True
    assert t.edit_focus_hit(baro_pt) is False


def test_push_semantics_differ_per_box(alt_db, qtbot):
    """ALTSEL push syncs and ends the edit (Bill, 2026-10-27); baro push sets
    standard and keeps focus (#311)."""
    host = _Host()
    qtbot.addWidget(host)
    t = _tape(qtbot, host)
    ctl = host.encoder_controller
    ctl.configure_inputs(None)
    t._touch_box("baro")
    ctl.button_changed(True)
    assert ctl.focused_instrument() is t
    t._touch_box("altsel")
    ctl.button_changed(True)
    assert ctl.focused_instrument() is None
    assert t._edit_box is None


def test_knob_walk_lands_on_altsel_first(alt_db, qtbot):
    t = _tape(qtbot)
    assert t.enc_selectable() is True
    t.enc_highlight(True)
    assert t.enc_select() is True
    assert t._edit_box == "altsel"
    t.enc_highlight(False)
    assert t._edit_box is None
    vs_like = _tape(qtbot, altsel_box=False)
    vs_like.enc_highlight(True)
    vs_like.enc_select()
    assert vs_like._edit_box == ("baro" if vs_like.baro_shown() else None)
