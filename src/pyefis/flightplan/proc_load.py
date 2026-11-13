#  SPDX-License-Identifier: GPL-2.0-or-later
"""Turning a coded procedure into flight-plan segments, and placing it in a
route (PA7, billmallard/pyEfis#238, AER-1606).

See ``makerplane/briefs/procedures_and_airways_plan.md`` sections 3.2 and
3.5. The PROC page picks a procedure from :class:`procedures.ProcedureIndex`;
this module assembles its legs into ``model.Segment`` rows the bridge
publishes, and inserts them where the GNX 375 guide puts them (p. 3-65:
"Departure, En route, Arrival, Approach").

What this module decides, so a reviewer can see each choice:

- **Legs are passed through, never coerced** (guardrail 1). Every leg keeps
  its path terminator. One the engine cannot fly (``FC`` today) reaches the
  engine, which refuses the whole route with a reason on ``FPLMSG``; the FPL
  page's refusal strip says why. Nothing here drops or rewrites a leg type.
- **The rare fields are resolved here, not sent down the bus** (section
  3.2): an ``RF``'s centre and radius from the pack, an ``AF``'s centre from
  its recommended navaid through *resolve_navaid*. A value the data does not
  carry is left empty, and the engine refuses the route for it
  (``BADCENTER``/``BADRADIUS``/...), rather than being made up here.
- **A time-coded hold** (``T010``, one minute) reaches the engine as a
  distance: the bus carries no leg time (fix-gateway
  ``doc/plugins/flightplan.md``). It is converted at *hold_speed_kt*. Too
  low a speed makes the racetrack shorter than flown, which keeps it inside
  the protected airspace that was designed for the maximum holding speed.
- **A leg with no fix** (``CA``, ``VA``, ``VI``, ``VM``) has an empty ident
  and a position ``NO_FIX_POINT_NM`` along its coded course from the fix
  before it, converted to true with *magvar*. The engine flies a ``CA``
  along its course through that point, so any point on the line gives the
  same leg; ``fixgw/sim/fplroute.py`` makes the same choice.
- **The transition's last fix and the final's ``IF`` are one slot**: the
  final starts where the transition ends, and the same fix coded twice
  would be a zero-length leg (see :func:`insert`).
- **Flags**: the pack's fly-over bit stays a flag; IAF (transition legs of
  an approach only), FAF, MAP and MAHP (the missed approach's hold fix)
  become the slot's role; ``0x20`` (from a coded procedure) is set on every
  slot. A final coded with more than one FAF-flagged fix keeps the FAF
  nearest the MAP: the pack sets the FAF bit for ARINC's final approach
  course fix too, and that one comes first.
- **Segments**: a SID or STAR is one row, an approach is two -- the
  approach (kind 4) and its missed approach (kind 5). The missed approach
  is loaded but not sequenced into: the engine never auto-sequences past the
  MAP (guardrail 2).

Qt-free: nothing here may import PyQt6.
"""

from __future__ import annotations

import copy

from . import geo
from . import model

#: The PROC page's three procedure kinds, as the pack names them.
PAGE_KINDS = ("departure", "arrival", "approach")
PACK_KIND = {"departure": "sid", "arrival": "star", "approach": "approach"}
#: The segment kinds one loaded procedure of each kind occupies.
SEGMENT_KINDS = {"departure": ("departure",), "arrival": ("arrival",),
                 "approach": ("approach", "missed")}
PROCEDURE_SEGMENT_KINDS = frozenset(k for kinds in SEGMENT_KINDS.values() for k in kinds)

#: Transition choices that are not a transition in the pack.
VECTORS = "VECTORS"
NO_TRANSITION = "NONE"

# The pack's legs.flags, ARINC 424 waypoint description code
# (makerplane-data packtools/arinc424.py). Not the bus's FPLfFLAGS: the
# pack's 0x10 is "hold" and 0x20 "first missed approach leg", where the
# bus has 0x10 MAHP and 0x20 "from a coded procedure".
PACK_FLYOVER = 0x01
PACK_IAF = 0x02
PACK_FAF = 0x04
PACK_MAP = 0x08
PACK_FIRST_MISSED = 0x20

#: FPLfFLAGS bits this module sets on a slot besides its role.
FLAG_FLYOVER = 0x01
FLAG_FROM_PROCEDURE = 0x20

HOLD_PTS = frozenset({"HM", "HF", "HA"})
# Two slots with one ident this close are one fix: the waypoint database
# (NASR) and the procedures pack (CIFP) code the same navaid a few feet
# apart, and a fix name is reused only far away.
SAME_FIX_NM = 0.5
NO_FIX_POINT_NM = 2.0
HOLD_SPEED_KT = 90.0

# Approach-type prefixes (ARINC 424 5.10, the letter the pack keeps as
# approach_type) spelled the way a pilot reads them. A prefix not listed
# is shown as the pack codes it.
_APPROACH_NAMES = {
    "I": "ILS", "L": "LOC", "B": "LOCBC", "R": "RNAV", "H": "RNP", "P": "GPS",
    "V": "VOR", "D": "VORDME", "S": "VORDME", "N": "NDB", "Q": "NDBDME",
    "X": "LDA", "U": "SDF",
}

_FIX_TYPES = {"vor": "vor", "ndb": "ndb", "airport": "airport"}


class ProcedureLoadError(ValueError):
    """The procedure cannot be assembled from the pack as coded. The message
    is shown to the pilot as it is."""


def _norm(ident):
    return (ident or "").strip().upper()


def runway_label(ident):
    """``"RW07"`` for a runway transition ident or designator."""
    norm = _norm(ident).removeprefix("RW")
    return f"RW{norm}" if norm else ""


def procedure_name(proc):
    """The name the FPL page and the segment table use: ``ILS07``,
    ``RNAV30``, ``VOR-A``; a SID or STAR keeps its ident (``FLOUT5``)."""
    ident = _norm(proc.ident)
    if proc.kind != "approach":
        return ident
    prefix = (proc.approach_type or "").strip().upper()
    if prefix and ident.startswith(prefix) and prefix in _APPROACH_NAMES:
        return _APPROACH_NAMES[prefix] + ident[len(prefix):]
    return ident


def segment_ident(proc, transition=None, runway=None):
    """The segment table's ``ID`` for this selection, at most 24 characters:
    ``ILS07.GOLET``, ``ILS07.VECTORS``, ``FLOUT5.RW07.GVO``,
    ``PITBL2.HEC.RW25``. The parts are the ones the pilot picked, in the
    order the PROC page asks for them."""
    parts = [procedure_name(proc)]
    if proc.kind == "sid" and runway:
        parts.append(runway_label(runway))
    if transition and transition != NO_TRANSITION:
        parts.append(_norm(transition))
    if proc.kind == "star" and runway:
        parts.append(runway_label(runway))
    return ".".join(parts)[:model.SEGMENT_IDENT_MAX_LEN]


# ---------------------------------------------------------------------------
# What the PROC page offers
# ---------------------------------------------------------------------------
def transition_choices(index, proc):
    """The transition picker for *proc*: its en-route transitions, in
    published order, then ``VECTORS`` for an approach (the final alone,
    vectors to final) or ``NONE`` for a SID/STAR with a route that stands
    without one."""
    names = [t.ident for t in index.transitions_for(proc.id, role="enroute") if t.ident]
    if proc.kind == "approach":
        if index.transitions_for(proc.id, role="common"):
            names.append(VECTORS)
        return names
    if index.transitions_for(proc.id, role="common") or index.transitions_for(proc.id, role="runway"):
        names.append(NO_TRANSITION)
    return names


def runway_choices(index, proc):
    """The runway picker for a SID or STAR: its runway transitions as
    ``RW07``, in published order. Empty for an approach (its runway is part
    of the procedure) and for a procedure with no runway transition."""
    if proc.kind == "approach":
        return []
    return [runway_label(t.ident) for t in index.transitions_for(proc.id, role="runway")
            if t.ident]


def needs_runway(index, proc):
    return bool(runway_choices(index, proc))


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------
def _alt_text(leg):
    """The leg's altitude constraint in the bus's packed notation
    (``+3500``, ``-5000``, ``@1800``, ``B2900,4000``). The glide-slope and
    step-down descriptors keep the altitude they constrain the fix to.
    An altitude descriptor this module does not know refuses the load: a
    guessed constraint is worse than none."""
    a1, a2 = leg.alt1_ft, leg.alt2_ft
    desc = (leg.alt_desc or "").strip().upper()
    if a1 is None and a2 is None:
        return ""
    if desc in ("+", "H", "J", "V"):
        return f"+{int(a1)}" if a1 is not None else ""
    if desc in ("-", "Y"):
        return f"-{int(a1)}" if a1 is not None else ""
    if desc in ("", "@", "G", "I", "X"):
        return f"@{int(a1)}" if a1 is not None else ""
    if desc == "B":
        if a1 is None or a2 is None:
            return ""
        lo, hi = sorted((int(a1), int(a2)))
        return f"B{lo},{hi}"
    if desc == "C":
        return f"+{int(a2)}" if a2 is not None else ""
    raise ProcedureLoadError(f"ALTITUDE CODE {desc!r} AT {_norm(leg.fix_id) or leg.path_term}")


def _point_on_course(lat, lon, course_mag, magvar, dist_nm):
    return geo.destination_point(lat, lon, (course_mag - magvar) % 360.0, dist_nm)


def _waypoint(leg, prev, *, magvar, hold_speed_kt, resolve_navaid):
    """One leg as a route slot. *prev* is the slot before it that has a
    position, or None."""
    ident = _norm(leg.fix_id)
    pt = _norm(leg.path_term) or "??"
    if ident:
        if leg.lat is None or leg.lon is None:
            raise ProcedureLoadError(f"NO POSITION FOR {ident}")
        lat, lon = leg.lat, leg.lon
    elif prev is not None and leg.course is not None:
        lat, lon = _point_on_course(prev.lat, prev.lon, leg.course, magvar, NO_FIX_POINT_NM)
    elif prev is not None:
        lat, lon = prev.lat, prev.lon
    else:
        raise ProcedureLoadError(f"{pt} LEG HAS NO FIX TO START FROM")
    wp = model.Waypoint(
        id=ident, type=_FIX_TYPES.get((leg.fix_type or "").lower(), "fix"), lat=lat, lon=lon,
        pt=pt, crs=leg.course, alt=_alt_text(leg),
        spd=int(leg.speed_kt or 0), turn=_norm(leg.turn_dir),
        flags=FLAG_FROM_PROCEDURE | (FLAG_FLYOVER if leg.flags & PACK_FLYOVER else 0))
    if pt == "RF":
        if leg.centre_lat is not None and leg.centre_lon is not None:
            wp.ctr_lat, wp.ctr_lon = leg.centre_lat, leg.centre_lon
        wp.dst = float(leg.arc_radius_nm or 0.0)
    elif pt == "AF":
        centre = resolve_navaid(leg.recd_navaid, lat, lon) if resolve_navaid else None
        if centre is not None:
            wp.ctr_lat, wp.ctr_lon = centre
        wp.dst = float(leg.rho or 0.0)
    elif pt in HOLD_PTS or pt == "PI":
        if leg.dist_nm:
            wp.dst = float(leg.dist_nm)
        elif leg.time_min and pt in HOLD_PTS:
            wp.dst = round(float(leg.time_min) * float(hold_speed_kt) / 60.0, 2)
    return wp


def _assemble_legs(parts, origin, *, magvar, hold_speed_kt, resolve_navaid):
    """*parts* is ``[(part_name, [ProcedureLeg])]`` in flying order. Returns
    ``[(part_name, pack_flags, Waypoint)]``; a part's leading ``IF`` at the
    fix the previous part ended on is merged into that slot. *origin* is the
    point a first leg without a fix starts from."""
    out = []
    for part, legs in parts:
        for leg in legs:
            prev = next((w for _, _, w in reversed(out)), origin)
            if (_norm(leg.path_term) == "IF" and prev is not None and prev.id
                    and prev.id == _norm(leg.fix_id)):
                continue
            wp = _waypoint(leg, prev, magvar=magvar, hold_speed_kt=hold_speed_kt,
                           resolve_navaid=resolve_navaid)
            out.append((part, leg.flags or 0, wp))
    return out


def _transition_legs(index, proc, role, ident):
    for t in index.transitions_for(proc.id, role=role):
        if role == "runway":
            if runway_label(t.ident) == runway_label(ident):
                return index.legs_for(t.id)
        elif _norm(t.ident) == _norm(ident):
            return index.legs_for(t.id)
    raise ProcedureLoadError(f"{_norm(ident)} IS NOT A TRANSITION OF {procedure_name(proc)}")


def _common_legs(index, proc):
    legs = []
    for t in index.transitions_for(proc.id, role="common"):
        legs.extend(index.legs_for(t.id))
    return legs


def assemble(index, proc, transition=None, runway=None, *, magvar=0.0,
             hold_speed_kt=HOLD_SPEED_KT, resolve_navaid=None, origin=None):
    """The segments for *proc* (a ``procedures.Procedure``) flown via
    *transition* and, for a SID/STAR, *runway*: ``[Segment]`` for a SID or
    STAR, ``[approach, missed]`` for an approach (``[approach]`` when it
    codes no missed approach).

    *transition* is a transition ident from :func:`transition_choices`
    (``VECTORS`` for the final alone, ``NONE`` or None for no en-route
    transition). *magvar* is the variation (positive west) a no-fix leg's
    magnetic course is converted with. *resolve_navaid(ident, lat, lon)*
    returns an ``AF`` arc's centre ``(lat, lon)`` or None. *origin* is the
    point a SID's first leg starts from when it has no fix (a ``VA`` off
    the runway): the departure airport, an object with ``lat``/``lon``.

    Raises :class:`ProcedureLoadError` when the selection is incomplete or
    the pack cannot describe a leg; never returns part of a procedure."""
    kw = {"magvar": magvar, "hold_speed_kt": hold_speed_kt, "resolve_navaid": resolve_navaid}
    name = procedure_name(proc)
    has_trans = bool(transition) and transition not in (NO_TRANSITION, VECTORS)
    if proc.kind == "approach":
        if not transition:
            raise ProcedureLoadError(f"SELECT A TRANSITION FOR {name}")
        parts = []
        if has_trans:
            parts.append(("transition", _transition_legs(index, proc, "enroute", transition)))
        parts.append(("final", _common_legs(index, proc)))
    else:
        rw = []
        if needs_runway(index, proc):
            if not runway:
                raise ProcedureLoadError(f"SELECT A RUNWAY FOR {name}")
            rw = [("runway", _transition_legs(index, proc, "runway", runway))]
        trans = ([("transition", _transition_legs(index, proc, "enroute", transition))]
                 if has_trans else [])
        common = [("common", _common_legs(index, proc))]
        # A SID flies runway -> common -> en route; a STAR the reverse.
        parts = rw + common + trans if proc.kind == "sid" else trans + common + rw
    slots = _assemble_legs(parts, origin, **kw)
    if not slots:
        raise ProcedureLoadError(f"{name} HAS NO LEGS")
    ident = segment_ident(proc, transition, runway)
    if proc.kind != "approach":
        kind = "departure" if proc.kind == "sid" else "arrival"
        return [model.Segment(kind=kind, legs=[w for _, _, w in slots], ident=ident,
                              cycle=proc.cycle or "")]
    _set_approach_roles(slots)
    first_missed = next((n for n, (part, f, _w) in enumerate(slots)
                         if part == "final" and f & PACK_FIRST_MISSED), None)
    approach = [w for _, _, w in (slots if first_missed is None else slots[:first_missed])]
    if not approach:
        raise ProcedureLoadError(f"{name} HAS NO LEGS BEFORE THE MISSED APPROACH")
    segments = [model.Segment(kind="approach", legs=approach, ident=ident,
                              cycle=proc.cycle or "")]
    if first_missed is not None:
        segments.append(model.Segment(kind="missed", legs=[w for _, _, w in slots[first_missed:]],
                                      ident=name, cycle=proc.cycle or ""))
    return segments


def _set_approach_roles(slots):
    """IAF, FAF, MAP and MAHP as roles (one per slot; the model's
    FAF-before-MAP rule holds by construction)."""
    first_missed = next((n for n, (part, f, _w) in enumerate(slots)
                         if part == "final" and f & PACK_FIRST_MISSED), len(slots))
    map_i = next((n for n, (_p, f, _w) in enumerate(slots[:first_missed]) if f & PACK_MAP), None)
    fafs = [n for n, (_p, f, _w) in enumerate(slots[:first_missed])
            if f & PACK_FAF and (map_i is None or n < map_i)]
    faf_i = fafs[-1] if fafs else None
    hold_fix = next((w.id for _p, _f, w in slots[first_missed:] if w.pt in HOLD_PTS and w.id), None)
    for n, (part, f, wp) in enumerate(slots):
        if n == map_i:
            wp.role = "map"
        elif n == faf_i:
            wp.role = "faf"
        elif n >= first_missed and hold_fix and wp.id == hold_fix:
            wp.role = "mahp"
        elif part == "transition" and f & PACK_IAF:
            wp.role = "iaf"


# ---------------------------------------------------------------------------
# Placing a procedure in a route
# ---------------------------------------------------------------------------
def loaded(plan, page_kind):
    """The segment indices *plan* holds for a procedure of *page_kind*."""
    kinds = SEGMENT_KINDS[page_kind]
    return [k for k, seg in enumerate(plan.segments) if seg.kind in kinds]


def _same_fix(a, b):
    return bool(a.id) and a.id == b.id and geo.distance_nm(a.lat, a.lon, b.lat, b.lon) < SAME_FIX_NM


def _plain(seg):
    return seg.kind == "waypoint"


def _airport_waypoint(seg, airport):
    return (_plain(seg) and seg.legs[0].type == "airport"
            and _norm(seg.legs[0].id) == _norm(airport))


def remove(plan, page_kind):
    """Remove *plan*'s procedure of *page_kind*, its whole block (``PROCX``
    in the brief's words): an approach goes with its missed approach.
    Returns True if there was one. A procedure after it whose leading ``IF``
    was merged into this block's last fix gets it back (see :func:`insert`)."""
    ks = loaded(plan, page_kind)
    if not ks:
        return False
    last_leg = plan.segments[ks[-1]].legs[-1]
    nxt = ks[-1] + 1
    for k in reversed(ks):
        del plan.segments[k]
    after = nxt - len(ks)
    if after < len(plan.segments):
        _restore_leading_if(plan.segments[after], last_leg)
    return True


def _restore_leading_if(seg, last_leg):
    """An arrival or approach always opens with an ``IF`` (ARINC 424). One
    that does not had it merged into the fix before it, which is now
    gone: put it back at that fix."""
    if seg.kind not in ("arrival", "approach") or not seg.legs or seg.legs[0].pt == "IF":
        return
    if not last_leg.id:
        return
    seg.legs.insert(0, last_leg.copy(pt="IF", crs=None, dst=0.0, ctr_lat=0.0, ctr_lon=0.0,
                                     turn="", spd=0, flags=last_leg.flags & FLAG_FLYOVER
                                     | FLAG_FROM_PROCEDURE))


def _insert_index(plan, page_kind, airport):
    segs = plan.segments
    if page_kind == "departure":
        return 1 if segs and _airport_waypoint(segs[0], airport) else 0
    if page_kind == "arrival":
        approach = loaded(plan, "approach")
        if approach:
            return approach[0]
    if segs and _airport_waypoint(segs[-1], airport):
        return len(segs) - 1
    return len(segs)


def insert(plan, page_kind, segments, airport):
    """Load *segments* (from :func:`assemble`) into *plan* as its procedure
    of *page_kind*, replacing the one it held (guide p. 3-69: "Loading a
    departure when one is already present will replace the existing
    entry"). Returns the notices for the pilot (a merged fix).

    Placement follows the guide's order: a departure after the departure
    airport (the first waypoint, when it is *airport*), an arrival before
    the approach, an approach at the end -- ahead of the destination
    airport when that is the last waypoint, so removing the approach gives
    the route back as it was.

    Where the block meets the route at the same fix, the fix is kept once:
    two slots at one fix make a zero-length leg, and the engine flies it
    as course 000 until it sequences. A plain waypoint there is dropped (the
    procedure carries the fix); a procedure's leading ``IF`` is merged into
    the procedure before it, and :func:`remove` restores it.

    All or nothing: on :class:`model.FlightPlanError` *plan* is unchanged."""
    if page_kind not in SEGMENT_KINDS:
        raise ProcedureLoadError(f"unknown procedure kind {page_kind!r}")
    before = copy.deepcopy(plan.segments)
    notices = []
    try:
        remove(plan, page_kind)
        if page_kind == "approach":
            pilot = [w.id for s in plan.segments if s.kind not in PROCEDURE_SEGMENT_KINDS
                     for w in s.legs if w.role in ("faf", "map")]
            if pilot:
                raise model.FlightPlanError(
                    f"CLEAR THE FAF/MAP ON {pilot[0]} BEFORE LOADING AN APPROACH")
        at = _insert_index(plan, page_kind, airport)
        new = [model.Segment(kind=s.kind, legs=list(s.legs), ident=s.ident, cycle=s.cycle)
               for s in segments]
        plan.segments[at:at] = new
        end = at + len(new)
        # The fix where the block starts.
        if at > 0:
            prev = plan.segments[at - 1]
            first = new[0].legs[0]
            if _same_fix(prev.legs[-1], first):
                if _plain(prev):
                    notices.append(f"{first.id} MERGED INTO {new[0].ident}")
                    del plan.segments[at - 1]
                    at -= 1
                    end -= 1
                elif first.pt == "IF" and len(new[0].legs) > 1:
                    if prev.legs[-1].role == "none" and first.role != "none":
                        prev.legs[-1].role = first.role
                    del new[0].legs[0]
        # The fix where it ends.
        if end < len(plan.segments):
            nxt = plan.segments[end]
            last = new[-1].legs[-1]
            if _same_fix(last, nxt.legs[0]):
                if _plain(nxt):
                    notices.append(f"{last.id} MERGED INTO {new[-1].ident}")
                    del plan.segments[end]
                elif nxt.legs[0].pt == "IF" and len(nxt.legs) > 1:
                    if last.role == "none" and nxt.legs[0].role != "none":
                        last.role = nxt.legs[0].role
                    del nxt.legs[0]
        if plan.count > model.MAX_WAYPOINTS:
            raise model.FlightPlanError(
                f"ROUTE FULL -- {new[0].ident} NEEDS {sum(len(s.legs) for s in new)} SLOTS")
    except model.FlightPlanError:
        plan.segments[:] = before
        raise
    return notices


def leg_label(wp):
    """What a slot is called in a list: its fix, or for a leg without one
    what ends it (``075° TO +700`` for a climb, ``HDG 255°`` for a vector)."""
    if wp.id:
        return wp.id
    crs = "" if wp.crs is None else "%03d°" % (int(round(wp.crs)) % 360 or 360)
    if wp.pt in ("CA", "FA") and wp.alt:
        return f"{crs} TO {wp.alt}".strip()
    if wp.pt in ("VA", "VI", "VM"):
        return f"HDG {crs}".strip()
    return f"{wp.pt} {crs}".strip()
