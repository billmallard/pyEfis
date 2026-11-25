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

FPA7 (AER-6545) pins the shared vocabulary the same way: the ``FPLfTYPE``
numbers, ``FPLfFLAGS`` bits, segment kinds, path-terminator sets and packed
``FPLfALT`` grammar in ``pyefis/flightplan/vocab.py`` against the engine's
``TYPE_*``, ``FLAG_*``, ``SEGKIND_*``, ``PT_*`` and ``_parse_alt_constraint``.
"""

import ast
import os
import pathlib

import pytest

from pyefis.flightplan import vocab

_SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "pyefis"
_FLIGHT_PLAN = _SRC / "instruments" / "flight_plan" / "__init__.py"
_NAV_STATUS = _SRC / "instruments" / "nav_status" / "__init__.py"
_MAP_LAYER = _SRC / "instruments" / "map" / "layers" / "flight_plan.py"
_LEG_PATHS = _SRC / "flightplan" / "leg_paths.py"
_FIXBRIDGE = _SRC / "flightplan" / "fixbridge.py"


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


def string_sets(source):
    """Module-level ``NAME = frozenset({...})`` of string literals, and the
    ``|``/``-`` of such names, as {name: set}. Anything else is skipped."""
    out = {}

    def value(node):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "frozenset" and len(node.args) == 1
                and isinstance(node.args[0], ast.Set)
                and all(isinstance(e, ast.Constant) and isinstance(e.value, str)
                        for e in node.args[0].elts)):
            return {e.value for e in node.args[0].elts}
        if isinstance(node, ast.Name):
            return out.get(node.id)
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.BitOr, ast.Sub)):
            a, b = value(node.left), value(node.right)
            if a is None or b is None:
                return None
            return a | b if isinstance(node.op, ast.BitOr) else a - b
        return None

    for node in ast.parse(source).body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)):
            v = value(node.value)
            if v is not None:
                out[node.targets[0].id] = v
    return out


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


def test_fixbridge_carries_back_every_course_the_engine_flies(engine):
    """FPA1: ``route_to_plan`` keeps a slot's ``FPLfCRS`` only for
    ``vocab.CODED_COURSE_PTS``; for any other leg the next publish replaces it
    with the great-circle bearing. The engine flies a coded course or
    heading on every leg it loads except the IF/TF/DF great circles and the
    RF/AF arcs (``_leg_path_key``), and keys the leg's identity on it, so a
    coded leg missing here turns on the map and drops its activation after
    an unrelated edit. FM was the one missing."""
    sets = string_sets(engine)
    assert "FM" in sets["PT_VECTOR"] and "CF" in sets["PT_TIER1"]
    derived = (sets["PT_TIER1"] - {"CF"}) | sets["PT_ARC"]
    assert derived == {"IF", "TF", "DF", "RF", "AF"}
    supported = sets["PT_SUPPORTED"]
    coded = vocab.CODED_COURSE_PTS
    assert (supported - derived) - coded == set(), (
        "the engine flies these path terminators on their coded course and the "
        "editor drops it on read-back: add them to vocab.CODED_COURSE_PTS")
    assert coded & derived == set(), (
        "these legs' FPLfCRS is a derived bearing, not a coded course")


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
    sets = string_sets('A = frozenset({"X", "Y"})\nB = frozenset({"Z"})\n'
                       'C = A | B\nD = C - frozenset({"Y"})\nE = make()\n')
    assert sets == {"A": {"X", "Y"}, "B": {"Z"}, "C": {"X", "Y", "Z"}, "D": {"X", "Z"}}


# --- FPA7: the vocabulary (pyefis/flightplan/vocab.py) against the engine's -----

def test_vocab_type_numbers_are_the_engines(engine):
    """``FPLfTYPE``: every ``TYPE_*`` the engine declares, by name and value,
    and nothing the engine does not."""
    theirs = {k: v for k, v in module_constants(engine).items() if k.startswith("TYPE_")}
    ours = {k: v for k, v in vars(vocab).items() if k.startswith("TYPE_") and isinstance(v, int)}
    assert {"TYPE_UNKNOWN", "TYPE_MAPPOINT"} <= set(theirs)
    assert ours == theirs
    assert sorted(vocab.TYPE_TO_FPLTYPE.values()) == sorted(theirs.values())


def test_vocab_flag_bits_are_the_engines(engine):
    theirs = {k: v for k, v in module_constants(engine).items() if k.startswith("FLAG_")}
    ours = {k: v for k, v in vars(vocab).items() if k.startswith("FLAG_")}
    assert {"FLAG_FLYOVER", "FLAG_FROM_PROCEDURE"} <= set(theirs)
    assert ours == theirs
    roles = {k for k in theirs if k not in ("FLAG_FLYOVER", "FLAG_FROM_PROCEDURE")}
    assert vocab.ROLE_BITS == sum(theirs[k] for k in roles)
    assert {r: b for r, b in vocab.ROLE_TO_FLAG.items() if b} == {
        k.removeprefix("FLAG_").lower(): theirs[k] for k in roles}


def test_vocab_segment_kinds_are_the_engines(engine):
    theirs = {k: v for k, v in module_constants(engine).items() if k.startswith("SEGKIND_")}
    assert len(theirs) >= 6
    assert {f"SEGKIND_{kind.upper()}": n for n, kind in enumerate(vocab.SEGMENT_KINDS)} == theirs


def test_vocab_path_terminator_sets_are_the_engines(engine):
    sets = string_sets(engine)
    assert vocab.HOLD_PTS == sets["PT_HOLD"]
    assert vocab.ARC_PTS == sets["PT_ARC"]
    assert vocab.ALT_TERM_PTS == sets["PT_ALT_TERM"]
    assert vocab.VECTOR_PTS == sets["PT_VECTOR"]
    assert vocab.HEADING_PTS < sets["PT_VECTOR"]
    # Legs that end at no fix: the headings and the climb to an altitude.
    assert vocab.NO_FIX_PTS <= sets["PT_SUPPORTED"]
    assert vocab.NO_FIX_PTS - vocab.HEADING_PTS <= sets["PT_ALT_TERM"]


def _engine_function(source, name):
    """The engine's module-level function *name*, compiled on its own: it
    must need nothing but builtins."""
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            namespace = {}
            exec(compile(ast.Module(body=[node], type_ignores=[]), name, "exec"), namespace)
            return node, namespace[name]
    raise AssertionError(f"the engine has no function {name}")


def test_vocab_packed_altitude_is_the_engines_grammar(engine):
    """``FPLfALT``: the engine evaluates every prefix ``vocab.pack_alt``
    writes, as the constraint it means, and knows no prefix we do not."""
    node, parse = _engine_function(engine, "_parse_alt_constraint")
    prefixes = {c.comparators[0].value for c in ast.walk(node)
                if isinstance(c, ast.Compare) and isinstance(c.left, ast.Name)
                and isinstance(c.comparators[0], ast.Constant)
                and isinstance(c.comparators[0].value, str) and len(c.comparators[0].value) == 1}
    assert prefixes == set(vocab.ALT_PREFIXES)
    assert parse(vocab.pack_alt(vocab.ALT_AT_OR_ABOVE, 3500)) == (3500.0, True)
    assert parse(vocab.pack_alt(vocab.ALT_AT_OR_BELOW, 5000)) == (5000.0, False)
    assert parse(vocab.pack_alt(vocab.ALT_AT, 1800)) == (1800.0, True)
    # A window terminates at its floor, which pack_alt writes first.
    assert parse(vocab.pack_alt(vocab.ALT_BETWEEN, 4000, 2900)) == (2900.0, True)
    assert parse("") is None


def test_the_vocab_readers_catch_a_disagreement():
    """The pins above read what they claim to: an engine that renumbers a
    type, drops a hold PT or learns a new altitude prefix differs."""
    source = (
        "TYPE_UNKNOWN = 0\nTYPE_MAPPOINT = 7\n"
        "PT_HOLD = frozenset({'HM', 'HF'})\n"
        "def _parse_alt_constraint(alt_desc):\n"
        "    sign = alt_desc[0]\n"
        "    if sign == 'A':\n"
        "        return 0.0, True\n"
        "    return None\n")
    assert module_constants(source)["TYPE_MAPPOINT"] != vocab.TYPE_MAPPOINT
    assert string_sets(source)["PT_HOLD"] != vocab.HOLD_PTS
    node, parse = _engine_function(source, "_parse_alt_constraint")
    assert parse("A1") == (0.0, True)
    with pytest.raises(AssertionError):
        test_vocab_packed_altitude_is_the_engines_grammar(source)
