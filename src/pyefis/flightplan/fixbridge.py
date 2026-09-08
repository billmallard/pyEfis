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

Every callback this module exposes is a plain Python callable, never a
``pyqtSignal`` -- the instrument (FP5a) and the map layer (FP6) wrap them in
Qt signals themselves. This module does not import PyQt6 itself; connecting
to a ``pyavtools.fix`` ``DB_Item``'s existing bound signal does not require
importing Qt.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

MAX_SLOTS = 50

TYPE_TO_FPLTYPE = {"unknown": 0, "airport": 1, "vor": 2, "ndb": 3, "fix": 4, "user": 5, "map": 6}
FPLTYPE_TO_TYPE = {v: k for k, v in TYPE_TO_FPLTYPE.items()}
ROLE_TO_FPLROLE = {"none": 0, "iaf": 1, "faf": 2, "map": 3, "mahp": 4}
FPLROLE_TO_ROLE = {v: k for k, v in ROLE_TO_FPLROLE.items()}

# Appendix A engine outputs the ActivePlan read-back watches.
ENGINE_OUTPUT_KEYS = (
    "FPLSTATE", "FPLACTLEG", "FPLPHASE", "FPLAPR", "FPLINTEG", "CDISCALE",
    "FPLCRS", "FPLXTK", "FPLCDI", "FPLTF", "FPLFRLAT", "FPLFRLON",
    "WPNAME", "WPLAT", "WPLON", "WPFROM", "WPNEXT", "WPDIS", "WPETE",
    "FPLREMDIS", "FPLREMETE", "FPLALERT", "GPSSRC",
)

_STATIC_KEYS = (
    "FPLCOUNT", "FPLNAME", "FPLSEQ",
    "DTOID", "DTOLAT", "DTOLON", "DTOTYPE",
    "FPLCMD", "FPLCMDACK", "FPLMSG",
)


def _slot_keys(n: int) -> tuple[str, str, str, str, str]:
    return (f"FPL{n}ID", f"FPL{n}LAT", f"FPL{n}LON", f"FPL{n}TYPE", f"FPL{n}ROLE")


def _probe_keys():
    keys = list(_STATIC_KEYS) + list(ENGINE_OUTPUT_KEYS)
    keys.extend(_slot_keys(1))
    keys.extend(_slot_keys(MAX_SLOTS))
    return keys


@dataclass
class RouteSlot:
    id: str
    lat: float
    lon: float
    type: str
    role: str


@dataclass
class RouteBlock:
    name: str
    seq: int
    waypoints: list[RouteSlot] = field(default_factory=list)


@dataclass
class ItemValue:
    value: object
    old: bool
    bad: bool
    fail: bool


class FixBridge:
    """Wraps ``pyavtools.fix``. *fix_module* is the imported ``pyavtools.fix``
    (or a compatible test double exposing ``.db``)."""

    def __init__(self, fix_module):
        self._fix = fix_module
        self._seq_counter = 0
        self._published_count = 0
        self._ack_callbacks: dict[int, callable] = {}
        self._listeners: list[callable] = []

        self.available = self._probe()
        if self.available:
            self._published_count = int(self._get("FPLCOUNT").value)
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
        self._fix.db.set_value(key, value)

    # -- publish (editor -> bus) -----------------------------------------
    def publish(self, plan) -> None:
        """Write every slot 1..max(count, previously-published count) --
        blanking whatever the previous plan left behind -- then
        ``FPLCOUNT``, ``FPLNAME``, then ``FPLSEQ`` last (Appendix A
        protocol: consumers act only on the ``FPLSEQ`` change)."""
        if not self.available:
            return
        count = plan.count
        for i in range(1, max(count, self._published_count) + 1):
            id_key, lat_key, lon_key, type_key, role_key = _slot_keys(i)
            if i <= count:
                wp = plan.waypoints[i - 1]
                self._set(id_key, wp.id)
                self._set(lat_key, wp.lat)
                self._set(lon_key, wp.lon)
                self._set(type_key, TYPE_TO_FPLTYPE.get(wp.type, 0))
                self._set(role_key, ROLE_TO_FPLROLE.get(wp.role, 0))
            else:
                self._set(id_key, "")
                self._set(lat_key, 0.0)
                self._set(lon_key, 0.0)
                self._set(type_key, 0)
                self._set(role_key, 0)
        self._set("FPLCOUNT", count)
        self._set("FPLNAME", plan.name or plan.default_name())
        self._set("FPLSEQ", int(self._get("FPLSEQ").value) + 1)
        self._published_count = count

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
            id_key, lat_key, lon_key, type_key, role_key = _slot_keys(i)
            slots.append(RouteSlot(
                id=self._get(id_key).value,
                lat=self._get(lat_key).value,
                lon=self._get(lon_key).value,
                type=FPLTYPE_TO_TYPE.get(int(self._get(type_key).value), "unknown"),
                role=FPLROLE_TO_ROLE.get(int(self._get(role_key).value), "none")))
        return RouteBlock(name=self._get("FPLNAME").value,
                           seq=int(self._get("FPLSEQ").value), waypoints=slots)

    def read_engine(self) -> dict[str, ItemValue] | None:
        if not self.available:
            return None
        out = {}
        for key in ENGINE_OUTPUT_KEYS:
            item = self._get(key)
            out[key] = ItemValue(value=item.value, old=item.old, bad=item.bad, fail=item.fail)
        return out
