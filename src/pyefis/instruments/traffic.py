#  SPDX-License-Identifier: GPL-2.0-or-later
"""The ADS-B traffic block on the FIX bus, read once for every display.

``docs/fix_dynamic_list_spec.md`` section 5 is the contract: what a display
may assume about the ``TFCk*`` block that the fix-gateway traffic writer
fills. :class:`TrafficBlock` reads it by those rules, and the functions
here classify a target the way GDL90's display recommendations ask. The
moving map's traffic layer (P3b, ``map/layers/traffic.py``) and the
synthetic vision (SVSTFC1, ``ai/svs_traffic.py``) both draw from this one
reader. It lives outside the map package so a screen with synthetic vision
and no map loads no map code.

Reading rules, each from the spec:

- **Act on the commit key.** A slot is read only when its ``TFCkTGT`` is
  written (section 2.5). The handler runs synchronously in the thread that
  wrote ``TGT`` (the FIX client thread, or the test), and the writer writes
  every field before ``TGT``, so the fields it reads belong to that target.
  It builds an immutable :class:`Target` and stores it under a lock; paint
  only reads the stored targets.
- **Key state by identity, not slot.** Targets are stored by their ``TGT``
  value. A slot only says which identity to drop when it is emptied.
- **Flags.** ``TGT`` ``fail`` (the source failed, section 4.7) hides the
  target. ``TGT`` ``old`` (no report for 3 s) marks the target stale, until
  the writer evicts it (section 4.6: ``evict_s`` exceeds ``tol`` so that a
  stale target is shown as stale before it disappears). A stale target the
  writer never evicts -- the writer itself has died -- is hidden after
  :data:`STALE_HIDE_S`.
- A field marked ``bad`` is unavailable: it is read as None, never as zero.
  ``TTYP = 0`` (``TRK`` bad) gives a non-directional symbol (GDL90
  G§3.5.1.9).
- **Relative altitude** is ``TFCkALT - PALT`` (section 4.9). With ``PALT``
  absent, ``old``, ``bad`` or ``fail``, it is unavailable, never computed
  from another altitude.
- **No geometry filter.** Ownship is removed by identity in the writer
  (section 4.8, Bill's F6 ruling). Every target on the bus is a target,
  including one at ownship's own position.

Symbology classes follow GDL90's display recommendations (G§3.5.1.1,
G§3.5.1.6): alert = yellow, flashing; degraded (NIC or NACp 4 or lower) =
an open outline instead of a filled symbol; stale = grey, dashed.
"""

import threading
import time
from dataclasses import dataclass

from PyQt6.QtGui import QColor

#: probe bound for ``TFCnTGT``, matching the gateway writer's own (traffic.py
#: MAX_SLOTS). The block size is discovered, never hard-coded (spec 2.4).
MAX_SLOTS = 1000

#: slot fields read on a ``TGT`` write.
_FIELDS = ("LAT", "LON", "ALT", "VS", "TRK", "TTYP", "NIC", "NACP",
           "ALRT", "CS")

#: GDL90 G§3.5.1.6: a target with NIC or NACp at or below this is degraded.
DEGRADED_MAX = 4

#: vertical speed, fpm, at or beyond which the trend arrow shows (the TCAS
#: and ADS-B traffic convention, AC 20-172).
TREND_FPM = 500.0

#: seconds a stale target stays on screen after its last ``TGT`` write if
#: the writer never evicts it. The writer evicts at its ``evict_s`` (default
#: 10 s); still being stale past that means the writer is not running.
STALE_HIDE_S = 12.0

#: flash period of an alerted target, seconds per phase.
FLASH_S = 0.5

NORMAL_COLOR = QColor(255, 255, 255)
ALERT_COLOR = QColor(255, 210, 0)
STALE_COLOR = QColor(150, 150, 150)
OUTLINE_COLOR = QColor(0, 0, 0)
FAIL_COLOR = QColor(255, 190, 60)


@dataclass(frozen=True)
class Target:
    """One target as of its last ``TGT`` write. ``None`` = the field was
    ``bad`` (unavailable at the source)."""

    ident: int
    lat: float
    lon: float
    alt_ft: object          # float or None
    vs_fpm: object          # float or None
    trk_deg: object         # float or None; what ``ttyp`` says it is
    ttyp: int
    nic: int
    nacp: int
    alert: bool
    callsign: str
    stale: bool
    t_write: float          # time.monotonic() of the TGT write


def is_degraded(t):
    """GDL90 G§3.5.1.6: NIC or NACp 4 or lower (0 = unknown, also degraded)."""
    return t.nic <= DEGRADED_MAX or t.nacp <= DEGRADED_MAX


def true_track(t, magvar):
    """The target's direction of travel in degrees TRUE, or None for a
    non-directional symbol. ``TTYP`` 1 and 3 are true already; 2 is a
    magnetic heading, converted with ``MAGVAR`` (positive west, MAG = TRUE
    + VAR). With no ``MAGVAR`` a magnetic heading is not guessed at: the
    symbol goes non-directional rather than point the wrong way."""
    if t.trk_deg is None or t.ttyp == 0:
        return None
    if t.ttyp == 2:
        if magvar is None:
            return None
        return (t.trk_deg - magvar) % 360.0
    return t.trk_deg % 360.0


def relative_alt_ft(t, palt_ft):
    """``TFCkALT - PALT`` (spec 4.9), or None when either is unavailable."""
    if t.alt_ft is None or palt_ft is None:
        return None
    return t.alt_ft - palt_ft


def alt_tag(rel_ft):
    """Relative altitude in hundreds of feet, signed: ``+05``, ``-12``,
    ``00``. ``--`` when unavailable."""
    if rel_ft is None:
        return "--"
    h = int(round(rel_ft / 100.0))
    return "00" if h == 0 else "%+03d" % h


def trend(t):
    """+1 climbing, -1 descending, 0 level or unknown (``VS`` bad)."""
    if t.vs_fpm is None:
        return 0
    if t.vs_fpm >= TREND_FPM:
        return 1
    if t.vs_fpm <= -TREND_FPM:
        return -1
    return 0


def visible(t, now):
    """A stored target is drawn unless it has been stale past the cap."""
    return not (t.stale and now - t.t_write > STALE_HIDE_S)


def draw_order(targets):
    """Stale under live, alerts on top, so the target that matters most is
    never covered."""
    return sorted(targets, key=lambda t: (not t.stale, t.alert))


class TrafficBlock:
    """The ``TFC`` slots on the bus and the targets read from them.

    Thread-safe: the slot handlers run in whichever thread writes the keys,
    :meth:`targets` is called from paint on the GUI thread."""

    def __init__(self, db, on_change=None):
        self._db = db
        self._on_change = on_change
        self._lock = threading.Lock()
        self._by_ident = {}       # TGT value -> Target
        self._slot_ident = {}     # slot n -> TGT value held there
        self.slots = []
        self._seen_live = False
        self.count_item = self._get("TFCCOUNT")
        n = 1
        while n <= MAX_SLOTS:
            tgt = self._get("TFC%dTGT" % n)
            if tgt is None:
                break
            self.slots.append(n)
            tgt.valueWrite[int].connect(lambda _v, n=n: self.read_slot(n))
            tgt.oldChanged.connect(lambda _o, n=n: self.read_slot(n))
            tgt.failChanged.connect(lambda _f, n=n: self.read_slot(n))
            n += 1
        if self.count_item is not None:
            self.count_item.valueWrite[int].connect(lambda _v: self._count())
            self.count_item.failChanged.connect(lambda _f: self._count())
            self.count_item.oldChanged.connect(lambda _o: self._count())
            self._count()
        for n in self.slots:
            self.read_slot(n)

    @property
    def available(self):
        return bool(self.slots)

    def _get(self, key):
        try:
            return self._db.get_item(key)
        except KeyError:
            return None

    def _count(self):
        c = self.count_item
        if not (c.fail or c.old):
            self._seen_live = True
        self._changed()

    def _changed(self):
        if self._on_change is not None:
            self._on_change()

    def read_slot(self, n):
        """Re-read slot *n* after a write to (or a flag change on) its
        ``TGT``. Called in the writing thread, so the fields are the ones
        that preceded this ``TGT`` write."""
        tgt = self._db.get_item("TFC%dTGT" % n)
        ident = int(tgt.value)
        target = None
        if ident != -1 and not tgt.fail:
            target = self._read_fields(n, ident, bool(tgt.old))
        with self._lock:
            prev = self._slot_ident.pop(n, None)
            if prev is not None and prev != ident:
                self._by_ident.pop(prev, None)
            if target is not None:
                self._slot_ident[n] = ident
                self._by_ident[ident] = target
            elif ident != -1:
                # failed: hidden, but the slot still holds this identity
                self._slot_ident[n] = ident
                self._by_ident.pop(ident, None)
        self._changed()

    def _read_fields(self, n, ident, stale):
        def item(field):
            return self._db.get_item("TFC%d%s" % (n, field))

        def val(field):
            it = item(field)
            return None if it.bad else it.value

        lat, lon = item("LAT"), item("LON")
        if lat.bad or lon.bad:
            return None         # no valid position: nothing to place
        return Target(
            ident=ident, lat=float(lat.value), lon=float(lon.value),
            alt_ft=_float_or_none(val("ALT")),
            vs_fpm=_float_or_none(val("VS")),
            trk_deg=_float_or_none(val("TRK")),
            ttyp=int(item("TTYP").value or 0),
            nic=int(item("NIC").value or 0),
            nacp=int(item("NACP").value or 0),
            alert=int(item("ALRT").value or 0) == 1,
            callsign=str(item("CS").value or "").strip(),
            stale=stale, t_write=time.monotonic())

    def targets(self):
        with self._lock:
            return list(self._by_ident.values())

    def source_failed(self):
        """True when the writer reports its source failed (``TFCCOUNT``
        ``fail``) or has stopped writing (``TFCCOUNT`` ``old``) -- once it
        has been seen working. The gateway's default database carries the
        ``TFC`` block whether or not a receiver is fitted, so a block that
        has never been live is an installation without traffic, not a
        failure, and gets no chip."""
        c = self.count_item
        if c is None:
            return False
        if not (c.fail or c.old):
            self._seen_live = True
            return False
        return self._seen_live


def _float_or_none(v):
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def usable(item):
    """A FIX item's value as a float, or None when the item is absent,
    ``old``, ``bad`` or ``fail`` -- how ``PALT`` and ``MAGVAR`` are read."""
    if item is None or item.old or item.bad or item.fail:
        return None
    return _float_or_none(item.value)
