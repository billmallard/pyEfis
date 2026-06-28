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

"""Instrument schema exporter for the End-User Configuration Manager.

The visual editor needs a machine-readable description of every instrument it
can place: the palette of types, each type's default FIX dbkeys and options,
which options are required, and whether the type can be previewed offscreen
(GL/SVS widgets cannot -- they get a placeholder thumbnail instead).

The authoritative source for the *type list, default dbkeys, and default
options* is the screen-builder factory registry
(:mod:`pyefis.screens.screenbuilder_factory`) -- this module reads those
registries directly so the schema can never drift from what the screen builder
will actually instantiate. The editor-affordance metadata (human label, palette
category, required-options, offscreen-renderable / SVS-capable flags) is curated
here because the registries don't carry it; the test suite asserts every curated
key maps to a real registry type, so curation can't drift either.

CLI::

    python -m pyefis.editor.schema            # write JSON to stdout
    python -m pyefis.editor.schema -o out.json
"""

import argparse
import json

from pyefis.screens.screenbuilder_factory import (
    INSTRUMENT_DEFAULT_OPTIONS,
    INSTRUMENT_DEFAULTS,
    INSTRUMENT_FACTORIES,
    REGISTRY,
)

# v3: instruments migrated to screenbuilder_factory.REGISTRY are sourced from
# their InstrumentSpec record; every instrument entry now also carries a
# `preview` block (category 3) and a `fix_values` list (category 2). Types not
# yet migrated still come from the curated metadata in this module.
SCHEMA_VERSION = 3

# ---------------------------------------------------------------------------
# Curated editor-affordance metadata. Keys MUST be real INSTRUMENT_FACTORIES
# types (enforced by tests/editor/test_schema.py). Anything not listed falls
# back to sensible defaults in build_schema().
# ---------------------------------------------------------------------------

# Palette grouping for the editor's instrument picker.
_CATEGORIES = {
    "airspeed_dial": "airspeed",
    "airspeed_box": "airspeed",
    "airspeed_tape": "airspeed",
    "airspeed_trend_tape": "airspeed",
    "altimeter_dial": "altitude",
    "altimeter_tape": "altitude",
    "altimeter_trend_tape": "altitude",
    # "atitude_indicator" is migrated -- category from its registry record.
    "virtual_vfr": "attitude",
    "turn_coordinator": "attitude",
    "horizontal_situation_indicator": "navigation",
    "heading_display": "navigation",
    "heading_tape": "navigation",
    "vsi_dial": "vertical_speed",
    "vsi_pfd": "vertical_speed",
    "arc_gauge": "gauge",
    "horizontal_bar_gauge": "gauge",
    "vertical_bar_gauge": "gauge",
    "numeric_display": "text",
    "value_text": "text",
    "static_text": "text",
    "listbox": "list",
    "wind_display": "wind",
    "data_status": "system",
    "data_annunciation": "system",
    "button": "control",
    "weston": "system",
}

# Human-friendly labels where the prettified type name isn't good enough.
_LABELS = {
    # "atitude_indicator" is migrated -- label from its registry record.
    "horizontal_situation_indicator": "Horizontal Situation Indicator (HSI)",
    "virtual_vfr": "Virtual VFR / Synthetic Vision",
    "vsi_pfd": "VSI (PFD)",
    "vsi_dial": "VSI Dial",
    "data_status": "Data Status",
    "data_annunciation": "Data Annunciation",
}

# Options the factory *requires* -- the screen builder raises (or the widget is
# meaningless) without them. Derived by reading the build_* factories.
_REQUIRED_OPTIONS = {
    "button": ["config"],
    "static_text": ["text"],
    "listbox": ["lists"],
    "weston": ["socket", "ini", "command", "args"],
}

# Types whose GL surface (or external compositor) does NOT initialise under the
# offscreen Qt platform, so they can't produce a server-side thumbnail. The
# render service returns a placeholder image for these.
_NOT_OFFSCREEN_RENDERABLE = {
    "virtual_vfr",  # QOpenGLWidget SVS terrain; hangs offscreen
    "weston",       # launches the weston compositor / waydroid
}

# Types that can host the GL Synthetic Vision overlay via an `svs:` option.
# (The attitude indicator renders fine offscreen *without* svs; with svs its GL
# layer won't, so the render service placeholders when `svs` is present.)
_SVS_CAPABLE = {
    # "atitude_indicator" is migrated -- svs_capable from its registry record.
    "virtual_vfr",
}

# Fixed-aspect (round / square) instruments: the editor letterboxes these
# (object-fit: contain) instead of stretching, so a dial stays round. Tapes,
# bars and text stretch to their box.
_KEEP_ASPECT = {
    "airspeed_dial",
    "altimeter_dial",
    "vsi_dial",
    "turn_coordinator",
    # "atitude_indicator" is migrated -- keep_aspect from its registry record.
    "horizontal_situation_indicator",
    "arc_gauge",
}

# Layout fields every instrument accepts at the screen-builder level (not
# instrument options). Informational, for the editor's inspector.
_LAYOUT_FIELDS = {
    "row": "Grid row of the top-left corner (0-based).",
    "column": "Grid column of the top-left corner (0-based).",
    "span": "{rows, columns}: how many grid cells the instrument occupies.",
    "move": "{shrink: percent, justify: [top|bottom|left|right]} fine placement.",
    "disabled": "Feature-flag name resolved via the preferences `enabled:` "
                "section (string), or a literal bool to hide the instrument.",
}

# Options accepted by (almost) every instrument, forwarded by the factory.
# font_family is an enum of fonts reliably present on a stock Raspberry Pi OS
# (the DejaVu family -- pyEfis bundles no fonts of its own). Instrument-style
# segmented fonts (DSEG7/DSEG14) would need a delivered font pack first.
_COMMON_OPTIONS = {
    "font_family": {
        "type": "enum", "default": "DejaVu Sans Condensed", "label": "Font family",
        # DejaVu ships on every Pi. The clean sans-serifs (B612 = the Airbus
        # cockpit font; Inter/Roboto/Open Sans/Noto) are delivered by the font
        # pack and loaded as web fonts in the editor for live preview.
        "enum": ["DejaVu Sans Condensed", "DejaVu Sans", "DejaVu Sans Mono",
                 "B612", "Inter", "Roboto", "Open Sans"],
    },
    "font_percent": {"type": "number", "default": None, "min": 0, "max": 1,
                     "step": 0.01, "label": "Font size (fraction of height)"},
}


def _gauge_options():
    """Shared option set for the arc / bar gauge family."""
    return {
        "dbkey": {"type": "string", "default": "", "label": "FIX key"},
        "name": {"type": "string", "default": "", "label": "Name"},
        "decimal_places": {"type": "number", "default": 0, "label": "Decimal places"},
        "show_units": {"type": "boolean", "default": False, "label": "Show units"},
        "segments": {"type": "number", "default": 0, "label": "Segments"},
    }


# Curated, editor-facing editable options per type (beyond the common font
# options above). Drives the properties panel. Field metadata:
#   type: number|string|boolean|color|enum   default:   label:   [enum/min/max]
# A practical subset of what each widget accepts, kept in sync with the build_*
# factories + docs/screenbuilder.md. NOTE: V-speeds / gauge warn-alarm bands are
# NOT here -- those are FIX-database (fix-gateway) values, not layout (see #64).
_OPTIONS = {
    "airspeed_tape": {
        "dbkey": {"type": "string", "default": "IAS", "label": "FIX key"},
        "show_tas": {"type": "boolean", "default": True, "label": "Show TAS box"},
        "show_trend": {"type": "boolean", "default": True, "label": "Show trend arrow"},
        "trend_lookahead": {"type": "number", "default": 6.0, "label": "Trend look-ahead (s)"},
    },
    "altimeter_tape": {
        "dbkey": {"type": "string", "default": "ALT", "label": "FIX key"},
        "majorDiv": {"type": "number", "default": 100, "label": "Major division"},
        "minorDiv": {"type": "number", "default": None, "label": "Minor division"},
        "maxalt": {"type": "number", "default": 50000, "label": "Max altitude"},
        "font_scale": {"type": "number", "default": 1.0, "label": "Scale-number font scale"},
        "numeric_box": {"type": "boolean", "default": True, "label": "Show numeric box"},
        "font_mask": {"type": "string", "default": "00000", "label": "Font mask"},
    },
    "numeric_display": {
        "dbkey": {"type": "string", "default": "", "label": "FIX key"},
        "decimal_places": {"type": "number", "default": 0, "label": "Decimal places"},
        "font_mask": {"type": "string", "default": "000", "label": "Font mask"},
        "show_units": {"type": "boolean", "default": False, "label": "Show units"},
    },
    "value_text": {
        "dbkey": {"type": "string", "default": "", "label": "FIX key"},
        "font_mask": {"type": "string", "default": "", "label": "Font mask"},
    },
    "static_text": {
        "text": {"type": "string", "default": "Text", "label": "Text"},
        "alignment": {"type": "enum", "default": "AlignLeft",
                      "enum": ["AlignLeft", "AlignCenter", "AlignRight"],
                      "label": "Alignment"},
        "font_mask": {"type": "string", "default": "", "label": "Font mask"},
    },
    "heading_display": {
        "fg_color": {"type": "color", "default": "#aaaaaa", "label": "Foreground"},
        "bg_color": {"type": "color", "default": "#000000", "label": "Background"},
        "font_size": {"type": "number", "default": 17, "label": "Font size (px)"},
    },
    "heading_tape": {
        "dbkey": {"type": "string", "default": "HEAD", "label": "FIX key"},
    },
    "horizontal_situation_indicator": {
        "cdi_enabled": {"type": "boolean", "default": True, "label": "CDI"},
        "gsi_enabled": {"type": "boolean", "default": True, "label": "Glideslope"},
        "fg_color": {"type": "color", "default": "#ffffff", "label": "Foreground"},
        "bg_color": {"type": "color", "default": "#000000", "label": "Background"},
    },
    # "atitude_indicator" is migrated -- its options come from the registry
    # record (with the corrected aircraft_symbol enum: classic/garmin).
    "virtual_vfr": {
        "aircraft_symbol": {"type": "enum", "default": "classic",
                            "enum": ["classic", "delta"], "label": "Aircraft symbol"},
        "symbol_color": {"type": "color", "default": "#ffff00", "label": "Symbol colour"},
        # Editor preview only: the device renders real SVS terrain; this picks
        # which stylised backdrop the configurator shows for layout.
        "preview_scene": {"type": "enum", "default": "mountains",
                          "enum": ["mountains", "approach", "coastal"],
                          "label": "Preview scene (editor)"},
    },
    "arc_gauge": _gauge_options(),
    "horizontal_bar_gauge": _gauge_options(),
    "vertical_bar_gauge": _gauge_options(),
}


def _prettify(instrument_type):
    """Title-case a snake_case type name for display."""
    return instrument_type.replace("_", " ").title()


def _infer_type(value):
    """Best-effort JSON-schema-ish type name for a default option value."""
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, (list, tuple)):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "string"


def _default_options(instrument_type):
    """Typed default-option metadata from INSTRUMENT_DEFAULT_OPTIONS."""
    raw = INSTRUMENT_DEFAULT_OPTIONS.get(instrument_type)
    if not raw:
        return {}
    return {
        name: {"type": _infer_type(value), "default": value}
        for name, value in raw.items()
    }


# Map an instrument_spec.Prop.kind to the editor's option-field "type". The
# editor renders one input per field type; "fixkey" is a FIX-database key,
# shown as a text input today (a key-picker once the FIX editor lands).
_KIND_TO_FIELD_TYPE = {
    "string": "string", "number": "number", "integer": "integer",
    "boolean": "boolean", "enum": "enum", "color": "color",
    "fixkey": "string",
}


def _prop_to_field(p):
    """Render an ``instrument_spec.Prop`` as editor option-field metadata."""
    field = {"type": _KIND_TO_FIELD_TYPE[p.kind], "default": p.default,
             "label": p.label}
    if p.enum is not None:
        field["enum"] = list(p.enum)
    if p.minimum is not None:
        field["min"] = p.minimum
    if p.maximum is not None:
        field["max"] = p.maximum
    if p.step is not None:
        field["step"] = p.step
    if p.help:
        field["help"] = p.help
    return field


def _entry_from_spec(spec):
    """Schema entry for a migrated instrument, sourced entirely from its
    registry record (category 1 properties + category 2 fix_values +
    category 3 preview). This is the single source of truth."""
    return {
        "label": spec.label,
        "category": spec.category,
        "dbkeys": list(spec.dbkeys),
        "default_options": {
            p.name: {"type": _KIND_TO_FIELD_TYPE[p.kind], "default": p.default}
            for p in spec.properties if p.default is not None},
        "required_options": [p.name for p in spec.properties if p.required],
        "options": {p.name: _prop_to_field(p) for p in spec.properties},
        "offscreen_renderable": spec.offscreen_renderable,
        "svs_capable": spec.svs_capable,
        "keep_aspect": spec.keep_aspect,
        "preview": dict(spec.preview),
        "fix_values": [
            {"name": fv.name, "source": fv.source, "label": fv.label,
             "dbkey": fv.dbkey, "units": fv.units, "help": fv.help}
            for fv in spec.fix_values],
    }


def _entry_from_curation(instrument_type):
    """Schema entry for a not-yet-migrated instrument, from the curated
    metadata in this module. Transitional: shrinks as instruments migrate to
    ``screenbuilder_factory.REGISTRY``. ``preview``/``fix_values`` are empty
    here so every entry has a uniform shape for the editor."""
    return {
        "label": _LABELS.get(instrument_type, _prettify(instrument_type)),
        "category": _CATEGORIES.get(instrument_type, "other"),
        "dbkeys": list(INSTRUMENT_DEFAULTS.get(instrument_type, []) or []),
        "default_options": _default_options(instrument_type),
        "required_options": list(_REQUIRED_OPTIONS.get(instrument_type, [])),
        "options": _OPTIONS.get(instrument_type, {}),
        "offscreen_renderable":
            instrument_type not in _NOT_OFFSCREEN_RENDERABLE,
        "svs_capable": instrument_type in _SVS_CAPABLE,
        "keep_aspect": instrument_type in _KEEP_ASPECT,
        "preview": {},
        "fix_values": [],
    }


def build_schema():
    """Return the full instrument schema as a JSON-serialisable dict.

    The type list is exactly the keys of ``INSTRUMENT_FACTORIES`` so the schema
    always matches what the screen builder can create. Migrated instruments are
    sourced from ``screenbuilder_factory.REGISTRY`` (the single source of
    truth); the rest fall back to the curated metadata in this module.
    """
    instruments = {}
    for instrument_type in sorted(INSTRUMENT_FACTORIES):
        spec = REGISTRY.get(instrument_type)
        instruments[instrument_type] = (
            _entry_from_spec(spec) if spec is not None
            else _entry_from_curation(instrument_type))

    categories = set(_CATEGORIES.values()) | {
        spec.category for spec in REGISTRY.values()}
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_from": "pyefis.screens.screenbuilder_factory",
        "grid": {
            "note": "Coordinates are on the screen's normalised grid; each "
                    "screen defines its own rows/columns (the shipped screens "
                    "use 110 rows x 200 columns, ~16:9). z-order is the "
                    "instrument list order: later entries paint on top.",
        },
        "layout_fields": _LAYOUT_FIELDS,
        "common_options": _COMMON_OPTIONS,
        "categories": sorted(categories),
        "instruments": instruments,
    }


def to_json(indent=2):
    """Render the schema to a JSON string."""
    return json.dumps(build_schema(), indent=indent)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Export the pyEfis instrument schema for the config editor."
    )
    parser.add_argument(
        "-o", "--output", help="write JSON here (default: stdout)")
    parser.add_argument(
        "--indent", type=int, default=2, help="JSON indent (default 2)")
    args = parser.parse_args(argv)

    text = to_json(indent=args.indent)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        print(f"wrote {args.output} ({len(build_schema()['instruments'])} "
              f"instrument types)")
    else:
        print(text)


if __name__ == "__main__":
    main()
