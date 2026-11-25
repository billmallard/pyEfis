#  SPDX-License-Identifier: GPL-2.0-or-later
"""The autopilot state keys, read once per display (AFC1 contract).

fix-gateway ``database/autopilot.yaml`` and ``doc/autopilot_keys.md`` define
the keys. Every state and health key has a tol and the source rewrites it at
least once per tol, so a key that goes old means the source went quiet. A
display then shows "no autopilot data" and never the last value (brief
section 5.7, "stale is removed, not frozen").

:class:`APState` is the guarded subscription:

- Construction never raises. A gateway without ``autopilot.yaml`` (older than
  AFC1) logs a warning per missing key and leaves :attr:`available` False, so
  the host instrument still builds and draws nothing.
- :attr:`fresh` is True only while every key it reads is defined and none is
  old, bad or failed. One stale key blanks the whole reading: the keys
  describe one autopilot, and half of it is not a state.
- :attr:`seen_live` latches the first fresh reading. A key block in the
  default database exists whether or not an autopilot is installed, so "no
  data" is only worth showing once a source has been seen.

It only reads. Writing a request (``APCMD`` then ``APCMDSEQ``) is
:func:`send_request`, used by a display that offers one.
"""

import logging

from PyQt6.QtCore import QObject, pyqtSignal

import pyavtools.fix as fix

logger = logging.getLogger(__name__)

#: The state and health keys a mode annunciation reads (AFC1 section "State"
#: and "Health"). All have tol 2000 ms.
STATE_KEYS = ("APENG", "YDENG", "APLAT", "APLATARM", "APVERT", "APVERTARM",
              "APALTCAP", "APDISC")

#: Request keys (pilot-written, tol 0): the command, then its counter.
CMD_KEY = "APCMD"
SEQ_KEY = "APCMDSEQ"


def mode_list(value):
    """An armed-mode list (``"GS,ALT"``) as names in the order given.
    Blanks and stray spaces are dropped; a non-string reads as empty."""
    if not isinstance(value, str):
        return []
    return [name.strip().upper() for name in value.split(",") if name.strip()]


def mode_name(value):
    """An active-mode key's value as a name, ``""`` for none."""
    return value.strip().upper() if isinstance(value, str) else ""


class APState(QObject):
    """The AFC1 state keys, subscribed once. ``changed`` fires on any value
    or quality change of any of them."""

    changed = pyqtSignal()

    def __init__(self, keys=STATE_KEYS, parent=None):
        super().__init__(parent)
        self.keys = tuple(keys)
        self._items = {}
        self.missing = []
        for key in self.keys:
            try:
                item = fix.db.get_item(key)
            except KeyError:
                self.missing.append(key)
                continue
            self._items[key] = item
            try:
                item.valueChanged[item.dtype].connect(self._emit)
            except (KeyError, TypeError):
                item.valueChanged[str].connect(self._emit)
            for sig in (item.oldChanged, item.badChanged, item.failChanged):
                sig.connect(self._emit)
        if self.missing:
            logger.warning("autopilot: FIX keys %s not defined by the "
                           "gateway (fix-gateway older than AFC1); no "
                           "autopilot annunciation", ",".join(self.missing))
        self.seen_live = False
        # APENG as of the last fresh reading: was the autopilot flying when
        # the source went quiet?
        self.last_engaged = False
        self._latch()

    def _latch(self):
        if self.fresh:
            self.seen_live = True
            self.last_engaged = bool(self.value("APENG"))

    def _emit(self, *_):
        self._latch()
        self.changed.emit()

    @property
    def available(self):
        return not self.missing

    @property
    def fresh(self):
        if not self.available:
            return False
        for item in self._items.values():
            if item.old or item.bad or item.fail:
                return False
        return True

    @property
    def stale_after_live(self):
        """The source was seen and has gone quiet: the "no autopilot data"
        state."""
        return self.available and self.seen_live and not self.fresh

    def value(self, key):
        item = self._items.get(key)
        return None if item is None else item.value

    # -- the reading, valid only while fresh --------------------------------
    @property
    def disconnected(self):
        """A disconnect alert holds: ``APDISC`` set on a fresh reading. The
        mode strip flashes on it and the disconnect tone sounds on it (CAS4),
        one rule for both."""
        return self.fresh and bool(self.value("APDISC"))

    @property
    def lateral(self):
        return mode_name(self.value("APLAT"))

    @property
    def lateral_armed(self):
        return mode_list(self.value("APLATARM"))

    @property
    def vertical(self):
        return mode_name(self.value("APVERT"))

    @property
    def vertical_armed(self):
        return mode_list(self.value("APVERTARM"))

    def vertical_active_is(self, mode):
        """Is ``mode`` the active vertical mode, on a fresh reading?"""
        return self.fresh and self.vertical == mode

    def vertical_reported(self, mode):
        """Is ``mode`` the active or an armed vertical mode, on a fresh
        reading?"""
        return self.fresh and (self.vertical == mode
                               or mode in self.vertical_armed)

    @property
    def capturing(self):
        """``APALTCAP`` on a fresh reading: capturing ``ALTSEL``."""
        return self.fresh and bool(self.value("APALTCAP"))


def send_request(command):
    """Write one request: ``APCMD`` = ``command``, then bump ``APCMDSEQ``
    (AFC1: the source acts on the counter, so the command must land first).
    Both go to the gateway with ``output_value()``; a local set alone never
    leaves pyEfis. Returns False, writing nothing, when either key is
    missing."""
    try:
        cmd = fix.db.get_item(CMD_KEY)
        seq = fix.db.get_item(SEQ_KEY)
    except KeyError:
        logger.warning("autopilot: %s/%s not defined; request %s not sent",
                       CMD_KEY, SEQ_KEY, command)
        return False
    cmd.bad = False
    cmd.fail = False
    cmd.value = command
    cmd.output_value()
    hi = getattr(seq, "max", None) or 2147483647
    nxt = int(seq.value or 0) + 1
    seq.bad = False
    seq.fail = False
    seq.value = 0 if nxt > hi else nxt
    seq.output_value()
    return True
