#  SPDX-License-Identifier: GPL-2.0-or-later
"""The CAS tones and the rule for which one sounds (CAS4, CAP-403), apart from
Qt and from any audio device.

makerplane brief ``briefs/crew_alerting.md`` section 7 and requirements R4,
R5 and R9:

- **R4.** Warnings and cautions reach a second sense: each level has a tone.
  Advisories have none. The autopilot disconnect (``APDISC``) has its own
  tone at warning level, distinct from the CAS warning (Bill, AER-6346).
- **R5.** Acknowledge silences: a tone whose condition is gone (acknowledged
  or cleared) stops at once, mid-cycle.
- **R9.** One tone at a time. A tone that is playing finishes its sound
  unless a higher level needs to interrupt it. A higher level interrupts at
  once; an equal or lower one waits.

A tone repeats while its condition holds. Each cycle is the sound, then a
silent gap. Two tones of one level (a CAS warning and a disconnect) take
turns: the second starts in the first one's gap, :data:`MIN_GAP_S` after its
sound ends, so the pilot hears both. A lower level waits until every higher
one is gone.

What each tone sounds like is the project owner's call (BACKLOG CAS4,
"Bill judges looks and sounds"). :data:`TONES` holds the proposal; the
scheduler does not depend on it.
"""

import math
from array import array

#: Output format: signed 16-bit mono. 48 kHz is native to HDMI and most USB
#: adapters, so the device rarely has to resample.
RATE = 48000
#: The scheduler decides once per chunk: 10 ms.
CHUNK_FRAMES = RATE // 100
#: Between two tones of one level, at least this much silence.
MIN_GAP_S = 0.3
#: Attack and release ramp on every note, against clicks.
RAMP_S = 0.005

DISCONNECT = "disconnect"
WARNING = "warning"
CAUTION = "caution"


class Tone:
    """One repeating tone: ``notes`` is a list of ``(start_hz, end_hz,
    seconds, decay)``; ``start_hz`` 0 is a rest. ``decay`` 0 holds the level,
    otherwise the note dies away exponentially with that time constant (a
    chime). ``period_s`` is the full cycle, sound and gap."""

    def __init__(self, ident, level, notes, period_s, harmonics=((1, 1.0),)):
        self.id = ident
        self.level = level
        self.notes = tuple(notes)
        self.period_s = float(period_s)
        self.harmonics = tuple(harmonics)
        self.sound_s = sum(n[2] for n in self.notes)
        if self.sound_s > self.period_s:
            raise ValueError("{}: sound {:.2f} s is longer than its period "
                             "{:.2f} s".format(ident, self.sound_s,
                                               self.period_s))

    @property
    def sound_frames(self):
        return int(round(self.sound_s * RATE))

    @property
    def period_frames(self):
        return int(round(self.period_s * RATE))

    def render(self, volume=1.0):
        """One cycle as S16LE bytes: the sound, then silence to the period.
        The loudest sample of the sound sits at *volume* of full scale."""
        wave = []
        for f0, f1, dur, decay in self.notes:
            n = int(round(dur * RATE))
            if f0 <= 0:
                wave.extend([0.0] * n)
                continue
            ramp = max(1, int(RAMP_S * RATE))
            phase = 0.0
            for i in range(n):
                f = f0 + (f1 - f0) * i / n
                phase += 2.0 * math.pi * f / RATE
                v = sum(a * math.sin(k * phase) for k, a in self.harmonics)
                env = min(1.0, i / ramp, (n - 1 - i) / ramp)
                if decay:
                    env *= math.exp(-i / (decay * RATE))
                wave.append(env * v)
        top = max([abs(v) for v in wave] or [0.0]) or 1.0
        scale = 32767 * max(0.0, min(1.0, float(volume))) / top
        out = array("h", (int(v * scale) for v in wave))
        out.extend([0] * (self.period_frames - len(out)))
        return out.tobytes()


#: The proposal (BACKLOG CAS4: the sounds are Bill's call, on the PR with a
#: recording). Kept inside 500-2000 Hz, where a headset and an intercom pass
#: the most, with an odd harmonic so it cuts through engine noise.
TONES = (
    # Autopilot disconnect: three falling sweeps, then a short gap. Nothing
    # else sweeps, so it cannot be taken for a CAS warning.
    Tone(DISCONNECT, 3, [(1600, 800, 0.16, 0), (0, 0, 0.04, 0),
                         (1600, 800, 0.16, 0), (0, 0, 0.04, 0),
                         (1600, 800, 0.16, 0)],
         period_s=1.1, harmonics=((1, 1.0), (3, 0.25))),
    # Warning: three quick level beeps, repeating about once a second.
    Tone(WARNING, 3, [(1000, 1000, 0.12, 0), (0, 0, 0.08, 0),
                      (1000, 1000, 0.12, 0), (0, 0, 0.08, 0),
                      (1000, 1000, 0.12, 0)],
         period_s=1.2, harmonics=((1, 1.0), (3, 0.3))),
    # Caution: a falling two-note chime, repeated every 5 s until
    # acknowledged.
    Tone(CAUTION, 2, [(1100, 1100, 0.35, 0.15), (880, 880, 0.5, 0.2)],
         period_s=5.0, harmonics=((1, 1.0), (2, 0.3))),
)


class Scheduler:
    """Which tone sounds, chunk by chunk (R5, R9). Time is counted in frames
    written, so it is the audio clock, not the wall clock.

    :meth:`next_chunk` takes the set of tone ids whose condition holds now
    and returns ``(tone_id, frames, flush)``: the tone the chunk belongs to
    (None for nothing to play), its bytes, and whether audio already queued
    on the device must be dropped first (a stop or an interrupt). The order
    in :data:`TONES` breaks ties within a level: the first listed starts.
    """

    def __init__(self, tones=TONES, volume=1.0, chunk_frames=CHUNK_FRAMES):
        self.tones = {t.id: t for t in tones}
        self.order = [t.id for t in tones]
        self.chunk = int(chunk_frames)
        self.cycles = {t.id: t.render(volume) for t in tones}
        self.current = None
        self.pos = 0                    # frames into the current cycle
        self._last = {}                 # level -> id last started there

    def level(self, ident):
        return self.tones[ident].level

    def _pick(self, active):
        """The tone to start: the highest level present, and within it the
        next after the one last started at that level (taking turns)."""
        if not active:
            return None
        top = max(self.level(i) for i in active)
        cands = [i for i in self.order if i in active and self.level(i) == top]
        last = self._last.get(top)
        if last in self.order:
            k = self.order.index(last)
            later = [i for i in cands if self.order.index(i) > k]
            if later:
                return later[0]
        return cands[0]

    def _start(self, ident):
        self.current = ident
        self.pos = 0
        if ident is not None:
            self._last[self.level(ident)] = ident

    def next_chunk(self, active):
        active = set(i for i in active if i in self.tones)
        flush = False
        cur = self.current
        if cur is not None and cur not in active:
            # R5: acknowledged or cleared, so it stops now, mid-sound.
            flush = True
            self._start(None)
        elif cur is not None and active and \
                max(self.level(i) for i in active) > self.level(cur):
            # R9: a higher level interrupts.
            flush = True
            self._start(None)
        cur = self.current
        if cur is None:
            self._start(self._pick(active))
        else:
            tone = self.tones[cur]
            nxt = self._pick(active)
            if self.pos >= tone.period_frames:
                self._start(nxt)
            elif nxt != cur and self.pos >= tone.sound_frames + int(
                    MIN_GAP_S * RATE):
                # Another tone of this level waits: it starts in the gap.
                self._start(nxt)
        if self.current is None:
            return None, b"", flush
        cycle = self.cycles[self.current]
        n = self.tones[self.current].period_frames
        take = min(self.chunk, n - self.pos)
        data = cycle[2 * self.pos:2 * (self.pos + take)]
        self.pos += take
        return self.current, data, flush
