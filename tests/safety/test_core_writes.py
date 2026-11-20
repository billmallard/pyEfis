#  SPDX-License-Identifier: GPL-2.0-or-later
"""Rule R5, the write audit through the fake database, as a ratchet.

tests/safety/boot_probe.py boots the shipped default config (every shipped screen in the
default list) in a child process against the fake FIX database, then drives it: every
button clicked, the knob walked through every instrument, and a grid of taps over every
instrument each followed by knob turns and a push. Every write to the database from
pyefis code is recorded at the database item, with the module that made it and every
pyefis module on its call stack. The rule, from docs/safety/core_modules.yaml:

  - no pyefis code writes a sensed or computed primary key (PITCH, IAS, CDI, the engine
    values, ...);
  - a pilot-set key (BARO, ALTSEL, HEADBUG, NAVSRC) is written only from its listed core
    write paths, with no non-core module on the call stack.

A breach not under ratchet: writes fails, and so does a listed one that no longer occurs.

What the drive reaches is what a click, a knob step and a tap reach. A write behind a
long press, a drag, a timer or a gateway reply is not exercised; nor is a screen the
shipped default list does not load. The planted test shows the audit failing on a write
to PITCH and to BARO from a non-core module, and on a NAVSRC write passed through the
core HMI layer from non-core code."""

import collections

import pytest

from tests.safety import core_rules

# Appended to a non-core module that every boot imports (through E4), so the writes run
# during the boot itself: no drive needed.
PLANT = '''
import pyavtools.fix as _planted_fix
from pyefis.hmi import functions as _planted_hmi


def _planted():
    _planted_fix.db.get_item("PITCH").value = 1.0   # sensed, from a non-core module
    baro = _planted_fix.db.get_item("BARO")         # pilot-set, from a non-core module
    baro.value = 29.5
    baro.output_value()
    _planted_hmi.setValue("NAVSRC,1")               # pilot-set, a core path, non-core caller


_planted()
'''


@pytest.fixture(scope="module")
def doc():
    return core_rules.load()


@pytest.fixture(scope="module")
def audit(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("core_writes")
    cfg = core_rules.stage_config(tmp / "config")
    return core_rules.run_probe(cfg, tmp / "audit.json", writes=True, drive=True)


def test_the_drive_reached_the_shipped_screens_and_controls(audit):
    driven = {d["screen"]: d for d in audit["driven"]}
    assert {"PFD", "EMS", "RADIO"} <= set(driven)
    assert sum(d["button_clicks"] for d in driven.values()) > 0
    assert sum(d["knob_stops"] for d in driven.values()) > 0
    assert driven["PFD"]["taps"] > 0


def test_the_drive_reached_the_core_write_paths_of_the_pilot_set_keys(audit):
    """Not vacuous: the shipped PFD's baro box, selected altitude and heading bug are
    written during the drive, each from its owning instrument. NAVSRC is not:
    buttons/cdi-source.yaml ships, but no default screen places it."""
    writers = collections.defaultdict(set)
    for w in audit["writes"]:
        writers[w["key"]].add(w["writer"])
    assert "src/pyefis/instruments/altimeter/__init__.py" in writers["BARO"]
    assert "src/pyefis/instruments/altimeter/altsel.py" in writers["ALTSEL"]
    assert "src/pyefis/instruments/hsi/__init__.py" in writers["HEADBUG"]


def test_no_write_breaks_rule_r5_but_the_allowlist(doc, audit):
    new, stale = core_rules.write_check(doc, audit["writes"])
    assert not new, "\n".join(new)
    assert not stale, ("allowlisted writes that no longer occur; delete them from ratchet: "
                       "writes: %s" % stale)


def test_planted_writes_fail_the_audit(doc, tmp_path):
    src = core_rules.stage_source(tmp_path)
    core_rules.plant(src, "src/pyefis/instruments/about/__init__.py", PLANT)
    cfg = core_rules.stage_config(tmp_path / "config", core_rules.CORE_ONLY)
    planted = core_rules.run_probe(cfg, tmp_path / "planted.json", writes=True, src=src)
    found = core_rules.write_violations(doc, planted["writes"])
    assert set(found) == {
        ("PITCH", "src/pyefis/instruments/about/__init__.py"),
        ("BARO", "src/pyefis/instruments/about/__init__.py"),
        ("NAVSRC", "src/pyefis/hmi/functions.py"),
    }, found
    assert "non-core code on the call stack" in found[("NAVSRC", "src/pyefis/hmi/functions.py")]
    new, _ = core_rules.write_check(doc, planted["writes"])
    assert len(new) == 3


def test_the_same_boot_without_the_plant_passes(doc, tmp_path):
    src = core_rules.stage_source(tmp_path)
    cfg = core_rules.stage_config(tmp_path / "config", core_rules.CORE_ONLY)
    clean = core_rules.run_probe(cfg, tmp_path / "clean.json", writes=True, src=src)
    assert core_rules.write_violations(doc, clean["writes"]) == {}


@pytest.mark.parametrize("key,cls", [
    ("PITCH", "sensed_computed"), ("CDI", "sensed_computed"), ("CHT11", "sensed_computed"),
    ("TACH1", "sensed_computed"), ("EGTBTN2", None), ("BARO", "pilot_set"),
    ("HEADBUG", "pilot_set"), ("FPLCMD", None), ("HIDEBUTTON", None),
])
def test_key_classes(doc, key, cls):
    assert core_rules.key_class(key, doc) == cls
