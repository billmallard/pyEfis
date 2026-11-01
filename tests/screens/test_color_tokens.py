"""Colour tokens in the theme cascade (style contract sections 5-7, S1).

A colour option accepts a token name or a literal; the token resolves LAST, on
whatever value the preferences cascade picked; and introducing the tokens moves
nothing, because each token's built-in value is the current default of every
prop that reads it.
"""

import logging

import pytest

from pyefis.screens import color_tokens as ct
from pyefis.screens import screenbuilder_factory as factory
from pyefis.screens.instrument_spec import Prop
from pyefis.screens.screenbuilder_preferences import apply_preferences


# The contract's section 5 tier table, as (type, prop) -> token. The AI-family
# horizon_heading_color row covers both AI types.
CONTRACT_MAP = {
    ("horizontal_situation_indicator", "course_color"): "nav.course",
    ("horizontal_situation_indicator", "track_color"): "nav.course",
    ("horizontal_situation_indicator", "heading_bug_color"): "nav.reference",
    ("horizontal_situation_indicator", "bearing_color"): "nav.reference",
    ("horizontal_situation_indicator", "vloc_color"): "state.valid",
    ("checklist", "done_color"): "state.valid",
    ("checklist", "current_color"): "state.caution",
    ("horizontal_situation_indicator", "fg_color"): "ink.primary",
    ("horizontal_situation_indicator", "bg_color"): "surface.base",
    ("horizontal_situation_indicator", "needle_color"): "nav.ownship",
    ("atitude_indicator", "symbol_color"): "nav.ownship",
    ("virtual_vfr", "symbol_color"): "nav.ownship",
    ("moving_map", "symbol_color"): "nav.ownship",
    ("atitude_indicator", "horizon_heading_color"): "ink.primary",
    ("virtual_vfr", "horizon_heading_color"): "ink.primary",
    ("value_text", "value_color"): "ink.primary",
    ("value_text", "prefix_color"): "ink.secondary",
    ("value_text", "border_color"): "line.border",
    ("value_text", "bg_color"): "surface.base",
    ("altimeter_trend_tape", "bg_color"): "surface.base",
    ("heading_display", "fg_color"): "ink.muted",
    ("heading_display", "bg_color"): "surface.base",
    ("button", "fg_color"): "accent",
    ("button", "bg_color"): "surface.raised",
    ("checklist", "text_color"): "ink.primary",
    ("checklist", "section_color"): "ink.muted",
    ("checklist", "response_color"): "accent",
    ("moving_map", "road_color"): "map.road",
    ("moving_map", "river_color"): "map.water",
}


def _registry_map():
    return {(t, p.name): p.token
            for t, spec in factory.REGISTRY.items()
            for p in spec.properties if p.kind == "color" and p.token}


def _prefs(colors=None, style=None, styles=None, gauges=None):
    prefs = {"style": style or {"basic": True}, "styles": dict(styles or {}),
             "gauges": dict(gauges or {})}
    if colors is not None:
        prefs["styles"]["colors"] = colors
    return prefs


# -- the vocabulary ----------------------------------------------------------

def test_vocabulary_is_the_contract_section_6_set():
    assert set(ct.TOKENS) == {
        "surface.base", "surface.raised", "ink.primary", "ink.secondary",
        "ink.muted", "line.border", "line.major", "line.minor", "line.fine",
        "accent", "state.valid", "state.caution", "state.warning",
        "nav.course", "nav.reference", "nav.ownship", "map.road", "map.water",
        "map.terrain"}


def test_nav_and_state_are_theme_immutable():
    immutable = {t for t in ct.TOKENS if ct.is_immutable(t)}
    assert immutable == {t for t in ct.TOKENS
                         if t.startswith(("nav.", "state."))}


# -- the mapping (DoD d) -----------------------------------------------------

def test_registry_maps_exactly_the_contract_props():
    assert _registry_map() == CONTRACT_MAP


def test_each_token_value_is_the_default_of_every_prop_reading_it():
    """The identity half of DoD (d): resolving a mapped prop's own token gives
    back that prop's current default, for every one of them."""
    for (t, name), token in _registry_map().items():
        prop = next(p for p in factory.REGISTRY[t].properties
                    if p.name == name)
        assert ct.default_value(token) == prop.default, (t, name, token)


def test_token_only_on_colour_props():
    with pytest.raises(ValueError, match="only for kind 'color'"):
        Prop("width", "integer", default=1, token="ink.primary")


def test_unknown_token_rejected_at_registration():
    with pytest.raises(ValueError, match="unknown colour token"):
        Prop("fg_color", "color", default="#ffffff", token="ink.primry")


# -- token-or-literal (DoD a) ------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    ("ink.primary", "#ffffff"),
    ("#ffffff", "#ffffff"),
    ("#123456", "#123456"),
    ("lightgray", "lightgray"),     # Qt colour names stay literals
    ("state.caution", "#ffaa00"),
])
def test_option_accepts_token_or_literal(value, expected):
    config = {"type": "value_text", "options": {"value_color": value}}
    apply_preferences(config, _prefs())
    assert config["options"]["value_color"] == expected


def test_unmigrated_type_resolves_by_option_name():
    config = {"type": "airspeed_tape",
              "options": {"text_color": "accent", "label": "accent"}}
    apply_preferences(config, _prefs())
    assert config["options"] == {"text_color": "#00ffff", "label": "accent"}


def test_valueless_token_falls_back_to_widget_default(caplog):
    config = {"type": "value_text", "options": {"value_color": "state.warning"}}
    with caplog.at_level(logging.WARNING):
        apply_preferences(config, _prefs())
    assert "value_color" not in config["options"]
    assert "state.warning" in caplog.text


# -- resolution order (DoD b) ------------------------------------------------

def test_no_colors_block_leaves_options_untouched():
    """With no theme block the stock path changes nothing -- not even the dict."""
    options = {"value_color": "#ff0000"}
    config = {"type": "value_text", "options": options}
    apply_preferences(config, _prefs())
    assert config["options"] is options
    assert options == {"value_color": "#ff0000"}


def test_no_colors_block_does_not_fill_unset_props():
    config = {"type": "value_text", "options": {}}
    apply_preferences(config, _prefs())
    assert config["options"] == {}


def test_theme_fills_a_prop_nothing_else_set():
    config = {"type": "value_text", "options": {}}
    apply_preferences(config, _prefs(colors={"basic": {"ink.primary": "#eeeeee"}}))
    assert config["options"] == {"value_color": "#eeeeee"}


def test_instance_literal_beats_the_theme():
    config = {"type": "value_text", "options": {"value_color": "#ff0000"}}
    apply_preferences(config, _prefs(colors={"basic": {"ink.primary": "#eeeeee"}}))
    assert config["options"]["value_color"] == "#ff0000"


def test_type_style_override_can_itself_be_a_token():
    """The cascade picks the token from styles: <TYPE>, resolution runs after."""
    config = {"type": "value_text", "preferences": "VT1",
              "options": {"value_color": "#ff0000"}}
    prefs = _prefs(colors={"basic": {"ink.muted": "#777777"}},
                   styles={"VT": {"basic": {"value_color": "ink.muted"}}})
    apply_preferences(config, prefs)
    assert config["options"]["value_color"] == "#777777"


def test_gauge_override_can_itself_be_a_token():
    config = {"type": "value_text", "preferences": "VT1", "options": {}}
    prefs = _prefs(gauges={"VT1": {"border_color": "accent"}})
    apply_preferences(config, prefs)
    assert config["options"]["border_color"] == "#00ffff"


def test_later_enabled_style_wins_disabled_style_ignored():
    colors = {"basic": {"ink.primary": "#111111"},
              "dseg": {"ink.primary": "#222222"},
              "ghost": {"ink.primary": "#333333"}}
    config = {"type": "value_text", "options": {}}
    apply_preferences(config, _prefs(
        colors=colors, style={"basic": True, "dseg": True, "ghost": False}))
    assert config["options"]["value_color"] == "#222222"


# -- theme-immutable (DoD e) -------------------------------------------------

def test_theme_cannot_redefine_nav_or_state(caplog):
    colors = {"basic": {"nav.course": "#00ff00", "state.valid": "#ff0000"}}
    config = {"type": "horizontal_situation_indicator",
              "options": {"course_color": "nav.course",
                          "vloc_color": "state.valid"}}
    with caplog.at_level(logging.WARNING):
        apply_preferences(config, _prefs(colors=colors))
    assert config["options"] == {"course_color": "#ff00ff",
                                 "vloc_color": "#00ff00"}
    assert "theme-immutable" in caplog.text


def test_builder_may_still_override_a_tier1_prop_per_widget():
    config = {"type": "horizontal_situation_indicator",
              "options": {"course_color": "#00ff00"}}
    apply_preferences(config, _prefs())
    assert config["options"]["course_color"] == "#00ff00"


def test_unknown_theme_token_ignored(caplog):
    with caplog.at_level(logging.WARNING):
        colors = ct.theme_colors(_prefs(colors={"basic": {"ink.bogus": "#1"}}))
    assert colors == {}
    assert "ink.bogus" in caplog.text


@pytest.mark.parametrize("prefs", [{}, None, {"style": {"basic": True}},
                                   {"styles": {"colors": "nonsense"}}])
def test_malformed_preferences_never_raise(prefs):
    assert ct.theme_colors(prefs) == {}


# -- identity across the whole registry --------------------------------------

def test_theme_at_builtin_values_reproduces_every_default():
    """Force level 4 on every mapped prop with a theme set to the built-in
    values: every prop comes out at exactly its registry default."""
    colors = {"basic": {t: v for t, (v, _) in ct.TOKENS.items()
                        if v is not None and not ct.is_immutable(t)}}
    prefs = _prefs(colors=colors)
    for t, spec in factory.REGISTRY.items():
        mapped = {p.name: p for p in spec.properties
                  if p.kind == "color" and p.token}
        if not mapped:
            continue
        config = {"type": t, "options": {}}
        apply_preferences(config, prefs)
        for name, p in mapped.items():
            if ct.is_immutable(p.token):
                assert name not in config["options"], (t, name)
            else:
                assert config["options"][name] == p.default, (t, name)


def test_every_prop_named_by_its_token_resolves_to_its_default():
    for t, spec in factory.REGISTRY.items():
        mapped = {p.name: p for p in spec.properties
                  if p.kind == "color" and p.token}
        if not mapped:
            continue
        config = {"type": t, "options": {n: p.token for n, p in mapped.items()}}
        apply_preferences(config, _prefs())
        assert config["options"] == {n: p.default for n, p in mapped.items()}


def test_theme_filled_props_are_applied_before_instance_options():
    """value_text repaints its colours from setDbkey; a theme value applied
    after dbkey would not show until the next data-flag change."""
    config = {"type": "value_text", "options": {"dbkey": "IAS"}}
    apply_preferences(config, _prefs(colors={"basic": {"ink.primary": "#eeeeee"}}))
    assert list(config["options"]) == ["value_color", "dbkey"]
