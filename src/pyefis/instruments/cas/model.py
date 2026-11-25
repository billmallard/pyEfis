#  SPDX-License-Identifier: GPL-2.0-or-later
"""What the CAS window and marker show, apart from Qt (CAS3, CAP-119).

The gateway's ``cas`` plugin (fix-gateway ``plugins/cas.py``, CAS2) owns every
alert condition and the sorted list. It publishes the list as twelve slots plus
summary keys (fix-gateway ``database/cas.yaml``; makerplane brief
``briefs/crew_alerting.md`` section 5.3)::

    CASMSG1..CASMSG12   LEVEL|ACK|ID|TEXT|DETAIL, or "" for an empty slot
    CASCNT              active messages, including any beyond slot 12
    CASTOP              highest unacknowledged level
    CASSEQ              bumped on every list change, written after the slots
    CASACK              a display writes the CASSEQ it is showing

pyEfis only reads that list, writes ``CASACK`` on a touch, and raises the
alerts only a display can see (brief section 6.4):

- ``GATEWAY LINK LOST`` (warning): the CERT1 link watchdog has tripped.
- ``CAS FAIL`` (caution): the gateway answers, but a ``CAS*`` key is missing,
  old, bad or failed, or the list has not been rewritten within
  :data:`STALE_S` (the plugin rewrites every key each second, tol 3 s).
- ``CATALOG REFUSED`` (advisory): the updater's ``status.json`` carries the
  CERT3 rollback refusal row (makerplane-data ``pyefis_data/core.py``,
  ``ROLLBACK``).
- ``CAS NOT SHOWN`` (advisory) is not raised here: it is the case where no
  window exists to raise it in. :mod:`pyefis.instruments.cas.coverage` shows it.

**A stale list is never drawn as current (C4).** While either of the first
two is active, :meth:`CASModel.messages` holds the local alerts only. It does
not keep the last slots "greyed": the pilot is told the list is unknown, and
every instrument still shows its own failure look (FHA assumption A3).

Nothing here decides an alert condition the gateway owns. A slot that does not
parse is dropped and logged, never repaired into a message.
"""

import logging
import time

logger = logging.getLogger(__name__)

WARNING = 3
CAUTION = 2
ADVISORY = 1
LEVEL_NAMES = {WARNING: "warning", CAUTION: "caution", ADVISORY: "advisory"}

SLOTS = 12
SLOT_KEYS = tuple("CASMSG{}".format(n + 1) for n in range(SLOTS))
SUMMARY_KEYS = ("CASCNT", "CASTOP", "CASSEQ")
ACK_KEY = "CASACK"
#: Every key whose loss is CAS FAIL. CASACK is pilot input (tol 0), not part
#: of the published list, so its state says nothing about the plugin.
LIST_KEYS = SLOT_KEYS + SUMMARY_KEYS

#: The plugin rewrites every list key once a second (cas.yaml); tol is 3 s.
#: A list older than this on our side is stale even if no flag says so, which
#: covers a gateway that stopped sending while the link watchdog is off. It
#: sits above the watchdog's worst case (2.0 s silence, polled every 0.5 s,
#: plus up to 1 s since the last rewrite), so in a gateway hang the link
#: alert comes first and CAS FAIL does not.
STALE_S = 4.5
#: After the display starts, how long a missing or never-reported key may wait
#: before it counts as CAS FAIL. The client defines items as the gateway lists
#: them, and a fresh item is bad and failed until its first report.
BOOT_GRACE_S = 5.0
#: A local link alert stays this long after its condition clears, so an
#: intermittent link does not flap the line (brief C6). The window stays
#: local-only until it clears.
LOCAL_CLEAR_S = 2.0

LINK_LOST_ID = "GWLINK"
CAS_FAIL_ID = "CASFAIL"
CATALOG_ID = "CATREF"

#: The updater's status for a refused older catalog (makerplane-data
#: ``pyefis_data/core.py`` ROLLBACK).
CATALOG_REFUSED_STATUS = "CATALOG REFUSED"

LOCAL_TEXT = {
    LINK_LOST_ID: (WARNING, "GATEWAY LINK LOST"),
    CAS_FAIL_ID: (CAUTION, "CAS FAIL"),
    CATALOG_ID: (ADVISORY, "CATALOG REFUSED"),
}
#: The order local alerts take among themselves within a level.
LOCAL_ORDER = (LINK_LOST_ID, CAS_FAIL_ID, CATALOG_ID)


class Message:
    """One line of the window: from a gateway slot, or local."""

    __slots__ = ("level", "acked", "id", "text", "detail", "local")

    def __init__(self, level, acked, id, text, detail="", local=False):
        self.level = level
        self.acked = acked
        self.id = id
        self.text = text
        self.detail = detail
        self.local = local

    @property
    def line(self):
        """The text drawn, the detail appended when there is one."""
        return "{}  {}".format(self.text, self.detail) if self.detail else self.text

    def __eq__(self, other):
        return isinstance(other, Message) and all(
            getattr(self, a) == getattr(other, a) for a in self.__slots__)

    def __repr__(self):
        return "Message({}, acked={}, {!r}, {!r}{})".format(
            self.level, self.acked, self.id, self.line,
            ", local" if self.local else "")


def parse_slot(value):
    """A :class:`Message` from one ``CASMSGn`` value, or None for an empty or
    malformed slot. Malformed means anything but five ``|`` fields with a
    level of 1-3 and an ack of 0 or 1: the plugin refuses text holding ``|``
    at load, so a slot that splits otherwise was not written by it."""
    if not isinstance(value, str) or value == "":
        return None
    parts = value.split("|")
    if len(parts) != 5:
        return None
    level, ack, ident, text, detail = parts
    if level not in ("1", "2", "3") or ack not in ("0", "1") or not text:
        return None
    return Message(int(level), ack == "1", ident, text, detail)


def catalog_refused(status):
    """True when the updater's status.json carries the CERT3 rollback refusal
    (a pack row with status ``CATALOG REFUSED``). Read defensively, like
    data_status: anything that is not the expected shape means no."""
    if not isinstance(status, dict):
        return False
    packs = status.get("packs")
    if not isinstance(packs, list):
        return False
    return any(isinstance(p, dict) and p.get("status") == CATALOG_REFUSED_STATUS
               for p in packs)


def sort_key(m):
    """Brief 5.2: warnings, cautions, advisories; within a level
    unacknowledged before acknowledged. Python's sort is stable, so the
    gateway's newest-first order inside each group is kept."""
    return (-m.level, m.acked)


class CASModel:
    """The list a display shows, read from the FIX database.

    ``lookup(key)`` returns a FIX item or raises KeyError (``fix.db.get_item``
    with ``wait=False``). ``link_lost()`` says whether the link watchdog has
    tripped. ``status()`` returns the parsed status.json or None. ``clock``
    returns monotonic seconds. All are injected so tests drive them.

    :meth:`poll` reads everything once; the window calls it on its own timer,
    on the GUI thread, so nothing here runs in a FIX callback thread.
    """

    def __init__(self, lookup, link_lost=lambda: False, status=lambda: None,
                 clock=time.monotonic):
        self.lookup = lookup
        self.link_lost = link_lost
        self.status = status
        self.clock = clock
        self.started = clock()
        self._items = {}
        self._missing_logged = set()
        #: The last list read in one piece: (seq, [Message], count).
        self.snapshot = None
        # Local alert state: id -> {"since", "clear_at", "acked"}
        self._local = {}
        self.list_ok = False
        self.reason = "not read yet"
        self._read_failed = False
        self.poll()

    # -- reading ------------------------------------------------------------
    def _item(self, key):
        item = self._items.get(key)
        if item is not None:
            return item
        try:
            item = self.lookup(key)
        except KeyError:
            if key not in self._missing_logged:
                self._missing_logged.add(key)
                logger.warning("CAS: FIX key %s is not defined (fix-gateway "
                               "database/cas.yaml); CAS FAIL while it is "
                               "missing", key)
            return None
        self._items[key] = item
        return item

    def _list_health(self, now):
        """(ok, reason). ok only while every list key is defined, none is
        old, bad or failed, and the list was rewritten within STALE_S."""
        for key in LIST_KEYS:
            item = self._item(key)
            if item is None:
                return False, "{} not defined".format(key)
            if item.old or item.bad or item.fail:
                return False, "{} {}".format(
                    key, "old" if item.old else "bad" if item.bad else "failed")
        age_s = self._items["CASSEQ"].age / 1000.0
        if age_s > STALE_S:
            return False, "CASSEQ not rewritten for {:.1f} s".format(age_s)
        return True, ""

    def _read_list(self):
        """Read the slots in one piece: CASSEQ before and after must agree,
        since the plugin writes the slots first and CASSEQ last. Returns
        (seq, messages, count) or None when a write landed mid-read."""
        seq = int(self._items["CASSEQ"].value)
        msgs = []
        for key in SLOT_KEYS:
            raw = self._items[key].value
            m = parse_slot(raw)
            if m is None:
                if raw not in ("", None):
                    logger.error("CAS: %s holds %r, not a slot; dropped",
                                 key, raw)
                continue
            msgs.append(m)
        count = max(int(self._items["CASCNT"].value), len(msgs))
        if int(self._items["CASSEQ"].value) != seq:
            return None
        return seq, msgs, count

    def _set_local(self, ident, active, now):
        st = self._local.get(ident)
        if active:
            if st is None:
                self._local[ident] = {"since": now, "clear_at": None,
                                      "acked": False}
                level, text = LOCAL_TEXT[ident]
                logger.warning("CAS: local %s %s", LEVEL_NAMES[level], text)
            else:
                st["clear_at"] = None
            return
        if st is None:
            return
        hold = LOCAL_CLEAR_S if ident in (LINK_LOST_ID, CAS_FAIL_ID) else 0.0
        if st["clear_at"] is None:
            st["clear_at"] = now + hold
        if now >= st["clear_at"]:
            del self._local[ident]
            logger.info("CAS: local %s cleared", LOCAL_TEXT[ident][1])

    def poll(self):
        now = self.clock()
        try:
            link_lost = bool(self.link_lost())
            ok, reason = self._list_health(now)
            snap = self._read_list() if ok and not link_lost else None
        except Exception:
            # A read that raises on every poll must not leave the last list
            # drawn as current (FHA CAS-4): it is CAS FAIL, logged once.
            if not self._read_failed:
                logger.exception("CAS: reading the list failed; CAS FAIL")
            self._read_failed = True
            link_lost, ok, reason, snap = False, False, "read failed", None
        else:
            if self._read_failed:
                logger.info("CAS: reading the list works again")
            self._read_failed = False
        in_grace = now - self.started < BOOT_GRACE_S
        self.list_ok = ok
        self.reason = reason
        self._set_local(LINK_LOST_ID, link_lost, now)
        # CAS FAIL is "the gateway answers, but the list is lost": on link
        # loss every key is marked failed, and the link alert says why. So the
        # link alert also removes a CAS FAIL at once, without its clear delay:
        # the window never shows both causes for one loss.
        if link_lost:
            self._local.pop(CAS_FAIL_ID, None)
        self._set_local(CAS_FAIL_ID, not link_lost and not ok and not in_grace,
                        now)
        if ok and not link_lost:
            # None here is a write landing mid-read: keep the last whole list.
            if snap is not None:
                self.snapshot = snap
        else:
            self.snapshot = None
        self._set_local(CATALOG_ID, catalog_refused(self.status()), now)

    # -- what is shown --------------------------------------------------------
    @property
    def local_only(self):
        """True while the gateway list must not be shown (C4): the link is
        lost, the list is lost, or one of their alerts is still clearing."""
        return (self.snapshot is None or LINK_LOST_ID in self._local
                or CAS_FAIL_ID in self._local)

    def local_messages(self):
        out = []
        for ident in LOCAL_ORDER:
            st = self._local.get(ident)
            if st is None:
                continue
            level, text = LOCAL_TEXT[ident]
            out.append(Message(level, st["acked"], ident, text, local=True))
        return out

    def messages(self):
        """Every line, sorted (brief 5.2). Local alerts lead their level: they
        are about the alerting system itself."""
        msgs = self.local_messages()
        if not self.local_only:
            msgs += self.snapshot[1]
        return sorted(msgs, key=sort_key)

    def count(self):
        """Active messages, including gateway ones beyond slot 12."""
        n = len(self.local_messages())
        if not self.local_only:
            n += self.snapshot[2]
        return n

    def top_level(self):
        """Highest level among active messages (0 for none)."""
        return max([m.level for m in self.messages()] or [0])

    def unacked(self):
        return any(not m.acked for m in self.messages())

    def aural_level(self):
        """The level whose tone sounds (CAS4, brief section 7): the gateway's
        ``CASTOP`` while its list is shown, raised by any unacknowledged
        local alert. ``CASTOP`` is the plugin's own answer, so it is read,
        not recomputed from the slots. During link loss or ``CAS FAIL`` it is
        not read at all: a stale ``CASTOP`` must not sound (C4)."""
        level = max([m.level for m in self.local_messages() if not m.acked]
                    or [0])
        if not self.local_only:
            try:
                top = int(self._items["CASTOP"].value)
            except (KeyError, TypeError, ValueError):
                top = 0
            level = max(level, min(WARNING, max(0, top)))
        return level

    @property
    def seq(self):
        return None if self.local_only else self.snapshot[0]

    # -- acknowledge ----------------------------------------------------------
    def acknowledge(self):
        """Acknowledge what this display shows: the local alerts here, and on
        the gateway every message up to the ``CASSEQ`` of the list drawn
        (brief 6.5). A list newer than the one drawn is not acknowledged: the
        sequence written is the drawn one, not a fresh read. Returns True when
        anything was acknowledged."""
        did = False
        for st in self._local.values():
            if not st["acked"]:
                st["acked"] = True
                did = True
        if self.local_only:
            return did
        if not any(not m.acked for m in self.snapshot[1]):
            return did
        item = self._item(ACK_KEY)
        if item is None:
            return did
        item.bad = False
        item.fail = False
        item.value = self.snapshot[0]
        item.output_value()
        logger.info("CAS: acknowledged up to CASSEQ %d", self.snapshot[0])
        return True
