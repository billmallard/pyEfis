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

import functools
import logging
import weakref
from dataclasses import dataclass, field

from . import geo
from . import model
from . import proc_load
from . import vocab

log = logging.getLogger(__name__)


def _cmd_seq(text) -> int:
    """The seq at the head of an ``FPLCMD`` string, 0 if there is none."""
    try:
        return int(str(text or "").split()[0])
    except (IndexError, ValueError):
        return 0

MAX_SLOTS = 100

TYPE_TO_FPLTYPE = vocab.TYPE_TO_FPLTYPE
FPLTYPE_TO_TYPE = vocab.FPLTYPE_TO_TYPE

# The role rides in FPLfFLAGS beside fly-over and from-a-coded-procedure,
# which this module carries through untouched (vocab.ROLE_TO_FLAG).
ROLE_TO_FLAG = vocab.ROLE_TO_FLAG
_FLAG_TO_ROLE = tuple((bit, role) for role, bit in ROLE_TO_FLAG.items() if bit)


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

# Engine outputs newer than the base contract. They are read and watched
# when the gateway has them, but never probed: an older gateway without one
# keeps the bridge available, and read_engine() just leaves the key out, so
# the reader falls back to its pre-key behaviour (the HSI's absent CDIV/GSV
# precedent). FPLSUSPMAP (G49): 1 = suspended at the MAP auto-suspend.
# FPLLDSEQ (PA8): the FPLSEQ of the route the engine has loaded; it differs
# from FPLSEQ after a rejected commit, when the slots on the bus hold a
# route the engine refused. FPLHOLDSLOT/FPLHOLDENT/FPLHOLDCOMMIT
# (HOLDENT1): the next hold's slot, its AIM 5-3-8 entry, and whether that
# entry is the one being flown or a prediction.
OPTIONAL_ENGINE_OUTPUT_KEYS = ("FPLSUSPMAP", "FPLLDSEQ",
                               "FPLHOLDSLOT", "FPLHOLDENT", "FPLHOLDCOMMIT")

# TURN3 (fix-gateway flightplan.yaml, AER-5418): FPLfTA, each slot's fly-by
# turn anticipation in nm, the one slot field the engine writes. Read and
# watched when the gateway has it, never probed or written: an older
# gateway reads as no arcs, the square corners drawn before the key.
TURN_FIELD = "TA"

# The staged direct-to point (Appendix A): watched as well, since the map
# draws it, and its writes are rare (stage_direct_to).
_DTO_KEYS = ("DTOID", "DTOLAT", "DTOLON", "DTOTYPE")

_STATIC_KEYS = (
    "FPLCOUNT", "FPLNAME", "FPLSEQ", "FPLSEGCNT", "FPLAPRTYPE", "FPLDBCYC",
    *_DTO_KEYS,
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

# Staging blocks (EFB4b, AER-6706; PROV0, AER-6749): a plan an outside source
# has put on the bus beside the route block, waiting for the pilot to accept
# or reject it. Each block has the same shape: points <prefix>1..100 ID, LAT,
# LON, TYPE, then <prefix>COUNT and <prefix>NAME, then <prefix>SEQ written
# last; <prefix>DONE is the SEQ the pilot answered, and the one key of the
# block the editor writes. A plan is staged while SEQ > 0 and DONE differs
# from it. Nothing here knows where a block's plan came from: the page's
# prompt text does. Read and watched when the gateway has a block, never
# probed: an older gateway keeps the bridge available, with nothing staged.
@dataclass(frozen=True)
class StagingBlock:
    prefix: str
    count: str
    name: str
    seq: str
    done: str


# fix-gateway fpl_exchange's pending import (doc/flightplan_keys.md,
# "Pending import"). Further blocks of the same shape join STAGING_BLOCKS.
FPLIMP = StagingBlock(prefix="FPLIMP", count="FPLIMPCOUNT", name="FPLIMPNAME",
                      seq="FPLIMPSEQ", done="FPLIMPDONE")
STAGING_BLOCKS = (FPLIMP,)
STAGING_POINT_FIELDS = (("ID", "str", ""), ("LAT", "float", 0.0), ("LON", "float", 0.0),
                        ("TYPE", "int", 0))
# FPLfID holds up to 6 characters (doc/flightplan_keys.md); a staged ident
# may be longer (FPLIMPfID takes 12). Only a user waypoint is that long, and
# it is placed by its position, so its ident is a label: it loads cut to 6,
# with the whole identifier kept as the waypoint's name (ARCH1, AER-6402).
ROUTE_ID_MAX_LEN = 6
# The keys whose write can start, replace or withdraw a staged plan.
STAGING_WATCH_KEYS = frozenset(k for b in STAGING_BLOCKS for k in (b.seq, b.done))

# The FPLfFLAGS bits that are not the role (fly-over, from a coded
# procedure): carried on Waypoint.flags.
_ROLE_BITS = vocab.ROLE_BITS


def _slot_key(n: int, name: str) -> str:
    return f"FPL{n}{name}"


def _seg_key(k: int, name: str) -> str:
    return f"FPLS{k}{name}"


_SLOT_NAMES = tuple(name for name, _, _ in SLOT_FIELDS)
_SEG_NAMES = tuple(name for name, _, _ in SEGMENT_FIELDS)


@functools.cache
def _slot_keys(n: int) -> tuple[str, ...]:
    return tuple(_slot_key(n, name) for name in _SLOT_NAMES)


@functools.cache
def _seg_keys(k: int) -> tuple[str, ...]:
    return tuple(_seg_key(k, name) for name in _SEG_NAMES)


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
            ("FPLSEGCNT", "int", 0), ("FPLAPRTYPE", "str", ""), ("FPLDBCYC", "str", ""),
            ("DTOID", "str", ""), ("DTOLAT", "float", 0.0), ("DTOLON", "float", 0.0),
            ("DTOTYPE", "int", 0), ("FPLCMD", "str", ""), ("FPLCMDACK", "int", 0),
            ("FPLMSG", "str", "")):
        yield key, dtype, blank


def staging_key_specs(block=FPLIMP):
    """``(key, dtype, blank)`` for one staging block, apart from
    :func:`route_key_specs` because a gateway may not have it."""
    for n in range(1, MAX_SLOTS + 1):
        for name, dtype, blank in STAGING_POINT_FIELDS:
            yield f"{block.prefix}{n}{name}", dtype, blank
    yield from ((block.count, "int", 0), (block.name, "str", ""),
                (block.seq, "int", 0), (block.done, "int", 0))


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
class StagedPoint:
    id: str
    lat: float
    lon: float
    type: str


@dataclass
class StagedPlan:
    """A plan waiting for the pilot in *block*: *seq* is the block's SEQ it
    arrived under, the value Accept and Reject answer."""
    block: StagingBlock
    seq: int
    name: str
    points: list[StagedPoint] = field(default_factory=list)


@dataclass
class DirectTo:
    id: str
    lat: float
    lon: float
    type: str


class _KeyedWrite:
    """The slot of one watched item: FixBridge._notify with the item's key
    (FixBridge._watch). Holds the bridge weakly."""

    def __init__(self, bridge, key):
        self._bridge = weakref.ref(bridge)
        self._key = key

    def notify(self, *_args) -> None:
        bridge = self._bridge()
        if bridge is not None:
            bridge._notify(self._key)


class FixBridge:
    """Wraps ``pyavtools.fix``. *fix_module* is the imported ``pyavtools.fix``
    (or a compatible test double exposing ``.db``)."""

    # _get()'s item cache, and the database it was filled from.
    _items: dict | None = None
    _item_rows: dict | None = None
    _items_db = None

    def __init__(self, fix_module):
        self._fix = fix_module
        self._last_seq = 0
        self._published_count = 0
        self._published_segcnt = 0
        self._ack_callbacks: dict[int, callable] = {}
        self._listeners: list[tuple[callable, bool]] = []
        self._watchers: list[_KeyedWrite] = []

        self.available = self._probe()
        # The staging blocks this gateway has.
        self.staging = tuple(b for b in STAGING_BLOCKS
                             if self.available and self._probe_staging(b))
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

    def _probe_staging(self, block) -> bool:
        keys = [block.count, block.name, block.seq, block.done]
        for n in (1, MAX_SLOTS):
            keys.extend(f"{block.prefix}{n}{name}" for name, _, _ in STAGING_POINT_FIELDS)
        try:
            for key in keys:
                self._fix.db.get_item(key)
            return True
        except KeyError:
            return False

    def _get(self, key):
        # pyavtools keeps one item object per key for the life of its
        # database -- a gateway reconnect redefines the same object -- so
        # the item is looked up once. get_item() takes a lock and waits on
        # the database's init event every call, and the readers here make
        # some 300 lookups for one route (pyEfis #480). A key that is not
        # there is not cached: it may be defined later.
        db = self._fix.db
        if self._items is None or db is not self._items_db:
            self._items = {}
            self._item_rows = {}
            self._items_db = db
        item = self._items.get(key)
        if item is None:
            item = self._items[key] = db.get_item(key)
        return item

    def _row(self, keys):
        """The items for *keys* (one slot's or segment's fields), looked up
        together and kept, as _get keeps one."""
        self._get(keys[0])          # resets both caches on a new database
        row = self._item_rows.get(keys)
        if row is None:
            row = self._item_rows[keys] = tuple(self._get(k) for k in keys)
        return row

    def _set(self, key, value) -> None:
        # set_value() only updates pyEfis's local copy: pyavtools sends a key
        # to the gateway only on output_value() (or for keys listed in the
        # `outputs` config, which the FP1 keys are not). Without this the
        # route, DTO staging and FPLCMD never left the display -- the editor
        # looked right on glass while the engine saw nothing (AER-810 bench,
        # 2026-10-10: three waypoints on screen, FPLCOUNT=1 on fixgw). Same
        # value-then-output_value() pattern as hmi/functions.py setValue.
        item = self._get(key)
        item.value = value
        item.output_value()

    # -- publish (editor -> bus) -----------------------------------------
    def _magvar(self) -> float:
        """Local variation (``MAGVAR``, positive west, MAG = TRUE + VAR) --
        the value the engine converts ``FPLCRS`` with. 0 when the gateway
        does not publish it."""
        var = self.magvar_or_none()
        return 0.0 if var is None else var

    def magvar_or_none(self):
        """``MAGVAR`` as :meth:`_magvar`, but None when the gateway does not
        publish it, so a display can label the bearing true instead of
        passing it off as magnetic."""
        try:
            return float(self._get("MAGVAR").value or 0.0)
        except (KeyError, TypeError, ValueError):
            return None

    def publish(self, plan) -> None:
        """Write every slot field and the segment table, blanking whatever
        the previous plan left past the new counts, then ``FPLSEGCNT`` and
        ``FPLCOUNT``, ``FPLNAME``, ``FPLAPRTYPE`` (the loaded approach's
        type, PA9), ``FPLDBCYC``, and ``FPLSEQ`` last (RS1 writer order:
        consumers act only on the ``FPLSEQ`` change).

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
        self._set("FPLAPRTYPE", proc_load.approach_type(plan.segments))
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
        seq = self._next_seq()
        text = f"{seq} {verb}" if arg is None else f"{seq} {verb} {arg}"
        if on_ack is not None:
            self._ack_callbacks[seq] = on_ack
        self._set("FPLCMD", text)
        return seq

    def _next_seq(self) -> int:
        """One past the highest seq this bridge has sent or seen on the bus.
        Appendix C wants the seq strictly increasing per editor session, and
        one display can hold several bridges -- the flight_plan instrument's
        and the moving map's (FP10, billmallard/pyEfis#186) -- each writing
        ``FPLCMD``. Private counters would both start at 1, re-send an
        identical string and answer each other's ``FPLCMDACK``; the last
        command and ack on the bus are shared by every writer."""
        seen = max(_cmd_seq(self._get("FPLCMD").value),
                   abs(int(self._get("FPLCMDACK").value or 0)))
        self._last_seq = max(self._last_seq, seen) + 1
        return self._last_seq

    def _on_cmdack(self, value):
        seq = abs(int(value))
        cb = self._ack_callbacks.pop(seq, None)
        if cb is None:
            return
        cb(seq, value >= 0, self._get("FPLMSG").value)

    # -- ActivePlan read-back ---------------------------------------------
    def add_listener(self, callback, keyed=False) -> None:
        """*callback()* is invoked (no arguments) on every write of
        ``FPLSEQ``, of an engine output, of a slot's ``FPLfTA`` or of the
        staged direct-to point -- a write, not a change: the engine
        rewrites all its outputs each cycle, so expect some 25 calls per
        cycle. The listener re-reads what it needs via
        :meth:`read_engine`, and :meth:`read_route` only when
        :meth:`route_key` has moved.

        With *keyed* the callback gets the written key, ``callback(key)``,
        so a listener can skip a write that cannot change what it shows
        without reading anything: most of the 25 are readouts."""
        self._listeners.append((callback, keyed))

    def _optional_items(self):
        for key in OPTIONAL_ENGINE_OUTPUT_KEYS:
            try:
                yield key, self._get(key)
            except KeyError:
                continue

    def _watch(self, key, item):
        # A bound method, not a partial or lambda: PyQt holds a bound
        # method's object weakly, so a bridge that is dropped (a widget
        # rebuilt, a second writer) disconnects instead of staying alive
        # on the item's signal with its listeners. The bridge owns the
        # _KeyedWrite, which holds the bridge only weakly.
        watcher = _KeyedWrite(self, key)
        self._watchers.append(watcher)
        item.valueWrite[item.dtype].connect(watcher.notify)

    def _connect_readback(self):
        for key in ("FPLSEQ",) + ENGINE_OUTPUT_KEYS + _DTO_KEYS:
            self._watch(key, self._get(key))
        for key, item in self._optional_items():
            self._watch(key, item)
        for block in self.staging:
            # SEQ is written last by the block's writer; DONE by any
            # display's editor, so an answer on one display clears them all.
            for key in (block.seq, block.done):
                self._watch(key, self._get(key))
        for n in range(1, MAX_SLOTS + 1):
            key = _slot_key(n, TURN_FIELD)
            try:
                item = self._get(key)
            except KeyError:
                break
            self._watch(key, item)
        ack_item = self._get("FPLCMDACK")
        ack_item.valueWrite[ack_item.dtype].connect(self._on_cmdack)

    def _notify(self, key) -> None:
        for cb, keyed in list(self._listeners):
            if keyed:
                cb(key)
            else:
                cb()

    def route_key(self):
        """``(FPLSEQ, FPLCOUNT, FPLSEGCNT, FPLLDSEQ)``: equal keys mean the
        route block and the engine's answer to it are unchanged, so a
        reader holding a route read under this key has nothing to re-read.
        None when the bridge is unavailable; ``FPLLDSEQ`` is None on a
        gateway that does not publish it.

        Listeners are called on every write of an engine output, and the
        engine rewrites all of them each guidance cycle whether or not they
        changed. Reading the route costs a FIX lookup for every field of
        every slot, so a listener compares this first (RS1 writer order:
        ``FPLSEQ`` is written last, and consumers act only on its change;
        the engine's own write-back ends with ``FPLSEQ`` then
        ``FPLLDSEQ``)."""
        if not self.available:
            return None
        try:
            loaded = int(self._get("FPLLDSEQ").value)
        except (KeyError, TypeError, ValueError):
            loaded = None
        return (int(self._get("FPLSEQ").value), int(self._get("FPLCOUNT").value),
                int(self._get("FPLSEGCNT").value), loaded)

    def read_route(self) -> RouteBlock | None:
        if not self.available:
            return None
        count = int(self._get("FPLCOUNT").value)
        slots = []
        for i in range(1, count + 1):
            v = dict(zip(_SLOT_NAMES, [item.value for item in self._row(_slot_keys(i))]))
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
            v = dict(zip(_SEG_NAMES, [item.value for item in self._row(_seg_keys(k))]))
            kind = int(v["KIND"])
            segments.append(RouteSegment(
                kind=model.SEGMENT_KINDS[kind] if 0 <= kind < len(model.SEGMENT_KINDS)
                else "waypoint",
                ident=v["ID"] or "", entry=v["ENT"] or "", exit=v["EXT"] or "",
                first=int(v["FIRST"]), last=int(v["LAST"])))
        return RouteBlock(name=self._get("FPLNAME").value,
                           seq=int(self._get("FPLSEQ").value), waypoints=slots,
                           segments=segments, cycle=self._get("FPLDBCYC").value or "")

    def read_turn_anticipations(self, count: int) -> list[float]:
        """``FPLfTA`` for slots 1..*count*: the engine's fly-by turn
        anticipation at each fix, 0.0 for no arc. All 0.0 when the gateway
        does not publish the key (no arcs, as before it existed)."""
        if not self.available:
            return [0.0] * count
        out = []
        for i in range(1, count + 1):
            try:
                value = self._get(_slot_key(i, TURN_FIELD)).value
            except KeyError:
                return [0.0] * count
            try:
                out.append(max(float(value or 0.0), 0.0))
            except (TypeError, ValueError):
                out.append(0.0)
        return out

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
        for key, item in self._optional_items():
            out[key] = ItemValue(value=item.value, old=item.old, bad=item.bad, fail=item.fail)
        return out

    def staged_seq(self, block=FPLIMP) -> int | None:
        """The SEQ of the plan waiting in *block*: set while SEQ > 0 and
        DONE differs from it. None when nothing is staged there, or the
        gateway has no such block."""
        if block not in self.staging:
            return None
        try:
            seq = int(self._get(block.seq).value)
            done = int(self._get(block.done).value)
        except (TypeError, ValueError):
            return None
        return seq if seq > 0 and done != seq else None

    def read_staged(self, block=FPLIMP) -> StagedPlan | None:
        """The plan waiting in *block* (:meth:`staged_seq`), or None. Read
        whole: a caller that must know the points did not change under it
        compares two reads (SEQ is written last, but a newer plan overwrites
        the points before it bumps the counter)."""
        seq = self.staged_seq(block)
        if seq is None:
            return None
        count = max(0, min(int(self._get(block.count).value or 0), MAX_SLOTS))
        points = []
        for n in range(1, count + 1):
            ident, lat, lon, typ = (self._get(f"{block.prefix}{n}{name}").value
                                    for name, _, _ in STAGING_POINT_FIELDS)
            points.append(StagedPoint(id=str(ident or ""), lat=float(lat), lon=float(lon),
                                      type=FPLTYPE_TO_TYPE.get(int(typ), "unknown")))
        return StagedPlan(block=block, seq=seq, name=str(self._get(block.name).value or ""),
                          points=points)

    def answer_staged(self, block, seq: int) -> None:
        """Answer the plan *seq* in *block*, accepted or rejected
        (DONE = seq). An accepted plan is committed first, through
        :meth:`publish`; this only says it has been dealt with."""
        if block in self.staging:
            self._set(block.done, int(seq))  # writes: FPLIMPDONE

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
CODED_COURSE_PTS = vocab.CODED_COURSE_PTS


def route_to_plan(route: RouteBlock) -> model.FlightPlan:
    wps = [_slot_to_waypoint(s, s.pt in CODED_COURSE_PTS) for s in route.waypoints]
    segments = _segments_from_table(route, wps)
    if segments is None:
        if wps:
            log.warning("FixBridge: segment table does not describe the %d slots on the "
                        "bus; reading them as plain waypoints", len(wps))
        segments = [model.waypoint_segment(w) for w in wps]
    plan = model.FlightPlan(segments=segments)
    # FPLNAME carries a name whether or not the pilot gave one: publish()
    # fills an unnamed plan with its default "FIRST-LAST". Reading that back
    # as an explicit name froze it at the first waypoint ("KSBA-KSBA" for a
    # route to KSMX, pyEfis #327), so a name that is still the default for
    # the slots it was published with reads back as unnamed and keeps
    # tracking the route. A pilot name that happens to equal the endpoints
    # is indistinguishable on the wire and tracks too.
    if route.name != plan.default_name():
        plan.name = route.name
    return plan


def staged_to_plan(staged: StagedPlan, source: str = "device") -> model.FlightPlan:
    """The staged plan as the plan Accept commits: one waypoint segment per
    point, each a TF leg to its fix, the staged name, and *source* (the
    model's provenance field, which the caller names). A staging block
    carries no altitudes, speeds, airways or procedures, so the plan has
    none. An ident longer than ``FPLfID`` holds is cut to
    :data:`ROUTE_ID_MAX_LEN`, and the whole identifier kept as the name."""
    wps = []
    for pt in staged.points:
        wp_type = pt.type if pt.type in model.WAYPOINT_TYPES else "fix"
        ident = pt.id[:ROUTE_ID_MAX_LEN]
        wps.append(model.Waypoint(id=ident, type=wp_type, lat=pt.lat, lon=pt.lon,
                                  name=pt.id if ident != pt.id else ""))
    return model.FlightPlan(name=staged.name[:model.NAME_MAX_LEN], waypoints=wps,
                            source=source)


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
