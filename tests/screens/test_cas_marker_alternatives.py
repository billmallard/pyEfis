"""AER-6602: every screen file a builder is pointed at carries a CAS surface.

``preferences.yaml`` names each stock screen file and, in a comment beside it,
the portrait layout a builder may swap in (``SCREEN_PFD: screens/pfd.yaml  #
screens/pfd-portrait.yaml``); the Legacy wiki page offers the
``*-left-buttons.yaml`` layouts the same way. The runtime watch (gui.py
``_CASCoverageWatch``) only raises ``CAS NOT SHOWN`` when NO screen has a
``cas_window`` or ``cas_marker``, so a swapped-in layout without one would fly
silently. These tests hold that line on the files themselves:

- a screen with an attitude instrument carries a ``cas_window`` or
  ``cas_marker``;
- an alternative layout carries one whenever the stock file it replaces does;
- an alternative layout's marker covers no instrument, only the attitude
  display behind it.

Screens are loaded the way pyefis.main loads them (shipped preferences,
``cfg.from_yaml``) and expanded through the real include machinery; geometry
comes from the editor resolver, which uses the screen builder's own math. No
Qt is needed.
"""
import os
import re

import pytest
import yaml

import pyefis
import pyefis.cfg as cfg
from pyefis.editor import resolver
from pyefis.main import merge_dict
from pyefis.screens.screenbuilder_config import InstrumentExpander, is_disabled

CONFIG = os.path.join(os.path.dirname(pyefis.__file__), "config")
PREFERENCES = os.path.join(CONFIG, "preferences.yaml")

ATTITUDE = {"virtual_vfr", "atitude_indicator"}
CAS = {"cas_window", "cas_marker"}
# Full-area displays a marker necessarily sits on (as on every stock PFD).
BACKDROP = ATTITUDE | {"horizontal_situation_indicator"}
VARIANT_SUFFIXES = ("-portrait", "-left-buttons")


def _preferences():
    with open(PREFERENCES) as f:
        prefs = yaml.safe_load(f)
    custom = PREFERENCES + ".custom"
    if os.path.exists(custom):
        with open(custom) as f:
            merge_dict(prefs, yaml.safe_load(f) or {})
    return prefs


def _referenced():
    """{file: stock file it stands in for} for every screen file
    preferences.yaml names, live or in a comment, plus the left-buttons and
    portrait layouts of each live one. A live file maps to itself."""
    out = {}
    with open(PREFERENCES) as f:
        for line in f:
            names = re.findall(r"screens/([\w.-]+\.yaml)", line)
            if not names:
                continue
            live = names[0]
            out.setdefault(live, live)
            for name in names[1:]:
                out[name] = live
            stem = live[:-len(".yaml")]
            for suffix in VARIANT_SUFFIXES:
                variant = stem + suffix + ".yaml"
                if os.path.exists(os.path.join(CONFIG, "screens", variant)):
                    out.setdefault(variant, live)
    return out


def _screens(fname, prefs):
    """{screen name: (layout, expanded instruments)} for one screen file;
    preference-disabled instruments are dropped, as the screen builder does."""
    path = os.path.join(CONFIG, "screens", fname)
    loaded = cfg.from_yaml(path, bpath=CONFIG, preferences=prefs) or {}
    out = {}
    for name, sc in loaded.items():
        if not isinstance(sc, dict) or "instruments" not in sc:
            continue
        expander = InstrumentExpander(CONFIG, prefs, 1, None)
        expander.include_size_calculator = expander.calc_includes
        insts = []
        for inst in sc.get("instruments") or []:
            if is_disabled(inst, prefs):
                continue
            insts.extend(e for e, _r, _s in expander.expand(inst))
        out[name] = (sc["layout"], insts)
    return out


def _types(fname, prefs):
    return {i.get("type") for _l, insts in _screens(fname, prefs).values()
            for i in insts}


REFERENCED = _referenced()
ALTERNATIVES = sorted(f for f, live in REFERENCED.items() if f != live)


def test_the_offered_layouts_were_found():
    # The sweeps below only mean something if they saw what preferences.yaml
    # offers: the portrait files from its comments, and the left-buttons set.
    for stem in ("pfd", "ems", "ems2", "radio"):
        assert REFERENCED.get(stem + "-portrait.yaml") == stem + ".yaml"
        assert REFERENCED.get(stem + "-left-buttons.yaml") == stem + ".yaml"
    for f in REFERENCED:
        assert os.path.exists(os.path.join(CONFIG, "screens", f)), f


@pytest.mark.parametrize("fname", sorted(REFERENCED))
def test_attitude_screen_carries_cas(fname):
    prefs = _preferences()
    types = _types(fname, prefs)
    if not types & ATTITUDE:
        pytest.skip("no attitude instrument")
    assert types & CAS, (
        f"{fname} has an attitude display and no cas_window or cas_marker")


@pytest.mark.parametrize("fname", ALTERNATIVES)
def test_alternative_carries_cas_when_its_stock_file_does(fname):
    prefs = _preferences()
    stock = REFERENCED[fname]
    if not _types(stock, prefs) & CAS:
        pytest.skip(f"{stock} carries no CAS surface either")
    assert _types(fname, prefs) & CAS, (
        f"{fname} replaces {stock}, which carries a CAS surface; it has none")


def _overlaps(a, b):
    return (a["x"] < b["x"] + b["w"] and b["x"] < a["x"] + a["w"]
            and a["y"] < b["y"] + b["h"] and b["y"] < a["y"] + a["h"])


def _covered(fname, prefs):
    """(type, dbkey) of every instrument a marker on this file overlaps,
    other than the attitude display stack it sits on."""
    out = set()
    for layout, insts in _screens(fname, prefs).values():
        w, h = resolver.canvas_size(layout, 1000)
        placed = resolver.place(layout, insts, w, h)
        for m in (p for p in placed if p["type"] == "cas_marker"):
            out |= {(p["type"], (p.get("options") or {}).get("dbkey"))
                    for p in placed
                    if p is not m and p["type"] not in BACKDROP
                    and _overlaps(m["rect"], p["rect"])}
    return out


@pytest.mark.parametrize("fname", ALTERNATIVES)
def test_alternative_marker_covers_nothing_the_stock_marker_does_not(fname):
    # The stock placement is the project owner's (AER-6346); an alternative
    # layout may not put its marker over anything more. This sees grid
    # geometry only: what an instrument draws inside its own box (the HSI's
    # heading box) is checked on the renders in the PR.
    prefs = _preferences()
    extra = _covered(fname, prefs) - _covered(REFERENCED[fname], prefs)
    assert not extra, f"{fname}: marker covers {sorted(extra)}"
