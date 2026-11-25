#  SPDX-License-Identifier: GPL-2.0-or-later
"""The CAS tone player (CAS4, CAP-403): one module, not a widget.

It plays on whatever audio device the host has, keyed off the bus, so every
display with a speaker or an intercom feed sounds the same alert, and an
acknowledge on any display silences all of them (BACKLOG CAS4, Bill
2026-11-23). It decides no alert. Its inputs:

- **The autopilot disconnect.** ``APDISC`` on a fresh autopilot reading
  (:attr:`APState.disconnected`, the rule the mode strip flashes on). The
  source holds the latch until a display acknowledges it, so every display
  stops together.
- **The CAS level.** The gateway's ``CASTOP``, plus this display's
  unacknowledged local alerts (``GATEWAY LINK LOST``, ``CAS FAIL``):
  :meth:`CASModel.aural_level`. A local alert sounds from here because with
  the gateway gone there is no bus to key off. The CAS input is used only
  where CAS is: a panel carrying a CAS window or marker, or a gateway whose
  ``CASSEQ`` has been seen good. A panel and gateway without CAS never raise
  ``CAS FAIL``, so they never sound its tone.

Which tone sounds, and when one gives way to another, is
:class:`tones.Scheduler` (R5, R9). The audio is written by a daemon thread,
so a full device queue never blocks the GUI; the GUI thread only hands it
the set of tones whose condition holds, every :data:`POLL_MS`.

With no audio device the player logs it once, keeps trying every
:data:`RETRY_S`, and the display runs as before: the visual cue is the
baseline (FHA CAS-1, CAS-2).
"""

import logging
import threading

from PyQt6.QtCore import QObject, QTimer

import pyavtools.fix as fix

from pyefis.instruments.cas import alsa
from pyefis.instruments.cas import model as cm
from pyefis.instruments.cas import tones

log = logging.getLogger(__name__)

#: How often the inputs are read on the GUI thread.
POLL_MS = 100
#: With no device, how often to try again (a USB adapter plugged in late).
RETRY_S = 5.0

DEFAULT_DEVICE = "default"
DEFAULT_VOLUME = 0.8


def active_tones(cas_level, disconnected):
    """The tone ids whose condition holds. ``cas_level`` is 0-3; an advisory
    (1) has no tone (R4)."""
    out = set()
    if disconnected:
        out.add(tones.DISCONNECT)
    if cas_level >= cm.WARNING:
        out.add(tones.WARNING)
    elif cas_level == cm.CAUTION:
        out.add(tones.CAUTION)
    return out


class AuralPlayer:
    """Feeds the scheduler's chunks to a sink on its own thread.

    ``sink`` has ``open() -> bool``, ``is_open``, ``write(bytes) -> bool``,
    ``flush()`` and ``close()`` (:class:`alsa.AlsaSink`). Tests call
    :meth:`step` directly instead of :meth:`start`.
    """

    def __init__(self, sink, scheduler=None, volume=DEFAULT_VOLUME):
        self.sink = sink
        self.scheduler = scheduler or tones.Scheduler(volume=volume)
        self._active = frozenset()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread = None
        self._playing = None

    @property
    def active(self):
        return self._active

    def set_active(self, ids):
        ids = frozenset(ids)
        if ids != self._active:
            self._active = ids
            self._wake.set()

    def step(self):
        """One chunk. Returns the tone id written, or None when idle."""
        ident, data, flush = self.scheduler.next_chunk(self._active)
        if flush:
            self.sink.flush()
        if ident != self._playing:
            log.info("aural: %s", "{} tone".format(ident) if ident
                     else "silent")
            self._playing = ident
        if ident is None:
            return None
        self.sink.write(data)
        return ident

    def run(self):
        while not self._stop.is_set():
            if not self.sink.is_open and not self.sink.open():
                self._stop.wait(RETRY_S)
                continue
            self._wake.clear()
            try:
                ident = self.step()
            except Exception:
                # The tone must not take the display down; log and retry.
                log.exception("aural: player step failed")
                self.sink.close()
                self._stop.wait(RETRY_S)
                continue
            if ident is None:
                self._wake.wait(1.0)
        self.sink.close()

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self.run, name="cas-aural",
                                            daemon=True)
            self._thread.start()

    def stop(self, timeout=1.0):
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None


class _CASLive:
    """Is CAS in use on this display? Yes when the panel carries a window or
    a marker, or once ``CASSEQ`` has been read good: then it stays yes, so a
    gateway that later loses its list sounds ``CAS FAIL``."""

    def __init__(self, on_panel, lookup):
        self.on = bool(on_panel)
        self.lookup = lookup

    def __call__(self):
        if not self.on:
            try:
                item = self.lookup("CASSEQ")
            except KeyError:
                return False
            if not (item.old or item.bad or item.fail):
                self.on = True
                log.info("aural: CAS is live; its tones are on")
        return self.on


class TonePlayer(QObject):
    """Reads the inputs on the GUI thread and hands the tone set to an
    :class:`AuralPlayer`. Built once per display by gui.py."""

    def __init__(self, parent=None, cas_on_panel=False, device=DEFAULT_DEVICE,
                 volume=DEFAULT_VOLUME, sink=None, ap=None, cas_model=None,
                 lookup=None, start=True):
        super().__init__(parent)
        self._lookup = lookup or (lambda k: fix.db.get_item(k, wait=False))
        if ap is None:
            from pyefis.instruments.autopilot import state as apstate
            ap = apstate.APState(parent=self)
        self.ap = ap
        self._cas_model = cas_model
        self.cas_live = _CASLive(cas_on_panel, self._lookup)
        self.player = AuralPlayer(sink or alsa.AlsaSink(device, tones.RATE),
                                  volume=volume)
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self._tick)
        if start:
            self.player.start()
            self._timer.start()

    def cas_level(self):
        if not self.cas_live():
            return 0
        if self._cas_model is None:
            from pyefis.instruments import cas
            self._cas_model = cas.shared_model()
        return self._cas_model.poll().aural_level()

    def poll(self):
        """Read the inputs once; returns the tone set handed on."""
        ids = active_tones(self.cas_level(), self.ap.disconnected)
        self.player.set_active(ids)
        return ids

    def _tick(self):
        try:
            self.poll()
        except Exception:
            log.exception("aural: input poll failed")

    def stop(self):
        self._timer.stop()
        self.player.stop()
