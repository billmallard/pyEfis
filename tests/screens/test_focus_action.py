#  SPDX-License-Identifier: GPL-2.0-or-later
"""The ``focus`` HMI action: a panel key picks what the knob turns (TESS2b,
AER-6630).

A Tessera key pulses ``TSBTN{id}32``; the stock binding runs ``focus:
HEADBUG``, and the visible screen gives knob control to the value that edits
HEADBUG, as a touch on it would. The screens here are real ``Screen`` objects
built from config, and the pulse arrives the way fix-gateway writes it.
"""

import logging
import os
import threading

import pytest
import yaml
from PyQt6.QtCore import QRect, QThread, QTimer
from PyQt6.QtGui import QPaintEvent
from PyQt6.QtWidgets import QApplication, QWidget

import pyefis.hmi as hmi
from pyefis.hmi import data
from pyefis.instruments import edit_focus
from pyefis.instruments.altimeter import Altimeter_Tape
from pyefis.instruments.autopilot import AutopilotPanel
from pyefis.instruments.hsi import HSI
from pyefis.instruments.map import MovingMap
from pyefis.screens.screenbuilder import Screen

BINDINGS = "src/pyefis/config/databindings/default.yaml"


# Screens built by _screen in this test, kept alive until teardown.
_BUILT = []


@pytest.fixture(autouse=True)
def _clean_registry(qtbot):
    # qtbot first, so its widget teardown runs after ours.
    edit_focus.set_at_rest_hint(False)
    yield
    # A moving map repaints from its own frame clock. Stop every timer and
    # hide each screen while its Python objects are still referenced, or the
    # clock paints a map whose screen is half collected during qtbot's
    # teardown (a segfault in CI, AER-6622).
    while _BUILT:
        screen = _BUILT.pop()
        for timer in screen.findChildren(QTimer):
            timer.stop()
        screen.hide()
    owner = edit_focus.owner()
    if owner is not None:
        owner.release_focus()
    edit_focus.release(edit_focus.owner())
    edit_focus.set_at_rest_hint(True)


@pytest.fixture
def keys(fix, monkeypatch):
    for key, val in (("HEADBUG", 120.0), ("NAVSRC", 0.0), ("NAVTYPE", 1.0),
                     ("NAV1CRS", 45.0), ("NAV2CRS", 200.0), ("GPSCRS", 10.0)):
        fix.db.define_item(key, key, "float", 0.0, 359.9, "deg", 50000, "")
        fix.db.set_value(key, val)
        it = fix.db.get_item(key)
        it.old = it.bad = it.fail = False
    fix.db.set_value("HEAD", 87.0)
    fix.db.set_value("COURSE", 45.0)
    # Every key a stock binding names, so the bindings load.
    panel = [("TSBTN1%d" % n, "bool", None, None)
             for n in list(range(1, 12)) + list(range(27, 34)) + [36, 37, 38, 39]]
    for key, dtype, lo, hi in [("ENC1", "int", -32768, 32767),
                               ("BTN1", "bool", None, None),
                               ("MAPRANGE", "int", 0, 7)] + panel:
        fix.db.define_item(key, key, dtype, lo, hi, "", 0, "")
        fix.db.set_value(key, 0 if dtype == "int" else False)
        it = fix.db.get_item(key)
        it.old = it.bad = it.fail = False
    sent = []
    monkeypatch.setattr(fix.db, "queue_out", lambda b: sent.append(b.decode()))
    fix.sent = sent
    with open(BINDINGS) as f:
        bindings = yaml.safe_load(f)["items"]
    # As main.py does: the actions exist before any screen is built.
    hmi.initialize({"databindings": bindings, "main": {"nodeID": 1}})
    return fix


class _Main(QWidget):
    """The slice of gui.Main a Screen reads."""

    def __init__(self, config):
        super().__init__()
        self._config = config
        self.config_path = "."
        self.nodeID = 1
        self.preferences = {
            "style": {"basic": True, "dseg": False, "segmented": False,
                      "ghost": False},
            "styles": {}, "gauges": {}, "enabled": {}, "includes": {},
            "buttons": {},
        }

    def get_config_item(self, child, key):
        return self._config.get(key)

    def getRunningScreen(self):
        return "PFD"


def _screen(qtbot, instruments, show=True):
    config = {
        "layout": {"rows": 10, "columns": 20},
        "instruments": instruments,
        "encoder": "ENC1",
        "encoder_button": "BTN1",
        "encoder_timeout": None,
    }
    main = _Main(config)
    screen = Screen(main)
    screen.screenName = "PFD"
    qtbot.addWidget(main)
    main.resize(1000, 500)
    screen.resize(1000, 500)
    screen.init_screen()
    if show:
        main.show()
        screen.show()
        qtbot.waitExposed(screen)
        for inst in screen.instruments.values():
            if isinstance(inst, HSI):
                # Direct, as the HSI tests do: the paint records the readouts.
                inst.paintEvent(QPaintEvent(QRect(inst.rect())))
    _BUILT.append(screen)
    return screen


HSI_CFG = {"type": "horizontal_situation_indicator", "row": 0, "column": 0,
           "span": {"rows": 10, "columns": 10},
           "options": {"cdi_enabled": True}}
AP_CFG = {"type": "autopilot_panel", "row": 0, "column": 10,
          "span": {"rows": 4, "columns": 10}}


def _pulse(key):
    # fix-gateway's {pulse: KEY}: True, then False.
    data.fix.db.set_value(key, True)
    data.fix.db.set_value(key, False)


def _turn(fix, steps):
    # The knob, as fix-gateway writes it.
    fix.db.set_value("ENC1", steps)


def _sent(fix, key):
    return [float(m.split(";")[1]) for m in fix.sent if m.startswith(key + ";")]


def _of(screen, cls):
    (inst,) = [i for i in screen.instruments.values() if isinstance(i, cls)]
    return inst


def test_a_tsbtn_pulse_gives_the_knob_to_the_hsi_heading_bug(keys, qtbot):
    screen = _screen(qtbot, [HSI_CFG])
    hsi = _of(screen, HSI)
    _pulse("TSBTN132")
    assert hsi._edit_field == "hdg"
    assert screen.encoder_controller.focused_instrument() is hsi
    assert edit_focus.owner() is screen.encoder_controller
    _turn(keys, 3)
    assert _sent(keys, "HEADBUG")[-1] == pytest.approx(123.0)


def test_a_pulse_from_the_fix_client_thread_focuses_on_the_gui_thread(
        keys, qtbot, monkeypatch):
    # On a display the pulse arrives on pyavtools' client thread. Focus
    # moves widgets, so it must run on the GUI thread: PyQt's proxy for the
    # binding's plain-function slot lives there and queues the call.
    screen = _screen(qtbot, [HSI_CFG])
    hsi = _of(screen, HSI)
    ran_on = []
    real = type(screen.encoder_controller).touch_focus

    def recording(ctl, inst):
        ran_on.append(QThread.currentThread())
        return real(ctl, inst)

    monkeypatch.setattr(type(screen.encoder_controller), "touch_focus", recording)
    t = threading.Thread(target=_pulse, args=("TSBTN132",))
    t.start()
    t.join()
    qtbot.waitUntil(lambda: hsi._edit_field == "hdg", timeout=2000)
    assert ran_on == [QApplication.instance().thread()]


def test_the_pulse_focuses_the_autopilot_hdg_box(keys, qtbot):
    screen = _screen(qtbot, [AP_CFG])
    ap = _of(screen, AutopilotPanel)
    _pulse("TSBTN132")
    assert ap._edit_box == "hdg"
    assert ap.boxes["hdg"].focused
    assert screen.encoder_controller.focused_instrument() is ap
    _turn(keys, -2)
    assert _sent(keys, "HEADBUG")[-1] == pytest.approx(118.0)


def test_the_first_instrument_in_the_file_wins(keys, qtbot):
    screen = _screen(qtbot, [AP_CFG, HSI_CFG])
    _pulse("TSBTN132")
    assert screen.encoder_controller.focused_instrument() is \
        _of(screen, AutopilotPanel)
    assert _of(screen, HSI)._edit_field is None


def test_an_instrument_not_showing_is_passed_over(keys, qtbot):
    # As on a tab_section's other tab: the HSI painted once, so it still
    # holds its readout boxes, but it is not on the glass.
    screen = _screen(qtbot, [HSI_CFG, AP_CFG])
    _of(screen, HSI).hide()
    _pulse("TSBTN132")
    assert _of(screen, HSI)._edit_field is None
    assert screen.encoder_controller.focused_instrument() is \
        _of(screen, AutopilotPanel)


def test_a_readout_that_is_not_drawn_cannot_be_named(keys, qtbot):
    screen = _screen(qtbot, [HSI_CFG])
    hsi = _of(screen, HSI)
    hsi.readout_layout = "none"
    hsi.paintEvent(QPaintEvent(QRect(hsi.rect())))
    _pulse("TSBTN132")
    assert screen.encoder_controller.focused_instrument() is None


def _no_touch(cfg):
    return dict(cfg, options=dict(cfg.get("options", {}), touch_edit=False))


@pytest.mark.parametrize("first, other", [(HSI_CFG, AutopilotPanel),
                                          (AP_CFG, HSI)],
                         ids=["hsi", "autopilot"])
def test_touch_edit_off_means_the_action_cannot_focus_it_either(
        keys, qtbot, first, other):
    # First in the file, so it would win if it answered.
    screen = _screen(qtbot, [_no_touch(first), dict(HSI_CFG if other is HSI
                                                     else AP_CFG)])
    _pulse("TSBTN132")
    assert screen.encoder_controller.focused_instrument() is _of(screen, other)


def test_touch_edit_off_alone_does_nothing(keys, qtbot):
    screen = _screen(qtbot, [_no_touch(HSI_CFG)])
    _pulse("TSBTN132")
    assert screen.encoder_controller.focused_instrument() is None
    assert edit_focus.owner() is None


def test_a_key_no_shown_value_can_take_leaves_the_focus_alone(keys, qtbot):
    keys.db.define_item("ALTSEL", "ALTSEL", "int", -1000, 60000, "", 0, "")
    keys.db.set_value("ALTSEL", 5000)
    screen = _screen(qtbot, [_no_touch(HSI_CFG), AP_CFG])
    ap = _of(screen, AutopilotPanel)
    hmi.actions.trigger("focus", "ALTSEL")
    assert ap._edit_box == "altsel"
    hmi.actions.trigger("focus", "NAV1CRS")   # only the untouchable HSI edits it
    assert screen.encoder_controller.focused_instrument() is ap
    assert ap._edit_box == "altsel"


def test_the_autopilot_answers_for_each_box_by_its_key(keys, qtbot):
    keys.db.define_item("ALTSEL", "ALTSEL", "int", -1000, 60000, "", 0, "")
    keys.db.set_value("ALTSEL", 5000)
    screen = _screen(qtbot, [AP_CFG])
    ap = _of(screen, AutopilotPanel)
    hmi.actions.trigger("focus", "NAV1CRS")     # no box edits it
    assert screen.encoder_controller.focused_instrument() is None
    hmi.actions.trigger("focus", "ALTSEL")
    assert ap._edit_box == "altsel"
    _pulse("TSBTN132")                          # the other box: focus moves
    assert ap._edit_box == "hdg"


def test_a_hidden_screen_does_not_take_focus(keys, qtbot):
    screen = _screen(qtbot, [HSI_CFG], show=False)
    _pulse("TSBTN132")
    assert screen.encoder_controller.focused_instrument() is None
    assert edit_focus.owner() is None
    assert _of(screen, HSI)._edit_field is None


def test_only_the_visible_screen_answers(keys, qtbot):
    shown = _screen(qtbot, [HSI_CFG])
    hidden = _screen(qtbot, [HSI_CFG], show=False)
    _pulse("TSBTN132")
    assert edit_focus.owner() is shown.encoder_controller
    assert hidden.encoder_controller.focused_instrument() is None


def test_a_key_nothing_on_screen_edits_does_nothing(keys, qtbot, caplog):
    caplog.set_level(logging.INFO)
    screen = _screen(qtbot, [HSI_CFG])
    hmi.actions.trigger("focus", "ALTSEL")
    assert edit_focus.owner() is None
    assert "focus ALTSEL: no value on screen PFD edits it" in caplog.text
    # The heading readout is still there to take it.
    hmi.actions.trigger("focus", "HEADBUG")
    assert screen.encoder_controller.focused_instrument() is _of(screen, HSI)


@pytest.fixture
def baro(keys):
    keys.db.define_item("BARO", "Altimeter Setting", "float", 0.0, 35.0,
                        "inHg", 50000, "")
    keys.db.set_value("BARO", 29.92)
    keys.db.define_item("ALT", "ALT", "float", -1000.0, 60000.0, "ft",
                        50000, "")
    keys.db.define_item("ALTSEL", "ALTSEL", "int", -1000, 60000, "", 0, "")
    keys.db.set_value("ALTSEL", 5000)
    for key in ("BARO", "ALT", "ALTSEL"):
        it = keys.db.get_item(key)
        it.old = it.bad = it.fail = False
    return keys


ALT_CFG = {"type": "altimeter_tape", "row": 0, "column": 10,
           "span": {"rows": 10, "columns": 3},
           "options": {"dbkey": "ALT", "altsel_box": True}}


def test_a_tsbtn136_pulse_gives_the_knob_to_the_baro_box(baro, qtbot):
    # TESS2 on the bench: the panel's BARO key flashed red and the knob kept
    # whatever it had until the altitude box on the glass was touched.
    screen = _screen(qtbot, [HSI_CFG, ALT_CFG])
    tape = _of(screen, Altimeter_Tape)
    _pulse("TSBTN136")
    assert tape._edit_box == "baro"
    assert screen.encoder_controller.focused_instrument() is tape
    assert edit_focus.owner() is screen.encoder_controller
    _turn(baro, 2)
    assert _sent(baro, "BARO")[-1] == pytest.approx(29.94)


def test_the_altimeter_answers_for_each_box_by_its_key(baro, qtbot):
    screen = _screen(qtbot, [ALT_CFG])
    tape = _of(screen, Altimeter_Tape)
    hmi.actions.trigger("focus", "ALTSEL")
    assert tape._edit_box == "altsel"
    _pulse("TSBTN136")                          # the other box: focus moves
    assert tape._edit_box == "baro"
    assert screen.encoder_controller.focused_instrument() is tape


def test_heading_then_baro_moves_focus_between_instruments(baro, qtbot):
    screen = _screen(qtbot, [HSI_CFG, ALT_CFG])
    _pulse("TSBTN132")
    assert screen.encoder_controller.focused_instrument() is _of(screen, HSI)
    _pulse("TSBTN136")
    assert screen.encoder_controller.focused_instrument() is \
        _of(screen, Altimeter_Tape)
    assert _of(screen, HSI)._edit_field is None


def test_touch_edit_off_means_the_baro_box_cannot_be_named(baro, qtbot):
    screen = _screen(qtbot, [_no_touch(ALT_CFG)])
    _pulse("TSBTN136")
    assert screen.encoder_controller.focused_instrument() is None


MAP_CFG = {"type": "moving_map", "row": 0, "column": 10,
           "span": {"rows": 10, "columns": 10},
           "options": {"range_key": "MAPRANGE",
                       "range_ladder": "2,10,50,200,500,2000"}}


def _map_screen(qtbot, cfg=MAP_CFG):
    data.fix.db.set_value("MAPRANGE", 1)        # 10 NM on this ladder
    screen = _screen(qtbot, [cfg])
    m = _of(screen, MovingMap)
    # The map wires its range_key after its first paint.
    m.repaint()
    qtbot.waitUntil(lambda: bool(getattr(m, "_live_binds", None)), timeout=2000)
    assert m.range_nm == pytest.approx(10.0)
    return screen, m


def _outer(screen, steps):
    screen.encoder_controller.outer_changed(steps)


def _push(screen):
    screen.encoder_controller.button_changed(True)
    screen.encoder_controller.button_changed(False)


def test_a_tsbtn139_pulse_gives_the_knob_to_the_map_range(keys, qtbot):
    # TESS2 (AER-6622), Bill: zoom the map with the Knobster to any range,
    # not only the ladder's.
    screen, m = _map_screen(qtbot)
    _pulse("TSBTN139")
    assert screen.encoder_controller.focused_instrument() is m
    assert m._knob_focus
    assert edit_focus.owner() is screen.encoder_controller


def test_the_inner_knob_zooms_smoothly_clockwise_wider(keys, qtbot):
    screen, m = _map_screen(qtbot)
    _pulse("TSBTN139")
    _turn(keys, 1)
    assert m.range_nm == pytest.approx(12.5)
    _turn(keys, -2)
    assert m.range_nm == pytest.approx(8.0)
    # Clamped to the ladder's span, as a pinch is.
    _turn(keys, -40)
    assert m.range_nm == pytest.approx(2.0)


def test_the_outer_ring_steps_the_ladder(keys, qtbot):
    screen, m = _map_screen(qtbot)
    _pulse("TSBTN139")
    _turn(keys, 1)                               # 12.5, between rungs
    _outer(screen, 1)
    assert m.range_nm == pytest.approx(50.0)
    _outer(screen, -2)
    assert m.range_nm == pytest.approx(2.0)


def test_the_push_snaps_to_the_nearest_rung_and_keeps_the_knob(keys, qtbot):
    screen, m = _map_screen(qtbot)
    _pulse("TSBTN139")
    _turn(keys, 1)                               # 12.5
    _push(screen)
    assert m.range_nm == pytest.approx(10.0)
    assert screen.encoder_controller.focused_instrument() is m


def test_a_knob_zoom_publishes_the_nearest_rung(keys, qtbot):
    # So RANGE + and - step from the range on the glass.
    screen, m = _map_screen(qtbot)
    _pulse("TSBTN139")
    _turn(keys, 8)                               # 10 x 1.25^8 = 59.6 NM
    assert keys.db.get_item("MAPRANGE").value == 2   # 50 NM


def test_the_map_knob_times_out_like_a_touch(keys, qtbot):
    screen, m = _map_screen(qtbot)
    screen.encoder_timeout = 100
    _pulse("TSBTN139")
    qtbot.waitUntil(
        lambda: screen.encoder_controller.focused_instrument() is None,
        timeout=2000)
    assert not m._knob_focus


def test_a_map_bound_to_another_key_does_not_answer_maprange(keys, qtbot):
    cfg = dict(MAP_CFG, options=dict(MAP_CFG["options"], range_key="OTHER"))
    screen = _screen(qtbot, [cfg])
    hmi.actions.trigger("focus", "MAPRANGE")
    assert screen.encoder_controller.focused_instrument() is None


def test_a_baro_pulse_takes_the_knob_from_the_map(baro, qtbot):
    screen = _screen(qtbot, [ALT_CFG, dict(MAP_CFG, column=0)])
    _pulse("TSBTN139")
    assert screen.encoder_controller.focused_instrument() is \
        _of(screen, MovingMap)
    _pulse("TSBTN136")
    assert screen.encoder_controller.focused_instrument() is \
        _of(screen, Altimeter_Tape)
    assert not _of(screen, MovingMap)._knob_focus


def test_crs_answers_for_the_key_it_edits_now_and_hdg_takes_over(keys, qtbot):
    screen = _screen(qtbot, [HSI_CFG])
    hsi = _of(screen, HSI)
    hmi.actions.trigger("focus", "NAV2CRS")      # NAVSRC 0: CRS edits NAV1CRS
    assert hsi._edit_field is None
    hmi.actions.trigger("focus", "NAV1CRS")
    assert hsi._edit_field == "crs"
    # The same instrument, the other readout: focus moves, not just the
    # timeout restarting on CRS.
    _pulse("TSBTN132")
    assert hsi._edit_field == "hdg"
    _turn(keys, 1)
    assert _sent(keys, "HEADBUG")[-1] == pytest.approx(121.0)
    assert _sent(keys, "NAV1CRS") == []


def test_focus_times_out_like_a_touch(keys, qtbot):
    screen = _screen(qtbot, [HSI_CFG])
    screen.encoder_timeout = 100
    _pulse("TSBTN132")
    assert screen.encoder_controller.focused_instrument() is not None
    qtbot.waitUntil(
        lambda: screen.encoder_controller.focused_instrument() is None,
        timeout=2000)
    assert _of(screen, HSI)._edit_field is None


@pytest.mark.parametrize("name, dbkey, key", [
    ("heading-bug-focus.yaml", "TSBTN{id}32", "HEADBUG"),
    ("baro-focus.yaml", "TSBTN{id}36", "BARO"),
    ("map-range-focus.yaml", "TSBTN{id}39", "MAPRANGE"),
])
def test_the_button_file_runs_the_same_action(name, dbkey, key):
    path = os.path.join("src/pyefis/config/buttons", name)
    with open(path) as f:
        cfg = yaml.safe_load(f)
    assert cfg["dbkey"] == dbkey
    (cond,) = cfg["conditions"]
    assert cond["actions"] == [{"focus": key}]
