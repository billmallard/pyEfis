#  SPDX-License-Identifier: GPL-2.0-or-later
"""Every value the flightplan engine can publish on an enum key has an entry
in each display table that renders it (AER-6293).

The engine declares the values of ``FPLSTATE`` (``STATE_*``), ``FPLAPR``
(``APR_*``) and ``FPLHOLDENT`` (``HOLD_ENTRY_*``) as module constants in
fix-gateway's ``engine.py``. pyEfis turns each into words or colour through a
table, and a value missing from a table draws nothing, or worse: the
nav_status chip's badge colour was indexed directly, so ``FPLSTATE`` 4 (OBS)
raised in ``paintEvent``.

Both sides are read as source, with ``ast``: the tables live in Qt widget
modules, and fix-gateway's CI runs this file from a sparse pyEfis checkout
with no Qt imports, the way it runs ``test_refusal.py`` (fix-gateway #224).
So a new engine value goes red in fix-gateway until pyEfis has its entry.
``FIXGW_FLIGHTPLAN_ENGINE`` points at the engine in CI; with it set, a missing
file is a failure, not a skip.
"""

import ast
import os
import pathlib

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "pyefis"
_FLIGHT_PLAN = _SRC / "instruments" / "flight_plan" / "__init__.py"
_NAV_STATUS = _SRC / "instruments" / "nav_status" / "__init__.py"
_MAP_LAYER = _SRC / "instruments" / "map" / "layers" / "flight_plan.py"
_LEG_PATHS = _SRC / "flightplan" / "leg_paths.py"


def _engine_path():
    """The engine source: ``FIXGW_FLIGHTPLAN_ENGINE`` (CI; required), else
    the engine in the ``FIX_GATEWAY_SRC`` checkout the conformance test uses."""
    env = os.environ.get("FIXGW_FLIGHTPLAN_ENGINE")
    if env:
        return pathlib.Path(env), True
    root = pathlib.Path(os.environ.get("FIX_GATEWAY_SRC") or "/nonexistent")
    return root / "src" / "fixgw" / "plugins" / "flightplan" / "engine.py", False


def module_constants(source):
    """``NAME = <int or str literal>`` at module level, as {name: value}."""
    out = {}
    for node in ast.parse(source).body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Constant)
                and type(node.value.value) in (int, str)):
            out[node.targets[0].id] = node.value.value
    return out


def enum_values(source, prefix, exclude=()):
    """The values of the engine's ``<prefix>*`` constants."""
    return {v for k, v in module_constants(source).items()
            if k.startswith(prefix) and k not in exclude}


def table(source, name, names=None):
    """The module-level dict literal ``name`` as {key: value}. A key or value
    that is a literal, or an attribute or name found in ``names``, is
    resolved; anything else (a ``QColor(...)``) is kept as its source text."""
    names = names or {}

    def value(node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, (ast.Name, ast.Attribute)):
            attr = node.id if isinstance(node, ast.Name) else node.attr
            if attr in names:
                return names[attr]
        return ast.unparse(node)

    for node in ast.parse(source).body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == name and isinstance(node.value, ast.Dict)):
            return {value(k): value(v) for k, v in zip(node.value.keys, node.value.values)}
    raise AssertionError(f"no module-level dict literal {name}")


@pytest.fixture(scope="module")
def engine():
    path, required = _engine_path()
    if not path.is_file():
        if required:
            pytest.fail(f"FIXGW_FLIGHTPLAN_ENGINE={path} does not exist")
        pytest.skip("set FIX_GATEWAY_SRC to a fix-gateway checkout; CI sets "
                    "FIXGW_FLIGHTPLAN_ENGINE")
    return path.read_text()


def _states(engine):
    states = enum_values(engine, "STATE_")
    # The reader still finds what it was written against: one that stopped
    # matching the engine would otherwise pass on nothing.
    assert {0, 1, 2, 3, 4} <= states
    return states


def test_every_fplstate_has_an_fpl_page_badge(engine):
    badges = table(_FLIGHT_PLAN.read_text(), "_STATE_BADGES")
    assert _states(engine) - set(badges) == set(), (
        "the engine can publish these FPLSTATE values and the FPL page has no "
        "badge for them: add them to _STATE_BADGES in instruments/flight_plan")


def test_every_active_fplstate_has_a_nav_status_badge_and_colour(engine):
    nav = _NAV_STATUS.read_text()
    none = module_constants(engine)["STATE_NONE"]
    labels = table(nav, "STATE_LABELS")
    colours = table(nav, "_BADGE_COLORS")
    assert _states(engine) - {none} - set(labels) == set(), (
        "the engine can publish these FPLSTATE values and the nav_status chip "
        "has no badge for them: add them to STATE_LABELS")
    assert set(labels.values()) - set(colours) == set(), (
        "these nav_status badges have no colour: add them to _BADGE_COLORS")


def test_every_fplapr_has_fpl_page_text(engine):
    values = enum_values(engine, "APR_")
    assert {0, 1, 2, 3} <= values
    text = table(_FLIGHT_PLAN.read_text(), "_APR_TEXT")
    assert values - set(text) == set(), (
        "the engine can publish these FPLAPR values and the FPL page has no "
        "text for them: add them to _APR_TEXT in instruments/flight_plan")


def test_every_fplholdent_has_a_map_label(engine):
    # HOLD_ENTRY_LEG_S is the entry's leg time, not an entry.
    values = enum_values(engine, "HOLD_ENTRY_", exclude=("HOLD_ENTRY_LEG_S",))
    assert {"DIRECT", "TEARDROP", "PARALLEL"} <= values
    labels = table(_MAP_LAYER.read_text(), "_ENTRY_LABELS",
                   names=module_constants(_LEG_PATHS.read_text()))
    assert values - set(labels) == set(), (
        "the engine can publish these FPLHOLDENT values and the map has no "
        "label for them: add them to _ENTRY_LABELS in map/layers/flight_plan.py")


def test_the_readers_catch_a_new_value():
    """The coverage tests above fail for the change they exist to catch: an
    engine that adds a state, an approach mode or a hold entry."""
    source = '''
STATE_NONE = 0
STATE_WIDGET = 5
APR_WIDGET = 4
HOLD_ENTRY_WIDGET = "WIDGET"
HOLD_ENTRY_LEG_S = 60.0
STATE_NAME = some_call()
'''
    assert enum_values(source, "STATE_") == {0, 5}
    assert enum_values(source, "APR_") == {4}
    assert enum_values(source, "HOLD_ENTRY_", exclude=("HOLD_ENTRY_LEG_S",)) == {"WIDGET"}
    nav = 'STATE_LABELS = {1: "LEG"}\n_BADGE_COLORS = {"LEG": QColor("#fff")}\n'
    assert set(table(nav, "_BADGE_COLORS")) == {"LEG"}
    assert {5} - set(table(nav, "STATE_LABELS")) == {5}
    labels = table('_ENTRY_LABELS = {fp_legs.HOLD_ENTRY_DIRECT: ("DIRECT", "DIR")}\n',
                   "_ENTRY_LABELS", names={"HOLD_ENTRY_DIRECT": "DIRECT"})
    assert set(labels) == {"DIRECT"}
