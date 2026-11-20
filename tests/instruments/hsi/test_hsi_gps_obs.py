#  SPDX-License-Identifier: GPL-2.0-or-later
"""HSI CRS knob in GPS OBS (OBS3, AER-6086).

CRS on GPS is read-only (TK2) except while the flight-plan engine is in OBS
(FPLSTATE = 4, fix-gateway OBS2) and GPS guidance is the internal plan. Then
the knob sends ``FPLCMD OBS <deg>``, at most one per OBS_SEND_INTERVAL_MS,
and always ends on the last value turned to. Push syncs the course to the
bearing to the TO waypoint (GPSBRG). Nothing here is inferred: the gate is
FPLSTATE, and without the key the readout behaves as before.
"""

import pytest

from pyefis.instruments import hsi

from .test_hsi_touch_edit import _Host, _centre, _clean_registry, _paint, _tap  # noqa: F401


def _define(fix, key, dtype, value, mn=0, mx=359.9):
    fix.db.define_item(key, key, dtype, mn, mx, "", 50000, "")
    fix.db.set_value(key, value)
    it = fix.db.get_item(key)
    it.old = it.bad = it.fail = False


class _Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def gps(fix, monkeypatch):
    """A GPS-source HSI's keys with the engine in OBS, and a recorder on what
    is sent to fix-gateway."""
    for key, val in (("HEADBUG", 120.0), ("NAV1CRS", 45.0), ("NAV2CRS", 200.0),
                     ("GPSCRS", 90.0), ("GPSBRG", 271.6), ("VOR1BRG", 77.4)):
        _define(fix, key, "float", val)
    _define(fix, "NAVSRC", "float", 2.0, 0, 2)
    _define(fix, "NAVTYPE", "float", 0.0, 0, 3)
    _define(fix, "FPLSTATE", "int", 4, 0, 10)
    _define(fix, "GPSSRC", "int", 0, 0, 1)
    _define(fix, "FPLCMD", "str", "", None, None)
    _define(fix, "FPLCMDACK", "int", 0, -100000, 100000)
    fix.db.set_value("HEAD", 87.0)
    fix.db.set_value("COURSE", 90.0)
    sent = []
    monkeypatch.setattr(fix.db, "queue_out", lambda b: sent.append(b.decode()))
    fix.sent = sent
    return fix


def _hsi(qtbot, layout="top_panel"):
    host = _Host()
    w = hsi.HSI(host, font_percent=0.05, cdi_enabled=True)
    w.readout_layout = layout
    w.touch_edit = True
    w.setGeometry(0, 0, 432, 425)
    host.instruments[0] = w
    qtbot.addWidget(host)
    host.resize(432, 425)
    host.show()
    qtbot.waitExposed(host)
    w._obs_clock = _Clock()
    _paint(w)
    return host, w


def _commands(fix):
    """The FPLCMD strings sent, without their seq."""
    out = []
    for m in fix.sent:
        if m.startswith("FPLCMD;"):
            out.append(m.split(";")[1].split(None, 1)[1])
    return out


def _seqs(fix):
    return [int(m.split(";")[1].split()[0]) for m in fix.sent if m.startswith("FPLCMD;")]


# --- focusable only in OBS ----------------------------------------------------

def test_crs_is_focusable_on_gps_in_obs(gps, qtbot):
    host, w = _hsi(qtbot)
    _tap(qtbot, w, _centre(w, "crs"))
    assert w._edit_field == "crs"
    assert host.encoder_controller.focused_instrument() is w


@pytest.mark.parametrize("state", [0, 1, 2, 3])
def test_crs_is_not_focusable_on_gps_outside_obs(gps, qtbot, state):
    gps.db.set_value("FPLSTATE", state)
    _host, w = _hsi(qtbot)
    _tap(qtbot, w, _centre(w, "crs"))
    assert w._edit_field is None
    assert _commands(gps) == []


def test_crs_is_not_focusable_in_obs_on_the_external_navigator(gps, qtbot):
    """GPSSRC 1: the needle shows the external navigator's course, which an
    OBS command to the internal engine would not move."""
    gps.db.set_value("GPSSRC", 1)
    _host, w = _hsi(qtbot)
    _tap(qtbot, w, _centre(w, "crs"))
    assert w._edit_field is None


def test_without_fplstate_crs_stays_read_only_on_gps(fix, qtbot, monkeypatch):
    """An older gateway publishes no FPLSTATE: nothing changes."""
    for key, val in (("HEADBUG", 120.0), ("GPSCRS", 90.0)):
        _define(fix, key, "float", val)
    _define(fix, "NAVSRC", "float", 2.0, 0, 2)
    _define(fix, "FPLCMD", "str", "", None, None)
    _define(fix, "FPLCMDACK", "int", 0, -100000, 100000)
    monkeypatch.setattr(fix.db, "queue_out", lambda b: None)
    _host, w = _hsi(qtbot)
    assert w._fplstate is None
    assert not w._field_editable("crs")
    assert "crs" in w._edit_rects
    _tap(qtbot, w, _centre(w, "crs"))
    assert w._edit_field is None


def test_nav_sources_still_edit_their_own_course_in_obs(gps, qtbot):
    """FPLSTATE = 4 changes nothing on a NAV source: CRS writes NAV1CRS."""
    gps.db.set_value("NAVSRC", 0.0)
    _host, w = _hsi(qtbot)
    _tap(qtbot, w, _centre(w, "crs"))
    w.enc_changed(1)
    assert gps.db.get_item("NAV1CRS").value == 46.0
    assert _commands(gps) == []


# --- the edit sends FPLCMD OBS ------------------------------------------------

def test_a_step_sends_obs_from_the_course_shown(gps, qtbot):
    _host, w = _hsi(qtbot)
    _tap(qtbot, w, _centre(w, "crs"))
    w.enc_changed(1)
    assert _commands(gps) == ["OBS 91"]
    assert w._crs_display() == 91
    w._obs_clock.t += 1.0
    w.enc_outer_changed(-1)
    assert _commands(gps) == ["OBS 91", "OBS 81"]


def test_the_course_wraps_through_360(gps, qtbot):
    gps.db.set_value("COURSE", 355.0)
    _host, w = _hsi(qtbot)
    _tap(qtbot, w, _centre(w, "crs"))
    w.enc_outer_changed(1)
    assert _commands(gps) == ["OBS 5"]


def test_a_fast_spin_sends_a_bounded_stream_and_ends_on_the_last_value(gps, qtbot):
    """90 -> 270 in 180 one-degree detents inside 0.9 s: the gate lets one
    command through per OBS_SEND_INTERVAL_MS, and the last one is 270."""
    _host, w = _hsi(qtbot)
    _tap(qtbot, w, _centre(w, "crs"))
    for _ in range(180):
        w.enc_changed(1)
        w._obs_clock.t += 0.005
    assert w._crs_display() == 270
    # The gate's timer ends the stream on the last value.
    w._obs_clock.t += hsi.OBS_SEND_INTERVAL_MS / 1000.0
    qtbot.waitUntil(lambda: _commands(gps)[-1:] == ["OBS 270"],
                    timeout=hsi.OBS_SEND_INTERVAL_MS * 4)
    cmds = _commands(gps)
    spin_s = 180 * 0.005
    assert len(cmds) <= spin_s / (hsi.OBS_SEND_INTERVAL_MS / 1000.0) + 2
    assert cmds[0] == "OBS 91"
    assert cmds[-1] == "OBS 270"
    seqs = _seqs(gps)
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)


def test_releasing_focus_mid_spin_sends_the_last_value_at_once(gps, qtbot):
    host, w = _hsi(qtbot)
    _tap(qtbot, w, _centre(w, "crs"))
    w.enc_changed(1)          # sent at once: OBS 91
    w.enc_changed(1)          # inside the gap: held
    w.enc_changed(1)
    assert _commands(gps) == ["OBS 91"]
    host.encoder_controller.release_focus()
    assert _commands(gps) == ["OBS 91", "OBS 93"]
    assert not w._obs_timer.isActive()


def test_nothing_is_sent_when_the_knob_returns_to_the_start(gps, qtbot):
    host, w = _hsi(qtbot)
    _tap(qtbot, w, _centre(w, "crs"))
    w._obs_sent_at = w._obs_clock.t     # pretend a command just went out
    w.enc_changed(1)
    w.enc_changed(-1)
    host.encoder_controller.release_focus()
    assert _commands(gps) == []


def test_obs_ending_mid_edit_ends_the_edit_and_sends_nothing_late(gps, qtbot):
    """OBS OFF (or an ACT/DTO) while the knob turns: a held value must not
    go out afterwards, or it would put the engine back in OBS."""
    host, w = _hsi(qtbot)
    _tap(qtbot, w, _centre(w, "crs"))
    w.enc_changed(1)
    w.enc_changed(1)          # held by the gate
    gps.db.set_value("FPLSTATE", 1)
    assert w._edit_field is None
    assert host.encoder_controller.focused_instrument() is None
    qtbot.wait(hsi.OBS_SEND_INTERVAL_MS * 2)
    assert _commands(gps) == ["OBS 91"]


def test_source_change_mid_edit_sends_nothing_late(gps, qtbot):
    _host, w = _hsi(qtbot)
    _tap(qtbot, w, _centre(w, "crs"))
    w.enc_changed(1)
    w.enc_changed(1)
    gps.db.set_value("NAVSRC", 0.0)
    assert w._edit_field is None
    assert _commands(gps) == ["OBS 91"]


def test_course_key_is_never_written(gps, qtbot):
    host, w = _hsi(qtbot)
    _tap(qtbot, w, _centre(w, "crs"))
    w.enc_changed(5)
    host.encoder_controller.release_focus()
    assert not [m for m in gps.sent if m.split(";")[0] in ("COURSE", "GPSCRS")]


# --- push syncs to the bearing to the TO waypoint -----------------------------

def test_push_syncs_to_the_bearing_to_the_waypoint(gps, qtbot):
    host, w = _hsi(qtbot)
    _tap(qtbot, w, _centre(w, "crs"))
    assert w.enc_clicked() is True
    assert _commands(gps) == ["OBS 272"]
    assert host.encoder_controller.focused_instrument() is w


@pytest.mark.parametrize("flag", ["old", "bad", "fail"])
def test_push_without_a_valid_bearing_sends_nothing(gps, qtbot, flag):
    setattr(gps.db.get_item("GPSBRG"), flag, True)
    _host, w = _hsi(qtbot)
    _tap(qtbot, w, _centre(w, "crs"))
    assert w.enc_clicked() is False
    assert _commands(gps) == []


def test_marks_on_crs_only_in_obs(gps, qtbot):
    _host, w = _hsi(qtbot)
    assert w._field_editable("crs")
    gps.db.set_value("FPLSTATE", 1)
    assert not w._field_editable("crs")
