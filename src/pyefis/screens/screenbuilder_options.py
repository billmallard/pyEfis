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

import logging

import pyefis.hmi as hmi
from pyefis.screens import screenbuilder_preferences

log = logging.getLogger(__name__)


def _coerce_to_attr_type(instrument, option, value):
    """Coerce a string config value to the type of the widget's existing
    attribute (its default), so a numeric option delivered as a quoted string
    (e.g. from the configurator code pane / a quoted YAML scalar like
    ``minorDiv: '5'``) can't reach numeric/geometry code as a str. Several AI
    pitch-ladder options (minorDiv, majorDiv, numberedDiv, visiblePitchAngle,
    numberedDivWidth) feed Qt/geometry math that *segfaults* -- not raises -- on
    a str, which crashes the whole panel. Only string values whose target attr
    is numeric are converted; anything else is passed through unchanged."""
    if not isinstance(value, str):
        return value
    cur = getattr(instrument, option, None)
    try:
        if isinstance(cur, bool):
            return value.strip().lower() in ("true", "1", "yes", "on")
        if isinstance(cur, int):            # (bool handled above)
            return int(float(value))
        if isinstance(cur, float):
            return float(value)
    except (ValueError, TypeError):
        log.warning("option '%s': could not coerce %r to %s; leaving as-is",
                    option, value, type(cur).__name__)
    return value


def _warn_undeclared_option(inst_type, option):
    """Warn when a screen sets an option a *migrated* instrument doesn't declare
    in its InstrumentSpec -- catches typos and renamed attributes (the option is
    still applied via setattr, but it likely does nothing). Unmigrated types have
    no declared contract, so they're left alone. Never raises."""
    try:
        if option in ("font_family", "font_percent"):
            return  # common options, applied to every instrument
        from pyefis.screens import screenbuilder_factory as _factory
        spec = _factory.REGISTRY.get(inst_type)
        if spec is None:
            return  # not migrated -- no declared contract to check against
        if any(p.name == option for p in spec.properties):
            return
        log.warning(
            "instrument '%s': option '%s' is not declared in its "
            "InstrumentSpec; it is applied but may have no effect",
            inst_type, option)
    except Exception:
        pass


funcTempF = lambda x: x * (9.0 / 5.0) + 32.0
funcTempC = lambda x: x

funcPressHpa = lambda x: x * 33.863889532610884
funcPressInHg = lambda x: x

funcAltitudeMeters = lambda x: x / 3.28084
funcAltitudeFeet = lambda x: x


def configure_unit_switching(
    instrument, unit_group, unit1, unit2, conversion1, conversion2
):
    instrument.conversionFunction1 = conversion1
    instrument.unitsOverride1 = unit1
    instrument.conversionFunction2 = conversion2
    instrument.unitsOverride2 = unit2
    instrument.unitGroup = unit_group
    instrument.setUnitSwitching()


def apply_unit_default(screen, instrument):
    """Start a unit-switching instrument in its group's configured unit.

    The default comes from the ``units`` block of preferences, keyed by unit
    group, e.g. ``units: {Pressure: hPa}`` (the configurator's aircraft-level
    altimeter-setting unit lands here via preferences.yaml.custom). Without an
    entry the instrument keeps its first unit. An unknown unit name is logged
    and ignored -- a typo in the profile must not stop the screen building.
    The runtime "Set Instrument Units" toggle still works from either start.
    """
    try:
        units = screen.parent.preferences.get("units") or {}
        wanted = units.get(instrument.unitGroup)
    except AttributeError:
        return
    if wanted is None:
        return
    choices = (instrument.unitsOverride1, instrument.unitsOverride2)
    if str(wanted).lower() not in [str(c).lower() for c in choices]:
        log.warning(
            "preferences units.%s: '%s' is not one of %s; keeping %s",
            instrument.unitGroup, wanted, list(choices), choices[0])
        return
    instrument.setUnits(f"{instrument.unitGroup}:{wanted}")


def configure_tape_baro(screen):
    """Once a screen is built, settle each altimeter tape's baro box (pyEfis
    #311): a defaulted box stays off when the screen already shows BARO in
    another widget (an older screen's numeric_display), so no screen shows
    two readouts; and the box starts in the ``units: Pressure`` preference."""
    instruments = list(getattr(screen, "instruments", {}).values())
    other = any(
        getattr(i, "dbkey", None) == "BARO" and not i.isHidden()
        for i in instruments
        if not callable(getattr(i, "configure_baro", None)))
    try:
        prefs = screen.parent.preferences
    except AttributeError:
        prefs = None
    for inst in instruments:
        if callable(getattr(inst, "configure_baro", None)):
            inst.configure_baro(prefs, other_readout=other)


def apply_options(screen, index, config, state=False):
    if "options" not in config:
        return

    instrument = screen.instruments[index]
    unit_switching = False
    for option, value in config["options"].items():
        if "encoder_order" == option and not state:
            if callable(getattr(instrument, "enc_selectable", None)):
                screen.encoder_list.append(
                    {"inst": index, "order": config["options"]["encoder_order"]}
                )
            continue

        if (
            "egt_mode_switching" == option
            and value == True
            and config["type"] == "vertical_bar_gauge"
        ):
            hmi.actions.setEgtMode.connect(instrument.setMode)
            continue

        if "dbkey" in option:
            if callable(getattr(instrument, "setDbkey", None)):
                instrument.setDbkey(value)
            else:
                setattr(instrument, option, value)
            continue

        if "font_percent" == option:
            # Accept a whole-number percent (40) or legacy fraction (0.40); the
            # widget uses it as a fraction of height. Same rule as the
            # constructor path (screenbuilder_preferences.apply_preferences).
            setattr(instrument, option,
                    screenbuilder_preferences.normalize_font_percent(value))
            continue

        if (
            "temperature" in option
            and value == True
            and ("gauge" in config["type"] or config["type"] == "numeric_display")
        ):
            configure_unit_switching(
                instrument,
                "Temperature",
                "\N{DEGREE SIGN}F",
                "\N{DEGREE SIGN}C",
                funcTempF,
                funcTempC,
            )
            unit_switching = True
            continue

        elif (
            "pressure" in option
            and value == True
            and ("gauge" in config["type"] or config["type"] == "numeric_display")
        ):
            configure_unit_switching(
                instrument,
                "Pressure",
                "inHg",
                "hPa",
                funcPressInHg,
                funcPressHpa,
            )
            unit_switching = True
            continue

        elif (
            "altitude" in option
            and value == True
            and (
                config["type"]
                in ["gauge", "numeric_display", "altimeter_tape", "altimeter_dial"]
            )
        ):
            configure_unit_switching(
                instrument,
                "Altitude",
                "Ft",
                "M",
                funcAltitudeFeet,
                funcAltitudeMeters,
            )
            unit_switching = True
            continue

        else:
            _warn_undeclared_option(config["type"], option)
            setattr(instrument, option,
                    _coerce_to_attr_type(instrument, option, value))

    # After the loop, so dbkey is set whatever the option order in the YAML.
    if unit_switching:
        apply_unit_default(screen, instrument)
