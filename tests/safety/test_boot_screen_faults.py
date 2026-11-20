#  SPDX-License-Identifier: GPL-2.0-or-later
"""Brief R3 at construction: a fault building a non-flight screen costs that screen only
(AER-6106).

Every configured screen is built at startup, on the ground or in flight. Before the guard
in gui.Main, a constructor that raised on any screen -- data status, About, a map --
aborted the boot, and systemd restarted pyEfis into the same fault with no PFD.

Each case boots tests/safety/boot_probe.py over the core-only PFD plus a moving-map
screen, from a copy of the source with one instrument constructor made to raise once it
has built its widget, and checks the PFD is on the glass and the faulted screen is gone.
The flight screen's own fault must still stop the process: there is nothing to fall
back to, and the supervisor has to see it.
"""

import json
import os
import pathlib
import subprocess
import sys

import pytest
import yaml

from tests.safety import core_rules

MAP_SCREEN = {
    "module": "pyefis.screens.screenbuilder",
    "layout": {"rows": 10, "columns": 10},
    "instruments": [{"type": "moving_map", "row": 0, "column": 0,
                     "span": {"rows": 10, "columns": 10}}],
}

# The planted fault: the class builds as normal, then its constructor raises.
FAULT = """
def _plant_fault(cls):
    built = cls.__init__
    def __init__(self, *args, **kwargs):
        built(self, *args, **kwargs)
        raise RuntimeError("planted constructor fault (AER-6106)")
    cls.__init__ = __init__
_plant_fault({cls})
"""

DATA_STATUS = ("src/pyefis/instruments/data_status/__init__.py", "DataStatus")
ABOUT = ("src/pyefis/instruments/about/__init__.py", "AboutSystem")
MAP = ("src/pyefis/instruments/map/__init__.py", "MovingMap")
HSI = ("src/pyefis/instruments/hsi/__init__.py", "HSI")


def _boot(tmp_path, plant=None, ground=False):
    """Boot the staged source; returns (result or None, stderr)."""
    # stage_source brings config/ along: the bundled DataStatus and About definitions
    # live there, and without them those screens are never built.
    src = core_rules.stage_source(tmp_path)
    if plant is not None:
        path, cls = plant
        core_rules.plant(src, path, FAULT.format(cls=cls))
    cfg = core_rules.stage_config(tmp_path / "config", core_rules.CORE_ONLY)
    doc = yaml.safe_load((cfg / "default.yaml").read_text(encoding="utf-8"))
    doc["screens"]["MAP"] = MAP_SCREEN
    (cfg / "default.yaml").write_text(yaml.safe_dump(doc), encoding="utf-8")
    out = tmp_path / "boot.json"
    cmd = [sys.executable, str(core_rules.PROBE), "--config", str(cfg), "--out", str(out),
           "--src", str(src)]
    if ground:
        cmd.append("--ground")
    env = dict(os.environ)
    env.pop("INVOCATION_ID", None)
    env["MAKERPLANE_ACK_LOG"] = str(tmp_path / "acks.jsonl")
    proc = subprocess.run(cmd, cwd=core_rules.ROOT, capture_output=True, text=True,
                          timeout=600, env=env)
    if not out.is_file():
        return None, proc.stderr
    result = json.loads(out.read_text(encoding="utf-8"))
    assert pathlib.Path(result["pyefis"]).is_relative_to(src.resolve())
    return result, proc.stderr


@pytest.mark.parametrize("ground", [False, True], ids=["flight-boot", "ground-boot"])
def test_control_boot_builds_every_screen(tmp_path, ground):
    result, err = _boot(tmp_path, ground=ground)
    assert result is not None and result["status"] == "ok", err[-4000:]
    assert sorted(result["screens"]) == ["About", "DataStatus", "MAP", "PFD"]
    assert result["running"] == ("DataStatus" if ground else "PFD")


@pytest.mark.parametrize("ground", [False, True], ids=["flight-boot", "ground-boot"])
@pytest.mark.parametrize("plant,screen", [(DATA_STATUS, "DataStatus"), (ABOUT, "About"),
                                          (MAP, "MAP")], ids=["data-status", "about", "map"])
def test_a_non_flight_screen_fault_costs_that_screen_only(tmp_path, plant, screen, ground):
    result, err = _boot(tmp_path, plant=plant, ground=ground)
    assert result is not None, "the boot died on a %s fault:\n%s" % (screen, err[-4000:])
    assert result["status"] == "ok", err[-4000:]
    assert screen not in result["screens"]
    assert "pyefis.instruments.hsi.HSI" in result["screens"]["PFD"]
    # A dropped data-status screen on a ground boot falls through to the flight screen.
    expect = "DataStatus" if ground and screen != "DataStatus" else "PFD"
    assert result["running"] == expect
    assert "planted constructor fault" in err


def test_a_flight_screen_fault_still_stops_the_boot(tmp_path):
    result, err = _boot(tmp_path, plant=HSI)
    assert result is None, "the boot carried on past a fault in the flight screen"
    assert "Fatal error initializing GUI" in err and "planted constructor fault" in err
