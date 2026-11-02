#  SPDX-License-Identifier: GPL-2.0-or-later
"""Ground paths of procedure legs, for drawing (PA8, billmallard/pyEfis#239).

Turns the route block on the bus (``fixbridge.RouteSlot``: ``FPLfPT``,
``FPLfCRS``, ``FPLfDST``, ``FPLfTURN``, ``FPLfCTRLAT``/``CTRLON``) into a
lat/lon polyline per leg, following the geometry the fix-gateway engine
flies (``fixgw.plugins.flightplan.engine``; the leg types are listed in
fix-gateway ``doc/flightplan_keys.md``):

- ``IF``/``TF`` and a ``DF`` with no coded turn: the great circle from the
  previous point, as the map has always drawn every leg.
- ``DF`` with a coded turn (``FPLfTURN`` ``L``/``R``): a turn in the coded
  direction from the course the previous leg ends on, then straight to the
  fix. Never the short way when the data says otherwise (KSSF RNAV 28's
  missed approach turns right, the long way round, to GANLE).
- ``CF``/``CA``: along the coded course (``FPLfCRS``, magnetic). A ``CA``
  has no fix; its slot carries a point on the course line, and the leg is
  drawn to that point.
- ``RF``/``AF``: a real arc around ``FPLfCTRLAT``/``CTRLON`` in the coded
  turn direction, tessellated, not a chord.
- ``HM``/``HF``/``HA``: the leg into the fix, plus the racetrack the engine
  flies (``_hold_geometry``): turn out, outbound ``FPLfDST`` along-track,
  turn in, inbound to the fix.
- ``PI``: the leg into the fix, plus the 45/180 procedure turn shape: the
  engine's outbound point (reciprocal +-45 deg, ``FPLfDST`` out), the
  reversal, and the 45 deg intercept back to the inbound course.
- ``VA``/``VM``/``VI``/``FM``: a short stub along the coded heading or
  course, drawn as "to be vectored" (guardrail 4: the box flies no heading,
  so the map draws none past the stub either).

Every point is computed once per route commit (the map layer's
``collect``), never per frame. Turn and racetrack radii use a nominal
standard-rate turn at :data:`NOMINAL_GS_KT`: the engine sizes its own from
live groundspeed, which a chart-like depiction should not follow.

Qt-free: nothing here may import PyQt6.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import geo

#: the groundspeed the drawn turn and racetrack radii are sized for. A
#: standard-rate (3 deg/s) turn at 120 kt has a 0.64 NM radius.
NOMINAL_GS_KT = 120.0
TURN_RADIUS_NM = NOMINAL_GS_KT / (60.0 * math.pi)

#: arc tessellation step. At a 0.64 NM turn radius a 5 deg step leaves a
#: chord sag of 0.0006 NM, well under a pixel at the closest map range.
ARC_STEP_DEG = 5.0

#: length of a vector leg's "to be vectored" stub, and of the course-held
#: tail of an FA leg past its fix.
VECTOR_STUB_NM = 3.0
COURSE_STUB_NM = 2.0

#: legs with no fix of their own: no waypoint symbol, no label, no tap target.
NO_FIX_PTS = frozenset({"CA", "VA", "VM", "VI"})
VECTOR_PTS = frozenset({"VA", "VM", "VI", "FM"})
ARC_PTS = frozenset({"RF", "AF"})
HOLD_PTS = frozenset({"HM", "HF", "HA"})


@dataclass
class LegPath:
    """One leg's ground path. ``to_slot`` is the 1-based slot of the leg's
    TO waypoint, the numbering ``FPLACTLEG`` uses. ``points`` run from the
    leg's start to its end. ``vector`` marks a "to be vectored" stub.
    ``pattern`` holds the racetrack or procedure-turn polyline flown at the
    fix, drawn in the leg's colour."""

    to_slot: int
    points: list = field(default_factory=list)
    vector: bool = False
    pattern: list = field(default_factory=list)


def _wrap180(deg):
    return (deg + 180.0) % 360.0 - 180.0


def _true(crs_mag, magvar):
    """Magnetic -> true with ``MAGVAR`` positive west (MAG = TRUE + VAR),
    the convention the engine converts ``FPLfCRS`` with."""
    return (crs_mag - magvar) % 360.0


class _Local:
    """Flat east/north plane in NM about an origin. Every pattern here is a
    few NM across, where the flat-plane error is far below a pixel."""

    def __init__(self, lat, lon):
        self.lat0, self.lon0 = lat, lon
        self._k = math.cos(math.radians(lat))

    def xy(self, lat, lon):
        return ((lon - self.lon0) * 60.0 * self._k, (lat - self.lat0) * 60.0)

    def ll(self, x, y):
        return (self.lat0 + y / 60.0, self.lon0 + x / (60.0 * self._k))


def _unit(brg):
    r = math.radians(brg)
    return math.sin(r), math.cos(r)


def _bearing_xy(ax, ay, bx, by):
    return math.degrees(math.atan2(bx - ax, by - ay)) % 360.0


def turn_to_fix(start, course, turn, fix, radius_nm=TURN_RADIUS_NM):
    """A turn from *start* on true *course*, in direction *turn* (``"R"``
    clockwise seen from above, ``"L"`` anticlockwise), until the aircraft
    points at *fix*, then straight to it. Returns the ``[(lat, lon), ...]``
    path from *start* to *fix*. When the fix lies inside the turn circle
    (no tangent exists) the path is the plain straight line, the same
    geometry a ``DF`` had before the turn was drawn."""
    loc = _Local(*start)
    fx, fy = loc.xy(*fix)
    s = 1.0 if turn == "R" else -1.0
    ux, uy = _unit(course + s * 90.0)
    cx, cy = radius_nm * ux, radius_nm * uy
    if math.hypot(fx - cx, fy - cy) <= radius_nm * 1.0001:
        return [start, fix]

    def at(sweep):
        heading = course + s * sweep
        bx, by = _unit(heading + s * 90.0 + 180.0)
        return heading, cx + radius_nm * bx, cy + radius_nm * by

    def rel(sweep):
        heading, x, y = at(sweep)
        return s * _wrap180(_bearing_xy(x, y, fx, fy) - heading)

    pts = [start]
    prev = rel(0.0)
    if abs(prev) < 1e-6:
        return [start, fix]
    sweep = 0.0
    end_sweep = None
    while sweep < 360.0:
        nxt = min(sweep + ARC_STEP_DEG, 360.0)
        cur = rel(nxt)
        if prev > 0.0 >= cur:
            # Linear refinement inside this step.
            end_sweep = sweep + (nxt - sweep) * prev / (prev - cur)
            break
        sweep = nxt
        prev = cur
        _, x, y = at(sweep)
        pts.append(loc.ll(x, y))
    if end_sweep is None:
        return [start, fix]
    _, x, y = at(end_sweep)
    pts.append(loc.ll(x, y))
    pts.append(fix)
    return pts


def arc_points(center, radius_nm, start, end, turn):
    """The arc around *center* at *radius_nm* from *start*'s radial to
    *end*'s radial, clockwise for ``turn == "R"``, ending exactly at *end*."""
    r0 = geo.initial_bearing(center[0], center[1], start[0], start[1])
    r1 = geo.initial_bearing(center[0], center[1], end[0], end[1])
    if turn == "R":
        sweep = (r1 - r0) % 360.0
        step = ARC_STEP_DEG
    else:
        sweep = (r0 - r1) % 360.0
        step = -ARC_STEP_DEG
    n = max(1, int(math.ceil(sweep / ARC_STEP_DEG)))
    pts = [start]
    for i in range(1, n):
        pts.append(geo.destination_point(center[0], center[1], r0 + step * i, radius_nm))
    pts.append(end)
    return pts


def _semicircle(loc, cx, cy, from_brg, clockwise, radius_nm):
    """Points on a half circle about (cx, cy): starting at the radial
    *from_brg*, sweeping 180 deg."""
    out = []
    step = ARC_STEP_DEG if clockwise else -ARC_STEP_DEG
    for i in range(1, int(180.0 / ARC_STEP_DEG) + 1):
        bx, by = _unit(from_brg + step * i)
        out.append(loc.ll(cx + radius_nm * bx, cy + radius_nm * by))
    return out


def hold_pattern(fix, inbound_true, turn, leg_nm, radius_nm=TURN_RADIUS_NM):
    """The racetrack the engine flies at *fix* (``_hold_geometry``): turn
    out from the fix, the outbound leg two radii abeam the inbound course
    ending *leg_nm* along-track from the fix, the turn in, and the inbound
    leg back to the fix. Returns a closed ``[(lat, lon), ...]``."""
    loc = _Local(*fix)
    s = 1.0 if turn == "R" else -1.0
    clockwise = turn == "R"
    side = inbound_true + s * 90.0
    out_brg = inbound_true + 180.0
    sx, sy = _unit(side)
    ox, oy = _unit(out_brg)
    pts = [fix]
    # Turn out: centred one radius toward the holding side, from the fix.
    pts += _semicircle(loc, radius_nm * sx, radius_nm * sy, side + 180.0, clockwise, radius_nm)
    # Outbound to leg_nm along-track, then turn in onto the inbound course.
    ex, ey = leg_nm * ox, leg_nm * oy
    pts.append(loc.ll(ex + 2.0 * radius_nm * sx, ey + 2.0 * radius_nm * sy))
    pts += _semicircle(loc, ex + radius_nm * sx, ey + radius_nm * sy, side, clockwise, radius_nm)
    pts.append(fix)
    return pts


def procedure_turn_pattern(fix, inbound_true, turn, leg_nm, radius_nm=TURN_RADIUS_NM):
    """The 45/180 procedure turn at *fix*: out to the engine's outbound
    point (``_hold_outbound_target``: reciprocal of the inbound course,
    offset 45 deg toward *turn*, *leg_nm* out), a 180 deg reversal the other
    way, then 45 deg back to intercept the inbound course and on to the
    fix. Returns ``[(lat, lon), ...]`` from the fix back to the fix."""
    loc = _Local(*fix)
    s = 1.0 if turn == "R" else -1.0
    out_brg = inbound_true + 180.0 + s * 45.0
    tx, ty = _unit(out_brg)
    tx, ty = leg_nm * tx, leg_nm * ty
    pts = [fix, loc.ll(tx, ty)]
    # Reversal: opposite to the offset turn, so centred on the far side of
    # the outbound track from the inbound course.
    rev_clockwise = turn != "R"
    ns = 1.0 if rev_clockwise else -1.0
    ux, uy = _unit(out_brg + ns * 90.0)
    cx, cy = tx + radius_nm * ux, ty + radius_nm * uy
    pts += _semicircle(loc, cx, cy, out_brg + ns * 90.0 + 180.0, rev_clockwise, radius_nm)
    # After the reversal the heading is the inbound course +-45; intercept.
    bx, by = _unit(out_brg + ns * 90.0)
    px, py = cx + radius_nm * bx, cy + radius_nm * by
    hx, hy = _unit(out_brg + 180.0)
    ix, iy = _unit(inbound_true)
    # Solve P + t*h = u*i (the inbound course line through the fix).
    det = hx * (-iy) - hy * (-ix)
    if abs(det) > 1e-9:
        t = (px * (-iy) - py * (-ix)) / -det
        if t > 0:
            pts.append(loc.ll(px + t * hx, py + t * hy))
    pts.append(fix)
    return pts


def _has_point(slot):
    return not (slot.lat == 0.0 and slot.lon == 0.0)


def build_leg_paths(slots, magvar=0.0):
    """``[LegPath, ...]`` for every leg of *slots* (``fixbridge.RouteSlot``
    in slot order), one per slot after the first. *magvar* is ``MAGVAR``
    (positive west), used to turn the coded magnetic courses true."""
    out = []
    if not slots:
        return out
    first = slots[0]
    pos = (first.lat, first.lon)
    course = None   # true course the previous leg ends on, None if unknown
    for i in range(1, len(slots)):
        w = slots[i]
        fix = (w.lat, w.lon)
        leg = LegPath(to_slot=i + 1)
        pt = (w.pt or "TF").upper()
        if pt in ("CA", "VA", "VM", "VI"):
            crs = _true(w.crs, magvar)
            if pt == "CA":
                d = geo.distance_nm(pos[0], pos[1], *fix) if _has_point(w) else 0.0
                length = min(max(d, 0.5), 10.0) if d else COURSE_STUB_NM
            else:
                length = VECTOR_STUB_NM
                leg.vector = True
            end = geo.destination_point(pos[0], pos[1], crs, length)
            leg.points = [pos, end]
            pos, course = end, crs
        elif pt == "FM":
            crs = _true(w.crs, magvar)
            end = geo.destination_point(fix[0], fix[1], crs, VECTOR_STUB_NM)
            leg.points = [pos, fix]
            leg.pattern = [fix, end]
            leg.vector = True
            pos, course = end, crs
        elif pt == "CF":
            crs = _true(w.crs, magvar)
            d = max(geo.distance_nm(pos[0], pos[1], *fix), 0.1)
            start = geo.destination_point(fix[0], fix[1], (crs + 180.0) % 360.0, d)
            leg.points = [start, fix] if geo.distance_nm(*start, *pos) > 0.05 else [pos, fix]
            pos, course = fix, crs
        elif pt == "DF" and w.turn in ("L", "R") and course is not None:
            leg.points = turn_to_fix(pos, course, w.turn, fix)
            a, b = leg.points[-2], leg.points[-1]
            pos, course = fix, geo.initial_bearing(a[0], a[1], b[0], b[1])
        elif pt in ARC_PTS and w.turn in ("L", "R") and (w.ctr_lat or w.ctr_lon):
            center = (w.ctr_lat, w.ctr_lon)
            radius = w.dst or geo.distance_nm(center[0], center[1], *fix)
            leg.points = arc_points(center, radius, pos, fix, w.turn)
            radial = geo.initial_bearing(center[0], center[1], *fix)
            pos, course = fix, (radial + (90.0 if w.turn == "R" else -90.0)) % 360.0
        else:
            # IF/TF/DF without a turn, FA up to its fix, and the leg into a
            # hold or procedure turn: the great circle from the previous
            # point, as every leg has always been drawn.
            leg.points = [pos, fix]
            course = geo.initial_bearing(pos[0], pos[1], *fix) if pos != fix else course
            pos = fix
            if pt == "FA":
                crs = _true(w.crs, magvar)
                end = geo.destination_point(fix[0], fix[1], crs, COURSE_STUB_NM)
                leg.pattern = [fix, end]
                pos, course = end, crs
            elif pt in HOLD_PTS and w.turn in ("L", "R") and w.dst > 0:
                inbound = _true(w.crs, magvar)
                leg.pattern = hold_pattern(fix, inbound, w.turn, w.dst)
                course = inbound
            elif pt == "PI" and w.turn in ("L", "R") and w.dst > 0:
                inbound = _true(w.crs, magvar)
                leg.pattern = procedure_turn_pattern(fix, inbound, w.turn, w.dst)
                course = inbound
        out.append(leg)
    return out
