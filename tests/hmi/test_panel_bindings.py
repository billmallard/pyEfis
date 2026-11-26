"""Panel controls act on every screen (DSP2).

A button acts on its TSBTN key only while it shows, so a Tessera key or a GPIO
button on that key did nothing on any other screen, and nothing at all for the
baro, heading-bug and CDI-source buttons, which no stock screen places. The
stock data bindings now carry each button's command on its key. These tests
load the real shipped files, not fixture copies.
"""
import glob
import os
from unittest import mock

import pytest
import yaml
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget

import pyefis.hmi as hmi
from pyefis.hmi import data
from pyefis.instruments import button

CONFIG = "src/pyefis/config"
BINDINGS = os.path.join(CONFIG, "databindings/default.yaml")

# The keys fix-gateway's TESS1 spike page pulses (config/tessera/page.yaml,
# keys 2, 3, 5, 6, 7 and 9), with the key each press must change.
SPIKE_PAGE = {
    "TSBTN11": "BARO",
    "TSBTN12": "BARO",
    "TSBTN129": "HEADBUG",
    "TSBTN131": "HEADBUG",
    "TSBTN130": "HEADBUG",
    "TSBTN133": "NAVSRC",
    "TSBTN137": "MAPRANGE",
    "TSBTN138": "MAPRANGE",
}


def _stock_bindings():
    with open(BINDINGS) as f:
        return yaml.safe_load(f)["items"]


def _button_command(path):
    """The (dbkey, action, args, delay, interval) a button file runs on a click."""
    with open(path) as f:
        cfg = yaml.safe_load(f)
    for cond in cfg.get("conditions", []):
        if cond.get("when") == "CLICKED eq true":
            ((action, args),) = cond["actions"][0].items()
            timing = (None, None)
            if cfg.get("type") == "repeat":
                timing = (cfg.get("repeat_delay", 300), cfg.get("repeat_interval", 300))
            return cfg["dbkey"], action, str(args), timing
    return None


def _pulse(key):
    # What fix-gateway's {pulse: KEY} writes: True, then False.
    fix_db = data.fix.db
    fix_db.set_value(key, True)
    fix_db.set_value(key, False)


@pytest.fixture
def panel_keys(fix):
    for n in list(range(1, 12)) + list(range(27, 34)) + [36, 37, 38, 39]:
        for node in (1, 2):
            key = f"TSBTN{node}{n}"
            fix.db.define_item(key, "Touch Button", "bool", None, None, "", 0, "")
            fix.db.set_value(key, False)
            fix.db.get_item(key).bad = False
            fix.db.get_item(key).fail = False
    for key, lo, hi, val in (
        ("TRIMP", -100.0, 100.0, 0.0),
        ("TRIMR", -100.0, 100.0, 0.0),
        ("TRIMY", -100.0, 100.0, 0.0),
        ("DIM", 0.0, 100.0, 50.0),
        ("HEADBUG", 0.0, 360.0, 90.0),
        ("NAVSRC", 0.0, 3.0, 0.0),
    ):
        fix.db.define_item(key, key, "float", lo, hi, "", 50000, "")
        fix.db.set_value(key, val)
        fix.db.get_item(key).bad = False
        fix.db.get_item(key).fail = False
    # fix-gateway database/custom.yaml: the map's range ladder index.
    fix.db.define_item("MAPRANGE", "MAPRANGE", "int", 0, 7, "index", 0, "")
    fix.db.set_value("MAPRANGE", 2)
    fix.db.get_item("MAPRANGE").bad = False
    fix.db.get_item("MAPRANGE").fail = False
    fix.db.set_value("HEAD", 123.0)
    return fix


def _start(node_id=1):
    hmi.initialize({"databindings": _stock_bindings(), "main": {"nodeID": node_id}})


def _button(qtbot, name, visible):
    parent = QWidget()
    parent.screenName = "PFD"
    parent.parent = mock.Mock()
    parent.parent.nodeID = 1
    w = button.Button(parent, config_file=os.path.join(CONFIG, "buttons", name))
    qtbot.addWidget(parent)
    w.resize(100, 80)
    if visible:
        parent.resize(200, 200)
        parent.show()
        w.show()
        qtbot.waitExposed(w)
    return w


def test_baro_pulse_changes_baro_with_the_pfd_hidden(panel_keys, qtbot):
    # The definition of done: the button exists on a screen that is not
    # showing, as on a PFD behind the EMS screen.
    _start()
    _button(qtbot, "baro-down-invisible.yaml", visible=False)
    _pulse("TSBTN11")
    assert panel_keys.db.get_item("BARO").value == pytest.approx(29.91)


def test_map_range_keys_step_the_ladder_index_and_stop_at_its_ends(panel_keys):
    # TESS2 (AER-6622): RNG - and RNG + on the panel step MAPRANGE once a
    # press and do not wrap, so a pilot at the shortest range who presses
    # RNG - is not thrown out to the longest.
    _start()
    item = panel_keys.db.get_item("MAPRANGE")
    _pulse("TSBTN137")
    assert item.value == 1
    for _ in range(3):
        _pulse("TSBTN137")
    assert item.value == 0
    for _ in range(9):
        _pulse("TSBTN138")
    assert item.value == 7


@pytest.mark.parametrize("key, target", sorted(SPIKE_PAGE.items()))
def test_every_spike_page_press_changes_its_key_on_a_stock_config(
    panel_keys, key, target
):
    # No button anywhere: none of these files is on a stock screen.
    _start()
    before = panel_keys.db.get_item(target).value
    _pulse(key)
    assert panel_keys.db.get_item(target).value != before


def test_each_binding_is_its_button_files_command():
    # A binding and the button file it stands for must not drift apart.
    commands = {}
    for path in glob.glob(os.path.join(CONFIG, "buttons", "*.yaml")):
        cmd = _button_command(path)
        if cmd and cmd[0].startswith("TSBTN{id}"):
            commands[cmd[0]] = cmd
    bindings = _stock_bindings()
    assert len(bindings) == 22
    for b in bindings:
        dbkey, action, args, (delay, interval) = commands[b["key"]]
        assert (b["action"], b["args"]) == (action, args), b["key"]
        assert b["condition"] is True
        if b["action"] == "set value" or interval is None:
            assert "repeat_interval" not in b, b["key"]
        else:
            assert (b["repeat_delay"], b["repeat_interval"]) == (delay, interval)
    # Every invisible command button and the heading-bug, CDI-source,
    # baro-focus and map-range buttons have a binding.
    names = ("*-invisible.yaml", "heading-bug-*.yaml", "cdi-source.yaml",
             "baro-focus.yaml", "map-range-*.yaml")
    expected = {
        _button_command(p)[0]
        for name in names
        for p in glob.glob(os.path.join(CONFIG, "buttons", name))
    }
    assert {b["key"] for b in bindings} == expected


def test_visible_button_and_binding_step_once_per_press(panel_keys, qtbot):
    _start()
    w = _button(qtbot, "baro-up-invisible.yaml", visible=True)
    _pulse("TSBTN12")
    assert panel_keys.db.get_item("BARO").value == pytest.approx(29.93)
    # A touch on the button still acts, once.
    qtbot.mouseClick(w._button, Qt.MouseButton.LeftButton)
    assert panel_keys.db.get_item("BARO").value == pytest.approx(29.94)


def test_visible_button_without_a_binding_still_acts_on_its_key(panel_keys, qtbot):
    # An install whose bindings file predates DSP2 keeps today's behaviour:
    # the showing button acts on its key.  (Today that is three steps per
    # pulse, not one -- a separate defect of the repeat button's key path,
    # which the stock bindings bypass; not pinned here.)
    hmi.initialize({"main": {"nodeID": 1}})
    _button(qtbot, "baro-up-invisible.yaml", visible=True)
    _pulse("TSBTN12")
    assert panel_keys.db.get_item("BARO").value > 29.92


def test_held_key_repeats_like_the_button_and_stops_on_release(panel_keys, qtbot):
    _start()
    headbug = panel_keys.db.get_item("HEADBUG")
    panel_keys.db.set_value("TSBTN131", True)
    assert headbug.value == 91.0          # the press itself
    qtbot.wait(250)                      # inside repeat_delay (300 ms)
    assert headbug.value == 91.0
    qtbot.waitUntil(lambda: headbug.value >= 93.0, timeout=2000)
    panel_keys.db.set_value("TSBTN131", False)
    held = headbug.value
    qtbot.wait(200)
    assert headbug.value == held


def test_bindings_follow_the_display_node_id(panel_keys):
    # A second display (nodeID 2) answers its own keys, not display 1's, so a
    # node-1 panel press does not step BARO once per display.
    _start(node_id=2)
    baro = panel_keys.db.get_item("BARO")
    _pulse("TSBTN11")
    assert baro.value == pytest.approx(29.92)
    _pulse("TSBTN21")
    assert baro.value == pytest.approx(29.91)
    assert data.binds("TSBTN21") and not data.binds("TSBTN11")


def test_a_toggle_on_a_bound_key_switches_the_binding_off(panel_keys, qtbot, caplog):
    # The configurator hands out TSBTN{id}1.. for its own buttons.  A toggle
    # left on holds its key true; when that value arrives from the gateway
    # (a reconnect, or a boot with the toggle on), the baro binding would read
    # it as a press held forever and run BARO down every 100 ms.
    _start()
    parent = QWidget()
    parent.screenName = "PFD"
    parent.parent = mock.Mock()
    parent.parent.nodeID = 1
    w = button.Button(parent, config={"type": "toggle", "text": "LIGHTS",
                                      "dbkey": "TSBTN{id}1"})
    qtbot.addWidget(parent)
    parent.resize(200, 200)
    parent.show()
    w.resize(100, 80)
    w.show()
    qtbot.waitExposed(w)
    assert "TSBTN11 switched off: a toggle button uses it (LIGHTS)" in caplog.text
    assert not data.binds("TSBTN11")
    panel_keys.db.set_value("TSBTN11", True)   # the gateway's value arrives
    assert w._button.isChecked()               # the toggle still follows it
    qtbot.wait(500)
    assert panel_keys.db.get_item("BARO").value == pytest.approx(29.92)
    # The other bindings still act.
    _pulse("TSBTN12")
    assert panel_keys.db.get_item("BARO").value == pytest.approx(29.93)


def test_bound_repeat_button_still_draws_pressed_while_its_key_is_held(panel_keys, qtbot):
    # Before DSP2 a held key pressed the showing button, which drew its
    # pressed look.  The binding now acts; the button must still look the
    # same, without acting a second time.
    _start()
    w = _button(qtbot, "heading-bug-up.yaml", visible=True)
    headbug = panel_keys.db.get_item("HEADBUG")
    rest = w.grab().toImage()
    panel_keys.db.set_value("TSBTN131", True)
    assert w._button.isDown()
    assert w.grab().toImage() != rest
    assert headbug.value == 91.0
    panel_keys.db.set_value("TSBTN131", False)
    assert not w._button.isDown()
    assert w.grab().toImage() == rest
    assert headbug.value == 91.0
