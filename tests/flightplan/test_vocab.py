#  SPDX-License-Identifier: GPL-2.0-or-later
"""FPA7 (AER-6545): the flight plan vocabulary is written once, in
``pyefis/flightplan/vocab.py``.

``test_no_vocabulary_is_written_outside_vocab`` scans every module under
``src/pyefis`` with ``ast`` and fails on a second copy: a literal waypoint
type map, a literal set of two or more path terminators, an ``FPLfFLAGS``
bit written as a number, a role-to-flag table or an ident normaliser. The
engine side of the same vocabulary is pinned in ``test_engine_enums.py``.
"""

import ast
import pathlib

import pytest

from pyefis.flightplan import (airways, fixbridge, hold, leg_paths, model, plates,
                               proc_load, procedures, vocab, waypoints)

_SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "pyefis"
_VOCAB = _SRC / "flightplan" / "vocab.py"

#: The ARINC 424 path terminators.
_PATH_TERMINATORS = frozenset({"IF", "TF", "CF", "DF", "FA", "FC", "FD", "FM", "CA", "CD",
                               "CI", "CR", "RF", "AF", "VA", "VD", "VI", "VM", "VR", "PI",
                               "HA", "HF", "HM"})

#: Tables that look like the vocabulary and are not it, with the reason.
_NOT_THE_VOCABULARY = {
    # The order route_string resolves a duplicated ident in, not FPLfTYPE.
    ("flightplan/route_string.py", "_TYPE_RANK"),
    # The procedures pack's own flag bits (makerplane-data), which differ
    # from FPLfFLAGS at 0x10 and 0x20; proc_load translates them.
    ("flightplan/proc_load.py", "PACK_FLYOVER"),
    ("flightplan/proc_load.py", "PACK_IAF"),
    ("flightplan/proc_load.py", "PACK_FAF"),
    ("flightplan/proc_load.py", "PACK_MAP"),
    ("flightplan/proc_load.py", "PACK_FIRST_MISSED"),
}


def _strings(node):
    """The string elements of a set, tuple, list or ``frozenset({...})``
    literal, or None."""
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "frozenset" and len(node.args) == 1):
        node = node.args[0]
    if isinstance(node, (ast.Set, ast.Tuple, ast.List)) and node.elts and all(
            isinstance(e, ast.Constant) and isinstance(e.value, str) for e in node.elts):
        return {e.value for e in node.elts}
    return None


def _dict_keys(node):
    if isinstance(node, ast.Dict) and all(isinstance(k, ast.Constant) for k in node.keys):
        return {k.value: v for k, v in zip(node.keys, node.values)}
    return None


def _is_int_expr(node):
    """An int literal, or ``|`` of them (``0x02 | 0x04``)."""
    if isinstance(node, ast.Constant):
        return type(node.value) is int
    return (isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr)
            and _is_int_expr(node.left) and _is_int_expr(node.right))


def _is_normaliser(fn):
    """``def f(x): return (x or "").strip().upper()`` (or upper then strip)."""
    body = [n for n in fn.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
    if len(body) != 1 or not isinstance(body[0], ast.Return) or body[0].value is None:
        return False
    calls = []
    node = body[0].value
    while isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and not node.args:
        calls.append(node.func.attr)
        node = node.func.value
    return sorted(calls) == ["strip", "upper"] and isinstance(node, ast.BoolOp)


def vocabulary_copies(source, rel="<test>"):
    """``[(line, what), ...]``: each place *source* writes its own copy of
    the vocabulary."""
    found = set()
    tree = ast.parse(source)
    named = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    named[id(node.value)] = t.id
    inner = {id(n.args[0]) for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "frozenset" and n.args}
    for node in ast.walk(tree):
        name = named.get(id(node))
        if (rel, name) in _NOT_THE_VOCABULARY:
            continue
        strings = _strings(node)
        if (strings and len(strings) >= 2 and strings <= _PATH_TERMINATORS
                and id(node) not in inner):
            found.add((node.lineno, f"path-terminator set {sorted(strings)}"))
        keys = _dict_keys(node)
        if keys:
            if len(set(keys) & set(vocab.WAYPOINT_TYPES)) >= 3 and all(
                    isinstance(v, ast.Constant) and isinstance(v.value, int) for v in keys.values()):
                found.add((node.lineno, "waypoint type number map"))
            # A label table (``{"vor": "VOR"}``) is presentation, not a copy.
            if {"vor", "ndb", "airport"} <= set(keys) and all(
                    isinstance(keys[k], ast.Constant) and keys[k].value == k
                    for k in ("vor", "ndb", "airport")):
                found.add((node.lineno, "pack fix type map"))
            if len(set(keys) & set(vocab.ROLES[1:])) >= 2 and not all(
                    isinstance(v, ast.Constant) and isinstance(v.value, str)
                    for v in keys.values()):
                found.add((node.lineno, "role-to-flag table"))
        if (name and _is_int_expr(node)
                and (name.startswith(("FLAG_", "_FLAG_", "PACK_")) or "ROLE" in name)):
            found.add((node.lineno, f"flag bit {name}"))
        # ``((0x02, "iaf"), ...)``: a role table written as pairs.
        if isinstance(node, ast.Tuple) and len(node.elts) >= 2 and all(
                isinstance(e, ast.Tuple) and len(e.elts) == 2 and _is_int_expr(e.elts[0])
                and isinstance(e.elts[1], ast.Constant) and e.elts[1].value in vocab.ROLES
                for e in node.elts):
            found.add((node.lineno, "role-to-flag table"))
        if isinstance(node, ast.FunctionDef) and _is_normaliser(node):
            found.add((node.lineno, f"ident normaliser {node.name}()"))
    return sorted(found)


def test_no_vocabulary_is_written_outside_vocab():
    copies = []
    for path in sorted(_SRC.rglob("*.py")):
        if path == _VOCAB:
            continue
        rel = path.relative_to(_SRC).as_posix()
        copies += [f"{rel}:{line}: {what}"
                   for line, what in vocabulary_copies(path.read_text(), rel)]
    assert copies == [], (
        "these modules write their own copy of the flight plan vocabulary: "
        "import it from pyefis.flightplan.vocab\n" + "\n".join(copies))


@pytest.mark.parametrize("source, what", [
    ('HOLDS = frozenset({"HM", "HF", "HA"})\n', "path-terminator set"),
    ('def f(pt):\n    return pt in ("CA", "FA")\n', "path-terminator set"),
    ('T = {"unknown": 0, "airport": 1, "vor": 2, "ndb": 3}\n', "waypoint type number map"),
    ('P = {"vor": "vor", "ndb": "ndb", "airport": "airport"}\n', "pack fix type map"),
    ('R = {"none": 0, "iaf": B, "faf": C}\n', "role-to-flag table"),
    ('FLAG_FAF = 0x04\n', "flag bit"),
    ('_ROLE_BITS = 30\n', "flag bit"),
    ('_ROLE_BITS = 0x02 | 0x04\n', "flag bit"),
    ('_FLAG_TO_ROLE = ((0x02, "iaf"), (0x04, "faf"))\n', "role-to-flag table"),
    ('def _norm(s):\n    return (s or "").strip().upper()\n', "ident normaliser"),
    ('def k(s):\n    """Doc."""\n    return (s or "").upper().strip()\n', "ident normaliser"),
])
def test_the_scan_finds_a_planted_copy(source, what):
    assert [w for _line, w in vocabulary_copies(source) if w.startswith(what)]


def test_the_scan_passes_what_is_not_the_vocabulary():
    source = ('TURNS = ("L", "R")\nX = frozenset({"HM"})\nif pt == "CF": pass\n'
              'COLORS = {"vor": 1, "fix": 2}\nN = 0x20\n'
              'LABEL = {"airport": "APT", "vor": "VOR", "ndb": "NDB"}\n'
              'ROLE_ABBREV = {"none": "", "iaf": "IAF", "faf": "FAF"}\n'
              'def f(s):\n    return s.strip()\n')
    assert vocabulary_copies(source) == []


def test_every_user_reads_the_one_copy():
    """The names each module always exported are the vocabulary's own
    objects, not equal copies."""
    assert fixbridge.TYPE_TO_FPLTYPE is vocab.TYPE_TO_FPLTYPE
    assert fixbridge.FPLTYPE_TO_TYPE is vocab.FPLTYPE_TO_TYPE
    assert fixbridge.ROLE_TO_FLAG is vocab.ROLE_TO_FLAG
    assert fixbridge.CODED_COURSE_PTS is vocab.CODED_COURSE_PTS
    assert model.WAYPOINT_TYPES is vocab.WAYPOINT_TYPES
    assert model.ROLES is vocab.ROLES
    assert model.SEGMENT_KINDS is vocab.SEGMENT_KINDS
    assert waypoints.WAYPOINT_TYPES == frozenset(vocab.WAYPOINT_TYPES)
    for module in (hold, leg_paths, proc_load):
        assert module.HOLD_PTS is vocab.HOLD_PTS
    assert leg_paths.NO_FIX_PTS is vocab.NO_FIX_PTS
    assert leg_paths.VECTOR_PTS is vocab.VECTOR_PTS
    assert leg_paths.ARC_PTS is vocab.ARC_PTS
    assert hold.FLAG_FROM_PROCEDURE == proc_load.FLAG_FROM_PROCEDURE == vocab.FLAG_FROM_PROCEDURE
    assert proc_load.FLAG_FLYOVER == vocab.FLAG_FLYOVER
    for module in (model, proc_load, airways, procedures, plates):
        assert module._norm is vocab.norm
    assert waypoints._norm_ident is vocab.norm
    assert not hasattr(model, "TYPE_TO_FPLTYPE")


def test_the_role_table_reads_both_ways():
    for role, bit in vocab.ROLE_TO_FLAG.items():
        assert fixbridge._flag_to_role(bit | vocab.FLAG_FLYOVER | vocab.FLAG_FROM_PROCEDURE) == role
    assert vocab.ROLE_BITS & (vocab.FLAG_FLYOVER | vocab.FLAG_FROM_PROCEDURE) == 0


@pytest.mark.parametrize("args, packed", [
    (("+", 3500), "+3500"), (("-", 5000.0), "-5000"), (("@", 1800), "@1800"),
    (("B", 4000, 2900), "B2900,4000"), (("B", 2900, 4000), "B2900,4000"),
])
def test_pack_alt(args, packed):
    assert vocab.pack_alt(*args) == packed


def test_pack_alt_refuses_an_unknown_prefix():
    with pytest.raises(ValueError):
        vocab.pack_alt("X", 3000)


def test_norm():
    assert vocab.norm(" kSba ") == "KSBA"
    assert vocab.norm(None) == ""
