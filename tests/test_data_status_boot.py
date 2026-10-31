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

"""The nav-data management screen stays loaded -- the PFD data annunciation
opens it -- but is never the boot screen: it is a click-through, and pyEfis
can restart in flight (BACKLOG L3). Guards ``gui._ensure_data_status_screen``:
it boots the configured flight screen, points Continue at it, and never
returns DataStatus while any other screen exists."""

import logging

from pyefis import gui


def setup_module(module):
    # gui.log is normally created inside gui.initialize(); the helper logs.
    gui.log = logging.getLogger("test_data_status_boot")


def setup_function(function):
    gui.screens.clear()


def teardown_function(function):
    gui.screens.clear()


def _cfg(default, *others):
    cfg = {
        "main": {"defaultScreen": default},
        "screens": {
            "DataStatus": {
                "module": "pyefis.screens.screenbuilder",
                "instruments": [
                    {"type": "data_status",
                     "options": {"continue_screen": "PFD"}},
                ],
            },
        },
    }
    for name in others:
        cfg["screens"][name] = {"module": "pyefis.screens.screenbuilder"}
    for name, sc in cfg["screens"].items():
        gui.screens.append(gui.Screen(name, sc["module"], sc))
    return cfg


def _continue(cfg):
    return cfg["screens"]["DataStatus"]["instruments"][0]["options"][
        "continue_screen"]


def test_boots_configured_default_and_continue_goes_there():
    cfg = _cfg("PFD_AI_ONLY", "PFD_AI_ONLY")
    assert gui._ensure_data_status_screen(cfg, "PFD_AI_ONLY") == "PFD_AI_ONLY"
    assert _continue(cfg) == "PFD_AI_ONLY"


def test_default_data_status_boots_its_continue_target():
    cfg = _cfg("DataStatus", "SIX", "PFD")
    assert gui._ensure_data_status_screen(cfg, "DataStatus") == "PFD"
    assert _continue(cfg) == "PFD"


def test_default_data_status_without_target_boots_first_other_screen():
    cfg = _cfg("DataStatus", "SIX")
    assert gui._ensure_data_status_screen(cfg, "DataStatus") == "SIX"


def test_unknown_default_does_not_leave_glass_empty():
    cfg = _cfg("TYPO", "SIX", "PFD")
    assert gui._ensure_data_status_screen(cfg, "TYPO") == "PFD"


def test_missing_default_screen_boots_screen_zero_not_data_status():
    cfg = _cfg(0, "PFD")      # defaultScreen unset -> initialize() passes 0
    # screen 0 is DataStatus here, so fall through to its Continue target.
    assert gui._ensure_data_status_screen(cfg, 0) == "PFD"


def test_injects_bundled_screen_when_config_dropped_it():
    cfg = {"main": {}, "screens": {"PFD": {"module": "x"}}}
    gui.screens.append(gui.Screen("PFD", "pyefis.screens.screenbuilder",
                                  cfg["screens"]["PFD"]))
    assert gui._ensure_data_status_screen(cfg, "PFD") == "PFD"
    assert "DataStatus" in cfg["screens"]
    assert [s.name for s in gui.screens] == ["PFD", "DataStatus"]
    assert _continue(cfg) == "PFD"
