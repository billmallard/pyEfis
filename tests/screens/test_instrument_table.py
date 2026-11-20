"""CERT12c (brief U3, U4): instrument classes resolve by name, on first use,
from one table, and every import by name in pyEfis goes through it.

The runtime check boots a real screen in a fresh interpreter, because the
test session has long since imported every instrument: a ``sys.modules``
read in-process would prove nothing.
"""
import ast
import inspect
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import pyefis
from pyefis.screens import instrument_table, screenbuilder_factory
from pyefis.screens.instrument_table import INSTRUMENTS, instrument

SRC = Path(pyefis.__file__).resolve().parent
REPO = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("name", sorted(INSTRUMENTS))
def test_every_table_entry_resolves_to_the_class_its_package_defines(name):
    import importlib
    cls = instrument(name)
    assert inspect.isclass(cls)
    assert cls.__name__ == name
    assert cls is getattr(importlib.import_module(INSTRUMENTS[name]), name)


def test_unknown_name_is_a_key_error():
    with pytest.raises(KeyError):
        instrument("NoSuchInstrument")


def test_table_names_modules_only_as_strings():
    """R2b: the table may name a non-core module, but only as a string. A
    real import here would load every instrument for any screen again."""
    tree = ast.parse(Path(instrument_table.__file__).read_text())
    imported = {a.name for n in ast.walk(tree)
                if isinstance(n, (ast.Import, ast.ImportFrom))
                for a in n.names}
    assert imported == {"importlib", "logging"}


def _factory_import_targets():
    tree = ast.parse(Path(screenbuilder_factory.__file__).read_text())
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            out.update(f"{node.module}.{a.name}" for a in node.names)
    return out


def test_factory_imports_no_instrument_package():
    """E4 is gone: the factory names instruments through the table. The one
    instrument import left is a constant from the autopilot, which is core."""
    instrument_imports = {t for t in _factory_import_targets()
                          if t.startswith("pyefis.instruments")}
    assert instrument_imports == {"pyefis.instruments.autopilot.DEFAULT_BUTTONS"}


def _dynamic_import_sites():
    """(file, line) of every import by name in src/pyefis: a call to
    ``import_module`` or ``__import__``, or an ``import_module`` import."""
    sites = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
        for node in ast.walk(tree):
            hit = False
            if isinstance(node, ast.Call):
                f = node.func
                name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
                hit = name in ("import_module", "__import__")
            elif isinstance(node, ast.ImportFrom) and node.module == "importlib":
                hit = any(a.name == "import_module" for a in node.names)
            if hit:
                sites.append((path.relative_to(SRC).as_posix(), node.lineno))
    return sites


def test_every_dynamic_import_goes_through_the_table():
    """E5: the screen module, user hooks, the FMS bridge and the system
    menu's class lookup used to call importlib where they stood. Now only
    the table does, so a reviewer reads one file to see what a config can
    load."""
    outside = [s for s in _dynamic_import_sites()
               if s[0] != "screens/instrument_table.py"]
    assert outside == []


def test_dynamic_import_scan_sees_a_planted_site(tmp_path, monkeypatch):
    """The scan above must find a site, or its empty result means nothing."""
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "a.py").write_text("import importlib\nimportlib.import_module('x')\n")
    (pkg / "b.py").write_text("from importlib import import_module\n")
    (pkg / "c.py").write_text("__import__('y')\n")
    monkeypatch.setattr(sys.modules[__name__], "SRC", pkg)
    assert _dynamic_import_sites() == [("a.py", 2), ("b.py", 1), ("c.py", 1)]


# --- Runtime check: boot a real screen in a fresh interpreter ---------------

_PROBE = r"""
import json, os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PyQt6.QtWidgets import QApplication, QWidget
app = QApplication([])
# The in-memory FIX client and scheduler, as conftest.py installs them.
import tests.mock_db.client, tests.mock_db.scheduler
sys.modules["pyavtools.fix.client"] = tests.mock_db.client
sys.modules["pyavtools.scheduler"] = tests.mock_db.scheduler
import pyavtools.fix as fix
fix.initialize({"main": {"FixServer": "localhost", "FixPort": "3490"}})
db = fix.db
orig = db.get_item
def get_item(key, *args, **kwargs):
    # Define any key a widget asks for, the render_instrument.py way, so the
    # screen builds without a gateway.
    try:
        return orig(key, *args, **kwargs)
    except Exception:
        db.define_item(key, key, "float", 0, 100, "", 50000, "")
        item = orig(key, *args, **kwargs)
        item.bad = item.fail = item.old = False
        return item
db.get_item = get_item
# The airspeed tape reads V-speed aux values off IAS.
db.define_item("IAS", "IAS", "float", 0.0, 2000.0, "knots", 50000,
               "Min,Max,V1,V2,Vne,Vfe,Vmc,Va,Vno,Vs,Vs0,Vx,Vy")
import pyefis.hmi as hmi
hmi.initialize({})
from pyefis.screens.screenbuilder import Screen

class Parent(QWidget):
    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.config_path = ""
        self.nodeID = 1
        self.preferences = {"style": {}, "styles": {}, "gauges": {},
                            "enabled": {}, "includes": {}, "buttons": {}}
    def get_config_item(self, child, key):
        return self.cfg.get(key)
    def getRunningScreen(self):
        return "TEST"

types = json.loads(sys.argv[1])
cfg = {"layout": {"rows": 10, "columns": 10}, "encoder": None,
       "encoder_button": None, "encoder_timeout": None,
       "instruments": [{"type": t, "row": 0, "column": i,
                        "span": {"rows": 5, "columns": 1}}
                       for i, t in enumerate(types)]}
screen = Screen(Parent(cfg))
screen.resize(800, 480)
screen.init_screen()
print(json.dumps({"built": len(screen.instruments),
                  "modules": sorted(m for m in sys.modules
                                    if m.startswith("pyefis"))}))
"""

# The map and everything that only the map, flight plan and plates bring in.
MAP_MODULES = ("pyefis.instruments.map", "pyefis.instruments.flight_plan",
               "pyefis.flightplan")

# A PFD's instruments: attitude, airspeed, altitude, VSI, heading, turn.
PFD = ["atitude_indicator", "airspeed_tape", "altimeter_tape", "vsi_pfd",
       "horizontal_situation_indicator", "turn_coordinator"]


def _boot(types):
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(SRC.parent), str(REPO)]
        + [p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p])
    out = subprocess.run([sys.executable, "-c", _PROBE, json.dumps(types)],
                         capture_output=True, text=True, env=env, timeout=120,
                         cwd=REPO)
    assert out.returncode == 0, out.stderr[-3000:]
    result = json.loads(out.stdout.strip().splitlines()[-1])
    assert result["built"] == len(types), result
    return set(result["modules"])


def _map_loaded(modules):
    return sorted(m for m in modules
                  if any(m == p or m.startswith(p + ".") for p in MAP_MODULES))


def test_a_screen_without_a_map_loads_no_map_module():
    assert _map_loaded(_boot(PFD)) == []


def test_a_screen_with_a_map_loads_it():
    """The control: the probe sees the map when a screen places one, so the
    empty result above is the factory's doing, not a blind probe."""
    loaded = _map_loaded(_boot(PFD + ["moving_map"]))
    assert "pyefis.instruments.map" in loaded
