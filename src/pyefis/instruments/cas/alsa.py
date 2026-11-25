#  SPDX-License-Identifier: GPL-2.0-or-later
"""Play S16LE mono PCM on an ALSA device, through ``libasound`` by ctypes
(CAS4).

No Python package and no command-line player is needed: ``libasound.so.2``
is on every Linux that can play sound, while ``aplay`` is not (the Beelink
bench has the library and no ``aplay``). ALSA's ``default`` device reaches
PipeWire or PulseAudio where they run, and the card directly where they do
not.

Like the data loaders, it never raises: :meth:`AlsaSink.open` returns False
and logs once when the library or the device is missing, and a write error
closes the device so the player can try again later (a USB adapter pulled
and put back).
"""

import ctypes
import ctypes.util
import logging

log = logging.getLogger(__name__)

SND_PCM_STREAM_PLAYBACK = 0
SND_PCM_FORMAT_S16_LE = 2
SND_PCM_ACCESS_RW_INTERLEAVED = 3
#: How much audio the device queues. A stop or an interrupt drops it, so it
#: costs no latency there; it is the slack the player thread has.
LATENCY_US = 100000

_lib = None
_lib_error = None


def load_library():
    """The libasound handle, or None. Loaded once."""
    global _lib, _lib_error
    if _lib is not None or _lib_error is not None:
        return _lib
    name = ctypes.util.find_library("asound") or "libasound.so.2"
    try:
        lib = ctypes.CDLL(name)
    except OSError as e:
        _lib_error = str(e)
        return None
    lib.snd_strerror.restype = ctypes.c_char_p
    lib.snd_strerror.argtypes = [ctypes.c_int]
    lib.snd_pcm_open.argtypes = [ctypes.POINTER(ctypes.c_void_p),
                                 ctypes.c_char_p, ctypes.c_int, ctypes.c_int]
    lib.snd_pcm_set_params.argtypes = [
        ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_uint,
        ctypes.c_uint, ctypes.c_int, ctypes.c_uint]
    lib.snd_pcm_writei.restype = ctypes.c_long
    lib.snd_pcm_writei.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                   ctypes.c_ulong]
    lib.snd_pcm_recover.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                    ctypes.c_int]
    for fn in ("snd_pcm_drop", "snd_pcm_prepare", "snd_pcm_drain",
               "snd_pcm_close"):
        getattr(lib, fn).argtypes = [ctypes.c_void_p]
    _lib = lib
    return lib


def _err(lib, code):
    try:
        return lib.snd_strerror(int(code)).decode("utf-8", "replace")
    except Exception:
        return str(code)


class AlsaSink:
    """One ALSA playback stream. Used from one thread, the player's."""

    def __init__(self, device="default", rate=48000):
        self.device = str(device)
        self.rate = int(rate)
        self._pcm = None
        self._failed = None             # the last open failure, logged once

    @property
    def is_open(self):
        return self._pcm is not None

    def open(self):
        if self._pcm is not None:
            return True
        lib = load_library()
        if lib is None:
            self._fail("libasound not found ({}): no audio output".format(
                _lib_error))
            return False
        pcm = ctypes.c_void_p()
        rc = lib.snd_pcm_open(ctypes.byref(pcm), self.device.encode(),
                              SND_PCM_STREAM_PLAYBACK, 0)
        if rc < 0:
            self._fail("cannot open ALSA device {!r}: {}".format(
                self.device, _err(lib, rc)))
            return False
        rc = lib.snd_pcm_set_params(pcm, SND_PCM_FORMAT_S16_LE,
                                    SND_PCM_ACCESS_RW_INTERLEAVED, 1,
                                    self.rate, 1, LATENCY_US)
        if rc < 0:
            lib.snd_pcm_close(pcm)
            self._fail("ALSA device {!r} refused S16 mono {} Hz: {}".format(
                self.device, self.rate, _err(lib, rc)))
            return False
        self._pcm = pcm
        if self._failed is not None:
            log.warning("aural: ALSA device %r open again", self.device)
        else:
            log.info("aural: playing on ALSA device %r", self.device)
        self._failed = None
        return True

    def _fail(self, why):
        if why != self._failed:
            log.warning("aural: %s", why)
        self._failed = why

    def write(self, data):
        """Queue *data* (S16LE mono); blocks while the device queue is full.
        False when the device failed, and it is then closed."""
        if self._pcm is None:
            return False
        lib = _lib
        frames = len(data) // 2
        buf = ctypes.create_string_buffer(bytes(data), len(data))
        done = 0
        while done < frames:
            n = lib.snd_pcm_writei(self._pcm, ctypes.byref(buf, 2 * done),
                                   frames - done)
            if n < 0:
                rc = lib.snd_pcm_recover(self._pcm, int(n), 1)
                if rc < 0:
                    self._fail("ALSA write on {!r} failed: {}".format(
                        self.device, _err(lib, n)))
                    self.close()
                    return False
                continue
            done += n
        return True

    def flush(self):
        """Drop what is queued (a stop or an interrupt), ready to play."""
        if self._pcm is not None:
            _lib.snd_pcm_drop(self._pcm)
            _lib.snd_pcm_prepare(self._pcm)

    def drain(self):
        """Let what is queued finish playing."""
        if self._pcm is not None:
            _lib.snd_pcm_drain(self._pcm)
            _lib.snd_pcm_prepare(self._pcm)

    def close(self):
        if self._pcm is not None:
            pcm, self._pcm = self._pcm, None
            _lib.snd_pcm_close(pcm)
