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
#
# When the watchdog is not running the display still runs: a dead display
# is worse than an unmonitored one.  But a hung gateway would then go
# unflagged, so the loss is shown on the glass (AER-5983): ``start`` records
# why the watchdog is off in ``off_reason``, and ``show_off_cue`` draws a
# persistent cue over every screen until pyEfis restarts with it running.

import logging
import time

from PyQt6.QtCore import QEvent, QObject, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QWidget

log = logging.getLogger(__name__)

# Input keys the gateway is expected to carry, tried in order.  The ping
# key must be one pyEfis never writes itself: a local write also moves the
# timestamp and would read as a frame from the gateway.
DEFAULT_PING_KEYS = ("PITCH", "ROLL", "ALT", "IAS")

DEFAULT_TIMEOUT_S = 2.0
DEFAULT_INTERVAL_S = 0.5

# Why the watchdog is not running, set by start(); None while it runs.
OFF_START_FAILED = "start-failed"   # start raised (bad FixLinkTimeout, ...)
OFF_DISABLED = "disabled"           # FixLinkTimeout <= 0
OFF_NO_PING_KEY = "no-ping-key"     # no ping candidate in the FIX database
off_reason = None
# The watchdog start() made, or None; read by link_lost().
running = None

# The cue's wording and look are a safety-cue decision for Bill (AER-5983);
# this is the proposal on that card.
OFF_CUE_TEXT = "LINK MON OFF"
OFF_CUE_COLOR = QColor(255, 176, 0)


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
    Returns the running watchdog, or None with ``off_reason`` saying why.
    Never raises: a watchdog that cannot start must not stop the display.
    """
    global off_reason, running
    try:
        watchdog, off_reason = _start(db, config)
    except Exception:
        log.critical("FIX link watchdog failed to start", exc_info=True)
        watchdog, off_reason = None, OFF_START_FAILED
    running = watchdog
    return watchdog


def link_lost():
    """True while the running watchdog has tripped (CAS3: the display's
    GATEWAY LINK LOST alert). False when it is not running: that case has its
    own cue, LINK MON OFF."""
    return running is not None and bool(running.tripped)


def _start(db, config):
    timeout = float(config.get("FixLinkTimeout", DEFAULT_TIMEOUT_S))
    if timeout <= 0:
        log.warning("FIX link watchdog disabled (FixLinkTimeout <= 0)")
        return None, OFF_DISABLED
    configured = config.get("FixLinkPingKey")
    candidates = (configured,) if configured else DEFAULT_PING_KEYS
    key = choose_ping_key(db, candidates)
    if key is None:
        log.error(
            "FIX link watchdog NOT running: none of %s is in the FIX "
            "database, so a hung gateway will not be flagged",
            ", ".join(candidates))
        return None, OFF_NO_PING_KEY
    interval = min(DEFAULT_INTERVAL_S, timeout / 2)
    watchdog = FixLinkWatchdog(db, key, timeout=timeout, interval=interval)
    watchdog.start()
    log.info("FIX link watchdog: ping %s, fail after %.1f s", key, timeout)
    return watchdog, None


class LinkMonitorOffCue(QWidget):
    """The persistent cue that the link watchdog is not running.  Transparent
    to touch, stacked over every screen, refitted when the window resizes.
    It sits just below the DEMO strip's band so the two never overlap."""

    def __init__(self, parent, reason, font_family="DejaVu Sans Condensed"):
        super().__init__(parent)
        self.reason = reason
        self.font_family = font_family
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        parent.installEventFilter(self)
        self.fit_to_parent()

    def eventFilter(self, obj, event):
        if obj is self.parentWidget() and event.type() == QEvent.Type.Resize:
            self.fit_to_parent()
        return False

    def fit_to_parent(self):
        p = self.parentWidget()
        if p is None:
            return
        # size(), not width()/height(): gui.initialize assigns plain ints over
        # mainWindow.width/height in windowed mode.
        w, h = p.size().width(), p.size().height()
        top = max(18, int(h * 0.035)) + 4   # kiosk.DemoMarking's height
        bh = max(22, int(h * 0.05))
        bw = max(bh * 7, int(w * 0.2))
        self.setGeometry(int((w - bw) / 2), top, bw, bh)

    def paintEvent(self, event):
        qp = QPainter(self)
        qp.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        qp.setPen(QPen(OFF_CUE_COLOR, 2))
        qp.setBrush(QColor(0, 0, 0, 220))
        qp.drawRoundedRect(r, 3, 3)
        font = QFont(self.font_family)
        font.setPixelSize(max(12, int(self.height() * 0.6)))
        font.setBold(True)
        qp.setFont(font)
        qp.drawText(r, Qt.AlignmentFlag.AlignCenter, OFF_CUE_TEXT)


def show_off_cue(parent, reason):
    """Put the cue over ``parent`` when ``reason`` says the watchdog is off.
    Returns the cue, or None when the watchdog runs or the cue could not be
    built -- a failure here is logged and never propagates into boot."""
    if reason is None:
        return None
    try:
        cue = LinkMonitorOffCue(parent, reason)
        cue.show()
        cue.raise_()
        log.warning("FIX link watchdog off (%s): showing %s",
                    reason, OFF_CUE_TEXT)
        return cue
    except Exception:
        log.error("could not show the %s cue", OFF_CUE_TEXT, exc_info=True)
        return None
