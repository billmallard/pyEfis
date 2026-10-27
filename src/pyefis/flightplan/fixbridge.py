#  SPDX-License-Identifier: GPL-2.0-or-later
"""FIX bus bridge for the flight-plan editor (FP4): publishes a
``model.FlightPlan`` as the Appendix A route block, stages/commands the
engine, and reads its guidance back. See
``makerplane/briefs/flight_plan_plan.md`` sections 3.2/3.4 Appendix A/C and
billmallard/pyEfis#183.

Construct-never-raises, the graceful-missing-key convention this codebase
uses everywhere a FIX key might not exist yet (``ai/__init__.py``): if the
gateway does not define the FP1 keys, ``available`` is False and every
method is a no-op instead of raising ``KeyError``.

RS2 (billmallard/pyEfis#305, fix-gateway ``doc/flightplan_keys.md`` "Route
segment table"): the bridge publishes and reads every slot field -- not just
the five FP1 ones -- and the segment table, so the route's segments are on
the bus and every reader (a restarted display, a second display, the map)
sees the same ones. :meth:`FixBridge.read_plan` rebuilds a
``model.FlightPlan`` with its segments from the bus alone.

Every callback this module exposes is a plain Python callable, never a
``pyqtSignal`` -- the instrument (FP5a) and the map layer (FP6) wrap them in
Qt signals themselves. This module does not import PyQt6 itself; connecting
to a ``pyavtools.fix`` ``DB_Item``'s existing bound signal does not require
importing Qt.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from . import geo
from . import model

log = logging.getLogger(__name__)

MAX_SLOTS = 100

TYPE_TO_FPLTYPE = {"unknown": 0, "airport": 1, "vor": 2, "ndb": 3, "fix": 4, "user": 5, "map": 6}
FPLTYPE_TO_TYPE = {v: k for k, v in TYPE_TO_FPLTYPE.items()}

# PA3 (fix-gateway#27) replaced the scalar FPLfROLE (0 none/1 iaf/2 faf/3
# map/4 mahp) with a FPLfFLAGS bitfield shared with fly-over (0x01) and
# from-a-coded-procedure (0x20) -- neither of which this module reads or
# writes yet. The bit positions do NOT match the old scalar values (faf was
# 2, IAF's bit is 0x02), so this has to be an explicit table in both
# directions -- a straight rename/shift would silently turn faf into iaf.
ROLE_TO_FLAG = {"none": 0x00, "iaf": 0x02, "faf": 0x04, "map": 0x08, "mahp": 0x10}
_FLAG_TO_ROLE = ((0x02, "iaf"), (0x04, "faf"), (0x08, "map"), (0x10, "mahp"))


def _flag_to_role(flags: int) -> str:
    for bit, role in _FLAG_TO_ROLE:
        if flags & bit:
            return role
    return "none"


# Appendix A engine outputs the ActivePlan read-back watches.
ENGINE_OUTPUT_KEYS = (
    "FPLSTATE", "FPLACTLEG", "FPLPHASE", "FPLAPR", "FPLINTEG", "CDISCALE",
    "FPLCRS", "FPLXTK", "FPLCDI", "FPLTF", "FPLFRLAT", "FPLFRLON",
    "WPNAME", "WPLAT", "WPLON", "WPFROM", "WPNEXT", "WPDIS", "WPETE",
    "FPLREMDIS", "FPLREMETE", "FPLALERT", "GPSSRC", "FPLACTSEG", "FPLSEGREM",
)

_STATIC_KEYS = (
    "FPLCOUNT", "FPLNAME", "FPLSEQ", "FPLSEGCNT", "FPLDBCYC",
    "DTOID", "DTOLAT", "DTOLON", "DTOTYPE",
    "FPLCMD", "FPLCMDACK", "FPLMSG",
)

# Every per-slot field of the PA3/RS1 route block, with its FIX dtype and
# the value an unused slot is blanked to (fix-gateway flightplan.yaml
# ``initial``).
SLOT_FIELDS = (
    ("ID", "str", ""), ("LAT", "float", 0.0), ("LON", "float", 0.0), ("TYPE", "int", 0),
    ("PT", "str", "TF"), ("CRS", "float", 0.0), ("DST", "float", 0.0), ("ALT", "str", ""),
    ("SPD", "int", 0), ("SGI", "int", 0), ("FLAGS", "int", 0),
    ("CTRLAT", "float", 0.0), ("CTRLON", "float", 0.0), ("TURN", "str", ""),
)
# The segment table, FPLS1..FPLS<MAX_SLOTS>: as long as the slot block, so
# it can never be the limit (RS1, Bill 2026-10-26).
SEGMENT_FIELDS = (
    ("KIND", "int", 0), ("ID", "str", ""), ("ENT", "str", ""), ("EXT", "str", ""),
    ("FIRST", "int", 0), ("LAST", "int", 0),
)
KIND_TO_WIRE = {kind: n for n, kind in enumerate(model.SEGMENT_KINDS)}

# The FPLfFLAGS bits that are not the role (fly-over, from a coded
# procedure): carried on Waypoint.flags.
_ROLE_BITS = 0x02 | 0x04 | 0x08 | 0x10


def _slot_key(n: int, name: str) -> str:
    return f"FPL{n}{name}"


def _seg_key(k: int, name: str) -> str:
    return f"FPLS{k}{name}"


def route_key_specs():
    """``(key, dtype, blank)`` for every route-block, segment-table, staging
    and command key this bridge writes or probes (not the engine outputs).
    Test doubles define the gateway's keys from this one list."""
    for n in range(1, MAX_SLOTS + 1):
        for name, dtype, blank in SLOT_FIELDS:
            yield _slot_key(n, name), dtype, blank
        for name, dtype, blank in SEGMENT_FIELDS:
            yield _seg_key(n, name), dtype, blank
    for key, dtype, blank in (
            ("FPLCOUNT", "int", 0), ("FPLNAME", "str", ""), ("FPLSEQ", "int", 0),
            ("FPLSEGCNT", "int", 0), ("FPLDBCYC", "str", ""),
            ("DTOID", "str", ""), ("DTOLAT", "float", 0.0), ("DTOLON", "float", 0.0),
            ("DTOTYPE", "int", 0), ("FPLCMD", "str", ""), ("FPLCMDACK", "int", 0),
            ("FPLMSG", "str", "")):
        yield key, dtype, blank


def _probe_keys():
    keys = list(_STATIC_KEYS) + list(ENGINE_OUTPUT_KEYS)
    for n in (1, MAX_SLOTS):
        keys.extend(_slot_key(n, name) for name, _, _ in SLOT_FIELDS)
        keys.extend(_seg_key(n, name) for name, _, _ in SEGMENT_FIELDS)
    return keys


@dataclass
class RouteSlot:
    id: str
    lat: float
    lon: float
    type: str
    role: str
    pt: str = "TF"
    crs: float = 0.0
    dst: float = 0.0
    alt: str = ""
    spd: int = 0
    sgi: int = 0
    flags: int = 0
    ctr_lat: float = 0.0
    ctr_lon: float = 0.0
    turn: str = ""


@dataclass
class RouteSegment:
    kind: str
    ident: str
    entry: str
    exit: str
    first: int  # 1-based slot numbers, as on the bus
    last: int


@dataclass
class RouteBlock:
    name: str
    seq: int
    waypoints: list[RouteSlot] = field(default_factory=list)
    segments: list[RouteSegment] = field(default_factory=list)
    cycle: str = ""


@dataclass
class ItemValue:
    value: object
    old: bool
    bad: bool
    fail: bool


@dataclass
class DirectTo:
    id: str
    lat: float
    lon: float
    type: str


class FixBridge:
    """Wraps ``pyavtools.fix``. *fix_module* is the imported ``pyavtools.fix``
    (or a compatible test double exposing ``.db``)."""

    def __init__(self, fix_module):
        self._fix = fix_module
        self._seq_counter = 0
        self._published_count = 0
        self._published_segcnt = 0
        self._ack_callbacks: dict[int, callable] = {}
        self._listeners: list[callable] = []

        self.available = self._probe()
        if self.available:
            self._published_count = int(self._get("FPLCOUNT").value)
            self._published_segcnt = int(self._get("FPLSEGCNT").value)
            self._connect_readback()

    # -- availability --------------------------------------------------
    def _probe(self) -> bool:
        try:
            for key in _probe_keys():
                self._fix.db.get_item(key)
            return True
        except KeyError:
            return False

    def _get(self, key):
        return self._fix.db.get_item(key)

    def _set(self, key, value) -> None:
        # set_value() only updates pyEfis's local copy: pyavtools sends a key
        # to the gateway only on output_value() (or for keys listed in the
        # `outputs` config, which the FP1 keys are not). Without this the
        # route, DTO staging and FPLCMD never left the display -- the editor
        # looked right on glass while the engine saw nothing (AER-810 bench,
        # 2026-10-10: three waypoints on screen, FPLCOUNT=1 on fixgw). Same
        # value-then-output_value() pattern as hmi/functions.py setValue.
        item = self._fix.db.get_item(key)
        item.value = value
        item.output_value()

    # -- publish (editor -> bus) -----------------------------------------
    def _magvar(self) -> float:
        """Local variation (``MAGVAR``, positive west, MAG = TRUE + VAR) --
        the value the engine converts ``FPLCRS`` with. 0 when the gateway
        does not publish it."""
        try:
            return float(self._get("MAGVAR").value or 0.0)
        except (KeyError, TypeError, ValueError):
            return 0.0

    def publish(self, plan) -> None:
        """Write every slot field and the segment table, blanking whatever
        the previous plan left past the new counts, then ``FPLSEGCNT`` and
        ``FPLCOUNT``, ``FPLNAME``, ``FPLDBCYC``, and ``FPLSEQ`` last
        (RS1 writer order: consumers act only on the ``FPLSEQ`` change).

        ``FPLfCRS`` is magnetic. A leg with no coded course (every TF leg
        a pilot builds) gets the great-circle course into its fix,
        converted with the current ``MAGVAR`` -- the conversion the engine
        applies to ``FPLCRS``. ``FPLfALT`` carries an airway leg's MEA."""
        if not self.available:
            return
        wps = plan.waypoints
        count = len(wps)
        magvar = self._magvar()
        sgi = [k + 1 for k, seg in enumerate(plan.segments) for _ in seg.legs]
        for i in range(1, max(count, self._published_count) + 1):
            if i > count:
                for name, _, blank in SLOT_FIELDS:
                    self._set(_slot_key(i, name), blank)
                continue
            wp = wps[i - 1]
            crs = wp.crs
            if crs is None:
                crs = 0.0
                if i > 1:
                    prev = wps[i - 2]
                    crs = geo.initial_bearing(prev.lat, prev.lon, wp.lat, wp.lon) + magvar
            values = {
                "ID": wp.id, "LAT": wp.lat, "LON": wp.lon,
                "TYPE": TYPE_TO_FPLTYPE.get(wp.type, 0), "PT": wp.pt or "TF",
                "CRS": round(crs % 360.0, 1) % 360.0, "DST": wp.dst, "ALT": wp.alt,
                "SPD": wp.spd, "SGI": sgi[i - 1],
                "FLAGS": (wp.flags & ~_ROLE_BITS) | ROLE_TO_FLAG.get(wp.role, 0),
                "CTRLAT": wp.ctr_lat, "CTRLON": wp.ctr_lon, "TURN": wp.turn,
            }
            for name, _, _ in SLOT_FIELDS:
                self._set(_slot_key(i, name), values[name])
        segcnt = len(plan.segments)
        first = 1
        for k in range(1, max(segcnt, self._published_segcnt) + 1):
            if k > segcnt:
                for name, _, blank in SEGMENT_FIELDS:
                    self._set(_seg_key(k, name), blank)
                continue
            seg = plan.segments[k - 1]
            last = first + len(seg.legs) - 1
            values = {"KIND": KIND_TO_WIRE[seg.kind], "ID": seg.ident,
                      "ENT": seg.entry, "EXT": seg.exit, "FIRST": first, "LAST": last}
            for name, _, _ in SEGMENT_FIELDS:
                self._set(_seg_key(k, name), values[name])
            first = last + 1
        self._set("FPLSEGCNT", segcnt)
        self._set("FPLCOUNT", count)
        self._set("FPLNAME", plan.name or plan.default_name())
        self._set("FPLDBCYC", next((s.cycle for s in plan.segments if s.cycle), ""))
        self._set("FPLSEQ", int(self._get("FPLSEQ").value) + 1)
        self._published_count = count
        self._published_segcnt = segcnt

    def stage_direct_to(self, wp) -> None:
        if not self.available:
            return
        self._set("DTOID", wp.id)
        self._set("DTOLAT", wp.lat)
        self._set("DTOLON", wp.lon)
        self._set("DTOTYPE", TYPE_TO_FPLTYPE.get(wp.type, 0))

    # -- commands (Appendix C) --------------------------------------------
    def command(self, verb: str, arg=None, on_ack=None) -> int | None:
        """Write ``FPLCMD = "<seq> VERB [arg]"``; *on_ack* -- if given -- is
        called ``on_ack(seq, ok, msg)`` when ``FPLCMDACK`` answers this seq.
        Returns the seq, or None if the bridge is unavailable."""
        if not self.available:
            return None
        self._seq_counter += 1
        seq = self._seq_counter
        text = f"{seq} {verb}" if arg is None else f"{seq} {verb} {arg}"
        if on_ack is not None:
            self._ack_callbacks[seq] = on_ack
        self._set("FPLCMD", text)
        return seq

    def _on_cmdack(self, value):
        seq = abs(int(value))
        cb = self._ack_callbacks.pop(seq, None)
        if cb is None:
            return
        cb(seq, value >= 0, self._get("FPLMSG").value)

    # -- ActivePlan read-back ---------------------------------------------
    def add_listener(self, callback) -> None:
        """*callback()* is invoked (no arguments) whenever the route block
        (``FPLSEQ``) or any engine output changes. The listener re-reads
        whatever it needs via :meth:`read_route` / :meth:`read_engine`."""
        self._listeners.append(callback)

    def _connect_readback(self):
        for key in ("FPLSEQ",) + ENGINE_OUTPUT_KEYS:
            item = self._get(key)
            item.valueWrite[item.dtype].connect(self._notify)
        ack_item = self._get("FPLCMDACK")
        ack_item.valueWrite[ack_item.dtype].connect(self._on_cmdack)

    def _notify(self, *_args) -> None:
        for cb in list(self._listeners):
            cb()

    def read_route(self) -> RouteBlock | None:
        if not self.available:
            return None
        count = int(self._get("FPLCOUNT").value)
        slots = []
        for i in range(1, count + 1):
            v = {name: self._get(_slot_key(i, name)).value for name, _, _ in SLOT_FIELDS}
            flags = int(v["FLAGS"])
            slots.append(RouteSlot(
                id=v["ID"], lat=v["LAT"], lon=v["LON"],
                type=FPLTYPE_TO_TYPE.get(int(v["TYPE"]), "unknown"),
                role=_flag_to_role(flags), pt=v["PT"] or "TF", crs=float(v["CRS"]),
                dst=float(v["DST"]), alt=v["ALT"] or "", spd=int(v["SPD"]),
                sgi=int(v["SGI"]), flags=flags & ~_ROLE_BITS, ctr_lat=float(v["CTRLAT"]),
                ctr_lon=float(v["CTRLON"]), turn=v["TURN"] or ""))
        segments = []
        for k in range(1, int(self._get("FPLSEGCNT").value) + 1):
            v = {name: self._get(_seg_key(k, name)).value for name, _, _ in SEGMENT_FIELDS}
            kind = int(v["KIND"])
            segments.append(RouteSegment(
                kind=model.SEGMENT_KINDS[kind] if 0 <= kind < len(model.SEGMENT_KINDS)
                else "waypoint",
                ident=v["ID"] or "", entry=v["ENT"] or "", exit=v["EXT"] or "",
                first=int(v["FIRST"]), last=int(v["LAST"])))
        return RouteBlock(name=self._get("FPLNAME").value,
                           seq=int(self._get("FPLSEQ").value), waypoints=slots,
                           segments=segments, cycle=self._get("FPLDBCYC").value or "")

    def read_plan(self):
        """The route on the bus as a ``model.FlightPlan``, segments and all
        -- the bus is the truth (route segments brief, guardrail 1). None
        if the bridge is unavailable. A table that does not describe the
        slots (a writer that predates RS1, which the engine itself would
        reject) reads as one waypoint segment per slot, with a log line,
        rather than a guess at what the segments were."""
        route = self.read_route()
        if route is None:
            return None
        return route_to_plan(route)

    def read_engine(self) -> dict[str, ItemValue] | None:
        if not self.available:
            return None
        out = {}
        for key in ENGINE_OUTPUT_KEYS:
            item = self._get(key)
            out[key] = ItemValue(value=item.value, old=item.old, bad=item.bad, fail=item.fail)
        return out

    def read_direct_to(self) -> DirectTo | None:
        """The staged direct-to point (``DTO*``, Appendix A) -- consumed by
        the map layer (FP6) to draw the activation-point-to-DTO line when
        off-route (``FPLSTATE=DIRECT``, ``FPLACTLEG=0``)."""
        if not self.available:
            return None
        return DirectTo(id=self._get("DTOID").value, lat=self._get("DTOLAT").value,
                         lon=self._get("DTOLON").value,
                         type=FPLTYPE_TO_TYPE.get(int(self._get("DTOTYPE").value), "unknown"))


def _slot_to_waypoint(slot: RouteSlot, coded_crs: bool) -> model.Waypoint:
    # The type comes off the wire as "unknown" for an out-of-range FPLfTYPE;
    # the model has no "unknown" waypoint type, so it reads as a plain fix.
    wp_type = slot.type if slot.type in model.WAYPOINT_TYPES else "fix"
    return model.Waypoint(
        id=slot.id, type=wp_type, lat=slot.lat, lon=slot.lon, role=slot.role,
        pt=slot.pt, crs=slot.crs if coded_crs else None, dst=slot.dst, alt=slot.alt,
        spd=slot.spd, flags=slot.flags, ctr_lat=slot.ctr_lat, ctr_lon=slot.ctr_lon,
        turn=slot.turn)


# Path terminators whose FPLfCRS is a coded course the editor must carry
# back (the engine flies it). For every other leg the bridge derived CRS
# from the great circle and the then-current MAGVAR, so reading it back as
# a coded course would freeze a variation-dependent number into the plan.
CODED_COURSE_PTS = frozenset({"CF", "CA", "FC", "VA", "VM", "VI", "FA", "HM", "HF", "HA", "PI"})


def route_to_plan(route: RouteBlock) -> model.FlightPlan:
    wps = [_slot_to_waypoint(s, s.pt in CODED_COURSE_PTS) for s in route.waypoints]
    segments = _segments_from_table(route, wps)
    if segments is None:
        if wps:
            log.warning("FixBridge: segment table does not describe the %d slots on the "
                        "bus; reading them as plain waypoints", len(wps))
        segments = [model.waypoint_segment(w) for w in wps]
    return model.FlightPlan(name=route.name, segments=segments)


def _segments_from_table(route: RouteBlock, wps):
    """The model segments the table describes, or None if it does not
    describe the slots exactly: every slot in exactly one segment, in
    order, each row's FIRST/LAST matching the slots' SGI. The same rules
    the engine enforces on commit (RS1), so a table that passes there
    passes here."""
    if len(route.segments) == 0:
        return [] if not wps else None
    segments = []
    expected_first = 1
    for k, row in enumerate(route.segments, start=1):
        if row.first != expected_first or row.last < row.first or row.last > len(wps):
            return None
        if any(route.waypoints[i - 1].sgi != k for i in range(row.first, row.last + 1)):
            return None
        try:
            segments.append(model.Segment(
                kind=row.kind, legs=wps[row.first - 1:row.last], ident=row.ident,
                cycle=route.cycle if row.kind != "waypoint" else ""))
        except model.FlightPlanError:
            return None
        expected_first = row.last + 1
    if expected_first != len(wps) + 1:
        return None
    return segments
