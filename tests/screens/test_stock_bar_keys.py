"""
Stock bar gauges show the key their label names (AER-5179, BACKLOG CERT2b).

Two misleading-display bugs shipped in the stock configs:

- EMS2's "Right" fuel bar (BAR21) read ``FUELQ1``, the same key as "Left"
  (BAR19). A pilot with a dry right tank saw the left tank's quantity.
- EMS's "IT", "AFR" and "EGO" bars (BAR23-25) all read ``MAP1``, so they
  showed manifold pressure under three other names.

Bill's ruling (2026-11-07): fuel bars carry neutral labels, "Tank N" for
``FUELQN``. Stock configs never map Left, Center or Right to a tank number;
tank names will come from the aircraft profile.

The checks, over every stock screen with its includes and ``preferences:``
references resolved the way ``screenbuilder`` resolves them:

1. Within one gauge block, no two fuel-quantity bars share a key.
2. On one screen, two gauges in ganged blocks bound to the same key carry
   the same name. A second name on a key is a label that contradicts it.
3. Every stock fuel-quantity bar, on a screen or in an include, is labelled
   "Tank N" for its ``FUELQN`` ("Total" for ``FUELQT``).
"""
import glob
import os
import re

import pytest
import yaml

from pyefis.screens import screenbuilder_config


CONFIG_DIR = os.path.normpath(os.path.join(
    os.path.dirname(__file__), "..", "..", "src", "pyefis", "config"))

FUEL_TANK_KEY = re.compile(r"^FUELQ(\d+)$")


def _preferences():
    with open(os.path.join(CONFIG_DIR, "preferences.yaml")) as f:
        return yaml.safe_load(f)


def _resolve_bar(entry, common, prefs):
    """(name, dbkey) for one ganged instrument entry, merged in the order
    screenbuilder uses: common_options, then the entry's own options, then
    its ``preferences:`` gauge block."""
    options = dict(common or {}) | dict(entry.get("options") or {})
    if "preferences" in entry:
        options |= prefs["gauges"].get(entry["preferences"], {})
    return options.get("name"), options.get("dbkey")


def _gauge_blocks(instruments, prefs, depth=0):
    """Yield one list of (name, dbkey) per ganged gauge, descending into
    ``type: include,...`` instruments."""
    assert depth < 20, "include loop"
    for inst in instruments or []:
        if not isinstance(inst, dict) or "type" not in inst:
            continue
        if screenbuilder_config.is_include(inst):
            included = screenbuilder_config.load_include_config(
                CONFIG_DIR, prefs, inst)
            yield from _gauge_blocks(included.get("instruments"), prefs,
                                     depth + 1)
        elif "ganged" in inst["type"]:
            bars = []
            for group in inst.get("groups", []):
                for entry in group.get("instruments", []):
                    bars.append(_resolve_bar(
                        entry, group.get("common_options"), prefs))
            yield bars


def _stock_screens():
    screens = []
    for path in sorted(glob.glob(os.path.join(CONFIG_DIR, "screens", "*.yaml"))):
        with open(path) as f:
            doc = yaml.safe_load(f)
        if not isinstance(doc, dict):
            continue
        for screen_name, screen in doc.items():
            if isinstance(screen, dict) and "instruments" in screen:
                screens.append((os.path.basename(path), screen_name, screen))
    return screens


SCREENS = _stock_screens()
SCREEN_IDS = [f"{fname}:{name}" for fname, name, _ in SCREENS]


def test_screens_found_and_fuel_bars_resolved():
    """Guard the guard: the walk must actually reach the EMS fuel bars, or
    every check below passes on nothing."""
    prefs = _preferences()
    fuel_keys = set()
    for _, _, screen in SCREENS:
        for block in _gauge_blocks(screen["instruments"], prefs):
            fuel_keys |= {k for _, k in block if k and FUEL_TANK_KEY.match(k)}
    assert len(SCREENS) >= 10
    assert fuel_keys == {"FUELQ1", "FUELQ2", "FUELQ3"}


@pytest.mark.parametrize("fname,name,screen", SCREENS, ids=SCREEN_IDS)
def test_no_two_fuel_bars_in_a_block_share_a_key(fname, name, screen):
    prefs = _preferences()
    for block in _gauge_blocks(screen["instruments"], prefs):
        fuel = [(n, k) for n, k in block if k and FUEL_TANK_KEY.match(k)]
        keys = [k for _, k in fuel]
        assert len(keys) == len(set(keys)), (
            f"{fname}:{name}: fuel bars share a key: {fuel}")


# Known, not yet ruled on. EMS's BAR27 "IAT" (intake air) reads CAT, which
# fix-gateway defines as Cabin Air Temperature; the same screen also labels
# it "CAT". Which label is right changes the glass, so it is Bill's call
# (BACKLOG CERT2e). Listed exactly, so a fix or a new case fails this test.
KNOWN_CONTRADICTIONS = {
    ("ems.yaml", "EMS"): {"CAT": ["CAT", "IAT"]},
    ("ems-left-buttons.yaml", "EMS"): {"CAT": ["CAT", "IAT"]},
    ("ems-portrait.yaml", "EMS"): {"CAT": ["CAT", "IAT"]},
}


@pytest.mark.parametrize("fname,name,screen", SCREENS, ids=SCREEN_IDS)
def test_one_key_one_name_per_screen(fname, name, screen):
    prefs = _preferences()
    names_by_key = {}
    for block in _gauge_blocks(screen["instruments"], prefs):
        for bar_name, key in block:
            if key:
                names_by_key.setdefault(key, set()).add(bar_name)
    contradictions = {k: sorted(map(str, v))
                      for k, v in names_by_key.items() if len(v) > 1}
    assert contradictions == KNOWN_CONTRADICTIONS.get((fname, name), {}), (
        f"{fname}:{name}: one key shown under several names: {contradictions}")


def _option_blocks(node):
    """Every dict in a YAML tree that carries a ``dbkey``."""
    if isinstance(node, dict):
        if "dbkey" in node:
            yield node
        for value in node.values():
            yield from _option_blocks(value)
    elif isinstance(node, list):
        for value in node:
            yield from _option_blocks(value)


def _all_stock_option_blocks():
    for path in sorted(glob.glob(os.path.join(CONFIG_DIR, "**", "*.yaml"),
                                 recursive=True)):
        with open(path) as f:
            try:
                doc = yaml.safe_load(f)
            except yaml.YAMLError:
                continue
        for block in _option_blocks(doc):
            yield os.path.relpath(path, CONFIG_DIR), block


def test_every_stock_fuel_bar_is_labelled_tank_n():
    wrong = []
    checked = 0
    for path, block in _all_stock_option_blocks():
        key = block["dbkey"]
        if not isinstance(key, str) or "name" not in block:
            continue
        m = FUEL_TANK_KEY.match(key)
        if m:
            checked += 1
            if block["name"] != f"Tank {m.group(1)}":
                wrong.append((path, key, block["name"]))
        elif key == "FUELQT" and block["name"] != "Total":
            wrong.append((path, key, block["name"]))
    assert checked >= 6, "walk found too few fuel bars to mean anything"
    assert not wrong, f"fuel bars not labelled 'Tank N' for FUELQN: {wrong}"
