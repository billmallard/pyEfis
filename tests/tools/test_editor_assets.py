#  Copyright (c) 2026 Bill Mallard
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.

"""The palette-thumbnail tools read the instrument records, not hand lists
(INS2): render_instrument's demo-key set and build_editor_assets' check that
every type which should render did."""

import os
import sys

_TOOLS = os.path.join(os.path.dirname(__file__), "..", "..", "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import build_editor_assets  # noqa: E402
import render_instrument  # noqa: E402

from pyefis.screens import screenbuilder_factory as factory  # noqa: E402
from pyefis.screens.instrument_spec import InstrumentSpec, Prop  # noqa: E402


def _spec(t, props=(), isolation=True, offscreen=True):
    return InstrumentSpec(type=t, label=t, category="other",
                          properties=list(props),
                          builds_in_isolation=isolation,
                          offscreen_renderable=offscreen)


# --- _NEEDS_DBKEY ------------------------------------------------------------

def test_needs_dbkey_rule():
    """A type gets the demo key exactly when its record has a ``dbkey``
    fixkey prop with no default."""
    registry = {s.type: s for s in (
        _spec("generic", [Prop("dbkey", "fixkey", default="")]),
        _spec("none_default", [Prop("dbkey", "fixkey")]),
        _spec("defaulted", [Prop("dbkey", "fixkey", default="ALT")]),
        _spec("not_fixkey", [Prop("dbkey", "string", default="")]),
        _spec("other_key", [Prop("slot_key", "fixkey", default="")]),
        _spec("no_props"),
    )}
    assert render_instrument._needs_dbkey_types(registry) == {
        "generic", "none_default"}


def test_needs_dbkey_is_read_from_the_registry():
    """The module set is the rule applied to the real REGISTRY. It still
    covers the four gauges the old hand list named, and picks up value_text,
    which that list had missed."""
    assert render_instrument._NEEDS_DBKEY == \
        render_instrument._needs_dbkey_types(factory.REGISTRY)
    assert {"arc_gauge", "horizontal_bar_gauge", "vertical_bar_gauge",
            "numeric_display", "value_text"} <= render_instrument._NEEDS_DBKEY
    assert "altimeter_tape" not in render_instrument._NEEDS_DBKEY


def test_demo_dbkey_sets_a_name_only_where_the_type_takes_one():
    gauge, text, given = {}, {}, {"dbkey": "OILP1"}
    render_instrument._demo_dbkey("arc_gauge", gauge)
    render_instrument._demo_dbkey("value_text", text)
    render_instrument._demo_dbkey("arc_gauge", given)
    assert gauge == {"dbkey": "DEMOGAUGE", "name": "DEMO"}
    assert text == {"dbkey": "DEMOGAUGE"}
    assert given == {"dbkey": "OILP1"}


# --- unexpected placeholders ---------------------------------------------------

def test_unexpected_placeholder_rule():
    """Only a type that builds standalone, renders offscreen and is not on
    the placeholder list counts as a broken render."""
    registry = {s.type: s for s in (
        _spec("gauge"),
        _spec("config_driven"),
        _spec("needs_screen", isolation=False),
        _spec("gl", offscreen=False),
    )}
    placeholders = ["gl", "needs_screen", "config_driven", "gauge", "unknown"]
    assert build_editor_assets.unexpected_placeholders(
        placeholders, registry, expected={"config_driven"}) == ["gauge"]


def test_todays_placeholders_are_all_expected():
    """The four types CI placeholders on dev today pass; a gauge does not.
    The default placeholder list is render_instrument's _CONFIG_DRIVEN."""
    today = ["button", "listbox", "virtual_vfr", "weston"]
    assert build_editor_assets.unexpected_placeholders(today) == []
    assert build_editor_assets.unexpected_placeholders(
        today + ["arc_gauge"]) == ["arc_gauge"]


def test_main_exits_1_on_an_unexpected_placeholder(monkeypatch, tmp_path,
                                                   capsys):
    out = str(tmp_path)
    monkeypatch.setattr(build_editor_assets, "build",
                        lambda *a: (3, ["weston", "value_text"]))
    assert build_editor_assets.main(["--out", out]) == 1
    assert "value_text" in capsys.readouterr().err
    monkeypatch.setattr(build_editor_assets, "build",
                        lambda *a: (3, ["weston"]))
    assert build_editor_assets.main(["--out", out]) == 0
