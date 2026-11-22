"""
Knob options in the instrument records (pyEfis #97, BACKLOG G95).

The screen knob was configurable only by hand-editing YAML: the gauges'
``encoder_*`` options and every instrument's ``encoder_order`` were read by
the widgets but declared nowhere, so the configurator could not offer them.
These tests pin the record rules that keep enrolment and knob options
consistent, and that the declared options reach a widget built through the
real screen path from the YAML shape a panel carries.

The anti-drift gate that holds each record's ``EncoderSupport`` to the real
widget's ``enc_*`` methods is in tests/editor/test_registry.py, next to the
action-catalogue gate.
"""
import logging

import pytest
from PyQt6.QtWidgets import QWidget

import pyefis.hmi as hmi
from pyefis.editor import schema
from pyefis.screens import instrument_spec as ispec
from pyefis.screens.instrument_spec import EncoderSupport, InstrumentSpec, Prop
from pyefis.screens.screenbuilder import Screen
from pyefis.screens.screenbuilder_factory import REGISTRY

_GAUGES = ["arc_gauge", "horizontal_bar_gauge", "vertical_bar_gauge",
           "numeric_display"]


def _order():
    return Prop("encoder_order", "integer", apply="special")


# --- record rules -------------------------------------------------------------

def test_encoder_order_needs_selectable():
    with pytest.raises(ValueError, match="exactly when encoder.selectable"):
        InstrumentSpec("x", "X", "other", properties=[_order()])
    with pytest.raises(ValueError, match="exactly when encoder.selectable"):
        InstrumentSpec("x", "X", "other", properties=[_order()],
                       encoder=EncoderSupport(editable=True))


def test_selectable_needs_encoder_order():
    with pytest.raises(ValueError, match="exactly when encoder.selectable"):
        InstrumentSpec("x", "X", "other",
                       encoder=EncoderSupport(selectable=True))


def test_encoder_order_is_special():
    with pytest.raises(ValueError, match="apply must be 'special'"):
        InstrumentSpec("x", "X", "other",
                       properties=[Prop("encoder_order", "integer")],
                       encoder=EncoderSupport(selectable=True))


@pytest.mark.parametrize("name", ["encoder_multiplier", "touch_edit"])
def test_knob_options_need_editable(name):
    with pytest.raises(ValueError, match="need encoder.editable"):
        InstrumentSpec("x", "X", "other", properties=[_order(),
                       Prop(name, "number", default=1)],
                       encoder=EncoderSupport(selectable=True))


def test_encoder_options_lists_knob_options_only():
    spec = InstrumentSpec("x", "X", "other", properties=[
        Prop("dbkey", "fixkey", default=""), _order(),
        Prop("encoder_multiplier", "number", default=1),
        Prop("touch_edit", "boolean", default=False)],
        encoder=EncoderSupport(selectable=True, editable=True))
    assert spec.encoder_options() == ["encoder_multiplier", "touch_edit"]
    assert not ispec.is_encoder_option("encoder_order")


# --- the exported schema ------------------------------------------------------

def test_every_entry_has_an_encoder_block():
    """The configurator's knob editor (G96) reads one shape for every type."""
    s = schema.build_schema()
    assert s["schema_version"] == 4
    for t, entry in s["instruments"].items():
        assert set(entry["encoder"]) == {
            "selectable", "editable", "outer_ring", "options"}, t
        for name in entry["encoder"]["options"]:
            assert name in entry["options"], f"{t}: {name} has no field"
        assert ("encoder_order" in entry["options"]) == \
            entry["encoder"]["selectable"], t


def test_gauges_export_the_full_knob_set_and_button_listbox_none():
    s = schema.build_schema()["instruments"]
    for t in _GAUGES:
        assert s[t]["encoder"] == {
            "selectable": True, "editable": True, "outer_ring": True,
            "options": REGISTRY[t].encoder_options()}
        assert "encoder_multiplier" in s[t]["encoder"]["options"]
        assert "encoder_num_mask" in s[t]["encoder"]["options"]
    assert s["button"]["encoder"] == {
        "selectable": True, "editable": False, "outer_ring": False,
        "options": []}
    assert s["listbox"]["encoder"] == {
        "selectable": True, "editable": True, "outer_ring": False,
        "options": []}
    assert s["static_text"]["encoder"] == {
        "selectable": False, "editable": False, "outer_ring": False,
        "options": []}


# --- options reach the widget through the real screen path --------------------

@pytest.fixture
def hmi_actions(qapp):
    hmi.initialize({})
    yield


class _Parent(QWidget):
    """The interface screenbuilder.Screen needs from its parent."""

    def __init__(self, screen_config):
        super().__init__()
        self._screen_config = screen_config
        self.config_path = ""
        self.nodeID = 1
        self.preferences = {
            "style": {"basic": True, "dseg": False, "segmented": False,
                      "ghost": False},
            "styles": {}, "gauges": {}, "enabled": {}, "includes": {},
            "buttons": {},
        }

    def get_config_item(self, child, key):
        return self._screen_config.get(key)

    def getRunningScreen(self):
        return "TEST"


def _build(qtbot, options, inst_type="numeric_display"):
    screen = Screen(_Parent({
        "layout": {"rows": 10, "columns": 10},
        "instruments": [{"type": inst_type, "row": 0, "column": 0,
                         "span": {"rows": 4, "columns": 4},
                         "options": options}],
        "encoder": None, "encoder_button": None, "encoder_timeout": None,
    }))
    qtbot.addWidget(screen)
    screen.resize(800, 480)
    screen.init_screen()
    return screen


@pytest.mark.parametrize("inst_type", _GAUGES)
def test_declared_knob_options_reach_the_gauge(qtbot, fix, caplog,
                                               hmi_actions, inst_type):
    """The YAML shape of the shipped radio display, minus the digit mask
    (see the next test). Every option lands, ``encoder_order`` enrols the
    gauge on the knob walk, and none is reported as undeclared."""
    caplog.set_level(logging.WARNING)
    screen = _build(qtbot, {
        "dbkey": "NUMOK", "encoder_order": 24, "encoder_set_key": "TEST",
        "encoder_multiplier": 0.025, "encoder_coarse_multiplier": 40,
        "encoder_set_real_time": True, "touch_edit": True,
        "encoder_num_mask_blank_character": "!",
        "encoder_num_enforce_multiplier": True,
        "encoder_num_require_confirm": True,
        "encoder_num_8khz_channels": True,
        "encoder_num_blink_time_on": 400, "encoder_num_blink_time_off": 200,
    }, inst_type)
    w = screen.instruments[0]
    assert screen.encoder_list == [{"inst": 0, "order": 24}]
    assert w.encoder_set_key == "TEST"
    assert w.encoder_multiplier == pytest.approx(0.025)
    assert w.encoder_coarse_multiplier == 40
    assert w.encoder_set_real_time is True
    assert w.touch_edit is True
    assert w.encoder_num_mask_blank_character == "!"
    assert w.encoder_num_enforce_multiplier is True
    assert w.encoder_num_require_confirm is True
    assert w.encoder_num_8khz_channels is True
    assert (w.encoder_num_blink_time_on, w.encoder_num_blink_time_off) == (
        400, 200)
    assert "not declared in its InstrumentSpec" not in caplog.text


def test_digit_mask_reaches_the_gauge(qtbot, fix, hmi_actions):
    """A quoted mask in YAML lands as that string. The gauge's default used
    to be the bool False, so _coerce_to_attr_type turned "000.000" into False
    and digit entry never started (4083275b to G95a)."""
    screen = _build(qtbot, {"dbkey": "NUMOK", "encoder_num_mask": "000.000"})
    assert screen.instruments[0].encoder_num_mask == "000.000"


@pytest.fixture
def com_freq(fix):
    fix.db.define_item("COMACTFREQ1", "COM active", "float", 118.0, 136.975,
                       "MHz", 50000, "")
    fix.db.set_value("COMACTFREQ1", 121.5)
    item = fix.db.get_item("COMACTFREQ1")
    item.bad = item.fail = item.old = False
    return item


def test_radio_digit_entry_push_turn_push(qtbot, com_freq, hmi_actions):
    """The knob options of includes/mgl/v16/square-active-radio-display.yaml,
    through the real screen path. Push starts digit entry, a turn moves the
    current digit, a push takes it and moves on. The first digit of
    118.000-136.975 can only be 1, so entry starts on the second."""
    screen = _build(qtbot, {
        "clipping": True, "font_mask": "000.000", "decimal_places": 3,
        "dbkey": "COMACTFREQ1", "encoder_order": 400024,
        "encoder_multiplier": 0.025, "encoder_num_enforce_multiplier": True,
        "encoder_num_mask": "000.000",
    })
    w = screen.instruments[0]
    assert w.enc_select() is True                     # push
    assert w.encoder_num_digit == 1
    assert w.encoder_num_digit_options == ["1", "2", "3"]
    assert w.encoder_num_string.startswith("11")
    assert w.enc_changed(1) is True                   # turn
    assert w.encoder_num_string.startswith("12")
    assert w.enc_clicked() is True                    # push: next digit
    assert w.encoder_num_digit == 2
    assert w.encoder_num_string.startswith("12")
    assert w.encoder_num_digit_options == [str(d) for d in range(10)]
    assert w.encoder_set_value is None                # not committed yet


@pytest.mark.parametrize("inst_type", _GAUGES)
def test_string_options_do_not_default_to_bool(qtbot, fix, hmi_actions,
                                               inst_type):
    """A declared string option whose widget default is a bool is coerced to
    True/False by apply_options; that is how the digit mask died."""
    w = _build(qtbot, {"dbkey": "NUMOK"}, inst_type).instruments[0]
    bad = [p.name for p in REGISTRY[inst_type].properties
           if p.kind == "string"
           and isinstance(getattr(w, p.name, None), bool)]
    assert bad == []
