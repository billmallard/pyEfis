#  SPDX-License-Identifier: GPL-2.0-or-later
"""The flight plan vocabulary (FPA7): the words the editor, the bus mirror,
the map and the engine share, written once.

The waypoint types and their ``FPLfTYPE`` numbers, the ``FPLfFLAGS`` bits, the
segment kinds, the path-terminator sets, the packed ``FPLfALT`` notation and
ident normalisation were each written 4 to 7 times across this package before
FPA7 (ARCH1, ``makerplane/briefs/architecture_audit.md`` section 2.3), and the
copies had already drifted once: ``FM`` was missing from one coded-course set
(FPA1). Every module imports them from here.

The numbers, bits and sets the engine also declares (fix-gateway
``plugins/flightplan/engine.py``: ``TYPE_*``, ``SEGKIND_*``, ``FLAG_*``,
``PT_*``, ``_parse_alt_constraint``) are pinned against the engine's source by
``tests/flightplan/test_engine_enums.py``, which fix-gateway's CI also runs.
The wire contract is fix-gateway ``doc/flightplan_keys.md``.

No Qt, and no imports: fix-gateway's CI reads this from a sparse checkout.
"""

# --- FPLfTYPE ---------------------------------------------------------------
TYPE_UNKNOWN = 0
TYPE_AIRPORT = 1
TYPE_VOR = 2
TYPE_NDB = 3
TYPE_FIX = 4
TYPE_USER = 5
TYPE_MAPPOINT = 6

#: ``model.Waypoint.type`` -> ``FPLfTYPE``.
TYPE_TO_FPLTYPE = {"unknown": TYPE_UNKNOWN, "airport": TYPE_AIRPORT, "vor": TYPE_VOR,
                   "ndb": TYPE_NDB, "fix": TYPE_FIX, "user": TYPE_USER, "map": TYPE_MAPPOINT}
FPLTYPE_TO_TYPE = {v: k for k, v in TYPE_TO_FPLTYPE.items()}

#: The types a ``model.Waypoint`` may carry ("unknown" is only ever read off
#: the bus).
WAYPOINT_TYPES = ("airport", "vor", "ndb", "fix", "user", "map")

#: Pack ``fix_type`` -> ``model.Waypoint.type``. Anything not listed
#: (``waypoint``, ``runway``, blank) is a plain ``fix``.
PACK_FIX_TYPES = {"vor": "vor", "ndb": "ndb", "airport": "airport"}

# --- FPLfFLAGS ----------------------------------------------------------------
FLAG_FLYOVER = 0x01
FLAG_IAF = 0x02
FLAG_FAF = 0x04
FLAG_MAP = 0x08
FLAG_MAHP = 0x10
FLAG_FROM_PROCEDURE = 0x20

ROLES = ("none", "iaf", "faf", "map", "mahp")

# PA3 (fix-gateway#27) replaced the scalar FPLfROLE (0 none/1 iaf/2 faf/3
# map/4 mahp) with this bitfield. The bit positions do NOT match the old
# scalar values (faf was 2, IAF's bit is 0x02), so the role is an explicit
# table in both directions -- a straight rename/shift would silently turn faf
# into iaf.
ROLE_TO_FLAG = {"none": 0x00, "iaf": FLAG_IAF, "faf": FLAG_FAF, "map": FLAG_MAP,
                "mahp": FLAG_MAHP}
#: The bits that are the role; the rest (fly-over, from a coded procedure)
#: ride through the editor untouched.
ROLE_BITS = FLAG_IAF | FLAG_FAF | FLAG_MAP | FLAG_MAHP

# --- FPLSsKIND (RS1) ------------------------------------------------------------
#: In wire order. Kind 0 is one waypoint the pilot entered -- not a
#: Direct-To, which never touches the table.
SEGMENT_KINDS = ("waypoint", "airway", "departure", "arrival", "approach", "missed")

# --- FPLfPT -----------------------------------------------------------------------
HOLD_PTS = frozenset({"HM", "HF", "HA"})
ARC_PTS = frozenset({"RF", "AF"})
#: Held until an altitude: the engine's PT_ALT_TERM.
ALT_TERM_PTS = frozenset({"CA", "FA"})
#: A heading flown to no fix.
HEADING_PTS = frozenset({"VA", "VM", "VI"})
#: Vector legs: they end on pilot or ATC action, never on geometry.
VECTOR_PTS = HEADING_PTS | {"FM"}
#: Legs that end at no fix: drawn as a stub, and listed by what ends them.
NO_FIX_PTS = HEADING_PTS | {"CA"}
#: Legs whose ``FPLfCRS`` is a coded course or heading, which the read-back
#: keeps; on every other leg it is a derived bearing, recomputed on publish.
CODED_COURSE_PTS = frozenset({"CF", "CA", "FC", "VA", "VM", "VI", "FM", "FA", "HM", "HF",
                              "HA", "PI"})

# --- FPLfALT: the packed altitude constraint --------------------------------------
#: ``+3500`` at or above, ``-5000`` at or below, ``@1800`` at, and
#: ``B2900,4000`` between (floor first).
ALT_AT_OR_ABOVE = "+"
ALT_AT_OR_BELOW = "-"
ALT_AT = "@"
ALT_BETWEEN = "B"
ALT_PREFIXES = (ALT_AT_OR_ABOVE, ALT_AT_OR_BELOW, ALT_AT, ALT_BETWEEN)


def pack_alt(prefix, alt_ft, alt2_ft=None):
    """The packed constraint: ``pack_alt("+", 3500)`` is ``"+3500"``;
    ``pack_alt("B", 4000, 2900)`` is ``"B2900,4000"``, floor first."""
    if prefix == ALT_BETWEEN:
        lo, hi = sorted((int(alt_ft), int(alt2_ft)))
        return f"{ALT_BETWEEN}{lo},{hi}"
    if prefix not in ALT_PREFIXES:
        raise ValueError(f"no FPLfALT prefix {prefix!r}")
    return f"{prefix}{int(alt_ft)}"


# --- Idents -------------------------------------------------------------------------
def norm(ident) -> str:
    """An ident as the packs and the bus compare it: trimmed, upper case;
    ``""`` for None."""
    return (ident or "").strip().upper()
