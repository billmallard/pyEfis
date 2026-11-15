#  Copyright (c) 2026 MakerPlane
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.

# FIX link liveness watchdog (CERT1, AER-5031).
#
# pyavtools' FIX client only marks the database failed when the gateway
# closes the socket cleanly.  A gateway that hangs with the socket open
# (deadlock, SIGSTOP) or a link that dies with an error (RST) leaves every
# value on the glass as it was, still flagged good.  The client never ages
# values against TOL either, so nothing downstream notices.
#
# This watchdog closes that gap from the pyEfis side, through the client
# library's public surface only:
#
#   * Every tick it asks the gateway for one input key (``@r<KEY>``).  A
#     live gateway answers; the answer, like any value frame for that key,
#     rewrites the item's ``timestamp``.
#   * A tick that sees the timestamp unchanged for ``timeout`` seconds
#     calls ``db.mark_all_fail()``: the same state the client itself
#     produces on an orderly disconnect.
#   * The first changed timestamp after that is the next good frame: it
#     re-reads every item, so each one gets its value and flags back from
#     the gateway rather than staying failed until its value next moves.
#
# Liveness is a timestamp CHANGE measured on time.monotonic(), never the
# timestamp's age: the item timestamp is wall-clock, and a GPS time set
# that steps the clock back would otherwise hide a hung gateway for as
# long as the step.

import logging
import time

from PyQt6.QtCore import QObject, QTimer

log = logging.getLogger(__name__)

# Input keys the gateway is expected to carry, tried in order.  The ping
# key must be one pyEfis never writes itself: a local write also moves the
# timestamp and would read as a frame from the gateway.
DEFAULT_PING_KEYS = ("PITCH", "ROLL", "ALT", "IAS")

DEFAULT_TIMEOUT_S = 2.0
DEFAULT_INTERVAL_S = 0.5


class FixLinkWatchdog(QObject):
    def __init__(self, db, ping_key, timeout=DEFAULT_TIMEOUT_S,
                 interval=DEFAULT_INTERVAL_S, clock=time.monotonic, parent=None):
        super().__init__(parent)
        self.db = db
        self.ping_key = ping_key
        self.item = db.get_item(ping_key, wait=False)
        self.timeout = float(timeout)
        self.interval = float(interval)
        self.clock = clock
        self.tripped = False
        self._last_stamp = self.item.timestamp
        self._last_frame = clock()
        self._timer = QTimer(self)
        self._timer.setInterval(int(self.interval * 1000))
        self._timer.timeout.connect(self.poll)

    def start(self):
        self._last_frame = self.clock()
        self._timer.start()

    def stop(self):
        self._timer.stop()

    def poll(self):
        now = self.clock()
        stamp = self.item.timestamp
        if stamp != self._last_stamp:
            self._last_stamp = stamp
            self._last_frame = now
            if self.tripped:
                self._recover()
        elif not self.tripped and now - self._last_frame >= self.timeout:
            self._trip(now - self._last_frame)
        self.db.queue_out("@r{0}\n".format(self.ping_key).encode())

    def _trip(self, silent_for):
        self.tripped = True
        log.error(
            "No frame from FIX gateway for %.1f s: marking all data failed",
            silent_for)
        self.db.mark_all_fail()

    def _recover(self):
        self.tripped = False
        keys = item_keys(self.db)
        log.warning(
            "FIX gateway answering again: re-reading %d items", len(keys))
        for key in keys:
            self.db.queue_out("@r{0}\n".format(key).encode())


def item_keys(db):
    # pyavtools' Database keeps its items in a private dict and exposes no
    # key list.  Reading it is the only way to re-request every item
    # without the client's full re-definition path (sending @l), which
    # re-registers interval output timers on every recovery.  The pinned
    # pyavtools version is covered by test_item_keys_reads_the_real_database.
    items = getattr(db, "_Database__items", None)
    if items is None:
        log.error("FIX database has no item list; re-reading ping key only")
        return []
    return list(items)


def choose_ping_key(db, candidates):
    for key in candidates:
        try:
            db.get_item(key, wait=False)
        except KeyError:
            continue
        return key
    return None


def start(db, config):
    """Start the watchdog from the ``main`` config section.

    ``FixLinkTimeout`` (seconds, default 2.0) is how long the gateway may
    stay silent before every item is marked failed; 0 disables the
    watchdog.  ``FixLinkPingKey`` overrides the key used to ping it.
    Returns the running watchdog, or None.
    """
    timeout = float(config.get("FixLinkTimeout", DEFAULT_TIMEOUT_S))
    if timeout <= 0:
        log.warning("FIX link watchdog disabled (FixLinkTimeout <= 0)")
        return None
    configured = config.get("FixLinkPingKey")
    candidates = (configured,) if configured else DEFAULT_PING_KEYS
    key = choose_ping_key(db, candidates)
    if key is None:
        log.error(
            "FIX link watchdog NOT running: none of %s is in the FIX "
            "database, so a hung gateway will not be flagged",
            ", ".join(candidates))
        return None
    interval = min(DEFAULT_INTERVAL_S, timeout / 2)
    watchdog = FixLinkWatchdog(db, key, timeout=timeout, interval=interval)
    watchdog.start()
    log.info("FIX link watchdog: ping %s, fail after %.1f s", key, timeout)
    return watchdog
