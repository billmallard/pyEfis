#  SPDX-License-Identifier: GPL-2.0-or-later
"""A pilot-built hold at any fix, from the clearance ATC gives (HOLDFIX1,
AER-6210; brief ``makerplane/briefs/hold_at_any_fix_spike.md``).

The fix-gateway engine flies an ``HM`` slot at any fix: inbound course
``FPLfCRS`` (magnetic, as for ``CF``), leg ``FPLfDST`` and turns
``FPLfTURN``. A clearance is not given that way. ATC says "hold southeast
of X on the 130 radial, left turns, 10-mile legs", so this module turns
the clearance into those fields.

What it decides, so a reviewer can see each choice:

- **Direction and radial.** The direction is the side of the fix the
  pattern lies on, one of the eight compass points. A radial (or a bearing
  from the fix) lies on that side, and the inbound course is its
  reciprocal: the 130 radial gives inbound 310. Given only a direction, the
  radial is the direction itself (north: the 360 radial, inbound 180).
- **An inbound course instead.** "Hold on the inbound course" names the
  course flown to the fix. The pattern then lies on the reciprocal side.
- **A radial on the wrong side is refused**, not corrected: more than
  ``SIDE_TOLERANCE_DEG`` between the radial and the direction is a
  mis-entry (north of the fix on the 130 radial), and the pilot is told.
- **Turns** are right unless the clearance says left (AIM 5-3-8).
- **The leg** is minutes or miles. The bus carries no leg time, so minutes
  are turned into ``FPLfDST`` at the hold speed with :func:`minutes_to_nm`,
  the conversion ``proc_load`` applies to a coded ``T010``. The default is
  one minute at or below 14,000 ft MSL and 1.5 minutes above (AIM 5-3-8).
- **As published** (HOLDFIX3, AER-6328). The navaids pack carries the
  holds NASR publishes (``holds``, built by ``tools/build_navaid_db.py``).
  :func:`published_holds` finds those at a fix, and the editor fills its
  fields from one: side, inbound course (magnetic), turns and leg. NASR
  never publishes a leg time, so a timed hold gets the AIM 5-3-8 standard
  time and is marked STD TIME (Bill, AER-6328): the chart can say 2 MIN
  and nothing in the data shows it. The fields go through the same checks
  as a typed clearance, so a published hold whose direction contradicts
  its inbound course (38 in AIRAC 2611) is refused, not corrected.
- **The slot** is the fix again, as ``HM``, right after the fix it holds
  at (``TF X, HM X``, the way a procedure codes a hold). The engine starts
  such a slot on its outbound leg once the fix is reached
  (``COINCIDENT_FIX_NM``). It carries no role and no flags, so it is never
  mistaken for a leg from a coded procedure.

Hold at present position (HOLDFIX2, AER-6322) is the same hold at a
fix that is not in the plan yet: a user waypoint ``PPOS`` where the
aircraft is, then the ``HM`` on it, inbound on the present track. Both go
in front of the active leg's TO fix, so exiting the hold flies on to the
fix the aircraft was going to (:func:`ppos_insert_index`).

Qt-free: nothing here may import PyQt6.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass

from . import geo
from . import model

#: The eight directions a clearance gives, clockwise from north, and the
#: bearing from the fix each one names (magnetic, like the radial).
DIRECTIONS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
DIRECTION_BEARING = {d: 45.0 * n for n, d in enumerate(DIRECTIONS)}

#: How far a radial may lie from the named direction. Half the gap to the
#: next direction but one: the radial is in the named octant or halfway
#: into a neighbour, which a controller would still call that side.
SIDE_TOLERANCE_DEG = 45.0

#: AIM 5-3-8: the inbound leg is one minute at or below 14,000 ft MSL,
#: 1.5 minutes above.
LEG_TIME_BREAK_FT = 14000.0
LEG_MIN_LOW = 1.0
LEG_MIN_HIGH = 1.5

TURNS = ("L", "R")
DEFAULT_TURN = "R"
LEG_UNITS = ("MIN", "NM")

#: The hold path terminator this module builds (hold until the pilot exits).
HOLD_PT = "HM"
HOLD_PTS = frozenset({"HM", "HF", "HA"})
#: FPLfFLAGS 0x20, "from a coded procedure" (``proc_load.FLAG_FROM_PROCEDURE``;
#: not imported, since ``proc_load`` imports this module).
FLAG_FROM_PROCEDURE = 0x20


#: The ident of the user waypoint a hold at present position is built on.
PPOS_IDENT = "PPOS"
#: How close a slot read back from the bus must be to the PPOS fix built
#: here to be that fix (about 10 m; the bus may not carry every digit).
PPOS_MATCH_DEG = 1e-4


#: Short names for the charts a published hold is on, for its line in the
#: chooser. A name not listed is shown as NASR gives it.
CHART_SHORT = {
    "ENROUTE LOW": "ENR LOW", "ENROUTE HIGH": "ENR HIGH", "STAR": "STAR",
    "MILITARY STAR": "MIL STAR", "AREA": "AREA", "SPECIAL ENROUTE": "SPC ENR",
    "IAP": "IAP", "MILITARY IAP": "MIL IAP", "SPECIAL IAP": "SPC IAP",
    "SID": "SID", "SPECIAL DP": "SPC DP", "NOT REQUIRED": "NOT REQ",
}
#: Charts that make a hold an enroute or arrival hold, listed first.
ENROUTE_CHARTS = frozenset({"ENROUTE LOW", "ENROUTE HIGH", "STAR", "MILITARY STAR",
                            "AREA", "SPECIAL ENROUTE"})

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PublishedHold:
    """One NASR hold at a fix, as the editor needs it. ``leg_nm`` None is
    a timed hold: the time is not published."""
    hp_name: str
    hp_no: int
    direction: str
    inbound: float
    turn: str
    leg_nm: float | None
    charts: tuple[str, ...]


def published_holds(db_path, fix: model.Waypoint) -> list[PublishedHold]:
    """The published holds at *fix* in ``navaids.sqlite`` at *db_path*:
    the ident must match and the point lie within ``model.SAME_FIX_NM``.
    Enroute and arrival holds come first. Never raises: no path, an older
    pack without the ``holds`` table, or a bad file all give ``[]``."""
    if not db_path or not fix.id:
        return []
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            rows = con.execute(
                "SELECT hp_name, hp_no, lat, lon, hold_dir, inbound_crs, turn, leg_nm,"
                " charts FROM holds WHERE point_id = ?", (fix.id,)).fetchall()
        finally:
            con.close()
    except sqlite3.Error as e:
        log.info("published_holds: %s: %s", db_path, e)
        return []
    out = []
    for name, no, lat, lon, direction, inbound, turn, leg, charts in rows:
        if (lat is None or lon is None or inbound is None or turn not in TURNS
                or geo.distance_nm(lat, lon, fix.lat, fix.lon) >= model.SAME_FIX_NM):
            continue
        out.append(PublishedHold(
            hp_name=name, hp_no=no,
            direction=direction or nearest_direction(inbound + 180.0),
            inbound=norm_course(inbound), turn=turn,
            leg_nm=float(leg) if leg else None,
            charts=tuple(c for c in (charts or "").split("|") if c)))
    out.sort(key=lambda h: (not ENROUTE_CHARTS.intersection(h.charts), h.hp_no, h.hp_name))
    return out


def published_text(h: PublishedHold) -> str:
    """The hold's line in the chooser: ``SE INB 310° R 10 NM ENR LOW``."""
    leg = f"{h.leg_nm:g} NM" if h.leg_nm is not None else "STD TIME"
    charts = "/".join(CHART_SHORT.get(c, c) for c in h.charts[:2])
    return " ".join(t for t in (h.direction, "INB", course_text(h.inbound), h.turn,
                                leg, charts) if t)


class HoldError(ValueError):
    """A clearance that cannot be built as entered. The message is shown
    to the pilot as is."""


def norm_course(deg: float) -> float:
    return float(deg) % 360.0


def course_text(deg: float) -> str:
    """``310°``; north reads ``360°``, as a course is spoken."""
    return "%03d°" % (int(round(norm_course(deg))) % 360 or 360)


def angle_between(a: float, b: float) -> float:
    """The smaller angle between two bearings, 0..180."""
    d = abs(norm_course(a) - norm_course(b))
    return min(d, 360.0 - d)


def nearest_direction(bearing: float) -> str:
    """The compass point nearest *bearing* from the fix."""
    return DIRECTIONS[int(((norm_course(bearing) + 22.5) % 360.0) // 45.0)]


def inbound_course(direction: str, radial: float | None = None,
                   inbound: float | None = None) -> float:
    """The inbound course (magnetic) for a hold *direction* of the fix, on
    *radial* (from the fix), or on the *inbound* course to it. With neither,
    the radial is the direction itself. Raises :class:`HoldError` when the
    radial does not lie on the *direction* side."""
    if direction not in DIRECTION_BEARING:
        raise HoldError(f"NO DIRECTION {direction!r}")
    if radial is not None and inbound is not None:
        raise HoldError("RADIAL OR INBOUND COURSE, NOT BOTH")
    if inbound is not None:
        radial = norm_course(inbound + 180.0)
    elif radial is None:
        radial = DIRECTION_BEARING[direction]
    radial = norm_course(radial)
    if angle_between(radial, DIRECTION_BEARING[direction]) > SIDE_TOLERANCE_DEG:
        what = (f"INBOUND {course_text(inbound)}" if inbound is not None
                else f"RADIAL {course_text(radial)}")
        raise HoldError(f"{what} IS NOT {direction} OF THE FIX")
    return norm_course(radial + 180.0)


def default_leg_minutes(alt_ft: float | None) -> float:
    """AIM 5-3-8 leg time for an altitude in ft MSL; one minute when the
    altitude is unknown."""
    if alt_ft is not None and alt_ft > LEG_TIME_BREAK_FT:
        return LEG_MIN_HIGH
    return LEG_MIN_LOW


def minutes_to_nm(minutes: float, hold_speed_kt: float) -> float:
    """A timed hold leg as the distance the bus carries: *minutes* at
    *hold_speed_kt*, to 0.01 nm. The one conversion for a coded ``T010``
    (``proc_load``) and a pilot hold alike."""
    return round(float(minutes) * float(hold_speed_kt) / 60.0, 2)


def leg_nm(value: float, unit: str, hold_speed_kt: float) -> float:
    """The leg *value* in *unit* (``MIN`` or ``NM``) as ``FPLfDST``."""
    if unit not in LEG_UNITS:
        raise HoldError(f"NO LEG UNIT {unit!r}")
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise HoldError("BAD LEG") from None
    if not value > 0.0:
        raise HoldError("LEG MUST BE MORE THAN 0")
    nm = minutes_to_nm(value, hold_speed_kt) if unit == "MIN" else round(value, 2)
    if nm <= 0.0:
        raise HoldError("LEG MUST BE MORE THAN 0")
    return nm


def arrival_course(plan: model.FlightPlan, i: int, magvar: float,
                   aircraft: tuple[float, float] | None = None) -> float | None:
    """The magnetic course of the leg into flat waypoint *i*, the default
    inbound course ("hold as you arrive"). A coded course (``CF``) is used
    as coded. Otherwise the great circle from the fix before, measured at
    the fix; for the first fix, from *aircraft* when known. None when there
    is nothing to measure from.

    Slots just before *i* at the same point are the same arrival, not a
    leg: a departure or airway that ends at the fix the next segment starts
    from codes the fix twice (bench, AER-6210: VTU after FLOUT5, then
    V485 from VTU). The leg into the fix is the one into the first of
    them."""
    wps = plan.waypoints
    fix = wps[i]
    if fix.crs is not None:
        return norm_course(fix.crs)
    while i > 0 and geo.distance_nm(wps[i - 1].lat, wps[i - 1].lon,
                                    fix.lat, fix.lon) < model.SAME_FIX_NM:
        i -= 1
    if wps[i].crs is not None:
        return norm_course(wps[i].crs)
    if i > 0:
        frm = (wps[i - 1].lat, wps[i - 1].lon)
    elif aircraft is not None:
        frm = aircraft
    else:
        return None
    if geo.distance_nm(frm[0], frm[1], fix.lat, fix.lon) < model.SAME_FIX_NM:
        return None
    # The course at the fix is the reciprocal of the bearing back to the
    # leg's start: a long leg's course changes along the great circle.
    back = geo.initial_bearing(fix.lat, fix.lon, frm[0], frm[1])
    return norm_course(back + 180.0 + magvar)


def hold_waypoint(fix: model.Waypoint, inbound: float, turn: str,
                  dst_nm: float) -> model.Waypoint:
    """The ``HM`` slot for a hold at *fix*: the same point and ident, with
    the hold's inbound course (magnetic), turns and leg, and nothing the
    fix's own leg carried (role, constraints, flags, comment)."""
    if turn not in TURNS:
        raise HoldError(f"NO TURN {turn!r}")
    if not fix.id:
        raise HoldError("A HOLD NEEDS A FIX")
    return model.Waypoint(id=fix.id, type=fix.type, lat=fix.lat, lon=fix.lon,
                          name=fix.name, pt=HOLD_PT, crs=round(norm_course(inbound), 1),
                          dst=float(dst_nm), turn=turn)


def can_hold_at(plan: model.FlightPlan, i: int) -> bool:
    """A hold can be built at flat waypoint *i*: it is a fix (not a leg
    without one), not a hold itself, and not already followed by a hold
    at the same fix."""
    wps = plan.waypoints
    if not (0 <= i < len(wps)):
        return False
    fix = wps[i]
    if not fix.id or fix.pt in HOLD_PTS:
        return False
    nxt = wps[i + 1] if i + 1 < len(wps) else None
    return not (nxt is not None and nxt.pt in HOLD_PTS and model.same_fix(fix, nxt))


def is_pilot_hold(wp: model.Waypoint) -> bool:
    """A hold slot the pilot built here, not one coded in a procedure."""
    return wp.pt in HOLD_PTS and not wp.flags & FLAG_FROM_PROCEDURE


def present_position_waypoint(lat: float, lon: float) -> model.Waypoint:
    """The user waypoint a hold at present position holds at: ``PPOS``
    at *lat*, *lon*. It lives in the plan only; the pilot's user waypoint
    file is not written, so a second PPOS hold never collides with the
    first one or with a waypoint the pilot named PPOS."""
    return model.Waypoint(id=PPOS_IDENT, type="user", lat=float(lat), lon=float(lon))


def ppos_insert_index(plan: model.FlightPlan, active_leg: int | None) -> int:
    """The flat index the ``PPOS`` fix goes at, with its hold right after.

    In front of the active leg's TO fix (``FPLACTLEG`` *active_leg*,
    1-based), so the hold sits on the way there and exiting it flies on
    to that fix. When the active slot is itself a hold, after it: a new
    hold clearance replaces that one, and its fix and hold slot stay one
    pair. With nothing active, at the start of the plan."""
    wps = plan.waypoints
    if not active_leg or not (1 <= active_leg <= len(wps)):
        return 0
    i = active_leg - 1
    return i + 1 if wps[i].pt in HOLD_PTS else i


def is_ppos_pair(plan: model.FlightPlan, i: int, fix: model.Waypoint) -> bool:
    """Flat slots *i* and *i* + 1 are the ``PPOS`` fix *fix* and its hold."""
    wps = plan.waypoints
    if not (0 <= i and i + 1 < len(wps)):
        return False
    a, h = wps[i], wps[i + 1]
    return (a.id == fix.id and a.pt not in HOLD_PTS and h.pt in HOLD_PTS
            and abs(a.lat - fix.lat) < PPOS_MATCH_DEG and abs(a.lon - fix.lon) < PPOS_MATCH_DEG
            and model.same_fix(a, h))
