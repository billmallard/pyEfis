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
    # Only un-migrated types remain as literals here; every other type folds in
    # from REGISTRY below (the single source of truth). Still pending:
    #   heading_display -- deferred (font_size no-op + fg_color default cleanup)
    #   virtual_vfr     -- pending its synthetic-vision customisation pass
    "heading_display": lambda screen, config, font_percent=None, font_family=None, replace=None: hsi.HeadingDisplay(
        screen, font_family=font_family
    ),
    "virtual_vfr": build_virtual_vfr,
}


INSTRUMENT_DEFAULTS = {
    # "airspeed_dial" / "airspeed_tape" / "airspeed_trend_tape" / "airspeed_box"
    # dbkeys are declared in REGISTRY below.
    # "altimeter_dial" / "altimeter_tape" / "altimeter_trend_tape" dbkeys are
    # declared in REGISTRY below.
    # "atitude_indicator" dbkeys are declared in REGISTRY below.
    "heading_display": ["HEAD"],
    # "heading_tape" / "horizontal_situation_indicator" dbkeys -> REGISTRY below.
    # "turn_coordinator" dbkeys are declared in REGISTRY below.
    # "vsi_dial" / "vsi_pfd" dbkeys are declared in REGISTRY below.
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
    # Representative pose for the twin (matches the render-tool demo so the
    # editor preview reads like a real panel).
    preview={"pitch": -2.0, "roll": 4.0, "slip": 1.0},
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
    # Representative 5-zone bands + needle fill so the twin draws a realistic
    # red-yellow-green-yellow-red gauge with no live FIX (fractions of range;
    # the device uses the real min/max + warn/alarm aux).
    preview={"value": "72.0", "fill": 0.72, "low_alarm": 0.10,
             "low_warn": 0.20, "high_warn": 0.80, "high_alarm": 0.90},
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
    preview={"value": -350},
))

_register(InstrumentSpec(
    type="airspeed_dial",
    label="Airspeed Dial",
    category="airspeed",
    builder=(lambda screen, config, font_percent=None, font_family=None,
             replace=None: airspeed.Airspeed(screen, font_family=font_family)),
    dbkeys=["IAS"],
    keep_aspect=True,
    # Fixed steam-gauge face; IAS hard-wired. V-speed arcs come from IAS aux.
    fix_values=[
        FixValue("Vs", source="aux", label="Stall, clean (Vs)", units="kt"),
        FixValue("Vs0", source="aux", label="Stall, landing (Vs0)", units="kt"),
        FixValue("Vno", source="aux", label="Max cruise (Vno)", units="kt"),
        FixValue("Vne", source="aux", label="Never-exceed (Vne)", units="kt"),
        FixValue("Vfe", source="aux", label="Flaps-extended (Vfe)", units="kt"),
    ],
    preview={"value": 110},
))

_register(InstrumentSpec(
    type="altimeter_dial",
    label="Altimeter Dial",
    category="altitude",
    builder=(lambda screen, config, font_percent=None, font_family=None,
             replace=None: altimeter.Altimeter(screen, font_family=font_family)),
    dbkeys=["ALT"],
    keep_aspect=True,
    preview={"value": 3500},
))

_register(InstrumentSpec(
    type="altimeter_tape",
    label="Altimeter Tape",
    category="altitude",
    builder=build_altimeter_tape,
    dbkeys=["ALT"],
    # All options are consumed by build_altimeter_tape at construction
    # (apply="special"); defaults are the Altimeter_Tape constructor defaults.
    properties=[
        Prop("dbkey", "fixkey", default="ALT", label="FIX key", apply="special"),
        Prop("maxalt", "integer", default=50000, label="Max altitude", apply="special"),
        Prop("majorDiv", "integer", default=200, label="Major division", apply="special"),
        Prop("minorDiv", "integer", default=100, label="Minor division", apply="special"),
        Prop("total_decimals", "integer", default=5, label="Total digits", apply="special"),
        Prop("font_mask", "string", default="00000", label="Font mask", apply="special"),
        Prop("round_to", "number", default=0, label="Round readout to", apply="special"),
        Prop("numeric_box", "boolean", default=True, label="Show numeric box", apply="special"),
        Prop("font_scale", "number", default=1.0, label="Scale-number font scale", apply="special"),
    ],
    preview={"value": 3500},
))

_register(InstrumentSpec(
    type="vsi_pfd",
    label="VSI (PFD)",
    category="vertical_speed",
    builder=(lambda screen, config, font_percent=None, font_family=None,
             replace=None: vsi.VSI_PFD(screen, font_family=font_family)),
    dbkeys=["VS"],
    preview={"value": -350},
))

_register(InstrumentSpec(
    type="horizontal_situation_indicator",
    label="Horizontal Situation Indicator (HSI)",
    category="navigation",
    builder=(lambda screen, config, font_percent=None, font_family=None,
             replace=None: hsi.HSI(screen, font_percent=font_percent,
                                    cdi_enabled=True, gsi_enabled=True,
                                    font_family=font_family)),
    dbkeys=["COURSE", "CDI", "GSI", "HEAD"],
    keep_aspect=True,
    # The factory enables CDI+GSI at construction; the editor toggles honour
    # self.cdi_enabled / self.gsi_enabled at paint time. COURSE/CDI/GSI/HEAD are
    # direct FIX keys (no aux), so no fix_values.
    properties=[
        Prop("cdi_enabled", "boolean", default=True, label="CDI"),
        Prop("gsi_enabled", "boolean", default=True, label="Glideslope"),
        Prop("fg_color", "color", default="#ffffff", label="Foreground"),
        Prop("bg_color", "color", default="#000000", label="Background"),
    ],
    preview={"heading": 87, "course": 110},
))

_register(InstrumentSpec(
    type="heading_tape",
    label="Heading Tape",
    category="navigation",
    builder=(lambda screen, config, font_percent=None, font_family=None,
             replace=None: hsi.DG_Tape(screen, font_family=font_family)),
    dbkeys=["HEAD"],
    # DG_Tape is hard-wired to HEAD (no setDbkey); the old curated dbkey option
    # was a no-op and is dropped.
    preview={"heading": 87},
))


# Shared option set + FIX values for the AbstractGauge family (arc / bar /
# numeric). Colour bands + range are FIX-database values (item min/max + aux),
# set in fix-gateway, not the panel editor (#64).
def _gauge_fix_values():
    return [
        FixValue("Min", source="min", label="Range minimum"),
        FixValue("Max", source="max", label="Range maximum"),
        FixValue("lowAlarm", source="aux", label="Low alarm (red)"),
        FixValue("lowWarn", source="aux", label="Low warning (yellow)"),
        FixValue("highWarn", source="aux", label="High warning (yellow)"),
        FixValue("highAlarm", source="aux", label="High alarm (red)"),
    ]


def _bar_gauge_props():
    return [
        Prop("dbkey", "fixkey", default="", label="FIX key",
             apply="setter:setDbkey"),
        Prop("name", "string", default="", label="Name"),
        Prop("decimal_places", "integer", default=1, label="Decimal places"),
        Prop("show_units", "boolean", default=True, label="Show units"),
        Prop("segments", "integer", default=0, label="Segments"),
    ]


_register(InstrumentSpec(
    type="horizontal_bar_gauge",
    label="Horizontal Bar Gauge",
    category="gauge",
    builder=(lambda screen, config, font_percent=None, font_family=None,
             replace=None: gauges.HorizontalBar(
                 screen, min_size=False, font_family=font_family)),
    properties=_bar_gauge_props(),
    fix_values=_gauge_fix_values(),
    preview={"value": "72", "fill": 0.72},
))

_register(InstrumentSpec(
    type="vertical_bar_gauge",
    label="Vertical Bar Gauge",
    category="gauge",
    builder=(lambda screen, config, font_percent=None, font_family=None,
             replace=None: gauges.VerticalBar(
                 screen, min_size=False, font_family=font_family)),
    properties=_bar_gauge_props(),
    fix_values=_gauge_fix_values(),
    preview={"value": "72", "fill": 0.72},
))

_register(InstrumentSpec(
    type="turn_coordinator",
    label="Turn Coordinator",
    category="attitude",
    builder=(lambda screen, config, font_percent=None, font_family=None,
             replace=None: tc.TurnCoordinator(screen, font_family=font_family)),
    dbkeys=["ROT", "ALAT"],
    keep_aspect=True,
    preview={"rate": 8, "ball": 2},
))

_register(InstrumentSpec(
    type="numeric_display",
    label="Numeric Display",
    category="text",
    builder=(lambda screen, config, font_percent=None, font_family=None,
             replace=None: gauges.NumericDisplay(
                 screen, font_family=font_family)),
    properties=[
        Prop("dbkey", "fixkey", default="", label="FIX key",
             apply="setter:setDbkey"),
        Prop("decimal_places", "integer", default=1, label="Decimal places"),
        Prop("font_mask", "string", default="000", label="Font mask"),
        Prop("show_units", "boolean", default=False, label="Show units"),
    ],
    fix_values=_gauge_fix_values(),
))

_register(InstrumentSpec(
    type="value_text",
    label="Value Text",
    category="text",
    builder=(lambda screen, config, font_percent=None, font_family=None,
             replace=None: misc.ValueDisplay(screen, font_family=font_family)),
    properties=[
        Prop("dbkey", "fixkey", default="", label="FIX key",
             apply="setter:setDbkey"),
        Prop("font_mask", "string", default="", label="Font mask"),
    ],
))

_register(InstrumentSpec(
    type="static_text",
    label="Static Text",
    category="text",
    builder=build_static_text,
    properties=[
        Prop("text", "string", default="Text", label="Text", required=True,
             apply="special"),
        Prop("alignment", "enum", default="AlignLeft",
             enum=["AlignLeft", "AlignCenter", "AlignRight"], label="Alignment"),
        Prop("font_mask", "string", default="", label="Font mask"),
    ],
))

_register(InstrumentSpec(
    type="airspeed_box",
    label="Airspeed Box",
    category="airspeed",
    builder=(lambda screen, config, font_percent=None, font_family=None,
             replace=None: airspeed.Airspeed_Box(screen, font_family=font_family)),
    dbkeys=["IAS", "GS", "TAS"],
))

_register(InstrumentSpec(
    type="airspeed_trend_tape",
    label="Airspeed Trend Tape",
    category="airspeed",
    builder=(lambda screen, config, font_percent=None, font_family=None,
             replace=None: vsi.AS_Trend_Tape(screen, font_family=font_family)),
    dbkeys=["IAS"],
))

_register(InstrumentSpec(
    type="altimeter_trend_tape",
    label="Altimeter Trend Tape",
    category="altitude",
    builder=(lambda screen, config, font_percent=None, font_family=None,
             replace=None: vsi.Alt_Trend_Tape(screen, font_family=font_family)),
    # The widget reads VS (vertical speed) directly; the legacy curated default
    # was "ALT", a key it never consumes.
    dbkeys=["VS"],
))

_register(InstrumentSpec(
    type="wind_display",
    label="Wind Display",
    category="wind",
    builder=(lambda screen, config, font_percent=None, font_family=None,
             replace=None: wind.WindDisplay(screen, font_family=font_family)),
    dbkeys=["HWIND", "XWIND"],
))

# --- Special / non-instrument types --------------------------------------
# These are migrated for catalog completeness but, unlike the gauges/dials,
# cannot be built in isolation (they need a live screen for config_path, embed
# an external process, or read host files), so builds_in_isolation=False keeps
# them out of the gate's construction probe. Their config is consumed inside the
# builder (apply="special"), not setattr'd onto the widget.

_register(InstrumentSpec(
    type="weston",
    label="Weston",
    category="system",
    builder=build_weston,
    # Upstream feature (Eric Blevins, 2023): embeds a weston/waydroid surface
    # under X11. Linux/X11 only -- inert on other platforms.
    offscreen_renderable=False,
    builds_in_isolation=False,
    properties=[
        Prop("socket", "string", required=True, apply="special",
             label="Wayland socket", help="weston -S socket name"),
        Prop("ini", "string", required=True, apply="special",
             label="weston.ini", help="path (under the config dir) to weston.ini"),
        Prop("command", "string", required=True, apply="special",
             label="Command", help="program to launch inside the compositor"),
        Prop("args", "string", required=True, apply="special",
             label="Arguments", help="arguments passed to the command"),
    ],
))

_register(InstrumentSpec(
    type="button",
    label="Button",
    category="control",
    builder=build_button,
    builds_in_isolation=False,
    properties=[
        Prop("config", "string", required=True, apply="special",
             label="Config file",
             help="path (under the config dir) to the button's YAML definition"),
    ],
))

_register(InstrumentSpec(
    type="listbox",
    label="Listbox",
    category="list",
    builder=build_listbox,
    builds_in_isolation=False,
    properties=[
        # Structured option (list of {name, file}); represented as a single
        # config value until the Prop model grows an explicit list/object kind.
        Prop("lists", "string", required=True, apply="special",
             label="Lists", help="selectable lists -- list of {name, file} entries"),
    ],
))

_register(InstrumentSpec(
    type="data_status",
    label="Data Status",
    category="system",
    builder=build_data_status,
    builds_in_isolation=False,
    # The builder also accepts optional status_path / continue_screen /
    # update_command; left out of the panel (they default sensibly) until there
    # is a reason to expose host-path plumbing in the editor.
))

_register(InstrumentSpec(
    type="data_annunciation",
    label="Data Annunciation",
    category="system",
    builder=build_data_annunciation,
    builds_in_isolation=False,
    # Optional status_path / target_screen handled by the builder; not exposed.
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
