"""
The unit-switching options are declared, and dispatch on the declaration
(AER-6586, BACKLOG INS3).

``temperature``, ``pressure``, ``altitude`` and ``egt_mode_switching`` were
handled by ``apply_options`` on a substring of the option name and of the type
name (``"gauge" in config["type"]``), and no InstrumentSpec declared them. So
the configurator could not offer them, and a typo in one drew no warning.
Each is now a boolean ``apply="special"`` Prop on exactly the types the old
tests served, and ``apply_options`` switches units only where it is declared.

1. The switch engages on each type it did before, and on no other:
   ``_old_dispatch`` is the removed predicates, verbatim, evaluated over every
   registered type.
2. Every shipped use of the four options is declared by its type. Every other
   shipped option is either declared or in a named baseline that can only
   shrink.
3. The editor schema carries the four options for those types.
"""
import glob
import logging
import os
import re
from types import SimpleNamespace

import pytest
import yaml

from pyefis.editor import schema as eschema
from pyefis.screens import screenbuilder_config
from pyefis.screens import screenbuilder_factory as factory
from pyefis.screens import screenbuilder_options


SWITCHES = ("temperature", "pressure", "altitude", "egt_mode_switching")

CONFIG_DIR = os.path.normpath(os.path.join(
    os.path.dirname(__file__), "..", "..", "src", "pyefis", "config"))


def _old_dispatch(option, inst_type):
    """What the pre-AER-6586 ``apply_options`` did with ``option: true``: the
    unit group it switched, "egt_mode", or None. Copied from the removed
    branches, in their order."""
    if "egt_mode_switching" == option and inst_type == "vertical_bar_gauge":
        return "egt_mode"
    if "temperature" in option and (
            "gauge" in inst_type or inst_type == "numeric_display"):
        return "Temperature"
    if "pressure" in option and (
            "gauge" in inst_type or inst_type == "numeric_display"):
        return "Pressure"
    if "altitude" in option and inst_type in [
            "gauge", "numeric_display", "altimeter_tape", "altimeter_dial"]:
        return "Altitude"
    return None


class _Widget:
    def __init__(self):
        self.unit_switching_set = 0
        self.unitGroup = None

    def setUnitSwitching(self):
        self.unit_switching_set += 1

    def setMode(self, args):
        pass

    def setUnits(self, units):
        pass


class _Signal:
    def __init__(self):
        self.connected = []

    def connect(self, slot):
        self.connected.append(slot)


def _apply(monkeypatch, inst_type, options):
    """Run the real apply_options on a stand-in widget; return the widget and
    the slots connected to the set-egt-mode action."""
    signal = _Signal()
    monkeypatch.setattr(screenbuilder_options, "hmi", SimpleNamespace(
        actions=SimpleNamespace(setEgtMode=signal)))
    widget = _Widget()
    screen = SimpleNamespace(instruments={0: widget},
                             parent=SimpleNamespace(preferences={}))
    screenbuilder_options.apply_options(
        screen, 0, {"type": inst_type, "options": dict(options)})
    return widget, signal.connected


def _new_dispatch(monkeypatch, option, inst_type):
    widget, connected = _apply(monkeypatch, inst_type, {option: True})
    if connected:
        return "egt_mode"
    if widget.unit_switching_set:
        return widget.unitGroup
    return None


@pytest.mark.parametrize("option", SWITCHES)
def test_switch_engages_on_exactly_the_types_it_did_before(monkeypatch, option):
    before = {t: _old_dispatch(option, t) for t in factory.REGISTRY}
    after = {t: _new_dispatch(monkeypatch, option, t)
             for t in factory.REGISTRY}
    assert after == before
    # And the comparison is not vacuous: each option engages somewhere.
    assert any(before.values())


def test_the_types_that_switch_are_the_ones_the_records_declare():
    """The declaration is the dispatch: a type switches an option's units
    exactly when its record declares that option."""
    for option in SWITCHES:
        for t, spec in factory.REGISTRY.items():
            declared = spec.prop(option) is not None
            assert declared == (_old_dispatch(option, t) is not None), (t, option)
            if declared:
                p = spec.prop(option)
                assert (p.kind, p.apply, p.default) == (
                    "boolean", "special", False), (t, option)


def test_declared_false_is_applied_as_before_and_not_warned(monkeypatch, caplog):
    """``temperature: false`` keeps the old fall-through (a plain attribute),
    and is no longer reported as undeclared."""
    with caplog.at_level(logging.WARNING, logger=screenbuilder_options.log.name):
        widget, connected = _apply(monkeypatch, "arc_gauge",
                                   {"temperature": False})
    assert widget.unit_switching_set == 0 and not connected
    assert widget.temperature is False
    assert "not declared" not in caplog.text


def test_undeclared_switch_is_warned_and_does_not_switch(monkeypatch, caplog):
    """``altitude: true`` on a bar gauge never switched units; it still does
    not, and it is reported as an option the type does not declare."""
    with caplog.at_level(logging.WARNING, logger=screenbuilder_options.log.name):
        widget, _ = _apply(monkeypatch, "vertical_bar_gauge",
                           {"altitude": True})
    assert widget.unit_switching_set == 0
    assert "'altitude' is not declared" in caplog.text


def test_a_name_that_only_contains_a_switch_no_longer_switches(monkeypatch):
    """The old substring test switched ``oil_temperature: true``; dispatch is
    now on the declared name only. No shipped config uses such a name (see
    test_shipped_configs_use_only_the_exact_switch_names)."""
    assert _old_dispatch("oil_temperature", "arc_gauge") == "Temperature"
    assert _new_dispatch(monkeypatch, "oil_temperature", "arc_gauge") is None


# --- Shipped configs --------------------------------------------------------

def _preferences():
    with open(os.path.join(CONFIG_DIR, "preferences.yaml")) as f:
        return yaml.safe_load(f)


def _entry_options(entry, common, prefs):
    """Every option an entry can carry, merged the way screenbuilder and
    apply_preferences merge them: common_options, the entry's own, then its
    ``preferences:`` gauge block and every style that block can pull in."""
    options = dict(common or {}) | dict(entry.get("options") or {})
    ref = entry.get("preferences")
    if ref is not None:
        styles = (prefs.get("styles") or {}).get(re.sub("[^A-Za-z]", "", ref))
        for style in (styles or {}).values():
            options |= style or {}
        gauge = (prefs.get("gauges") or {}).get(ref) or {}
        options |= gauge
        for style in (gauge.get("styles") or {}).values():
            options |= style or {}
    return options


def _shipped_uses():
    """{(type, option): {config file, ...}} over every shipped YAML file, with
    ganged instruments resolved to the type each member is built as."""
    prefs = _preferences()
    uses = {}

    def add(inst_type, options, path):
        for option in options:
            uses.setdefault((inst_type, option), set()).add(path)

    def walk(node, path):
        if isinstance(node, dict):
            t = node.get("type")
            if isinstance(t, str) and not screenbuilder_config.is_include(node):
                if "ganged" in t:
                    for group in node.get("groups") or []:
                        for entry in group.get("instruments") or []:
                            add(t.replace("ganged_", ""), _entry_options(
                                entry, group.get("common_options"), prefs),
                                path)
                else:
                    add(t, _entry_options(node, None, prefs), path)
            for v in node.values():
                walk(v, path)
        elif isinstance(node, list):
            for v in node:
                walk(v, path)

    for path in sorted(glob.glob(os.path.join(CONFIG_DIR, "**", "*.yaml"),
                                 recursive=True)):
        with open(path) as f:
            walk(yaml.safe_load(f), os.path.relpath(path, CONFIG_DIR))
    return uses


# Options shipped configs set that their type's record does not declare, as
# of AER-6586, counting every shipped style block (a pilot can turn dseg or
# ghost on). Each is applied by setattr and draws the device's "not declared"
# warning. Declaring one (or removing it from the configs) removes it from
# here; nothing may be added. INS3 covered only the four switches.
UNDECLARED_BASELINE = {
    ("arc_gauge", "font_ghost_mask"),
    ("arc_gauge", "font_mask"),
    ("arc_gauge", "name_font_ghost_mask"),
    ("arc_gauge", "name_font_mask"),
    ("arc_gauge", "styles"),
    ("arc_gauge", "units_font_ghost_mask"),
    ("arc_gauge", "units_font_mask"),
    ("button", "condition_keys"),
    ("button", "conditions"),
    ("button", "font_mask"),
    ("data_annunciation", "target_screen"),
    ("data_status", "continue_screen"),
    ("data_status", "update_command"),
    ("horizontal_bar_gauge", "bar_divisor"),
    ("horizontal_bar_gauge", "bar_width_percent"),
    ("horizontal_bar_gauge", "font_ghost_mask"),
    ("horizontal_bar_gauge", "font_mask"),
    ("horizontal_bar_gauge", "line_width_percent"),
    ("horizontal_bar_gauge", "name_font_ghost_mask"),
    ("horizontal_bar_gauge", "name_font_mask"),
    ("horizontal_bar_gauge", "show_value"),
    ("horizontal_bar_gauge", "small_font_percent"),
    ("horizontal_bar_gauge", "styles"),
    ("horizontal_bar_gauge", "units_font_ghost_mask"),
    ("horizontal_bar_gauge", "units_font_mask"),
    ("moving_map", "terrain_key"),
    ("numeric_display", "clipping"),
    ("numeric_display", "font_ghost_mask"),
    ("numeric_display", "name_font_mask"),
    ("numeric_display", "styles"),
    ("numeric_display", "units_font_mask"),
    ("static_text", "font_ghost_mask"),
    ("static_text", "name_font_mask"),
    ("static_text", "styles"),
    ("value_text", "font_ghost_mask"),
    ("value_text", "name_font_mask"),
    ("value_text", "styles"),
    ("vertical_bar_gauge", "bar_width_percent"),
    ("vertical_bar_gauge", "big_font_percent"),
    ("vertical_bar_gauge", "decPlaces"),
    ("vertical_bar_gauge", "disabled"),
    ("vertical_bar_gauge", "font_ghost_mask"),
    ("vertical_bar_gauge", "font_mask"),
    ("vertical_bar_gauge", "highlight_key"),
    ("vertical_bar_gauge", "line_width_percent"),
    ("vertical_bar_gauge", "name_font_ghost_mask"),
    ("vertical_bar_gauge", "name_font_mask"),
    ("vertical_bar_gauge", "normalize_range"),
    ("vertical_bar_gauge", "show_value"),
    ("vertical_bar_gauge", "small_font_percent"),
    ("vertical_bar_gauge", "styles"),
    ("vertical_bar_gauge", "text_gap"),
    ("vertical_bar_gauge", "units_font_ghost_mask"),
    ("vertical_bar_gauge", "units_font_mask"),
    ("virtual_vfr", "svs"),
}

# Common options apply_preferences consumes for every instrument.
_COMMON = {"font_family", "font_percent"}


def _undeclared(uses):
    return {(t, o) for (t, o) in uses
            if o not in _COMMON and factory.REGISTRY[t].prop(o) is None}


def test_every_shipped_type_is_registered():
    unknown = {t for (t, _) in _shipped_uses() if t not in factory.REGISTRY}
    assert not unknown


def test_every_shipped_switch_is_declared_by_its_type():
    uses = _shipped_uses()
    shipped = {(t, o) for (t, o) in uses if o in SWITCHES}
    # The shipped screens do use them: temperature on all four gauge kinds,
    # altitude on the PFD tape and its numeric readout, the EGT bars.
    assert {o for (_, o) in shipped} >= {
        "temperature", "altitude", "egt_mode_switching"}
    missing = {(t, o): sorted(uses[(t, o)])
               for (t, o) in shipped if factory.REGISTRY[t].prop(o) is None}
    assert not missing


def test_shipped_configs_use_only_the_exact_switch_names():
    """The substring dispatch would have switched any name containing one of
    the words; no shipped config relies on that."""
    loose = {(t, o) for (t, o) in _shipped_uses()
             if _old_dispatch(o, t) is not None and o not in SWITCHES}
    assert not loose


def test_every_other_shipped_option_is_declared_or_baselined():
    undeclared = _undeclared(_shipped_uses())
    new = undeclared - UNDECLARED_BASELINE
    assert not new, f"shipped options not declared by their type: {sorted(new)}"
    assert not {o for (_, o) in UNDECLARED_BASELINE} & set(SWITCHES)


def test_undeclared_baseline_has_no_stale_entries():
    """A baseline entry that is now declared, or no longer shipped, comes out
    of the baseline in the same change."""
    stale = UNDECLARED_BASELINE - _undeclared(_shipped_uses())
    assert not stale, f"remove from UNDECLARED_BASELINE: {sorted(stale)}"


# --- Schema ------------------------------------------------------------------

def test_schema_offers_the_switches_on_the_types_that_honour_them():
    instruments = eschema.build_schema()["instruments"]
    for option in SWITCHES:
        for t in factory.REGISTRY:
            field = instruments[t]["options"].get(option)
            if _old_dispatch(option, t) is None:
                assert field is None, (t, option)
            else:
                assert field is not None, (t, option)
                assert field["type"] == "boolean" and field["default"] is False
                assert field["label"], (t, option)
