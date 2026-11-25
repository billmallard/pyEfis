"""Write the CAS4 tone recordings from the shipped scheduler (AER-6415).

    PYTHONPATH=src python3 docs/aer-6415-evidence/make_recordings.py docs/aer-6415-evidence

Every file is what the player writes to the audio device, byte for byte:
the scheduler's chunks, at the default volume, 48 kHz 16-bit mono.
"""
import os
import sys
import wave

from pyefis.instruments.cas import aural, tones as tn

CHUNK_S = tn.CHUNK_FRAMES / float(tn.RATE)

#: (file, [(active tone set, seconds)], what it shows)
SCRIPTS = [
    ("disconnect.wav", [({tn.DISCONNECT}, 4 * 1.1)],
     "autopilot disconnect, four cycles"),
    ("warning.wav", [({tn.WARNING}, 4 * 1.2)], "warning, four cycles"),
    ("caution.wav", [({tn.CAUTION}, 2 * 5.0)], "caution, two cycles"),
    ("r9_sequence.wav", [
        ({tn.CAUTION}, 0.5),                    # a caution chimes
        ({tn.CAUTION, tn.WARNING}, 2.4),        # a warning cuts it off
        ({tn.CAUTION, tn.WARNING, tn.DISCONNECT}, 4.6),  # AP disconnects: turns
        ({tn.CAUTION, tn.WARNING}, 1.2),        # disconnect acknowledged
        ({tn.CAUTION}, 5.5),                    # warning acknowledged
        (set(), 1.0),                           # caution acknowledged: silence
    ], "caution; warning interrupts; disconnect and warning take turns; "
       "each acknowledged in turn"),
]


class Tape:
    def __init__(self):
        self.data = bytearray()
        self.is_open = True

    def open(self):
        return True

    def write(self, b):
        self.data += b
        return True

    def flush(self):
        pass

    def close(self):
        pass


def record(script):
    tape = Tape()
    p = aural.AuralPlayer(tape, volume=aural.DEFAULT_VOLUME)
    for active, secs in script:
        p.set_active(active)
        n = int(round(secs / CHUNK_S))
        for _ in range(n):
            if p.step() is None:
                tape.write(b"\0" * (2 * tn.CHUNK_FRAMES))
    return bytes(tape.data)


def main(out):
    os.makedirs(out, exist_ok=True)
    for name, script, what in SCRIPTS:
        pcm = record(script)
        with wave.open(os.path.join(out, name), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(tn.RATE)
            w.writeframes(pcm)
        print("{}: {:.1f} s, {}".format(name, len(pcm) / 2.0 / tn.RATE, what))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
