#  SPDX-License-Identifier: GPL-2.0-or-later
"""Rule R4, the runtime import check: a core-only screen boots with no non-core module
in sys.modules, as a ratchet.

tests/safety/boot_probe.py boots pyefis.main.main() in a child process, against the fake
FIX database, with tests/safety/data/core_only/default.yaml (attitude without synthetic
vision, the tapes, the VSI, turn and slip, the HSI, an engine gauge and a button). It
reports sys.modules once the screens are built and shown. Every non-core pyefis module
in it, and NumPy, SQLite or the GL bindings, must be allowlisted under ratchet: runtime
in docs/safety/core_modules.yaml with its edge and row; an allowlisted one that no
longer loads fails too.

This sees what the static check cannot: an import made by name at run time (the brief's
E5). The planted test shows one: a core module importing an SVS module from a computed
string, which the static check passes and this check fails."""

import pytest

from tests.safety import core_rules


@pytest.fixture(scope="module")
def doc():
    return core_rules.load()


@pytest.fixture(scope="module")
def boot(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("core_boot")
    cfg = core_rules.stage_config(tmp / "config", core_rules.CORE_ONLY)
    return core_rules.run_probe(cfg, tmp / "boot.json")


def test_the_core_only_screen_was_built(boot):
    built = set(boot["screens"]["PFD"])
    for cls in ("pyefis.instruments.ai.ai_widget.AI",
                "pyefis.instruments.airspeed.Airspeed_Tape",
                "pyefis.instruments.altimeter.Altimeter_Tape",
                "pyefis.instruments.vsi.VSI_PFD",
                "pyefis.instruments.tc.TurnCoordinator",
                "pyefis.instruments.hsi.HSI",
                "pyefis.instruments.gauges.arc.ArcGauge",
                "pyefis.instruments.button.Button"):
        assert cls in built, "%s not built; the screen built %s" % (cls, sorted(built))


def test_the_core_only_boot_loads_nothing_non_core_but_the_allowlist(doc, boot):
    new, stale = core_rules.runtime_check(doc, boot["modules"])
    assert not new, "non-core modules in a core-only boot, not allowlisted: %s" % new
    assert not stale, ("allowlisted modules that no longer load; delete them from ratchet: "
                       "runtime: %s" % stale)


def test_the_runtime_allowlist_is_empty(doc):
    """CERT12c removed E4 and CERT12b removed E1 to E3: a core-only boot
    loads no non-core module, numpy or sqlite3 at all."""
    assert core_rules.runtime_allowlist(doc) == {}


def test_a_planted_import_by_name_fails_the_runtime_check_but_not_the_static_one(doc, tmp_path):
    src = core_rules.stage_source(tmp_path)
    core_rules.plant(src, "src/pyefis/instruments/hsi/__init__.py",
                     "import importlib as _planted\n"
                     "_planted.import_module('pyefis.instruments.ai.' + 'svs_gl')")
    assert core_rules.core_imports.check(doc, tmp_path) == ([], []), \
        "the static check cannot see an import by a computed name"
    cfg = core_rules.stage_config(tmp_path / "config", core_rules.CORE_ONLY)
    result = core_rules.run_probe(cfg, tmp_path / "planted.json", src=src)
    new, stale = core_rules.runtime_check(doc, result["modules"])
    assert "pyefis.instruments.ai.svs_gl" in new
    assert not stale
