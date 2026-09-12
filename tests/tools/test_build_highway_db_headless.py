#  SPDX-License-Identifier: GPL-2.0-or-later
"""Headless-import regression for AER-1090.

``ai/__init__.py`` used to do ``from PyQt6.QtGui import *`` (etc.) at module
level to define the ``AI`` widget. Importing any submodule of a package always
executes that package's ``__init__.py`` first, so a pure-data sibling module
like ``highway_db.py`` or ``water_db.py`` transitively required the entire
PyQt6 GUI stack just to reach a couple of constants and a function -- fatal
for makerplane-data's headless ``packtool build-roads`` CI job, which installs
``pyshp numpy`` only, no PyQt6 (AER-623).

Each check below runs in a fresh subprocess with PyQt6 blocked via a
``sys.meta_path`` finder, rather than poking at ``sys.modules`` in-process --
this test session may have already imported the real PyQt6-backed ``ai``
package via another test module, and an in-process cache-clear is easy to get
wrong in a way that silently stops testing anything.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]

_BLOCK_PYQT6 = """\
import sys, importlib.abc

class _BlockPyQt6(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path, target=None):
        if name == "PyQt6" or name.startswith("PyQt6."):
            raise ModuleNotFoundError(name)
        return None

sys.meta_path.insert(0, _BlockPyQt6())
"""


def _run_headless(body):
    """Run ``body`` in a subprocess that cannot import PyQt6, and return
    stdout. Fails the test with the subprocess's traceback on a nonzero exit."""
    env = dict(os.environ, PYTHONPATH=str(_ROOT / "src"))
    result = subprocess.run(
        [sys.executable, "-c", _BLOCK_PYQT6 + "\n" + body],
        cwd=str(_ROOT), env=env, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, (
        f"headless import failed (exit {result.returncode}):\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
    return result.stdout


def test_highway_db_importable_without_pyqt6():
    out = _run_headless(
        "from pyefis.instruments.ai.highway_db import (\n"
        "    FLAG_BRIDGE, FLAG_TUNNEL, encode_vertices)\n"
        "assert 'PyQt6' not in sys.modules\n"
        "print('ok', FLAG_BRIDGE, FLAG_TUNNEL, encode_vertices)\n"
    )
    assert "ok" in out


def test_water_db_importable_without_pyqt6():
    out = _run_headless(
        "from pyefis.instruments.ai.water_db import encode_vertices\n"
        "assert 'PyQt6' not in sys.modules\n"
        "print('ok', encode_vertices)\n"
    )
    assert "ok" in out


def test_build_highway_db_tool_importable_without_pyqt6():
    """End-to-end: load the actual CLI tool the makerplane-data CI job runs
    (``packtool build-roads`` -> ``tools/build_highway_db.py``), the same way
    ``tests/tools/test_build_highway_db.py`` loads it for its own tests."""
    tool_path = _ROOT / "tools" / "build_highway_db.py"
    out = _run_headless(
        "import importlib.util\n"
        f"spec = importlib.util.spec_from_file_location(\n"
        f"    'build_highway_db', {str(tool_path)!r})\n"
        "mod = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(mod)\n"
        "assert 'PyQt6' not in sys.modules\n"
        "print('ok', mod.encode_vertices)\n"
    )
    assert "ok" in out


def test_ai_widget_still_resolves_lazily():
    """The thin ``__init__.py`` re-exports ``AI``/``FDTarget`` lazily (PEP
    562) so existing GUI callers (``screenbuilder_factory.py``,
    ``VirtualVfr.py``, ``tests/instruments/ai/test_ai.py``) keep working
    unchanged. Skips if the local PyQt6/GL stack can't load at all -- that is
    an environment gap, not this regression."""
    try:
        from pyefis.instruments import ai
        widget_cls, target_cls = ai.AI, ai.FDTarget
    except ImportError as exc:
        pytest.skip(f"PyQt6 GUI stack unavailable here: {exc}")
    assert widget_cls.__module__ == "pyefis.instruments.ai.ai_widget"
    assert target_cls.__module__ == "pyefis.instruments.ai.ai_widget"


def test_unknown_attribute_still_raises_attributeerror():
    try:
        from pyefis.instruments import ai
    except ImportError as exc:
        pytest.skip(f"PyQt6 GUI stack unavailable here: {exc}")

    with pytest.raises(AttributeError):
        ai.NotARealAttribute
