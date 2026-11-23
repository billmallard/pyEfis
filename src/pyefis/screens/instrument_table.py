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

"""The one place pyEfis turns a name into code (CERT12c, brief U3 and U4).

Instrument classes are named here as strings and imported on first use, so a
screen loads only the instruments it places: a PFD with no map never imports
the map, the flight plan or the plates (``briefs/primary_flight_core.md``,
rule R2b). Every other import by name in pyEfis -- the screen module a config
names, user hook modules, the external FMS -- goes through this module too, so
the dynamic imports a static check cannot follow (the brief's E5) sit in one
file a reviewer can read.

Nothing outside this module calls ``importlib.import_module``;
``tests/screens/test_instrument_table.py`` holds that line.
"""

import importlib
import logging

log = logging.getLogger(__name__)


# Class name -> the package that defines it. The class name is the key, so a
# lookup reads like the constructor call it replaces. A module named here is
# imported only when a screen asks for one of its classes.
INSTRUMENTS = {
    # Primary-flight core (brief section 3).
    "AI": "pyefis.instruments.ai",
    "Airspeed": "pyefis.instruments.airspeed",
    "Airspeed_Box": "pyefis.instruments.airspeed",
    "Airspeed_Tape": "pyefis.instruments.airspeed",
    "Altimeter": "pyefis.instruments.altimeter",
    "Altimeter_Tape": "pyefis.instruments.altimeter",
    "AS_Trend_Tape": "pyefis.instruments.vsi",
    "Alt_Trend_Tape": "pyefis.instruments.vsi",
    "VSI_Dial": "pyefis.instruments.vsi",
    "VSI_PFD": "pyefis.instruments.vsi",
    "TurnCoordinator": "pyefis.instruments.tc",
    "HSI": "pyefis.instruments.hsi",
    "DG_Tape": "pyefis.instruments.hsi",
    "HeadingDisplay": "pyefis.instruments.hsi",
    "Button": "pyefis.instruments.button",
    "AutopilotPanel": "pyefis.instruments.autopilot",
    "ModeAnnunciator": "pyefis.instruments.autopilot.fma",
    "Annunciator": "pyefis.instruments.annunciator",
    "TabSection": "pyefis.instruments.tab_section",
    # Powerplant group.
    "ArcGauge": "pyefis.instruments.gauges",
    "HorizontalBar": "pyefis.instruments.gauges",
    "VerticalBar": "pyefis.instruments.gauges",
    "NumericDisplay": "pyefis.instruments.gauges",
    # Not core.
    "MovingMap": "pyefis.instruments.map",
    "FlightPlan": "pyefis.instruments.flight_plan",
    "NavStatus": "pyefis.instruments.nav_status",
    "WindDisplay": "pyefis.instruments.wind",
    "Weston": "pyefis.instruments.weston",
    "ListBox": "pyefis.instruments.listbox",
    "Checklist": "pyefis.instruments.checklist",
    "StaticText": "pyefis.instruments.misc",
    "ValueDisplay": "pyefis.instruments.misc",
    "DataStatus": "pyefis.instruments.data_status",
    "DataAnnunciation": "pyefis.instruments.data_status",
    "AboutSystem": "pyefis.instruments.about",
}


# Background renderers the attitude widget can host (CERT12b, brief R2b):
# kind -> "module:factory", the factory taking the renderer's config dict.
# The interface they implement is in instruments/ai/background.py. Not core.
RENDERERS = {
    "svs": "pyefis.instruments.ai.svs:create_background_renderer",
}


def instrument(name):
    """Return the instrument class ``name``, importing its package now if no
    screen has needed it yet. An unknown name raises ``KeyError``: a builder
    asking for a class the table does not list is a coding error."""
    return getattr(importlib.import_module(INSTRUMENTS[name]), name)


def renderer(kind):
    """Return the factory for the background renderer ``kind``, importing
    its module now if no screen has needed it yet. An AI that never asks for
    one never loads it."""
    module, _, attr = RENDERERS[kind].partition(":")
    return getattr(importlib.import_module(module), attr)


def screen_module(name):
    """Import the screen module a screen config names (``module:``). The
    shipped screens all name ``pyefis.screens.screenbuilder``; a config may
    name its own, which runs in the display process like any screen."""
    return importlib.import_module(name)


def external_module(name):
    """Import code the installation supplies from outside pyEfis: user hook
    modules (``hooks:``) and the FMS bridge (``FMS:``). None of it is core.
    It runs in the display process, so it is the installer's to assess, the
    way the brief treats a wrong button file as a configuration fault."""
    log.info("loading external module %s", name)
    return importlib.import_module(name)
