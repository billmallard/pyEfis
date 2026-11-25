"""Label the bytes an ALSA ``file`` tap captured from pyEfis (AER-6415).

    PYTHONPATH=src python3 tap_tones.py tap.raw <start_byte> <end_byte>

The tap holds exactly what the player wrote, S16LE mono 48 kHz, with no
timing (nothing is written while silent). Every 10 ms chunk is matched
against the shipped tone cycles at the default volume; the output is the
run-length sequence of tones, and the count of chunks that match none.
"""
import sys

from pyefis.instruments.cas import aural, tones as tn


def main(path, start, end):
    raw = open(path, "rb").read()[start:end]
    s = tn.Scheduler(volume=aural.DEFAULT_VOLUME)
    n = 2 * tn.CHUNK_FRAMES
    index = {}
    for ident, cyc in s.cycles.items():
        for off in range(0, len(cyc), n):
            index.setdefault(cyc[off:off + n], ident)
    # A slice cut at a size sampled mid-run need not start on a chunk: find
    # the byte offset at which the most chunks match a tone.
    def hits(a):
        return sum(raw[o:o + n] in index
                   for o in range(a, min(len(raw), a + 400 * n) - n + 1, n))
    align = max(range(0, n, 2), key=hits)
    raw = raw[align:]
    print("aligned at byte {}".format(align))
    seq = []
    unknown = 0
    for off in range(0, len(raw) - n + 1, n):
        piece = raw[off:off + n]
        label = index.get(piece)
        if label is None:
            unknown += 1
            label = "?"
        if not any(piece):
            label = "gap"
        if seq and seq[-1][0] == label:
            seq[-1][1] += 1
        else:
            seq.append([label, 1])
    runs = [(l, c) for l, c in seq if l != "gap"]
    merged = []
    for l, c in runs:
        if merged and merged[-1][0] == l:
            merged[-1][1] += c
        else:
            merged.append([l, c])
    for l, c in merged:
        print("{:<11} {:6.2f} s of sound and gap chunks".format(l, c * 0.01))
    print("chunks matching no tone: {} of {}".format(unknown, len(raw) // n))


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]), int(sys.argv[3]))
