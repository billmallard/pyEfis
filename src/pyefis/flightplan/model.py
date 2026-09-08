#  SPDX-License-Identifier: GPL-2.0-or-later
"""Route model (FP4): the editor's in-memory ``FlightPlan`` and its
``mp-route/1`` JSON form. See ``makerplane/briefs/flight_plan_plan.md``
section 3.4 Appendix B and billmallard/pyEfis#183.

Mutating methods (``insert_before``/``insert_after``/``remove``/``set_role``)
change the plan in place -- the editor keeps one working copy and commits it
via ``fixbridge.FixBridge.publish`` after every edit (section 3.4: "the pyEfis
editor keeps a working copy, commits every change immediately"). ``invert()``
is the one method that returns a new plan, matching the GNX guide's "Invert &
Activate (a copy; the stored plan is unchanged)".

Qt-free: nothing here may import PyQt6.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import geo

SCHEMA = "mp-route/1"
MAX_WAYPOINTS = 50

WAYPOINT_TYPES = ("airport", "vor", "ndb", "fix", "user", "map")
ROLES = ("none", "iaf", "faf", "map", "mahp")

# Appendix A: FPLfTYPE 0..6, FPLfROLE 0..4.
TYPE_TO_FPLTYPE = {"unknown": 0, "airport": 1, "vor": 2, "ndb": 3, "fix": 4, "user": 5, "map": 6}
FPLTYPE_TO_TYPE = {v: k for k, v in TYPE_TO_FPLTYPE.items()}
ROLE_TO_FPLROLE = {"none": 0, "iaf": 1, "faf": 2, "map": 3, "mahp": 4}
FPLROLE_TO_ROLE = {v: k for k, v in ROLE_TO_FPLROLE.items()}

NAME_MAX_LEN = 32
_WAYPOINT_KNOWN_FIELDS = frozenset(
    {"id", "type", "lat", "lon", "name", "alt_ft", "comment", "role"})
_PLAN_KNOWN_FIELDS = frozenset(
    {"schema", "name", "comment", "created", "modified", "source", "waypoints"})


class FlightPlanError(ValueError):
    """A caller mistake -- an invalid edit, out-of-range index, or a role
    assignment that would break the FAF/MAP invariant. Never an internal
    fault; callers may show ``str(exc)`` to the pilot."""


@dataclass
class Waypoint:
    id: str
    type: str
    lat: float
    lon: float
    name: str = ""
    alt_ft: float | None = None
    comment: str = ""
    role: str = "none"
    extra: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.type not in WAYPOINT_TYPES:
            raise FlightPlanError(f"unknown waypoint type {self.type!r}")
        if self.role not in ROLES:
            raise FlightPlanError(f"unknown role {self.role!r}")

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
        return d

    @classmethod
    def from_json(cls, d: dict) -> Waypoint:
        extra = {k: v for k, v in d.items() if k not in _WAYPOINT_KNOWN_FIELDS}
        return cls(id=d["id"], type=d["type"], lat=float(d["lat"]), lon=float(d["lon"]),
                    name=d.get("name") or "", alt_ft=d.get("alt_ft"),
                    comment=d.get("comment") or "", role=d.get("role") or "none",
                    extra=extra)


@dataclass
class FlightPlan:
    name: str = ""
    comment: str = ""
    waypoints: list[Waypoint] = field(default_factory=list)
    created: str = ""
    modified: str = ""
    source: str = "device"
    extra: dict = field(default_factory=dict)

    def __post_init__(self):
        if len(self.waypoints) > MAX_WAYPOINTS:
            raise FlightPlanError(f"route exceeds {MAX_WAYPOINTS} waypoints")

    # -- editing -------------------------------------------------------
    def _check_cap(self):
        if len(self.waypoints) >= MAX_WAYPOINTS:
            raise FlightPlanError(f"route already has {MAX_WAYPOINTS} waypoints")

    def insert_before(self, i: int, wp: Waypoint) -> None:
        self._check_cap()
        if not (0 <= i <= len(self.waypoints)):
            raise FlightPlanError(f"index {i} out of range")
        self.waypoints.insert(i, wp)

    def insert_after(self, i: int, wp: Waypoint) -> None:
        self._check_cap()
        if not (-1 <= i < len(self.waypoints)):
            raise FlightPlanError(f"index {i} out of range")
        self.waypoints.insert(i + 1, wp)

    def remove(self, i: int) -> Waypoint:
        if not (0 <= i < len(self.waypoints)):
            raise FlightPlanError(f"index {i} out of range")
        return self.waypoints.pop(i)

    def invert(self) -> FlightPlan:
        """A copy of this plan with the waypoint order reversed and every
        role cleared -- an approach does not survive reversal (brief 3.4)."""
        inverted = [Waypoint(id=w.id, type=w.type, lat=w.lat, lon=w.lon, name=w.name,
                              alt_ft=w.alt_ft, comment=w.comment, role="none")
                    for w in reversed(self.waypoints)]
        plan = FlightPlan(comment=self.comment, waypoints=inverted, source=self.source)
        plan.name = plan.default_name()
        return plan

    def set_role(self, i: int, role: str) -> None:
        """At most one FAF and one MAP; the MAP must follow the FAF."""
        if role not in ROLES:
            raise FlightPlanError(f"unknown role {role!r}")
        if not (0 <= i < len(self.waypoints)):
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
        faf_i = next((k for k, w in enumerate(self.waypoints) if w.role == "faf"), None)
        map_i = next((k for k, w in enumerate(self.waypoints) if w.role == "map"), None)
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
        if not (0 <= i < len(self.waypoints) - 1):
            raise FlightPlanError(f"no leg at index {i}")
        a, b = self.waypoints[i], self.waypoints[i + 1]
        dtk = geo.initial_bearing(a.lat, a.lon, b.lat, b.lon)
        dist = geo.distance_nm(a.lat, a.lon, b.lat, b.lon)
        return dtk, dist

    def cumulative(self, i: int) -> float:
        """Distance in nm from the first waypoint to waypoint *i*."""
        if not (0 <= i < len(self.waypoints)):
            raise FlightPlanError(f"index {i} out of range")
        return sum(self.leg(k)[1] for k in range(i))

    @property
    def total_nm(self) -> float:
        if len(self.waypoints) < 2:
            return 0.0
        return self.cumulative(len(self.waypoints) - 1)

    @property
    def count(self) -> int:
        return len(self.waypoints)

    def default_name(self) -> str:
        if not self.waypoints:
            return ""
        return f"{self.waypoints[0].id}-{self.waypoints[-1].id}"[:NAME_MAX_LEN]

    # -- JSON (Appendix B, "mp-route/1") ----------------------------------
    def to_json(self) -> dict:
        d = dict(self.extra)
        d.update({
            "schema": SCHEMA,
            "name": self.name or self.default_name(),
            "comment": self.comment,
            "created": self.created,
            "modified": self.modified,
            "source": self.source,
            "waypoints": [w.to_json() for w in self.waypoints],
        })
        return d

    @classmethod
    def from_json(cls, d: dict) -> FlightPlan:
        if d.get("schema") != SCHEMA:
            raise FlightPlanError(f"unsupported route schema {d.get('schema')!r}")
        extra = {k: v for k, v in d.items() if k not in _PLAN_KNOWN_FIELDS}
        waypoints = [Waypoint.from_json(w) for w in d.get("waypoints", [])]
        return cls(name=d.get("name") or "", comment=d.get("comment") or "",
                    waypoints=waypoints, created=d.get("created") or "",
                    modified=d.get("modified") or "", source=d.get("source") or "device",
                    extra=extra)
