"""
The ``aircraft_ref`` Prop kind and the gauges' ``tank`` reference
(AER-5464, BACKLOG FUEL1d, row F4 of the FUEL1 brief).

A gauge can be bound to a fuel tank on the aircraft profile instead of to a
FIX key. The panel stores only the tank's id (``tank: tk_19c2``). The
configurator resolves it at serve time into ``dbkey: FUELQ<slot>`` and
``name: <label>`` and drops the reference (brief section 5, decision D1), so
the widget never sees it. These tests pin the record, the schema field the
editor's picker reads, and that an unresolved reference reaching the device
is ignored rather than applied.
"""
import json
import logging

import pytest
from PyQt6.QtWidgets import QWidget

import pyefis.hmi as hmi
from pyefis.editor import schema
from pyefis.screens import instrument_spec as ispec
from pyefis.screens.instrument_spec import InstrumentSpec, Prop
from pyefis.screens.screenbuilder import Screen
from pyefis.screens.screenbuilder_factory import REGISTRY

_GAUGES = ["vertical_bar_gauge", "horizontal_bar_gauge", "arc_gauge"]
_TANK_RESOLVES = {"dbkey": "slot_key", "name": "label"}


# --- the Prop kind ----------------------------------------------------------

def _ref(**kwargs):
    kwargs.setdefault("source", "aircraft.fuel.tanks")
    return Prop("tank", "aircraft_ref", **kwargs)


def test_aircraft_ref_is_a_prop_kind():
    assert "aircraft_ref" in ispec.PROP_KINDS


def test_aircraft_ref_requires_a_source():
    with pytest.raises(ValueError, match="requires source"):
        _ref(source="")


def test_aircraft_ref_takes_no_default():
    with pytest.raises(ValueError, match="no default"):
        _ref(default="tk_1")


def test_aircraft_ref_is_never_applied_to_the_widget():
    assert _ref().apply == "special"
    with pytest.raises(ValueError, match="apply must be 'special'"):
        _ref(apply="setter:setDbkey")


@pytest.mark.parametrize("resolves", [
    ["dbkey"], {"dbkey": 3}, {"": "label"}, {"name": ""},
])
def test_aircraft_ref_resolves_must_map_names_to_fields(resolves):
    with pytest.raises(ValueError, match="resolves must map"):
        _ref(resolves=resolves)


@pytest.mark.parametrize("extra", [
    {"source": "aircraft.fuel.tanks"}, {"multi": True},
    {"resolves": {"name": "label"}},
])
def test_reference_fields_belong_to_aircraft_ref_only(extra):
    with pytest.raises(ValueError, match="only for kind 'aircraft_ref'"):
        Prop("name", "string", **extra)


def test_multi_reference_is_allowed():
    p = Prop("checklists", "aircraft_ref", source="aircraft.checklists",
             multi=True)
    assert p.multi and p.resolves is None


def test_resolves_must_name_options_the_record_declares():
    with pytest.raises(ValueError, match=r"does not declare \['dbkey'\]"):
        InstrumentSpec(type="t", label="T", category="gauge", properties=[
            Prop("name", "string"), _ref(resolves=_TANK_RESOLVES)])


# --- the gauges' tank reference ---------------------------------------------

@pytest.mark.parametrize("inst_type", _GAUGES)
def test_gauge_declares_the_tank_reference(inst_type):
    p = REGISTRY[inst_type].prop("tank")
    assert p is not None, f"{inst_type} has no tank Prop"
    assert p.kind == "aircraft_ref"
    assert p.source == "aircraft.fuel.tanks"
    assert p.multi is False
    assert p.resolves == _TANK_RESOLVES
    assert p.label == "Tank"
    assert p.default is None


def test_only_the_bar_and_arc_gauges_reference_a_tank():
    owners = sorted(t for t, spec in REGISTRY.items()
                    if any(p.kind == "aircraft_ref" for p in spec.properties))
    assert owners == sorted(_GAUGES)


@pytest.mark.parametrize("inst_type", _GAUGES)
def test_schema_field_carries_source_multi_and_resolves(inst_type):
    entry = json.loads(schema.to_json())["instruments"][inst_type]
    assert entry["options"]["tank"] == {
        "type": "aircraft_ref", "default": None, "label": "Tank",
        "help": "Bind to a tank from the aircraft page",
        "source": "aircraft.fuel.tanks", "multi": False,
        "resolves": _TANK_RESOLVES,
    }
    # A new gauge is not given an empty reference.
    assert "tank" not in entry["default_options"]
    assert "tank" not in entry["required_options"]


# --- an unresolved reference on the device ----------------------------------

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


def _build(qtbot, instruments):
    screen = Screen(_Parent({
        "layout": {"rows": 10, "columns": 10},
        "instruments": instruments,
        "encoder": None, "encoder_button": None, "encoder_timeout": None,
    }))
    qtbot.addWidget(screen)
    screen.resize(800, 480)
    screen.init_screen()
    return screen


@pytest.mark.parametrize("inst_type", _GAUGES)
def test_unresolved_tank_is_ignored_on_the_device(qtbot, fix, caplog,
                                                  hmi_actions, inst_type):
    """A hand-copied editor YAML still carries ``tank:``. The gauge builds
    from its plain options and the reference never reaches the widget."""
    caplog.set_level(logging.WARNING)
    screen = _build(qtbot, [{
        "type": inst_type, "row": 0, "column": 0,
        "span": {"rows": 4, "columns": 2},
        "options": {"tank": "tk_19c2", "dbkey": "NUMOK", "name": "L TIP"},
    }])

    widget = screen.instruments[0]
    assert not hasattr(widget, "tank")
    assert widget.name == "L TIP"
    assert widget.value == pytest.approx(50.91)
    assert "unresolved aircraft reference" in caplog.text
    assert "not declared in its InstrumentSpec" not in caplog.text
