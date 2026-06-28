#  Copyright (c) 2026 Eric Blevins
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

import os

from PyQt6.QtCore import qRound

from pyefis.instruments import ai
from pyefis.instruments import airspeed
from pyefis.instruments import altimeter
from pyefis.instruments import button
from pyefis.instruments import data_status
from pyefis.instruments import gauges
from pyefis.instruments import hsi
from pyefis.instruments import listbox
from pyefis.instruments import misc
from pyefis.instruments import tc
from pyefis.instruments import vsi
from pyefis.instruments import weston
from pyefis.instruments import wind
from pyefis.instruments.ai.VirtualVfr import VirtualVfr
from pyefis.screens.instrument_spec import InstrumentSpec, Prop, FixValue


def build_weston(screen, config, font_percent=None, font_family=None, replace=None):
    options = config["options"]
    kwargs = {
        "socket": options["socket"],
        "ini": os.path.join(screen.parent.config_path, options["ini"]),
        "command": options["command"],
        "args": options["args"],
    }

    if (
        "span" in config
        and {"rows", "columns"} <= set(config["span"])
        and "row" in config
        and "column" in config
    ):
        _grid_x, _grid_y, grid_width, grid_height = screen.get_grid_coordinates(
            config["column"],
            config["row"],
        )
        kwargs["wide"] = qRound(grid_width * config["span"]["columns"])
        kwargs["high"] = qRound(grid_height * config["span"]["rows"])

    return weston.Weston(screen, **kwargs)


def build_altimeter_tape(
    screen, config, font_percent=None, font_family=None, replace=None
):
    # Forward the supported tape options from the screen config. Previously
    # only dbkey was passed, so minorDiv/majorDiv/maxalt/total_decimals/
    # font_mask in the YAML were silently ignored and the tape always used
    # its hardcoded defaults (e.g. a VS tape kept minorDiv=100 no matter what
    # the config said). Only keys present in the config are forwarded, so the
    # constructor defaults still apply to anything unset.
    opts = config.get("options") or {}
    kwargs = {}
    for k in ("dbkey", "maxalt", "majorDiv", "minorDiv", "total_decimals",
              "font_mask", "round_to", "numeric_box", "font_scale"):
        if k in opts:
            kwargs[k] = opts[k]
    return altimeter.Altimeter_Tape(
        screen, font_family=font_family, **kwargs)


def build_atitude_indicator(
    screen, config, font_percent=None, font_family=None, replace=None
):
    opts = config.get("options", {}) or {}
    show_fpm = opts.get("show_fpm", True)
    widget = ai.AI(
        screen, font_percent=font_percent, font_family=font_family,
        show_fpm=show_fpm,
    )
    widget.aircraft_symbol = opts.get("aircraft_symbol", "classic")
    widget.symbol_color = opts.get("symbol_color", "yellow")
    if "svs" in opts:
        widget.set_svs_config(opts["svs"])
    return widget


def build_virtual_vfr(
    screen, config, font_percent=None, font_family=None, replace=None
):
    opts = config.get("options", {}) or {}
    widget = VirtualVfr(screen, font_percent=font_percent, font_family=font_family)
    # VirtualVfr inherits set_svs_config from AI; SVS config flows through
    # the same way regardless of which widget type the screen uses.
    widget.aircraft_symbol = opts.get("aircraft_symbol", "classic")
    widget.symbol_color = opts.get("symbol_color", "yellow")
    if "svs" in opts:
        widget.set_svs_config(opts["svs"])
    return widget


def build_button(screen, config, font_percent=None, font_family=None, replace=None):
    if "options" in config and "config" in config["options"]:
        return button.Button(
            screen,
            config_file=os.path.join(
                screen.parent.config_path, config["options"]["config"]
            ),
            font_family=font_family,
        )
    raise ValueError("button must specify options: config:")


def build_static_text(
    screen, config, font_percent=None, font_family=None, replace=None
):
    return misc.StaticText(
        text=config["options"]["text"], parent=screen, font_family=font_family
    )


def build_data_status(
    screen, config, font_percent=None, font_family=None, replace=None
):
    opts = (config or {}).get("options", {}) or {}
    kwargs = {"parent": screen, "font_family": font_family}
    if "status_path" in opts:
        kwargs["status_path"] = opts["status_path"]
    if "continue_screen" in opts:
        kwargs["continue_screen"] = opts["continue_screen"]
    if "update_command" in opts:
        kwargs["update_command"] = opts["update_command"]
    return data_status.DataStatus(**kwargs)


def build_data_annunciation(
    screen, config, font_percent=None, font_family=None, replace=None
):
    opts = (config or {}).get("options", {}) or {}
    kwargs = {"parent": screen, "font_family": font_family}
    if "status_path" in opts:
        kwargs["status_path"] = opts["status_path"]
    if "target_screen" in opts:
        kwargs["target_screen"] = opts["target_screen"]
    return data_status.DataAnnunciation(**kwargs)


def build_listbox(screen, config, font_percent=None, font_family=None, replace=None):
    return listbox.ListBox(
        screen,
        lists=config["options"]["lists"],
        replace=replace,
        font_family=font_family,
    )


INSTRUMENT_FACTORIES = {
    "weston": build_weston,
    "airspeed_dial": lambda screen, config, font_percent=None, font_family=None, replace=None: airspeed.Airspeed(
        screen, font_family=font_family
    ),
    "airspeed_box": lambda screen, config, font_percent=None, font_family=None, replace=None: airspeed.Airspeed_Box(
        screen, font_family=font_family
    ),
    # "airspeed_tape" is migrated -- see REGISTRY below.
    "airspeed_trend_tape": lambda screen, config, font_percent=None, font_family=None, replace=None: vsi.AS_Trend_Tape(
        screen, font_family=font_family
    ),
    "altimeter_dial": lambda screen, config, font_percent=None, font_family=None, replace=None: altimeter.Altimeter(
        screen, font_family=font_family
    ),
    # "atitude_indicator" is migrated -- see REGISTRY below.
    "altimeter_tape": build_altimeter_tape,
    "altimeter_trend_tape": lambda screen, config, font_percent=None, font_family=None, replace=None: vsi.Alt_Trend_Tape(
        screen, font_family=font_family
    ),
    "button": build_button,
    "data_status": build_data_status,
    "data_annunciation": build_data_annunciation,
    "heading_display": lambda screen, config, font_percent=None, font_family=None, replace=None: hsi.HeadingDisplay(
        screen, font_family=font_family
    ),
    "heading_tape": lambda screen, config, font_percent=None, font_family=None, replace=None: hsi.DG_Tape(
        screen, font_family=font_family
    ),
    "horizontal_situation_indicator": lambda screen, config, font_percent=None, font_family=None, replace=None: hsi.HSI(
        screen,
        font_percent=font_percent,
        cdi_enabled=True,
        gsi_enabled=True,
        font_family=font_family,
    ),
    "numeric_display": lambda screen, config, font_percent=None, font_family=None, replace=None: gauges.NumericDisplay(
        screen, font_family=font_family
    ),
    "value_text": lambda screen, config, font_percent=None, font_family=None, replace=None: misc.ValueDisplay(
        screen, font_family=font_family
    ),
    "static_text": build_static_text,
    "turn_coordinator": lambda screen, config, font_percent=None, font_family=None, replace=None: tc.TurnCoordinator(
        screen, font_family=font_family
    ),
    # "vsi_dial" is migrated -- see REGISTRY below.
    "vsi_pfd": lambda screen, config, font_percent=None, font_family=None, replace=None: vsi.VSI_PFD(
        screen, font_family=font_family
    ),
    # "arc_gauge" is migrated -- see REGISTRY below.
    "horizontal_bar_gauge": lambda screen, config, font_percent=None, font_family=None, replace=None: gauges.HorizontalBar(
        screen, min_size=False, font_family=font_family
    ),
    "vertical_bar_gauge": lambda screen, config, font_percent=None, font_family=None, replace=None: gauges.VerticalBar(
        screen, min_size=False, font_family=font_family
    ),
    "virtual_vfr": build_virtual_vfr,
    "listbox": build_listbox,
    "wind_display": lambda screen, config, font_percent=None, font_family=None, replace=None: wind.WindDisplay(
        screen, font_family=font_family
    ),
}


INSTRUMENT_DEFAULTS = {
    "airspeed_dial": ["IAS"],
    # "airspeed_tape" dbkeys are declared in REGISTRY below.
    "airspeed_trend_tape": ["IAS"],
    "airspeed_box": ["IAS", "GS", "TAS"],
    "altimeter_dial": ["ALT"],
    "altimeter_tape": ["ALT"],
    "altimeter_trend_tape": ["ALT"],
    # "atitude_indicator" dbkeys are declared in REGISTRY below.
    "heading_display": ["HEAD"],
    "heading_tape": ["HEAD"],
    "horizontal_situation_indicator": ["COURSE", "CDI", "GSI", "HEAD"],
    "turn_coordinator": ["ROT", "ALAT"],
    # "vsi_dial" dbkeys are declared in REGISTRY below.
    "vsi_pfd": ["VS"],
    "virtual_vfr": [
        "PITCH",
        "LAT",
        "LONG",
        "HEAD",
        "ALT",
        "PITCH",
        "ROLL",
        "ALAT",
        "TAS",
    ],
}


INSTRUMENT_DEFAULT_OPTIONS = {
    "heading_display": {"font_size": 17},
}


# ---------------------------------------------------------------------------
# Instrument registry -- the single source of truth for migrated instruments.
#
# Each InstrumentSpec carries the builder PLUS the full editor contract: the
# config properties (category 1), the FIX-database values the instrument reads
# (category 2), twin preview hints (category 3), and the editor flags. The
# editor schema exporter and (by derivation) the configurator twins read from
# here -- so the three mirrors can no longer drift. Instruments not yet
# migrated fall back to the curated metadata in pyefis.editor.schema.
#
# Migration pattern (see docs/adding_an_instrument.md): move an instrument's
# entries out of the curated dicts in editor/schema.py and into a record here.
# ---------------------------------------------------------------------------
REGISTRY: dict[str, InstrumentSpec] = {}


def _register(spec: InstrumentSpec) -> InstrumentSpec:
    REGISTRY[spec.type] = spec
    return spec


_register(InstrumentSpec(
    type="atitude_indicator",
    label="Attitude Indicator",
    category="attitude",
    builder=build_atitude_indicator,
    dbkeys=["PITCH", "ROLL", "ALAT", "TAS"],
    keep_aspect=True,
    svs_capable=True,
    properties=[
        Prop("aircraft_symbol", "enum", default="classic",
             enum=["classic", "garmin"], label="Aircraft symbol",
             help="classic split-wing bars, or GI-275/G1000-style wedges"),
        Prop("symbol_color", "color", default="#ffff00", label="Symbol colour"),
        Prop("show_fpm", "boolean", default=True, label="Flight-path marker",
             help="GPS flight-path marker (needs VS/GS/TRACK/HEAD)"),
    ],
    # Attitude is read directly (PITCH/ROLL); no FIX aux values.
    fix_values=[],
    preview={"pitch": 4.0, "roll": -9.0, "slip": 2.0},
))

_register(InstrumentSpec(
    type="arc_gauge",
    label="Arc Gauge",
    category="gauge",
    builder=(lambda screen, config, font_percent=None, font_family=None,
             replace=None: gauges.ArcGauge(
                 screen, min_size=False, font_family=font_family)),
    keep_aspect=True,
    properties=[
        Prop("dbkey", "fixkey", default="", label="FIX key",
             apply="setter:setDbkey"),
        Prop("name", "string", default="", label="Name"),
        Prop("decimal_places", "integer", default=1, label="Decimal places"),
        Prop("show_units", "boolean", default=False, label="Show units"),
        Prop("segments", "integer", default=0, label="Segments",
             help="0 = solid band; >0 draws a segmented (LED-style) band"),
        Prop("name_location", "enum", default="top", enum=["top", "right"],
             label="Name location"),
    ],
    # The colour-band thresholds and the value range are FIX-database values
    # (item min/max + aux), set in fix-gateway, not in the panel editor (#64).
    fix_values=[
        FixValue("Min", source="min", label="Range minimum"),
        FixValue("Max", source="max", label="Range maximum"),
        FixValue("lowAlarm", source="aux", label="Low alarm (red)"),
        FixValue("lowWarn", source="aux", label="Low warning (yellow)"),
        FixValue("highWarn", source="aux", label="High warning (yellow)"),
        FixValue("highAlarm", source="aux", label="High alarm (red)"),
    ],
    # Representative bands + needle fill so the twin can draw a realistic gauge
    # with no live FIX (fractions of range; the device uses real aux values).
    preview={"value": "2350", "fill": 0.72, "green_to": 0.62, "yellow_to": 0.83},
))

_register(InstrumentSpec(
    type="airspeed_tape",
    label="Airspeed Tape",
    category="airspeed",
    builder=(lambda screen, config, font_percent=None, font_family=None,
             replace=None: airspeed.Airspeed_Tape(
                 screen, font_percent=font_percent)),
    dbkeys=["IAS"],
    properties=[
        # NOTE: no editable dbkey -- Airspeed_Tape is hard-wired to IAS (it has
        # no setDbkey and reads the V-speed aux off that item). The old curated
        # schema offered a dbkey option that did nothing; dropped.
        Prop("show_tas", "boolean", default=True, label="Show TAS box"),
        Prop("show_trend", "boolean", default=True, label="Show trend arrow"),
        Prop("trend_lookahead", "number", default=6.0,
             label="Trend look-ahead (s)"),
    ],
    # V-speeds come from the IAS item's aux (fix-gateway), not the panel editor.
    fix_values=[
        FixValue("Vs", source="aux", label="Stall, clean (Vs)", units="kt"),
        FixValue("Vs0", source="aux", label="Stall, landing (Vs0)", units="kt"),
        FixValue("Vno", source="aux", label="Max cruise (Vno)", units="kt"),
        FixValue("Vne", source="aux", label="Never-exceed (Vne)", units="kt"),
        FixValue("Vfe", source="aux", label="Flaps-extended (Vfe)", units="kt"),
    ],
    preview={"value": 110, "vs0": 40, "vs": 45, "vno": 125, "vne": 140,
             "vfe": 70},
))

_register(InstrumentSpec(
    type="vsi_dial",
    label="VSI Dial",
    category="vertical_speed",
    builder=(lambda screen, config, font_percent=None, font_family=None,
             replace=None: vsi.VSI_Dial(screen, font_family=font_family)),
    dbkeys=["VS"],
    keep_aspect=True,
    # VSI_Dial is hard-wired to VS and exposes no editor options today; this
    # record migrates it for catalog completeness. Range is the FIX item's.
    properties=[],
    fix_values=[
        FixValue("Min", source="min", label="Range minimum", units="ft/min"),
        FixValue("Max", source="max", label="Range maximum", units="ft/min"),
    ],
    preview={"value": 800},
))


# Fold the registry back into the legacy lookup tables so existing consumers
# keep working AND migrated instruments are sourced from the registry (the
# single source of truth). As instruments migrate, these literal dicts shrink;
# once everything is migrated they can be removed entirely.
for _t, _spec in REGISTRY.items():
    if _spec.builder is not None:
        INSTRUMENT_FACTORIES[_t] = _spec.builder
    if _spec.dbkeys:
        INSTRUMENT_DEFAULTS[_t] = list(_spec.dbkeys)


def create_instrument(
    screen, config, font_percent=None, font_family=None, replace=None
):
    factory = INSTRUMENT_FACTORIES.get(config["type"])
    if factory is None:
        raise ValueError(f"Unknown instrument type '{config['type']}'")
    return factory(
        screen,
        config,
        font_percent=font_percent,
        font_family=font_family,
        replace=replace,
    )


def get_instrument_defaults(instrument_type):
    return INSTRUMENT_DEFAULTS.get(instrument_type)


def get_instrument_default_options(instrument_type):
    return INSTRUMENT_DEFAULT_OPTIONS.get(instrument_type, False)
