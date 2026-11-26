#  SPDX-License-Identifier: GPL-2.0-or-later
"""The engine's ``FPLMSG`` refusal codes in plain words (G61a).

When the fix-gateway flightplan engine refuses a route commit or a command it
writes a short code to ``FPLMSG``: ``BADTURN RF RFFIX``, ``SEGENT S2 GVO``,
``NO POSITION``. The code list is the engine's (``engine.py``
``unsupported_leg_reason``, ``_tier2_data_reason``,
``segment_integrity_reason``, ``_obs_refusal`` and the ``_Reject`` reasons; fix-gateway
``doc/flightplan_keys.md``, the ``FPLMSG`` row). A pilot should not need that
list to know what to fix, so :func:`plain_reason` turns each code into a short
reason that names the waypoint where the code carries one.

Three codes are not refusals: an accepted commit that drops the active leg
says why with ``ACTIVE LEG REMOVED``, ``CHANGED`` or ``AMBIGUOUS`` (HOLDFIX0),
written after ``FPLLDSEQ``, so the FPL page never reads them as a refusal;
it shows them as a notice (:data:`ACTIVE_LEG_NOTICES`).

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

# GPS OBS refusals (fix-gateway OBS2): the OBS command with no waypoint or
# position, or on a leg OBS cannot hold, and SUSP/RESUME or OBS OFF in the
# wrong mode. Whole messages, like the command rejections.
_OBS = {
    "OBS N/A NO WPT": "OBS NOT AVAILABLE: NO ACTIVE WAYPOINT",
    "OBS N/A NO POSITION": "OBS NOT AVAILABLE: NO GPS POSITION",
    "OBS N/A FINAL APPROACH": "OBS NOT AVAILABLE ON FINAL APPROACH",
    "OBS N/A HOLD": "OBS NOT AVAILABLE IN A HOLD",
    "OBS N/A PROC TURN": "OBS NOT AVAILABLE ON A PROCEDURE TURN",
    "OBS N/A VECTORS": "OBS NOT AVAILABLE ON VECTORS",
    # A CA, or an FA past its fix: a climb with no fix to hold.
    "OBS N/A NO FIX": "OBS NOT AVAILABLE ON A CLIMB LEG",
    "IN OBS": "NOT AVAILABLE IN OBS",
    "NOT IN OBS": "OBS IS NOT ON",
    # The gateway's database/flightplan.yaml predates OBS2 and cannot carry
    # the OBS state. Refused on every leg; the pilot cannot fix it in flight.
    "OBS N/A DATABASE": "OBS NOT AVAILABLE: GATEWAY CONFIG OUT OF DATE",
}
_COMMAND.update(_OBS)

# ACT onto a DF with a coded turn direction, refused where the coded turn
# cannot be flown as ruled (fix-gateway AER-6294, Bill's ruling). Each points
# the pilot to Direct-To, which flies straight at the fix. Whole messages.
_ACT_DF = {
    # The fix is within 90 deg of the nose on the side away from the coded
    # turn: the turn toward it is already made, and the coded one would be
    # most of a circle.
    "ACT N/A TURNED": "ALREADY TURNED TOWARD FIX: USE DIRECT-TO",
    "ACT N/A NO TRACK": "NO GPS TRACK FOR CODED TURN: USE DIRECT-TO",
    # The fix is inside the coded turn's circle.
    "ACT N/A TOO CLOSE": "TOO CLOSE FOR CODED TURN: USE DIRECT-TO",
}
_COMMAND.update(_ACT_DF)

# An accepted commit that does not keep the active leg (fix-gateway HOLDFIX0):
# the route loads and nothing is active. Not a refusal; whole messages.
_ACTIVE_LEG = {
    "ACTIVE LEG REMOVED": "ACTIVE WAYPOINT REMOVED: NO LEG ACTIVE",
    # The TO fix is still there, but after another FROM fix or on another path.
    "ACTIVE LEG CHANGED": "ACTIVE LEG CHANGED: NO LEG ACTIVE",
    # The active leg is in the new route more than once.
    "ACTIVE LEG AMBIGUOUS": "ACTIVE LEG REPEATED IN PLAN: NO LEG ACTIVE",
}
_COMMAND.update(_ACTIVE_LEG)

#: The accepted-commit notices above: the FPL page toasts one when it lands
#: after ``FPLLDSEQ`` (G97, AER-6536).
ACTIVE_LEG_NOTICES = frozenset(_ACTIVE_LEG)

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
