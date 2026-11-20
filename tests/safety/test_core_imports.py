#  SPDX-License-Identifier: GPL-2.0-or-later
"""Rule R1, the static import check on the primary-flight core, as a ratchet.

The core is named by path prefix in docs/safety/core_modules.yaml. tools/core_imports.py
walks every import in every core module, including imports inside functions, and fails
on one that leaves the core, the standard library and the listed third-party packages,
unless the ratchet allowlists it. It also fails on an allowlisted crossing that no
longer occurs, so the allowlist only shrinks.

The planted-violation tests run the same check over a copy of the source with one
crossing added, and show it failing; the copy without the plant passes. No Qt."""

import pathlib

import pytest

from tests.safety import core_rules

ci = core_rules.core_imports
ROOT = core_rules.ROOT


@pytest.fixture(scope="module")
def doc():
    return core_rules.load()


@pytest.fixture
def copy(tmp_path):
    """A copy of src/pyefis to plant violations in; the check runs with root=tmp_path."""
    core_rules.stage_source(tmp_path)
    return tmp_path


def _append(root, relpath, text):
    p = pathlib.Path(root, relpath)
    p.write_text(p.read_text(encoding="utf-8") + "\n" + text + "\n", encoding="utf-8")


# ---------------------------------------------------------------- the list itself

def test_every_core_path_exists(doc):
    for prefix in ci.core_paths(doc):
        p = ROOT / prefix
        assert (p.is_dir() if prefix.endswith("/") else p.is_file()), prefix


def test_the_two_named_groups_exist(doc):
    assert set(doc["groups"]) == {"primary-flight", "powerplant"}


def test_every_ratchet_entry_names_an_edge_and_the_row_that_removes_it(doc):
    for section in ("imports", "runtime", "writes"):
        for entry in doc["ratchet"][section] or []:
            assert entry["edge"] in {"E1", "E2", "E3", "E4"}, entry
            assert entry["removed_by"] in {"CERT12b", "CERT12c"}, entry


def test_membership_is_by_prefix_so_a_new_file_in_a_core_package_is_core(doc):
    assert ci.core_group("src/pyefis/instruments/hsi/new_module.py", doc) == "primary-flight"
    assert ci.core_group("src/pyefis/instruments/gauges/new_gauge.py", doc) == "powerplant"
    assert ci.core_group("src/pyefis/instruments/ai/svs.py", doc) is None
    assert ci.core_group("src/pyefis/instruments/map/__init__.py", doc) is None


# ---------------------------------------------------------------- the ratchet holds

def test_the_core_imports_nothing_outside_rule_r1_but_the_allowlist(doc):
    new, stale = ci.check(doc)
    assert not new, "core imports outside R1: %s" % [
        "%s:%d %s" % (c["from"], c["line"], c["imports"]) for c in new]
    assert not stale, "allowlisted imports that no longer occur: %s" % stale


def test_the_allowlist_is_exactly_the_brief_edges_today(doc):
    """E1 to E3 from the attitude widget, E4 from the composition root, nothing else."""
    found = {(c["from"], c["imports"]) for c in ci.crossings(doc)}
    assert {m for f, m in found if f.endswith("ai_widget.py")} == {
        "pyefis.instruments.ai.svs", "pyefis.instruments.ai.camera", "pyefis.instruments.ai.pose"}
    assert {f for f, m in found if not f.endswith("ai_widget.py")} == {
        "src/pyefis/screens/screenbuilder_factory.py", "src/pyefis/screens/screenbuilder.py"}


# ---------------------------------------------------------------- planted violations

def test_a_planted_import_inside_a_function_fails_and_passes_once_removed(doc, copy):
    assert ci.check(doc, copy) == ([], []), "the unplanted copy must pass"
    _append(copy, "src/pyefis/instruments/vsi/__init__.py",
            "def _planted():\n    from pyefis.instruments import map  # noqa: F401")
    new, stale = ci.check(doc, copy)
    assert [(c["from"], c["imports"], c["in_function"]) for c in new] == [
        ("src/pyefis/instruments/vsi/__init__.py", "pyefis.instruments.map", True)]
    assert ci.main(["check", "--root", str(copy)]) == 1


def test_a_planted_third_party_import_fails(doc, copy):
    _append(copy, "src/pyefis/instruments/gauges/arc.py", "import numpy  # noqa: F401")
    new, _ = ci.check(doc, copy)
    assert [(c["from"], c["imports"], c["kind"]) for c in new] == [
        ("src/pyefis/instruments/gauges/arc.py", "numpy", "third-party")]


def test_a_planted_relative_import_into_the_svs_fails(doc, copy):
    p = pathlib.Path(copy, "src/pyefis/instruments/ai/ai_widget.py")
    p.write_text(p.read_text(encoding="utf-8").replace(
        "import math\n", "import math\nfrom . import svs_gl  # noqa: F401\n", 1), encoding="utf-8")
    new, _ = ci.check(doc, copy)
    assert [c["imports"] for c in new] == ["pyefis.instruments.ai.svs_gl"]


def test_a_new_core_file_is_checked_without_being_listed(doc, copy):
    pathlib.Path(copy, "src/pyefis/instruments/hsi/extra.py").write_text(
        "import pyefis.flightplan.plates  # noqa: F401\n", encoding="utf-8")
    new, _ = ci.check(doc, copy)
    assert [(c["from"], c["imports"]) for c in new] == [
        ("src/pyefis/instruments/hsi/extra.py", "pyefis.flightplan.plates")]


def test_an_allowlisted_import_that_is_gone_fails_until_its_entry_is_deleted(doc, copy):
    p = pathlib.Path(copy, "src/pyefis/instruments/ai/ai_widget.py")
    text = p.read_text(encoding="utf-8")
    line = "from pyefis.instruments.ai.pose import PoseSource\n"
    assert line in text
    p.write_text(text.replace(line, ""), encoding="utf-8")
    new, stale = ci.check(doc, copy)
    assert stale == [("src/pyefis/instruments/ai/ai_widget.py", "pyefis.instruments.ai.pose")]
    assert ci.main(["check", "--root", str(copy)]) == 1
