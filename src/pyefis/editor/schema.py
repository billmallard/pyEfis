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
)

SCHEMA_VERSION = 1

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
    "atitude_indicator": "attitude",
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
    "atitude_indicator": "Attitude Indicator",
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
    "atitude_indicator",
    "virtual_vfr",
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
_COMMON_OPTIONS = {
    "font_family": {"type": "string", "default": "DejaVu Sans Condensed"},
    "font_percent": {"type": "number", "default": None},
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


def build_schema():
    """Return the full instrument schema as a JSON-serialisable dict.

    The type list is exactly the keys of ``INSTRUMENT_FACTORIES`` so the schema
    always matches what the screen builder can create.
    """
    instruments = {}
    for instrument_type in sorted(INSTRUMENT_FACTORIES):
        instruments[instrument_type] = {
            "label": _LABELS.get(instrument_type, _prettify(instrument_type)),
            "category": _CATEGORIES.get(instrument_type, "other"),
            "dbkeys": list(INSTRUMENT_DEFAULTS.get(instrument_type, []) or []),
            "default_options": _default_options(instrument_type),
            "required_options": list(_REQUIRED_OPTIONS.get(instrument_type, [])),
            "offscreen_renderable":
                instrument_type not in _NOT_OFFSCREEN_RENDERABLE,
            "svs_capable": instrument_type in _SVS_CAPABLE,
        }

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
        "categories": sorted(set(_CATEGORIES.values())),
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
