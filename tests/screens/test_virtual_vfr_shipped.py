"""VVFR1 (AER-5417): the legacy CIFP Virtual VFR overlay is gone, but the
``virtual_vfr`` instrument type stays -- shipped screens and user configs name
it. Every shipped screen that places a ``virtual_vfr`` must still load and
build it, as the attitude widget with synthetic vision and no CIFP path.

Each shipped screen file is loaded the way pyefis.main loads config (shipped
preferences, ``cfg.from_yaml``), its instruments are expanded through the real
include machinery, and only the ``virtual_vfr`` entries are built: the rest of
a screen needs FIX keys the test database does not define.
"""
import glob
import os

import pytest
import yaml
from PyQt6.QtWidgets import QWidget

import pyefis
import pyefis.cfg as cfg
from pyefis.instruments import ai
from pyefis.main import merge_dict
from pyefis.screens.screenbuilder import Screen
from pyefis.screens.screenbuilder_config import InstrumentExpander

CONFIG = os.path.join(os.path.dirname(pyefis.__file__), "config")


def _preferences():
    with open(os.path.join(CONFIG, "preferences.yaml")) as f:
        prefs = yaml.safe_load(f)
    custom = os.path.join(CONFIG, "preferences.yaml.custom")
    if os.path.exists(custom):
        with open(custom) as f:
            merge_dict(prefs, yaml.safe_load(f) or {})
    return prefs


class _Parent(QWidget):
    def __init__(self, screen_config, preferences):
        super().__init__()
        self._screen_config = screen_config
        self.config_path = CONFIG
        self.nodeID = 1
        self.preferences = preferences

    def get_config_item(self, child, key):
        return self._screen_config.get(key)

    def getRunningScreen(self):
        return "TEST"


def _virtual_vfr_entries(screen_config, preferences):
    """The expanded ``virtual_vfr`` instrument configs of one screen, through
    the same expander Screen.load_instrument uses (no widget needed, so this
    also runs at collection time)."""
    sizes = InstrumentExpander(CONFIG, preferences, 1, None)
    expander = InstrumentExpander(CONFIG, preferences, 1, sizes.calc_includes)
    found = []
    for inst in screen_config.get("instruments") or []:
        for expanded, _repl, _state in expander.expand(inst):
            if expanded.get("type") == "virtual_vfr":
                found.append(expanded)
    return found


def _shipped_virtual_vfr_screens():
    """(file, screen name) for every shipped screen that places a virtual_vfr
    -- directly or through an instrument include."""
    out = []
    prefs = _preferences()
    for path in sorted(glob.glob(os.path.join(CONFIG, "screens", "*.yaml"))):
        loaded = cfg.from_yaml(path, bpath=CONFIG, preferences=prefs)
        for name, sc in (loaded or {}).items():
            if not isinstance(sc, dict) or "instruments" not in sc:
                continue
            if _virtual_vfr_entries(sc, prefs):
                out.append((os.path.basename(path), name))
    return out


def _build(fname, name, svs_override=None):
    prefs = _preferences()
    sc = cfg.from_yaml(os.path.join(CONFIG, "screens", fname), bpath=CONFIG,
                       preferences=prefs)[name]
    screen = Screen(_Parent(sc, prefs))
    # The state init_screen sets up before it builds anything.
    screen.layout = sc["layout"]
    screen.instruments = {}
    screen.instrument_config = {}
    widgets = []
    for n, inst in enumerate(_virtual_vfr_entries(sc, prefs)):
        if svs_override is not None:
            inst = dict(inst)
            inst["options"] = dict(inst.get("options") or {}, **svs_override)
        screen.setup_instruments(n, inst)
        widgets.append(screen.instruments[n])
    return screen, widgets


def test_the_shipped_screens_were_found(qapp):
    # The sweep below is only evidence if it saw the screens it is about:
    # PFD, EMS and RADIO in three layouts each, plus PFD_AI_ONLY.
    files = {f for f, _ in _shipped_virtual_vfr_screens()}
    assert {"pfd.yaml", "ems.yaml", "radio.yaml", "pfd_ai_only.yaml"} <= files
    assert len(files) >= 10, sorted(files)


def test_no_shipped_screen_includes_the_cifp_paths(qapp):
    """The CIFP path file is no longer included by any shipped screen; it
    stays only as an empty stub for older configs that still list it."""
    prefs = _preferences()
    for path in glob.glob(os.path.join(CONFIG, "screens", "*.yaml")):
        with open(path) as f:
            raw = yaml.safe_load(f) or {}
        for sc in raw.values():
            if isinstance(sc, dict):
                assert "screens/virtualvfr_db.yaml" not in (sc.get("include") or [])
    stub = cfg.from_yaml(os.path.join(CONFIG, "screens", "virtualvfr_db.yaml"),
                         bpath=CONFIG, preferences=prefs)
    assert not stub, "virtualvfr_db.yaml must stay an empty stub"


@pytest.mark.parametrize("fname,name", _shipped_virtual_vfr_screens())
def test_shipped_virtual_vfr_builds_without_the_legacy_overlay(
    fname, name, fix, qtbot
):
    screen, widgets = _build(fname, name)
    qtbot.addWidget(screen)
    assert widgets
    for w in widgets:
        assert type(w) is ai.AI
        for legacy in ("pov", "render_runway", "display_objects"):
            assert not hasattr(w, legacy), legacy


@pytest.mark.parametrize("fname,name", _shipped_virtual_vfr_screens())
def test_shipped_virtual_vfr_renders_svs_when_enabled(fname, name, fix, qtbot,
                                                       tmp_path):
    # svs_enabled is what the configurator injects on a provisioned device;
    # the shipped files leave it off so a fresh install needs no terrain data.
    tiles = tmp_path / "tiles"
    tiles.mkdir()
    screen, widgets = _build(fname, name, {"svs_enabled": True,
                                           "svs_tile_path": str(tiles)})
    qtbot.addWidget(screen)
    for w in widgets:
        svs = w._live_svs()
        assert svs is not None and svs.enabled


def test_a_config_that_still_lists_the_cifp_stub_loads(qapp, tmp_path):
    """An older user screen keeps ``include: screens/virtualvfr_db.yaml``; it
    must load, and the retired keys must not come back."""
    screen = tmp_path / "old.yaml"
    screen.write_text(yaml.safe_dump({"PFD": {
        "include": ["screens/virtualvfr_db.yaml"],
        "module": "pyefis.screens.screenbuilder",
        "instruments": [{"type": "virtual_vfr", "row": 0, "column": 0}],
    }}))
    loaded = cfg.from_yaml(str(screen), bpath=CONFIG, preferences=_preferences())
    pfd = loaded["PFD"]
    assert pfd["instruments"][0]["type"] == "virtual_vfr"
    for key in ("dbpath", "indexpath", "metadata"):
        assert key not in pfd
