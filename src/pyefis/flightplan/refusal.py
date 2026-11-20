#  SPDX-License-Identifier: GPL-2.0-or-later
"""The engine's ``FPLMSG`` refusal codes in plain words (G61a).

When the fix-gateway flightplan engine refuses a route commit or a command it
writes a short code to ``FPLMSG``: ``BADTURN RF RFFIX``, ``SEGENT S2 GVO``,
``NO POSITION``. The code list is the engine's (``engine.py``
``unsupported_leg_reason``, ``_tier2_data_reason``,
``segment_integrity_reason`` and the ``_Reject`` reasons; fix-gateway
``doc/flightplan_keys.md``, the ``FPLMSG`` row). A pilot should not need that
list to know what to fix, so :func:`plain_reason` turns each code into a short
reason that names the waypoint where the code carries one.

A code this module does not know -- an engine newer than this display -- is
shown as it came, never as nothing. ``tests/flightplan/test_refusal.py`` reads
the engine's source and fails when it can publish a code with no entry here.

Pure Python, no Qt: the FPL page's refusal strip and the moving map's
rejection toast both call it.
"""

from __future__ import annotations

# What a leg is called in a sentence, by path terminator (ARINC 424). The
# Tier-2 data codes only come from these types; anything else is a "LEG".
_LEG_NOUN = {
    "RF": "ARC", "AF": "ARC",
    "HM": "HOLD", "HF": "HOLD", "HA": "HOLD",
    "PI": "PROCEDURE TURN",
    "CA": "CLIMB", "FA": "CLIMB",
}

# Route loads, guardrail 1: a recognized leg type missing what its geometry
# needs. FPLMSG is "<CODE> <PT> <ident>".
_LEG_DATA = {
    "BADTURN": "NO TURN DIRECTION",
    "BADRADIUS": "NO RADIUS",
    "BADCENTER": "NO CENTER",
    "BADALT": "NO ALTITUDE",
    "BADLEGLEN": "NO LEG LENGTH",
}

# Route loads, RS1: the segment table on the bus does not describe the slots.
# The editor wrote it, so the pilot cannot fix it by hand; the words say where
# and what, for the report.
_SEGMENT = {
    "SEGCNT": "SEGMENT COUNT",
    "SEGSGI": "NOT IN A SEGMENT",
    "SEGNONCONTIG": "SEGMENT SPLIT",
    "SEGORDER": "SEGMENT ORDER",
    "SEGKIND": "SEGMENT TYPE",
    "SEGRANGE": "FIRST/LAST FIX",
    "SEGENT": "ENTRY FIX",
    "SEGEXT": "EXIT FIX",
    "SEGLEN": "FIX COUNT",
    "SEGID": "AIRWAY NAME",
}

# Command rejections (FPLCMDACK negative). Matched on the whole message,
# since two of them are two words.
_COMMAND = {
    "NO PLAN": "NO FLIGHT PLAN LOADED",
    "BAD SLOT": "WAYPOINT NOT IN PLAN",
    "NO POSITION": "NO GPS POSITION",
    "PARSE": "COMMAND NOT UNDERSTOOD",
}

#: Every code :func:`plain_reason` has words for: the first word of a route
#: refusal, or a whole command rejection.
KNOWN_CODES = frozenset({"UNSUPP"} | set(_LEG_DATA) | set(_SEGMENT) | set(_COMMAND))


def _place(ident):
    """The engine names a slot with no ident ``SLOT<n>``; say waypoint n."""
    if ident.startswith("SLOT") and ident[4:].isdigit():
        return f"WAYPOINT {ident[4:]}"
    return ident


def _segment_name(token, plan):
    """``S<k>`` as the pilot knows segment k of *plan*: the airway or
    procedure name, else its one fix. ``SEGMENT k`` when *plan* cannot say."""
    k = token[1:]
    if not (token.startswith("S") and k.isdigit()):
        return token
    segments = getattr(plan, "segments", None) or []
    if 1 <= int(k) <= len(segments):
        seg = segments[int(k) - 1]
        name = seg.ident or seg.entry
        if name:
            return name
    return f"SEGMENT {k}"


def _segment_reason(code, args, plan):
    what = _SEGMENT[code]
    if code == "SEGCNT" or not args:
        where = ""
    elif code == "SEGSGI":
        # SEGSGI <slot> <ident> <sgi>: the ident is the place.
        where = _place(args[1]) if len(args) > 1 else f"WAYPOINT {args[0]}"
    elif code in ("SEGNONCONTIG", "SEGORDER") and len(args) > 1 and args[1] != "UNUSED":
        # S<k> <ident>: the fix where the order breaks.
        where = _place(args[1])
    elif code == "SEGLEN" and len(args) > 1 and args[1] != "-":
        where = args[1]
    else:
        where = _segment_name(args[0], plan)
    at = f" AT {where}" if where else ""
    return f"ROUTE TABLE ERROR{at} ({what})"


def plain_reason(msg, plan=None):
    """*msg* (an ``FPLMSG`` value) in plain words. *plan* is the refused
    route, used to name a segment the code only gives by number. Empty in,
    empty out; an unknown code comes back as it came."""
    text = str(msg or "").strip()
    if not text:
        return ""
    if text in _COMMAND:
        return _COMMAND[text]
    code, *args = text.split()
    if code == "UNSUPP":
        # UNSUPP <PT> <ident>
        pt = args[0] if args and args[0] != "??" else ""
        leg = f"{pt} LEG" if pt else "LEG TYPE"
        at = f" AT {_place(args[1])}" if len(args) > 1 else ""
        return f"CAN'T FLY {leg}{at}"
    if code in _LEG_DATA:
        # <CODE> <PT> <ident>
        noun = _LEG_NOUN.get(args[0], "LEG") if args else "LEG"
        at = f" AT {_place(args[1])}" if len(args) > 1 else ""
        return f"{noun}{at}: {_LEG_DATA[code]}"
    if code in _SEGMENT:
        return _segment_reason(code, args, plan)
    return text
