#  SPDX-License-Identifier: GPL-2.0-or-later
"""Altimeter tape baro setting box (pyEfis #311, TK3).

BARO stays inHg on the bus. The box shows inHg (29.92) or hPa (1013); the inner
knob steps 0.01 inHg / 1 hPa, the outer ring 0.10 inHg / 10 hPa, push sets
standard and a second push restores the setting it replaced. In hPa every step must land on a whole hPa after the round trip.
"""

import os

import pytest
import yaml
from PyQt6.QtCore import QPoint, QPointF, QTimer, Qt
from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtWidgets import QWidget

import pyefis.hmi as hmi
from pyefis.instruments import altimeter, edit_focus
from pyefis.screens import screenbuilder_options
from pyefis.screens.screenbuilder_encoder import EncoderController

K = altimeter.HPA_PER_INHG


@pytest.fixture
def baro(fix):
    fix.db.define_item("BARO", "Altimeter Setting", "float", 0.0, 35.0,
                       "inHg", 50000, "")
    item = fix.db.get_item("BARO")
    item.value = 29.92
    item.bad = False
    item.fail = False
    item.old = False
    return item


@pytest.fixture(autouse=True)
def _clean_focus():
    edit_focus.set_at_rest_hint(False)
    yield
    owner = edit_focus.owner()
    if owner is not None:
        owner.release_focus()
    edit_focus.set_at_rest_hint(True)


def _tape(qtbot, **kw):
    t = altimeter.Altimeter_Tape(**kw)
    qtbot.addWidget(t)
    t.resize(120, 500)
    return t


def _hpa(item):
    return item.value * K


# --- display and conversion --------------------------------------------------

def test_box_reads_inhg_and_hpa(baro, qtbot):
    t = _tape(qtbot)
    assert t.baro_text() == ("29.92", "IN")
    t.baro_hpa = True
    assert t.baro_text() == ("1013", "HPA")


def test_inhg_fine_and_coarse_steps(baro, qtbot):
    t = _tape(qtbot)
    t.baro_step(1)
    assert baro.value == pytest.approx(29.93)
    t.baro_step(-3)
    assert baro.value == pytest.approx(29.90)
    t.baro_step(1, coarse=True)
    assert baro.value == pytest.approx(30.00)
    # Many steps do not accumulate float drift: the bus value stays on 0.01.
    for _ in range(37):
        t.baro_step(1)
    assert baro.value == round(baro.value, 2)
    assert t.baro_text()[0] == "30.37"


def test_hpa_steps_land_on_whole_hpa_after_the_round_trip(baro, qtbot):
    t = _tape(qtbot)
    t.baro_hpa = True
    # 29.92 inHg is 1013.21 hPa; the first step snaps to whole hPa.
    t.baro_step(1)
    assert _hpa(baro) == pytest.approx(1014, abs=1e-9)
    for n in range(1, 60):
        t.baro_step(-1)
        assert _hpa(baro) == pytest.approx(1014 - n, abs=1e-9)
        assert t.baro_text()[0] == str(1014 - n)
    t.baro_step(2, coarse=True)
    assert _hpa(baro) == pytest.approx(955 + 20, abs=1e-9)
    # BARO on the bus is still inHg.
    assert 28.0 < baro.value < 30.0


def test_unit_switch_mid_edit_keeps_the_bus_value(baro, qtbot):
    t = _tape(qtbot)
    t.baro_hpa = True
    t.baro_step(5)                  # 1018 hPa
    v = baro.value
    t.baro_hpa = False
    assert baro.value == v
    assert t.baro_text()[0] == "{0:.2f}".format(v)
    t.baro_step(1)                  # snaps to 0.01 inHg from there
    assert baro.value == pytest.approx(round(v, 2) + 0.01)


@pytest.mark.parametrize("hpa", [False, True])
def test_clamped_to_gcu_range(baro, qtbot, hpa):
    t = _tape(qtbot)
    t.baro_hpa = hpa
    t.baro_step(500, coarse=True)
    top = baro.value
    assert top <= altimeter.BARO_MAX_INHG
    t.baro_step(-1000, coarse=True)
    assert baro.value >= altimeter.BARO_MIN_INHG
    if hpa:
        assert _hpa(baro) == pytest.approx(932, abs=1e-9)    # ceil(27.5 inHg)
        assert top * K == pytest.approx(1066, abs=1e-9)      # floor(31.5 inHg)
    else:
        assert top == pytest.approx(31.50)
        assert baro.value == pytest.approx(27.50)


def test_clamped_to_the_fix_item_range_when_narrower(baro, qtbot):
    baro.max = 30.0
    t = _tape(qtbot)
    t.baro_step(50, coarse=True)
    assert baro.value == pytest.approx(30.0)
    t.baro_hpa = True
    t.baro_step(5)
    assert _hpa(baro) == pytest.approx(1015, abs=1e-9)       # floor(30.0 inHg)


@pytest.mark.parametrize("hpa", [False, True])
def test_push_sets_standard(baro, qtbot, hpa):
    t = _tape(qtbot)
    t.baro_hpa = hpa
    t.baro_step(7, coarse=True)
    assert t.enc_clicked() is True        # keeps focus
    assert baro.value == pytest.approx(29.92)
    assert t.baro_text()[0] == ("1013" if hpa else "29.92")


# --- second push restores (AER-4009) -----------------------------------------

@pytest.mark.parametrize("hpa", [False, True])
def test_second_push_restores_the_exact_prior_setting(baro, qtbot, hpa):
    t = _tape(qtbot)
    t.baro_hpa = hpa
    # An off-grid bus value (another source wrote it): the restore must give
    # it back bit for bit, not re-rounded to 0.01 inHg or a whole hPa.
    baro.value = 30.1234567
    t.enc_clicked()
    assert baro.value == pytest.approx(29.92)
    assert t.baro_text()[0] == ("1013" if hpa else "29.92")
    t.enc_clicked()
    assert baro.value == 30.1234567
    # The toggle is one level deep and repeats: standard, back, standard.
    t.enc_clicked()
    assert baro.value == pytest.approx(29.92)
    t.enc_clicked()
    assert baro.value == 30.1234567


def test_second_push_restores_an_hpa_setting_on_its_whole_hpa(baro, qtbot):
    t = _tape(qtbot)
    t.baro_hpa = True
    t.baro_step(-17)                       # 996 hPa
    before = baro.value
    t.enc_clicked()
    assert t.baro_text()[0] == "1013"
    t.enc_clicked()
    assert baro.value == before
    assert _hpa(baro) == pytest.approx(996, abs=1e-9)


def test_restore_reaches_the_gateway(baro, qtbot, monkeypatch):
    sent = []
    monkeypatch.setattr(baro, "output_value", lambda: sent.append(baro.value))
    t = _tape(qtbot)
    baro.value = 30.05
    t.enc_clicked()
    t.enc_clicked()
    assert sent == [pytest.approx(29.92), 30.05]


@pytest.mark.parametrize("coarse", [False, True])
def test_knob_turn_after_push_clears_the_saved_setting(baro, qtbot, coarse):
    t = _tape(qtbot)
    baro.value = 30.05
    t.enc_clicked()                        # standard, 30.05 saved
    t.baro_step(1, coarse=coarse)          # 29.93 / 30.02
    t.baro_step(-1, coarse=coarse)         # back on 29.92
    t.enc_clicked()
    # Already standard with nothing saved: no-op, 30.05 is not resurrected.
    assert baro.value == pytest.approx(29.92)
    t.baro_step(3)
    t.enc_clicked()
    assert baro.value == pytest.approx(29.92)
    t.enc_clicked()
    assert baro.value == pytest.approx(29.95)


def test_external_baro_change_clears_the_saved_setting(baro, qtbot):
    t = _tape(qtbot)
    baro.value = 30.05
    t.enc_clicked()                        # standard, 30.05 saved
    baro.value = 29.80                     # another display / the gateway
    t.enc_clicked()                        # standard again, 29.80 saved
    assert baro.value == pytest.approx(29.92)
    t.enc_clicked()
    assert baro.value == pytest.approx(29.80)


def test_external_write_back_to_standard_still_clears(baro, qtbot):
    t = _tape(qtbot)
    baro.value = 30.05
    t.enc_clicked()                        # standard, 30.05 saved
    baro.value = 30.10                     # elsewhere: changed ...
    baro.value = 29.92                     # ... and back to standard
    t.enc_clicked()
    assert baro.value == pytest.approx(29.92)   # no-op, nothing saved


def test_gateway_echo_of_our_own_write_keeps_the_saved_setting(baro, qtbot):
    t = _tape(qtbot)
    baro.value = 30.05
    t.enc_clicked()
    baro.value = baro.value                # same value back: no valueChanged
    t.enc_clicked()
    assert baro.value == 30.05


@pytest.mark.parametrize("hpa", [False, True])
def test_push_at_standard_with_nothing_saved_is_a_no_op(baro, qtbot, hpa,
                                                        monkeypatch):
    sent = []
    monkeypatch.setattr(baro, "output_value", lambda: sent.append(baro.value))
    t = _tape(qtbot)
    t.baro_hpa = hpa
    assert t.enc_clicked() is True         # still keeps focus
    assert t.enc_clicked() is True
    assert baro.value == 29.92
    assert sent == []


def test_saved_setting_survives_a_unit_switch(baro, qtbot):
    t = _tape(qtbot)
    baro.value = 30.05
    t.enc_clicked()
    t.baro_hpa = True                      # display only; BARO is unchanged
    t.enc_clicked()
    assert baro.value == 30.05
    assert t.baro_text()[0] == str(int(round(30.05 * K)))


def test_two_tapes_keep_their_own_saved_setting(baro, qtbot):
    a, b = _tape(qtbot), _tape(qtbot)
    baro.value = 30.05
    a.enc_clicked()                        # a saves 30.05; to b it is external
    b.enc_clicked()                        # standard already, nothing saved
    assert baro.value == pytest.approx(29.92)
    a.enc_clicked()
    assert baro.value == 30.05


def test_steps_are_sent_to_the_gateway(baro, qtbot, monkeypatch):
    sent = []
    monkeypatch.setattr(baro, "output_value", lambda: sent.append(baro.value))
    t = _tape(qtbot)
    t.enc_changed(1)
    t.enc_outer_changed(-1)
    assert sent == [pytest.approx(29.93), pytest.approx(29.83)]


# --- option defaults ---------------------------------------------------------

def test_box_on_for_alt_off_for_vs_explicit_wins(baro, qtbot):
    assert _tape(qtbot).baro_shown() is True
    assert _tape(qtbot, dbkey="TEST").baro_shown() is False
    assert _tape(qtbot, dbkey="TEST", show_baro=True).baro_shown() is True
    assert _tape(qtbot, show_baro=False).baro_shown() is False


def test_missing_baro_key_draws_no_box_and_never_raises(fix, qtbot, monkeypatch):
    real = fix.db.get_item

    def no_baro(key, *a, **kw):
        if key == "BARO":
            raise KeyError(key)
        return real(key, *a, **kw)

    monkeypatch.setattr(fix.db, "get_item", no_baro)
    t = _tape(qtbot)
    assert t.baro_shown() is False
    assert t.enc_selectable() is False
    assert t.touch_edit is False
    t.show()
    qtbot.waitExposed(t)
    t.viewport().repaint()


def test_screen_with_its_own_baro_readout_turns_a_defaulted_box_off(baro, qtbot):
    hmi.initialize({})
    t = _tape(qtbot)
    t.configure_baro({}, other_readout=True)
    assert t.baro_shown() is False
    assert t.touch_edit is False
    explicit = _tape(qtbot, show_baro=True)
    explicit.configure_baro({}, other_readout=True)
    assert explicit.baro_shown() is True


@pytest.mark.parametrize("pref,hpa", [(None, False), ("hPa", True),
                                      ("HPA", True), ("inHg", False),
                                      ("mb", False)])
def test_boot_unit_from_preferences(baro, qtbot, pref, hpa):
    hmi.initialize({})
    t = _tape(qtbot)
    prefs = {} if pref is None else {"units": {"Pressure": pref}}
    t.configure_baro(prefs)
    assert t.baro_hpa is hpa


def test_units_action_follows_the_pressure_group_only(baro, qtbot):
    hmi.initialize({})
    t = _tape(qtbot)
    t.configure_baro({})
    hmi.actions.trigger("Set Instrument Units", "Altitude:Toggle")
    assert t.baro_hpa is False
    # The stock Units button's argument.
    hmi.actions.trigger("Set Instrument Units",
                        "OAT,OILT1,Temperature,Pressure,Altitude:Toggle")
    assert t.baro_hpa is True
    hmi.actions.trigger("Set Instrument Units", "*:inHg")
    assert t.baro_hpa is False
    hmi.actions.trigger("Set Instrument Units", "Pressure:hPa")
    assert t.baro_hpa is True
    hmi.actions.trigger("Set Instrument Units", "Pressure:bogus")
    assert t.baro_hpa is True


class _Screen(QWidget):
    """A QWidget parent with just what EncoderController and the screen-level
    post-pass read."""

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


def test_configure_tape_baro_post_pass(baro, qtbot):
    hmi.initialize({})

    class _Readout(QWidget):
        dbkey = "BARO"

    s = _Screen()
    qtbot.addWidget(s)
    tape = altimeter.Altimeter_Tape(s)
    s.instruments = {0: tape, 1: _Readout(s)}
    screenbuilder_options.configure_tape_baro(s)
    assert tape.baro_shown() is False

    s2 = _Screen()
    qtbot.addWidget(s2)
    tape2 = altimeter.Altimeter_Tape(s2)
    hidden = _Readout(s2)
    hidden.setVisible(False)          # disabled: on an older screen
    s2.instruments = {0: tape2, 1: hidden}
    screenbuilder_options.configure_tape_baro(s2)
    assert tape2.baro_shown() is True


def _screen_with_tape(qtbot, timeout=10_000):
    hmi.initialize({})
    s = _Screen(timeout)
    qtbot.addWidget(s)
    s.resize(200, 600)
    tape = altimeter.Altimeter_Tape(s)
    tape.resize(120, 500)
    s.instruments = {0: tape}
    screenbuilder_options.configure_tape_baro(s)
    s.show()
    qtbot.waitExposed(s)
    s.encoder_controller.configure_inputs(None)
    return s, tape


def test_touch_box_then_knob_routes_fine_coarse_push(baro, qtbot):
    s, tape = _screen_with_tape(qtbot)
    box = tape.baro_box_rect().center().toPoint()
    qtbot.mouseClick(tape.viewport(), Qt.MouseButton.LeftButton, pos=box)
    ctl = s.encoder_controller
    assert ctl.focused_instrument() is tape
    assert tape.encoder_selected is True
    assert edit_focus.owner() is ctl
    ctl.changed(2)
    assert baro.value == pytest.approx(29.94)
    ctl.outer_changed(-1)
    assert baro.value == pytest.approx(29.84)
    ctl.button_changed(True)
    assert baro.value == pytest.approx(29.92)
    assert ctl.focused_instrument() is tape     # push keeps focus


def test_touch_on_the_scale_is_not_a_baro_touch(baro, qtbot):
    s, tape = _screen_with_tape(qtbot)
    qtbot.mouseClick(tape.viewport(), Qt.MouseButton.LeftButton,
                     pos=QPoint(60, 100))
    assert s.encoder_controller.focused_instrument() is None


def test_touch_elsewhere_and_timeout_clear_focus(baro, qtbot):
    s, tape = _screen_with_tape(qtbot, timeout=50)
    box = tape.baro_box_rect().center().toPoint()
    qtbot.mouseClick(tape.viewport(), Qt.MouseButton.LeftButton, pos=box)
    assert tape.encoder_selected is True
    qtbot.waitUntil(lambda: tape.encoder_selected is False, timeout=2000)
    assert edit_focus.owner() is None

    s.encoder_timeout = 10_000
    qtbot.mouseClick(tape.viewport(), Qt.MouseButton.LeftButton, pos=box)
    assert tape.encoder_selected is True
    glob = tape.viewport().mapToGlobal(QPoint(60, 100))
    assert s.encoder_controller.focus_hit(QPointF(glob)) is False
    assert s.encoder_controller.focus_hit(
        QPointF(tape.viewport().mapToGlobal(box))) is True
    qtbot.mouseClick(tape.viewport(), Qt.MouseButton.LeftButton,
                     pos=QPoint(60, 100))
    assert tape.encoder_selected is False


def test_knob_walk_reaches_the_box(baro, qtbot):
    s, tape = _screen_with_tape(qtbot)
    s.encoder_list_sorted = [0]
    s.encoder_current_selection = 0
    ctl = s.encoder_controller
    ctl.changed(1)                       # walk lands on the tape
    assert tape._baro_walk is True
    ctl.button_changed(True)             # push enters edit
    assert tape.encoder_selected is True
    ctl.changed(1)
    assert baro.value == pytest.approx(29.93)


def _render(tape):
    img = QImage(tape.viewport().size(), QImage.Format.Format_ARGB32)
    img.fill(0)
    tape.viewport().render(img)
    return img


def test_focus_marks_drawn_only_when_focused(baro, qtbot):
    s, tape = _screen_with_tape(qtbot)
    zone = tape._baro_zone()
    ring = edit_focus.ring_rect(tape.baro_box_rect())
    y = int(ring.center().y())
    x = int(ring.left())

    def ring_px():
        c = _render(tape).pixelColor(x, y)
        return (c.red(), c.green(), c.blue())

    assert ring_px() != (0, 255, 255)
    tape.enc_select()
    assert ring_px()[1:] == (255, 255) and ring_px()[0] < 80
    assert zone.contains(ring)


# --- default screens ---------------------------------------------------------

_INCLUDES = os.path.join(os.path.dirname(altimeter.__file__), "..", "..",
                         "config", "includes", "ahrs")


@pytest.mark.parametrize("name", ["virtual_vfr.yaml", "svs.yaml"])
def test_default_screens_show_one_baro_readout(name):
    with open(os.path.join(_INCLUDES, name)) as f:
        cfg = yaml.safe_load(f)
    insts = cfg["instruments"]
    others = [i for i in insts
              if (i.get("options") or {}).get("dbkey") == "BARO"
              or "baro-" in str((i.get("options") or {}).get("config", ""))]
    assert others == []
    alt_tapes = [i for i in insts if i["type"] == "altimeter_tape"
                 and (i.get("options") or {}).get("dbkey", "ALT") == "ALT"]
    assert len(alt_tapes) == 1
    opts = alt_tapes[0]["options"]
    assert opts.get("show_baro", True) is True
    assert "encoder_order" in opts


@pytest.mark.parametrize("action", ["select", "clear", "step", "units"])
def test_state_change_repaints_synchronously(baro, qtbot, monkeypatch, action):
    # On the live X11 panel a queued update() of the box reached the glass
    # seconds late on a static screen (AER-3914 bench probes); every state
    # change repaints the visible box synchronously.
    hmi.initialize({})
    t = _tape(qtbot)
    t.configure_baro({})
    t.show()
    qtbot.waitExposed(t)
    if action == "clear":
        t.enc_select()
    vp = t.viewport()
    calls = []
    monkeypatch.setattr(vp, "repaint", lambda *a: calls.append(1))
    {"select": t.enc_select,
     "clear": lambda: t.enc_highlight(False),
     "step": lambda: t.enc_changed(1),
     "units": lambda: hmi.actions.trigger("Set Instrument Units",
                                          "Pressure:hPa")}[action]()
    assert calls
