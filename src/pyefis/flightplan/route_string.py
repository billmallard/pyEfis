#  SPDX-License-Identifier: GPL-2.0-or-later
"""Route-string import (RTE1, AER-6454): an ATC route, as a clearance or an
EFB's route line gives it, expanded into a ``model.FlightPlan`` from the
panel's own navdata.

``KSBA FLOUT VTU V485 OHIGH TTE V459 LHS KPMD`` carries no coordinates, so
the route is only as good as the packs on the device: every ident and
airway has to resolve there. This module is an adapter onto
``model.FlightPlan``, as ``makerplane/briefs/architecture_audit.md`` section
2.2 recommends (route B): idents through ``waypoints.WaypointIndex``,
airways through ``model.FlightPlan.insert_airway``, procedures through
``proc_load.assemble`` and ``proc_load.insert``. It adds no plan shape and no
FIX key. The caller stages the result for the pilot to accept; nothing here
touches the bus.

The grammar, and what is left out of it:

- **Points**: an airport, navaid, fix or user waypoint by ident. At the two
  ends of the route an airport is preferred, because an ATC route starts
  and ends at one. In between, a navaid or fix is preferred over an airport
  reached only through its three-letter FAA alias (``SMX`` is the VOR, and
  ``KSMX`` the airport); an airport's own ident that is also a navaid's is
  ambiguous.
- **Lat/lon**: ICAO ``DDMMNDDDMMW`` (``3407N11901W``) or ``DDNDDDW``
  (``34N119W``), entered as a user waypoint named as written.
- **Airways**: ``V``, ``J``, ``T`` and ``Q`` routes, between an entry fix and
  an exit fix, the entry being the fix before the airway or the end of the
  SID before it. Two airways need their junction fix between them.
- **DCT** is accepted and means nothing more than its absence: points are
  flown direct.
- **SID**: the token after the departure airport, ``FLOUT5`` or
  ``FLOUT5.VTU``. **STAR**: the token before the destination,
  ``PITBL2`` or ``HEC.PITBL2``. A transition not written with a dot is taken
  from the point next to the procedure when that point names one of its
  transitions, which is how a clearance reads ("FLOUT5 departure, Ventura
  transition"). A route string carries no runway, so a procedure that needs
  one raises :class:`RunwayNeededError` with the choices, unless the caller
  passes it.
- **Left out**: radial-distance points (``VTU090025``) -- the navaids pack
  has no station declination to turn a radial into a true bearing, and the
  aircraft's variation would be a guess. Speed and level groups
  (``N0140A080``, ``VTU/N0140A080``). The FAA's dotted form
  (``KSBA..VTU.V27.GVO``). Each is refused with the token named.

Ambiguity is shown, never guessed (Bill, 2026-11-22). The packs carry no
ICAO region (``architecture_audit.md`` 2.3 finding 5, FPA5), so an ident
that names two places is refused, with one exception that is not a guess:
next to an airway, only the place the airway itself passes through can be
meant. Two records within ``model.SAME_FIX_NM`` of each other are one place
(NASR and CIFP code a navaid a few feet apart). Every unknown and ambiguous
ident is collected and named in one refusal, so the pilot fixes the string
once.

Qt-free: nothing here may import PyQt6.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import geo
from . import model
from . import proc_load

AIRWAY_RE = re.compile(r"^[VJTQ]\d{1,4}$")
LATLON_RE = re.compile(r"^(\d{2})(\d{2})?([NS])(\d{3})(\d{2})?([EW])$")
RADIAL_DISTANCE_RE = re.compile(r"^[A-Z]{2,5}\d{6}$")
SPEED_LEVEL_RE = re.compile(r"^[NKM]\d{3,4}(?:[AFSM]\d{3,4}|VFR)$")
DIRECT = "DCT"

#: Which record wins when two of one ident are one place.
_TYPE_RANK = {"airport": 0, "vor": 1, "ndb": 2, "fix": 3, "user": 4, "map": 5}


class RouteStringError(ValueError):
    """The route cannot be expanded as written. ``str(exc)`` is shown to the
    pilot. *unknown* lists idents the database does not hold, and
    *ambiguous* maps each ident that names more than one place to those
    places (``waypoints.Waypoint``), so a page can offer a choice."""

    def __init__(self, message, unknown=(), ambiguous=None):
        super().__init__(message)
        self.unknown = tuple(unknown)
        self.ambiguous = dict(ambiguous or {})


class RunwayNeededError(RouteStringError):
    """*procedure* at *airport* needs a runway, which a route string does
    not carry. *choices* are its runway transitions (``RW25``); pass one in
    ``runways`` to expand the route."""

    def __init__(self, message, airport, procedure, choices):
        super().__init__(message)
        self.airport = airport
        self.procedure = procedure
        self.choices = tuple(choices)


@dataclass
class _Token:
    text: str
    kind: str  # point | latlon | airway | dct | sid | star
    proc: object = None
    transition: str | None = None
    places: list = field(default_factory=list)


def tokens(text: str) -> list[str]:
    """*text* split into route tokens, upper case."""
    return (text or "").upper().split()


def _latlon(text):
    m = LATLON_RE.match(text)
    if not m:
        return None
    lat_d, lat_m, ns, lon_d, lon_m, ew = m.groups()
    if (lat_m is None) != (lon_m is None):
        return None
    lat = int(lat_d) + int(lat_m or 0) / 60.0
    lon = int(lon_d) + int(lon_m or 0) / 60.0
    if lat > 90 or lon > 180 or int(lat_m or 0) >= 60 or int(lon_m or 0) >= 60:
        return None
    return (-lat if ns == "S" else lat), (-lon if ew == "W" else lon)


def _airport(index, text):
    found = [w for w in index.lookup(text) if w.type == "airport"]
    return found[0] if len(found) == 1 else None


def _procedure(procedures, airport, kind, text):
    """``(proc, transition)`` if *text* names a *kind* procedure at
    *airport*: ``NAME``, ``NAME.TRANS`` or ``TRANS.NAME``."""
    if procedures is None or airport is None or not getattr(procedures, "ready", False):
        return None
    parts = text.split(".")
    if len(parts) == 1:
        proc = procedures.find(airport.id, kind, parts[0])
        return (proc, None) if proc is not None else None
    if len(parts) == 2:
        for name, trans in (parts, parts[::-1]):
            proc = procedures.find(airport.id, kind, name)
            if proc is not None:
                return proc, trans
    return None


def _one_place_each(places):
    """*places* with records of one place folded into the best-ranked one."""
    out = []
    for w in sorted(places, key=lambda w: _TYPE_RANK.get(w.type, 9)):
        if not any(geo.distance_nm(w.lat, w.lon, p.lat, p.lon) < model.SAME_FIX_NM
                   for p in out):
            out.append(w)
    return out


def _candidates(index, text, at_end, pins):
    found = index.lookup(text)
    airports = [w for w in found if w.type == "airport"]
    others = [w for w in found if w.type != "airport"]
    if at_end and airports:
        found = airports
    elif not at_end and airports and others and all(w.id != text for w in airports):
        found = others
    if pins:
        pinned = [w for w in found if any(
            geo.distance_nm(w.lat, w.lon, lat, lon) < model.SAME_FIX_NM for lat, lon in pins)]
        if pinned:
            found = pinned
    return _one_place_each(found)


def _airway_pins(graph, airway, text):
    return [(leg.lat, leg.lon) for leg in graph.legs(airway) if leg.fix_id == text]


def _classify(toks, index, graph, procedures):
    """Every token's kind, and the refusals that need no navdata search."""
    n = len(toks)
    out, unsupported = [], []
    departure = _airport(index, toks[0]) if n >= 3 else None
    destination = _airport(index, toks[-1]) if n >= 3 else None
    graph_ready = graph is not None and getattr(graph, "ready", False)
    for i, t in enumerate(toks):
        if t == DIRECT:
            out.append(_Token(t, "dct"))
            continue
        if "/" in t or SPEED_LEVEL_RE.match(t):
            unsupported.append(f"SPEED/LEVEL NOT SUPPORTED: {t}")
            out.append(_Token(t, "dct"))
            continue
        if _latlon(t) is not None:
            out.append(_Token(t, "latlon"))
            continue
        if i == 1 and n >= 3:
            hit = _procedure(procedures, departure, "sid", t)
            if hit:
                out.append(_Token(t, "sid", proc=hit[0], transition=hit[1]))
                continue
        if i == n - 2 and n >= 3:
            hit = _procedure(procedures, destination, "star", t)
            if hit:
                out.append(_Token(t, "star", proc=hit[0], transition=hit[1]))
                continue
        if 0 < i < n - 1 and AIRWAY_RE.match(t) and graph_ready and graph.legs(t):
            out.append(_Token(t, "airway"))
            continue
        if "." in t:
            unsupported.append(f"NOT A PROCEDURE HERE: {t}")
            out.append(_Token(t, "dct"))
            continue
        if RADIAL_DISTANCE_RE.match(t) and not index.lookup(t):
            unsupported.append(f"RADIAL-DISTANCE NOT SUPPORTED: {t}")
            out.append(_Token(t, "dct"))
            continue
        out.append(_Token(t, "point"))
    return out, unsupported


def _resolve(toks, index, graph):
    """Each point token's places, and the idents that are unknown or name
    more than one place."""
    unknown, ambiguous, both = [], {}, []
    n = len(toks)
    for i, tok in enumerate(toks):
        if tok.kind == "airway":
            places = index.lookup(tok.text)
            if places:
                ambiguous[tok.text] = places
                both.append(tok.text)
            continue
        if tok.kind != "point":
            continue
        pins = []
        for j in (i - 1, i + 1):
            if 0 <= j < n and toks[j].kind == "airway":
                pins.extend(_airway_pins(graph, toks[j].text, tok.text))
        tok.places = _candidates(index, tok.text, i in (0, n - 1), pins)
        if not tok.places:
            unknown.append(tok.text)
        elif len(tok.places) > 1:
            ambiguous[tok.text] = tok.places
    messages = []
    if unknown:
        messages.append("NOT FOUND: " + ", ".join(dict.fromkeys(unknown)))
    places = [k for k in ambiguous if k not in both]
    if places:
        messages.append("TWO PLACES NAMED: " + ", ".join(places))
    messages.extend(f"{k} IS AN AIRWAY AND A WAYPOINT" for k in both)
    return unknown, ambiguous, messages


def _model_waypoint(w):
    return model.Waypoint(id=w.id, type=w.type, lat=w.lat, lon=w.lon, name=w.name or "")


def _append(plan, wp):
    legs = plan.waypoints
    if legs and model.same_fix(legs[-1], wp):
        # Written twice, as "FLOUT5.VTU VTU V27" does: one slot.
        return
    plan.insert_after(plan.count - 1, wp)


def _implicit_transition(index, proc, neighbour):
    if neighbour is None or neighbour.kind != "point":
        return None
    names = proc_load.transition_choices(index, proc)
    return neighbour.text if neighbour.text in names else None


def _load_procedure(plan, tok, page_kind, airport, neighbour, procedures, runways, kw):
    proc = tok.proc
    name = proc_load.procedure_name(proc)
    transition = tok.transition or _implicit_transition(procedures, proc, neighbour)
    choices = proc_load.transition_choices(procedures, proc)
    if transition is None:
        if proc_load.NO_TRANSITION not in choices:
            raise RouteStringError(f"{name}: NAME ITS TRANSITION ({', '.join(choices)})")
        transition = proc_load.NO_TRANSITION
    runway = None
    if proc_load.needs_runway(procedures, proc):
        runway = (runways or {}).get(airport.id)
        if not runway:
            rw = proc_load.runway_choices(procedures, proc)
            raise RunwayNeededError(f"{name} NEEDS A RUNWAY: {', '.join(rw)}",
                                    airport.id, name, rw)
        runway = proc_load.runway_label(runway)
    try:
        segments = proc_load.assemble(procedures, proc, transition, runway, origin=airport, **kw)
        proc_load.insert(plan, page_kind, segments, airport.id)
    except (proc_load.ProcedureLoadError, model.FlightPlanError) as e:
        raise RouteStringError(str(e)) from e


def expand(text, index, graph=None, procedures=None, *, runways=None, magvar=0.0,
           hold_speed_kt=proc_load.HOLD_SPEED_KT, resolve_navaid=None) -> model.FlightPlan:
    """The route *text* as a new ``model.FlightPlan``.

    *index* is a ``waypoints.WaypointIndex``, *graph* an
    ``airways.AirwayGraph`` and *procedures* a ``procedures.ProcedureIndex``;
    without the last two, an airway or a procedure is not recognised and
    reads as an unknown ident. *runways* maps an airport ident to the
    runway for its SID or STAR (``{"KSBA": "RW25"}``). *magvar*,
    *hold_speed_kt* and *resolve_navaid* are passed to
    ``proc_load.assemble``, as the PROC page passes them.

    Raises :class:`RouteStringError` naming every unknown or ambiguous
    ident, or the first token that cannot be expanded; never returns part of
    a route."""
    toks = tokens(text)
    if not toks:
        raise RouteStringError("ENTER A ROUTE")
    classified, unsupported = _classify(toks, index, graph, procedures)
    unknown, ambiguous, messages = _resolve(classified, index, graph)
    if unsupported or messages:
        raise RouteStringError("; ".join(messages + unsupported), unknown, ambiguous)

    kw = {"magvar": magvar, "hold_speed_kt": hold_speed_kt, "resolve_navaid": resolve_navaid}
    plan = model.FlightPlan(source="route", comment=" ".join(toks))
    n = len(classified)
    consumed = set()
    try:
        for i, tok in enumerate(classified):
            prev = classified[i - 1] if i > 0 else None
            nxt = classified[i + 1] if i + 1 < n else None
            if i in consumed or tok.kind == "dct":
                continue
            if tok.kind == "point":
                _append(plan, _model_waypoint(tok.places[0]))
            elif tok.kind == "latlon":
                lat, lon = _latlon(tok.text)
                _append(plan, model.Waypoint(id=tok.text, type="user", lat=lat, lon=lon))
            elif tok.kind == "airway":
                if prev is None or prev.kind not in ("point", "sid") or plan.count == 0:
                    raise RouteStringError(f"{tok.text} NEEDS AN ENTRY FIX")
                if nxt is None or nxt.kind != "point":
                    raise RouteStringError(f"{tok.text} NEEDS AN EXIT FIX")
                plan.insert_airway(plan.count - 1, tok.text, nxt.places[0].id, graph)
                consumed.add(i + 1)
            elif tok.kind == "sid":
                _load_procedure(plan, tok, "departure", classified[0].places[0], nxt,
                                procedures, runways, kw)
            elif tok.kind == "star":
                _load_procedure(plan, tok, "arrival", classified[-1].places[0], prev,
                                procedures, runways, kw)
    except model.FlightPlanError as e:
        raise RouteStringError(str(e).upper()) from e
    if plan.count < 2:
        raise RouteStringError("A ROUTE NEEDS TWO POINTS")
    plan.name = plan.default_name()
    return plan
