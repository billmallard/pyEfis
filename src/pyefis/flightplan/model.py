#  SPDX-License-Identifier: GPL-2.0-or-later
"""Route model (FP4, RS2): the editor's in-memory ``FlightPlan`` and its
``mp-route/2`` JSON form. See ``makerplane/briefs/flight_plan_plan.md``
section 3.4 Appendix B, ``makerplane/briefs/route_segments_plan.md``
section 4, and billmallard/pyEfis#183 / #305.

A route is an ordered list of :class:`Segment`, and each segment owns a
contiguous run of legs (RS2). A plain waypoint is a one-leg ``waypoint``
segment; an airway is one ``airway`` segment holding every fix from its
entry to its exit, inclusive. ``FlightPlan.waypoints`` is the flat, derived
view of every segment's legs in order, so a reader that only wants the leg
list keeps working. It is a tuple: changing a leg's attributes through it is
fine, but adding or removing legs goes through the segment operations below.

Mutating methods change the plan in place -- the editor keeps one working
copy and commits it via ``fixbridge.FixBridge.publish`` after every edit
(section 3.4: "the pyEfis editor keeps a working copy, commits every change
immediately"). ``invert()`` is the one method that returns a new plan,
matching the GNX guide's "Invert & Activate (a copy; the stored plan is
unchanged)".

The airway operations take an ``AirwayGraph`` (``airways.py``) as an
argument instead of importing it: ``airways.py`` imports this module, and the
model stays usable without a procedures pack.

Qt-free: nothing here may import PyQt6.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import geo

SCHEMA = "mp-route/2"
SCHEMA_V1 = "mp-route/1"
# Must match fixbridge.MAX_SLOTS, the FPL1..FPLn bus block width the engine
# actually publishes. PA3 (fix-gateway#27) grew that block 50->100
# (AER-1709), but this constant -- the model-layer cap enforced before a
# route ever reaches the bridge -- was never bumped to match, so every
# route was capped at half the engine's real capacity. Surfaced live by
# AER-1605: inserting a real-world Victor airway (V27, 88 published fixes)
# routinely needs more than 50 total waypoints.
MAX_WAYPOINTS = 100

WAYPOINT_TYPES = ("airport", "vor", "ndb", "fix", "user", "map")
ROLES = ("none", "iaf", "faf", "map", "mahp")

# The segment table's FPLSsKIND, in wire order (RS1, fix-gateway
# doc/flightplan_keys.md). Kind 0 is one waypoint the pilot entered -- not a
# Direct-To, which never touches the table.
SEGMENT_KINDS = ("waypoint", "airway", "departure", "arrival", "approach", "missed")
SEGMENT_IDENT_MAX_LEN = 24

# Appendix A: FPLfTYPE 0..6. Role<->FPLfFLAGS translation lives in
# fixbridge.py, the only module that talks to the bus.
TYPE_TO_FPLTYPE = {"unknown": 0, "airport": 1, "vor": 2, "ndb": 3, "fix": 4, "user": 5, "map": 6}
FPLTYPE_TO_TYPE = {v: k for k, v in TYPE_TO_FPLTYPE.items()}

NAME_MAX_LEN = 32
# Leg fields (PA3) default to a plain TF leg with no constraints; to_json
# omits a field at its default so an ordinary route file stays readable.
_LEG_DEFAULTS = {"pt": "TF", "crs": None, "dst": 0.0, "alt": "", "spd": 0, "flags": 0,
                 "ctr_lat": 0.0, "ctr_lon": 0.0, "turn": ""}
_WAYPOINT_KNOWN_FIELDS = frozenset(
    {"id", "type", "lat", "lon", "name", "alt_ft", "comment", "role"} | set(_LEG_DEFAULTS))
_SEGMENT_KNOWN_FIELDS = frozenset({"kind", "ident", "entry", "exit", "cycle", "legs"})
_PLAN_KNOWN_FIELDS = frozenset(
    {"schema", "name", "comment", "created", "modified", "source", "segments", "waypoints"})


class FlightPlanError(ValueError):
    """A caller mistake -- an invalid edit, out-of-range index, a role
    assignment that would break the FAF/MAP invariant, or an airway edit the
    published airway does not allow. Never an internal fault; callers may
    show ``str(exc)`` to the pilot."""


@dataclass
class Waypoint:
    """One leg of the route: the fix it ends at, plus the PA3 leg fields
    that cross the bus on its slot. ``crs`` is the coded course (magnetic)
    for the leg types that fly one; ``None`` means the bridge derives it
    from the great circle into this fix. ``alt`` is the packed altitude
    constraint (``"+7000"``), distinct from ``alt_ft``, the pilot's planned
    altitude note. ``flags`` holds the FPLfFLAGS bits that are not the role
    (``0x01`` fly-over, ``0x20`` from a coded procedure)."""

    id: str
    type: str
    lat: float
    lon: float
    name: str = ""
    alt_ft: float | None = None
    comment: str = ""
    role: str = "none"
    extra: dict = field(default_factory=dict)
    pt: str = "TF"
    crs: float | None = None
    dst: float = 0.0
    alt: str = ""
    spd: int = 0
    flags: int = 0
    ctr_lat: float = 0.0
    ctr_lon: float = 0.0
    turn: str = ""

    def __post_init__(self):
        if self.type not in WAYPOINT_TYPES:
            raise FlightPlanError(f"unknown waypoint type {self.type!r}")
        if self.role not in ROLES:
            raise FlightPlanError(f"unknown role {self.role!r}")

    def copy(self, **changes) -> Waypoint:
        values = {f: getattr(self, f) for f in self.__dataclass_fields__}
        values["extra"] = dict(self.extra)
        values.update(changes)
        return Waypoint(**values)

    def to_json(self) -> dict:
        d = dict(self.extra)
        d.update({"id": self.id, "type": self.type, "lat": self.lat, "lon": self.lon})
        if self.name:
            d["name"] = self.name
        if self.alt_ft is not None:
            d["alt_ft"] = self.alt_ft
        if self.comment:
            d["comment"] = self.comment
        if self.role != "none":
            d["role"] = self.role
        for key, default in _LEG_DEFAULTS.items():
            value = getattr(self, key)
            if value != default:
                d[key] = value
        return d

    @classmethod
    def from_json(cls, d: dict) -> Waypoint:
        extra = {k: v for k, v in d.items() if k not in _WAYPOINT_KNOWN_FIELDS}
        crs = d.get("crs")
        return cls(id=d["id"], type=d["type"], lat=float(d["lat"]), lon=float(d["lon"]),
                    name=d.get("name") or "", alt_ft=d.get("alt_ft"),
                    comment=d.get("comment") or "", role=d.get("role") or "none",
                    extra=extra, pt=d.get("pt") or "TF",
                    crs=None if crs is None else float(crs),
                    dst=float(d.get("dst") or 0.0), alt=d.get("alt") or "",
                    spd=int(d.get("spd") or 0), flags=int(d.get("flags") or 0),
                    ctr_lat=float(d.get("ctr_lat") or 0.0),
                    ctr_lon=float(d.get("ctr_lon") or 0.0), turn=d.get("turn") or "")


@dataclass
class Segment:
    """A contiguous run of legs with one meaning (RS1's segment table row).
    ``entry`` and ``exit`` are the first and last legs' idents -- derived,
    so they can never disagree with the legs (the engine rejects a commit
    where they do, ``SEGENT``/``SEGEXT``). ``cycle`` is the AIRAC cycle the
    legs were expanded from; empty for a waypoint, or when unknown."""

    kind: str
    legs: list[Waypoint]
    ident: str = ""
    cycle: str = ""
    extra: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.kind not in SEGMENT_KINDS:
            raise FlightPlanError(f"unknown segment kind {self.kind!r}")
        if not self.legs:
            raise FlightPlanError(f"a {self.kind} segment needs at least one leg")
        if len(self.ident) > SEGMENT_IDENT_MAX_LEN or ";" in self.ident:
            raise FlightPlanError(f"segment ident {self.ident!r} is longer than "
                                   f"{SEGMENT_IDENT_MAX_LEN} characters or contains ';'")
        if self.kind == "waypoint":
            if len(self.legs) != 1:
                raise FlightPlanError("a waypoint segment holds exactly one leg")
            if self.ident:
                raise FlightPlanError("a waypoint segment has no ident")
        if self.kind == "airway":
            if not self.ident:
                raise FlightPlanError("an airway segment needs its ident")
            if len(self.legs) < 2:
                raise FlightPlanError(f"airway {self.ident} needs its entry and exit fix")

    @property
    def entry(self) -> str:
        return self.legs[0].id

    @property
    def exit(self) -> str:
        return self.legs[-1].id

    def to_json(self) -> dict:
        d = dict(self.extra)
        d["kind"] = self.kind
        if self.kind != "waypoint":
            d.update({"ident": self.ident, "entry": self.entry, "exit": self.exit,
                      "cycle": self.cycle})
        d["legs"] = [w.to_json() for w in self.legs]
        return d

    @classmethod
    def from_json(cls, d: dict) -> Segment:
        extra = {k: v for k, v in d.items() if k not in _SEGMENT_KNOWN_FIELDS}
        return cls(kind=d.get("kind") or "waypoint",
                    legs=[Waypoint.from_json(w) for w in d.get("legs", [])],
                    ident=d.get("ident") or "", cycle=d.get("cycle") or "", extra=extra)


def waypoint_segment(wp: Waypoint) -> Segment:
    return Segment(kind="waypoint", legs=[wp])


def _norm(ident: str) -> str:
    return (ident or "").strip().upper()


def _pieces(kind: str, ident: str, cycle: str, legs: list[Waypoint]) -> list[Segment]:
    """*legs* as one segment of *kind*, or -- when too short for that kind --
    as waypoint segments, so cutting an airway never leaves a one-fix
    "airway" the engine would reject (``SEGLEN``)."""
    if not legs:
        return []
    if kind == "airway" and len(legs) < 2:
        return [waypoint_segment(w) for w in legs]
    if kind == "waypoint":
        return [waypoint_segment(w) for w in legs]
    return [Segment(kind=kind, legs=legs, ident=ident, cycle=cycle)]


class FlightPlan:
    """*segments* is the route. *waypoints* is accepted for convenience (and
    for every caller written before RS2): each becomes its own waypoint
    segment. Passing both is an error."""

    def __init__(self, name: str = "", comment: str = "",
                 waypoints: list[Waypoint] | None = None, created: str = "",
                 modified: str = "", source: str = "device", extra: dict | None = None,
                 segments: list[Segment] | None = None):
        if waypoints is not None and segments is not None:
            raise FlightPlanError("pass waypoints or segments, not both")
        self.name = name
        self.comment = comment
        self.created = created
        self.modified = modified
        self.source = source
        self.extra = dict(extra or {})
        if segments is None:
            segments = [waypoint_segment(w) for w in (waypoints or [])]
        self.segments: list[Segment] = list(segments)
        # Things the pilot should be told about this plan that are not part
        # of it -- e.g. an airway re-expanded against a newer AIRAC cycle on
        # load (catalog.py). Transient: never stored, never on the bus.
        self.notices: list[str] = []
        if self.count > MAX_WAYPOINTS:
            raise FlightPlanError(f"route exceeds {MAX_WAYPOINTS} waypoints")

    def __repr__(self):
        return (f"FlightPlan(name={self.name!r}, "
                f"segments={[(s.kind, s.ident, s.entry, s.exit) for s in self.segments]!r})")

    def __eq__(self, other):
        if not isinstance(other, FlightPlan):
            return NotImplemented
        return self.to_json() == other.to_json()

    # -- the flat view -----------------------------------------------------
    @property
    def waypoints(self) -> tuple[Waypoint, ...]:
        return tuple(w for s in self.segments for w in s.legs)

    @property
    def count(self) -> int:
        return sum(len(s.legs) for s in self.segments)

    def locate(self, i: int) -> tuple[int, int]:
        """``(segment_index, leg_index)`` of flat waypoint *i*."""
        if i >= 0:
            for k, seg in enumerate(self.segments):
                if i < len(seg.legs):
                    return k, i
                i -= len(seg.legs)
        raise FlightPlanError("index out of range")

    def segment_span(self, k: int) -> tuple[int, int]:
        """``(first, last)`` flat indices of segment *k*."""
        self._check_segment(k)
        first = sum(len(s.legs) for s in self.segments[:k])
        return first, first + len(self.segments[k].legs) - 1

    def _check_segment(self, k: int) -> Segment:
        if not (0 <= k < len(self.segments)):
            raise FlightPlanError(f"segment {k} out of range")
        return self.segments[k]

    # -- editing: single waypoints ----------------------------------------
    def _check_cap(self, adding: int = 1):
        if self.count + adding > MAX_WAYPOINTS:
            if adding == 1:
                raise FlightPlanError(f"route already has {MAX_WAYPOINTS} waypoints")
            raise FlightPlanError(f"route full -- needs {adding} more of "
                                   f"{MAX_WAYPOINTS} waypoints")

    def _insert_at(self, i: int, wp: Waypoint) -> None:
        """Insert *wp* as a waypoint segment so it becomes flat index *i*.
        Landing strictly inside an airway cuts it in two: the leg into and
        out of *wp* is no longer on the airway."""
        self._check_cap()
        if not (0 <= i <= self.count):
            raise FlightPlanError(f"index {i} out of range")
        new = waypoint_segment(wp)
        if i == self.count:
            self.segments.append(new)
            return
        k, j = self.locate(i)
        if j == 0:
            self.segments.insert(k, new)
            return
        seg = self.segments[k]
        self.segments[k:k + 1] = (_pieces(seg.kind, seg.ident, seg.cycle, seg.legs[:j]) + [new]
                                  + _pieces(seg.kind, seg.ident, seg.cycle, seg.legs[j:]))

    def insert_before(self, i: int, wp: Waypoint) -> None:
        if not (0 <= i <= self.count):
            raise FlightPlanError(f"index {i} out of range")
        self._insert_at(i, wp)

    def insert_after(self, i: int, wp: Waypoint) -> None:
        if not (-1 <= i < self.count):
            raise FlightPlanError(f"index {i} out of range")
        self._insert_at(i + 1, wp)

    def remove(self, i: int) -> Waypoint:
        """Remove flat waypoint *i*. Removing an airway's entry or exit
        shortens the airway; removing a fix in the middle cuts it in two
        (the corner it leaves is not on the airway). A remnant too short to
        be an airway becomes a plain waypoint -- no leg is ever orphaned."""
        if not (0 <= i < self.count):
            raise FlightPlanError(f"index {i} out of range")
        k, j = self.locate(i)
        seg = self.segments[k]
        wp = seg.legs[j]
        self.segments[k:k + 1] = (_pieces(seg.kind, seg.ident, seg.cycle, seg.legs[:j])
                                  + _pieces(seg.kind, seg.ident, seg.cycle, seg.legs[j + 1:]))
        return wp

    # -- editing: segments (RS2) -------------------------------------------
    def insert_airway(self, after: int, ident: str, exit_fix: str, graph) -> Segment:
        """Fly airway *ident* from flat waypoint *after* (the entry fix) to
        *exit_fix*. *graph* is an ``airways.AirwayGraph``; its errors
        (unknown airway, fix not on it, one-way) are re-raised as
        :class:`FlightPlanError` with the same message.

        A plain-waypoint entry fix becomes the airway's first leg -- the
        segment's entry is its own first slot (RS1). An entry fix that
        already ends another segment (chaining one airway onto the next)
        stays there, and the new airway starts at the fix after it. All or
        nothing: a route without room for the whole airway is left
        unchanged."""
        if not (0 <= after < self.count):
            raise FlightPlanError(f"index {after} out of range")
        k, j = self.locate(after)
        seg = self.segments[k]
        if j != len(seg.legs) - 1:
            raise FlightPlanError(
                f"{seg.legs[j].id} is inside {seg.ident or seg.kind}; load the airway "
                f"from its exit, or change its exit first")
        expansion = self._expand(graph, ident, seg.legs[j].id, exit_fix)
        if seg.kind == "waypoint":
            legs = [seg.legs[0].copy(alt=expansion[0].alt)] + expansion[1:]
            replace = k
        else:
            legs = expansion[1:]
            replace = None
            if len(legs) < 2:
                raise FlightPlanError(
                    f"{_norm(ident)} from {seg.legs[j].id} to {_norm(exit_fix)} is a "
                    f"single leg -- enter {_norm(exit_fix)} as a waypoint")
        self._check_cap(len(expansion) - 1)
        new = Segment(kind="airway", legs=legs, ident=_norm(ident),
                      cycle=self._cycle(graph, ident))
        if replace is not None:
            self.segments[replace] = new
        else:
            self.segments.insert(k + 1, new)
        return new

    def remove_segment(self, k: int) -> Segment:
        """Remove segment *k*. An airway leaves its entry fix behind as a
        plain waypoint -- the pilot entered that fix before loading the
        airway, so this is exactly the undo of :meth:`insert_airway`."""
        seg = self._check_segment(k)
        if seg.kind == "airway":
            self.segments[k] = waypoint_segment(seg.legs[0].copy(alt=""))
        else:
            del self.segments[k]
        return seg

    def change_exit(self, k: int, exit_fix: str, graph) -> Segment:
        """Re-expand airway *k* from its current entry to *exit_fix*."""
        return self._reexpand(k, self._airway(k).entry, exit_fix, graph)

    def change_entry(self, k: int, entry_fix: str, graph) -> Segment:
        """Re-expand airway *k* from *entry_fix* to its current exit."""
        return self._reexpand(k, entry_fix, self._airway(k).exit, graph)

    def split_at(self, k: int, fix: str) -> tuple[Segment, Segment]:
        """Cut segment *k* so that *fix* starts its own remainder: the legs
        before *fix* and the legs from *fix* on. Each piece keeps the
        segment's identity where it is long enough to (an airway needs two
        fixes); a shorter piece becomes a plain waypoint. Not wired to
        Direct-To: the engine keeps the airway as the active segment through
        a DTO without any table rewrite (RS1)."""
        seg = self._check_segment(k)
        norm = _norm(fix)
        j = next((n for n, w in enumerate(seg.legs) if _norm(w.id) == norm), None)
        if j is None:
            raise FlightPlanError(f"{fix!r} is not in {seg.ident or seg.kind}")
        if j == 0:
            raise FlightPlanError(f"{fix!r} already starts {seg.ident or seg.kind}")
        head = _pieces(seg.kind, seg.ident, seg.cycle, seg.legs[:j])
        tail = _pieces(seg.kind, seg.ident, seg.cycle, seg.legs[j:])
        self.segments[k:k + 1] = head + tail
        return self.segments[k + len(head) - 1], self.segments[k + len(head)]

    def _airway(self, k: int) -> Segment:
        seg = self._check_segment(k)
        if seg.kind != "airway":
            raise FlightPlanError(f"segment {k} is not an airway")
        return seg

    def _reexpand(self, k: int, entry_fix: str, exit_fix: str, graph) -> Segment:
        seg = self._airway(k)
        expansion = self._expand(graph, seg.ident, entry_fix, exit_fix)
        self._check_cap(len(expansion) - len(seg.legs))
        if _norm(expansion[0].id) == _norm(seg.entry):
            expansion[0] = seg.legs[0].copy(alt=expansion[0].alt)
        new = Segment(kind="airway", legs=expansion, ident=seg.ident,
                      cycle=self._cycle(graph, seg.ident))
        self.segments[k] = new
        return new

    @staticmethod
    def _expand(graph, ident, entry_fix, exit_fix) -> list[Waypoint]:
        from .airways import AirwayError  # lazy: airways imports this module
        try:
            return graph.expand(ident, entry_fix, exit_fix)
        except AirwayError as e:
            raise FlightPlanError(str(e)) from e

    @staticmethod
    def _cycle(graph, ident) -> str:
        cycle = getattr(graph, "cycle", None)
        return (cycle(ident) or "") if cycle is not None else ""

    # -- invert --------------------------------------------------------------
    def invert(self, graph=None) -> FlightPlan:
        """A copy of this plan flown the other way: segments in reverse
        order, each segment's legs reversed, every role cleared -- an
        approach does not survive reversal (brief 3.4). An airway swaps its
        entry and exit, and the one-way direction check is re-run against
        *graph*: inverting across a leg coded one-way is refused with the
        reason, never silently produced. With airways in the plan and no
        loaded *graph*, the check cannot run, so the invert is refused too.
        A procedure segment does not survive reversal either; its fixes come
        back as plain waypoints."""
        segments = []
        for seg in reversed(self.segments):
            if seg.kind == "airway":
                legs = list(reversed(seg.legs))
                if graph is None or not getattr(graph, "ready", False):
                    raise FlightPlanError(
                        f"cannot invert: no airway data to check {seg.ident} "
                        f"{legs[0].id} -> {legs[-1].id} is flyable that way")
                try:
                    expansion = self._expand(graph, seg.ident, legs[0].id, legs[-1].id)
                except FlightPlanError as e:
                    raise FlightPlanError(f"cannot invert: {e}") from e
                # The leg into each fix now comes from the other side, so its
                # MEA is the reversed expansion's, not the stored one (and the
                # new entry fix, whose inbound leg is off the airway, has none).
                mea = {_norm(w.id): w.alt for w in expansion}
                new_legs = [self._inverted_leg(w, alt=mea.get(_norm(w.id), "")) for w in legs]
                segments.append(Segment(kind="airway", legs=new_legs, ident=seg.ident,
                                        cycle=seg.cycle))
            else:
                segments.extend(waypoint_segment(self._inverted_leg(w))
                                for w in reversed(seg.legs))
        plan = FlightPlan(comment=self.comment, segments=segments, source=self.source)
        plan.name = plan.default_name()
        return plan

    @staticmethod
    def _inverted_leg(w: Waypoint, alt: str = "") -> Waypoint:
        return Waypoint(id=w.id, type=w.type, lat=w.lat, lon=w.lon, name=w.name,
                         alt_ft=w.alt_ft, comment=w.comment, role="none", alt=alt)

    # -- roles -----------------------------------------------------------
    def set_role(self, i: int, role: str) -> None:
        """At most one FAF and one MAP; the MAP must follow the FAF."""
        if role not in ROLES:
            raise FlightPlanError(f"unknown role {role!r}")
        if not (0 <= i < self.count):
            raise FlightPlanError(f"index {i} out of range")
        if role in ("faf", "map"):
            faf_i, map_i = self._role_indices()
            if role == "faf":
                if faf_i is not None and faf_i != i:
                    raise FlightPlanError("route already has a FAF")
                if map_i is not None and i >= map_i:
                    raise FlightPlanError("the FAF must precede the MAP")
            else:  # role == "map"
                if map_i is not None and map_i != i:
                    raise FlightPlanError("route already has a MAP")
                if faf_i is not None and i <= faf_i:
                    raise FlightPlanError("the MAP must follow the FAF")
        self.waypoints[i].role = role

    def _role_indices(self):
        wps = self.waypoints
        faf_i = next((k for k, w in enumerate(wps) if w.role == "faf"), None)
        map_i = next((k for k, w in enumerate(wps) if w.role == "map"), None)
        return faf_i, map_i

    def approach(self) -> tuple[int, int] | None:
        """``(faf_index, map_index)`` when both roles are set, else ``None``."""
        faf_i, map_i = self._role_indices()
        if faf_i is None or map_i is None:
            return None
        return faf_i, map_i

    # -- geometry --------------------------------------------------------
    def leg(self, i: int) -> tuple[float, float]:
        """``(dtk_true, dist_nm)`` of the leg from waypoint *i* to *i+1*."""
        wps = self.waypoints
        if not (0 <= i < len(wps) - 1):
            raise FlightPlanError(f"no leg at index {i}")
        a, b = wps[i], wps[i + 1]
        dtk = geo.initial_bearing(a.lat, a.lon, b.lat, b.lon)
        dist = geo.distance_nm(a.lat, a.lon, b.lat, b.lon)
        return dtk, dist

    def cumulative(self, i: int) -> float:
        """Distance in nm from the first waypoint to waypoint *i*."""
        if not (0 <= i < self.count):
            raise FlightPlanError(f"index {i} out of range")
        return sum(self.leg(k)[1] for k in range(i))

    @property
    def total_nm(self) -> float:
        if self.count < 2:
            return 0.0
        return self.cumulative(self.count - 1)

    def default_name(self) -> str:
        wps = self.waypoints
        if not wps:
            return ""
        return f"{wps[0].id}-{wps[-1].id}"[:NAME_MAX_LEN]

    # -- JSON (Appendix B; "mp-route/2" since RS2) -------------------------
    def to_json(self) -> dict:
        d = dict(self.extra)
        d.update({
            "schema": SCHEMA,
            "name": self.name or self.default_name(),
            "comment": self.comment,
            "created": self.created,
            "modified": self.modified,
            "source": self.source,
            "segments": [s.to_json() for s in self.segments],
        })
        return d

    @classmethod
    def from_json(cls, d: dict) -> FlightPlan:
        """Reads ``mp-route/2`` and ``mp-route/1``. A v1 route has no
        segments, so every waypoint becomes a waypoint segment; saving it
        writes v2 (a one-way migration). PA6's display-only ``airway`` tag,
        which v1 files spilled onto their waypoints, is dropped: it is what
        RS2 replaces, and carrying it forward would be a second, stale
        record of airway membership."""
        schema = d.get("schema")
        extra = {k: v for k, v in d.items() if k not in _PLAN_KNOWN_FIELDS}
        if schema == SCHEMA:
            segments = [Segment.from_json(s) for s in d.get("segments", [])]
        elif schema == SCHEMA_V1:
            segments = []
            for w in d.get("waypoints", []):
                wp = Waypoint.from_json(w)
                wp.extra.pop("airway", None)
                segments.append(waypoint_segment(wp))
        else:
            raise FlightPlanError(f"unsupported route schema {schema!r}")
        return cls(name=d.get("name") or "", comment=d.get("comment") or "",
                    segments=segments, created=d.get("created") or "",
                    modified=d.get("modified") or "", source=d.get("source") or "device",
                    extra=extra)
