#  SPDX-License-Identifier: GPL-2.0-or-later
"""G61a: the engine's FPLMSG refusal codes in plain words.

The expected strings are the reasons as worded for the pilot; the engine
messages are the exact shapes fix-gateway's flightplan engine writes
(``engine.py``; ``doc/flightplan_keys.md``, the ``FPLMSG`` row).

``test_engine_publishes_no_code_without_plain_words`` reads the engine's own
source and fails when it can publish a refusal code this display has no words
for. CI checks fix-gateway ``dev`` out for it and points
``FIXGW_FLIGHTPLAN_ENGINE`` at the file; with the variable set, a missing file
is a failure, not a skip.
"""

import ast
import os
import pathlib

import pytest

from pyefis.flightplan import model as fp_model
from pyefis.flightplan import refusal


@pytest.mark.parametrize("msg, plain", [
    # Route loads: an unrecognized leg type (UNSUPP <PT> <ident>).
    ("UNSUPP FC GVO", "CAN'T FLY FC LEG AT GVO"),
    ("UNSUPP ?? GVO", "CAN'T FLY LEG TYPE AT GVO"),
    # Route loads: a recognized Tier-2 leg missing data (<CODE> <PT> <ident>).
    ("BADTURN RF RFFIX", "ARC AT RFFIX: NO TURN DIRECTION"),
    ("BADTURN HM HOLDA", "HOLD AT HOLDA: NO TURN DIRECTION"),
    ("BADTURN PI PTURN", "PROCEDURE TURN AT PTURN: NO TURN DIRECTION"),
    ("BADRADIUS AF DMEARC", "ARC AT DMEARC: NO RADIUS"),
    ("BADCENTER RF RFFIX", "ARC AT RFFIX: NO CENTER"),
    ("BADALT CA SLOT3", "CLIMB AT WAYPOINT 3: NO ALTITUDE"),
    ("BADALT HA HOLDA", "HOLD AT HOLDA: NO ALTITUDE"),
    ("BADLEGLEN HF HOLDA", "HOLD AT HOLDA: NO LEG LENGTH"),
    # Route loads: the segment table does not describe the slots (RS1).
    ("SEGCNT 7", "ROUTE TABLE ERROR (SEGMENT COUNT)"),
    ("SEGSGI 4 RZS 9", "ROUTE TABLE ERROR AT RZS (NOT IN A SEGMENT)"),
    ("SEGNONCONTIG S2 GVO", "ROUTE TABLE ERROR AT GVO (SEGMENT SPLIT)"),
    ("SEGORDER S3 RZS", "ROUTE TABLE ERROR AT RZS (SEGMENT ORDER)"),
    ("SEGORDER S4 UNUSED", "ROUTE TABLE ERROR AT SEGMENT 4 (SEGMENT ORDER)"),
    ("SEGKIND S2 9", "ROUTE TABLE ERROR AT SEGMENT 2 (SEGMENT TYPE)"),
    ("SEGRANGE S2 3-5", "ROUTE TABLE ERROR AT SEGMENT 2 (FIRST/LAST FIX)"),
    ("SEGENT S2 GVO", "ROUTE TABLE ERROR AT SEGMENT 2 (ENTRY FIX)"),
    ("SEGEXT S2 ??", "ROUTE TABLE ERROR AT SEGMENT 2 (EXIT FIX)"),
    ("SEGLEN S2 V27 1", "ROUTE TABLE ERROR AT V27 (FIX COUNT)"),
    ("SEGLEN S2 - 2", "ROUTE TABLE ERROR AT SEGMENT 2 (FIX COUNT)"),
    ("SEGID S2 -", "ROUTE TABLE ERROR AT SEGMENT 2 (AIRWAY NAME)"),
    # Command rejections.
    ("NO PLAN", "NO FLIGHT PLAN LOADED"),
    ("BAD SLOT", "WAYPOINT NOT IN PLAN"),
    ("NO POSITION", "NO GPS POSITION"),
    ("PARSE", "COMMAND NOT UNDERSTOOD"),
])
def test_each_engine_code_reads_in_plain_words(msg, plain):
    assert refusal.plain_reason(msg) == plain


def test_a_bare_code_still_reads_in_plain_words():
    assert refusal.plain_reason("BADTURN") == "LEG: NO TURN DIRECTION"
    assert refusal.plain_reason("UNSUPP") == "CAN'T FLY LEG TYPE"


def test_an_unknown_code_shows_as_it_came():
    """An engine newer than this display: the raw code, never nothing."""
    assert refusal.plain_reason("NEWCODE RF RFFIX") == "NEWCODE RF RFFIX"
    assert refusal.plain_reason("  NEWCODE  ") == "NEWCODE"


def test_no_message_is_no_reason():
    assert refusal.plain_reason("") == ""
    assert refusal.plain_reason(None) == ""


def test_a_segment_number_is_named_from_the_refused_plan():
    legs = [fp_model.Waypoint(id=ident, type="fix", lat=34.0 + n * 0.1, lon=-119.0)
            for n, ident in enumerate(("GVO", "RZS", "FIM"))]
    plan = fp_model.FlightPlan(name="R", segments=[
        fp_model.waypoint_segment(legs[0]),
        fp_model.Segment(kind="airway", ident="V27", legs=legs[1:]),
    ])
    assert refusal.plain_reason("SEGENT S2 RZS", plan) == "ROUTE TABLE ERROR AT V27 (ENTRY FIX)"
    assert refusal.plain_reason("SEGKIND S1 9", plan) == "ROUTE TABLE ERROR AT GVO (SEGMENT TYPE)"
    assert refusal.plain_reason("SEGEXT S5 ??", plan) == "ROUTE TABLE ERROR AT SEGMENT 5 (EXIT FIX)"


# ---------------------------------------------------------------------------
# every code the engine can publish has words here
# ---------------------------------------------------------------------------
def _str_code(node, constants):
    """The refusal code a string expression in the engine evaluates to: a
    whole constant (``"BADTURN"``, ``"NO PLAN"``), or the first word of an
    f-string's leading text (``f"UNSUPP {pt} {ident}"[:64]``). None when the
    expression does not start with literal text."""
    if isinstance(node, ast.Subscript):
        node = node.value
    if isinstance(node, ast.Name):
        node = constants.get(node.id)
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value.strip() or None
    if isinstance(node, ast.JoinedStr) and node.values:
        head = node.values[0]
        if isinstance(head, ast.Constant) and head.value.split():
            return head.value.split()[0]
    return None


def engine_refusal_codes(source):
    """Every refusal code the flightplan engine's *source* can write to
    FPLMSG: what the ``*_reason`` route checks return, what ``_Reject`` and
    ``RouteRejected`` are raised with, and the reason beside a negative ack
    ``handle_command`` returns directly."""
    tree = ast.parse(source)
    constants = {t.id: n.value for n in tree.body if isinstance(n, ast.Assign)
                 for t in n.targets if isinstance(t, ast.Name)}
    found = set()
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef) and fn.name.endswith("_reason"):
            for node in ast.walk(fn):
                if isinstance(node, ast.Return) and node.value is not None:
                    found.add(_str_code(node.value, constants))
        if (isinstance(fn, ast.Call) and isinstance(fn.func, ast.Name)
                and fn.func.id in ("_Reject", "RouteRejected") and fn.args):
            found.add(_str_code(fn.args[0], constants))
        if (isinstance(fn, ast.Return) and isinstance(fn.value, ast.Tuple)
                and len(fn.value.elts) == 2):
            ack = fn.value.elts[0]
            negative = (isinstance(ack, ast.UnaryOp) and isinstance(ack.op, ast.USub)) or (
                isinstance(ack, ast.Constant) and isinstance(ack.value, int) and ack.value < 0)
            if negative:
                found.add(_str_code(fn.value.elts[1], constants))
    found.discard(None)
    return found


def _engine_path():
    """The engine source: ``FIXGW_FLIGHTPLAN_ENGINE`` (CI; required), else
    the engine in the ``FIX_GATEWAY_SRC`` checkout the conformance test uses."""
    env = os.environ.get("FIXGW_FLIGHTPLAN_ENGINE")
    if env:
        return pathlib.Path(env), True
    root = pathlib.Path(os.environ.get("FIX_GATEWAY_SRC") or "/nonexistent")
    return root / "src" / "fixgw" / "plugins" / "flightplan" / "engine.py", False


def test_engine_publishes_no_code_without_plain_words():
    path, required = _engine_path()
    if not path.is_file():
        if required:
            pytest.fail(f"FIXGW_FLIGHTPLAN_ENGINE={path} does not exist")
        pytest.skip("set FIX_GATEWAY_SRC to a fix-gateway checkout; CI sets "
                    "FIXGW_FLIGHTPLAN_ENGINE")
    codes = engine_refusal_codes(path.read_text())
    # The reader still finds the codes it was written against: a reader that
    # stopped matching the engine's source would otherwise pass on nothing.
    assert {"UNSUPP", "BADTURN", "SEGENT", "NO POSITION", "PARSE"} <= codes
    assert codes - refusal.KNOWN_CODES == set(), (
        "the engine can publish these FPLMSG codes and plain_reason has no words for "
        "them: add them to pyefis/flightplan/refusal.py")


def test_the_engine_reader_catches_a_new_code():
    """The coverage test above fails for the change it exists to catch: an
    engine that adds a route check, a command rejection or a raw refusal."""
    source = '''
NEW_REASON = "NO FUEL"
def _tier2_data_reason(w):
    if w.x:
        return "BADTURN"
    return "BADWIDGET"
def segment_integrity_reason(waypoints, segments):
    return f"SEGFOO S{k} {seg.id}"[:64]
def handle_command(self):
    if x:
        return -1, "NOSUCH"
    raise _Reject(NEW_REASON)
def load(self, reason):
    raise RouteRejected(reason)
'''
    codes = engine_refusal_codes(source)
    assert codes == {"BADTURN", "BADWIDGET", "SEGFOO", "NOSUCH", "NO FUEL"}
    assert codes - refusal.KNOWN_CODES == {"BADWIDGET", "SEGFOO", "NOSUCH", "NO FUEL"}
