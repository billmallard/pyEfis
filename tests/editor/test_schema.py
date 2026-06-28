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

"""Tests for the config-editor instrument schema exporter."""

import json

from pyefis.editor import schema as eschema
from pyefis.screens import screenbuilder_factory as factory


def test_every_factory_type_is_in_schema():
    """The schema must describe exactly the instrument types the screen
    builder can create -- no missing types, no invented ones."""
    s = eschema.build_schema()
    assert set(s["instruments"]) == set(factory.INSTRUMENT_FACTORIES)


def test_curated_metadata_keys_are_real_types():
    """Curated metadata can only reference real instrument types, so the
    curation can't drift away from the registry."""
    real = set(factory.INSTRUMENT_FACTORIES)
    for name, mapping in (
        ("_CATEGORIES", eschema._CATEGORIES),
        ("_LABELS", eschema._LABELS),
        ("_REQUIRED_OPTIONS", eschema._REQUIRED_OPTIONS),
        ("_OPTIONS", eschema._OPTIONS),
    ):
        unknown = set(mapping) - real
        assert not unknown, f"{name} references unknown types: {unknown}"
    for name, members in (
        ("_NOT_OFFSCREEN_RENDERABLE", eschema._NOT_OFFSCREEN_RENDERABLE),
        ("_SVS_CAPABLE", eschema._SVS_CAPABLE),
        ("_KEEP_ASPECT", eschema._KEEP_ASPECT),
    ):
        unknown = members - real
        assert not unknown, f"{name} references unknown types: {unknown}"


def test_dbkeys_come_from_registry():
    """Default FIX dbkeys mirror INSTRUMENT_DEFAULTS."""
    s = eschema.build_schema()
    assert s["instruments"]["airspeed_tape"]["dbkeys"] == ["IAS"]
    assert s["instruments"]["horizontal_situation_indicator"]["dbkeys"] == [
        "COURSE", "CDI", "GSI", "HEAD"]
    # A type with no declared defaults gets an empty list, never missing.
    assert s["instruments"]["static_text"]["dbkeys"] == []


def test_default_options_are_typed():
    """INSTRUMENT_DEFAULT_OPTIONS values are exposed with an inferred type."""
    s = eschema.build_schema()
    opt = s["instruments"]["heading_display"]["default_options"]
    assert opt == {"font_size": {"type": "integer", "default": 17}}


def test_gl_types_flagged_not_offscreen_renderable():
    """SVS/compositor widgets are flagged so the render service placeholders
    them instead of hanging the offscreen platform."""
    s = eschema.build_schema()
    assert s["instruments"]["virtual_vfr"]["offscreen_renderable"] is False
    assert s["instruments"]["weston"]["offscreen_renderable"] is False
    # A plain QPainter widget renders offscreen fine.
    assert s["instruments"]["airspeed_tape"]["offscreen_renderable"] is True


def test_required_options_present():
    s = eschema.build_schema()
    assert s["instruments"]["button"]["required_options"] == ["config"]
    assert s["instruments"]["static_text"]["required_options"] == ["text"]


def test_options_are_well_formed():
    """The curated per-type options drive the editor properties panel."""
    s = eschema.build_schema()
    # numeric_display keeps an editable dbkey (curated); airspeed_tape no longer
    # exposes one (it is hard-wired to IAS), so assert dbkey typing here.
    asi = s["instruments"]["numeric_display"]["options"]
    assert asi["dbkey"]["type"] == "string"
    align = s["instruments"]["static_text"]["options"]["alignment"]
    assert align["type"] == "enum" and "AlignLeft" in align["enum"]
    color = s["instruments"]["heading_display"]["options"]["fg_color"]
    assert color["type"] == "color"
    # every option carries a type
    for inst in s["instruments"].values():
        for spec in inst["options"].values():
            assert "type" in spec


def test_schema_is_json_serialisable():
    text = eschema.to_json()
    reparsed = json.loads(text)
    assert reparsed["schema_version"] == eschema.SCHEMA_VERSION
    assert "instruments" in reparsed
    assert reparsed["instruments"]  # non-empty
