"""Draw the spectrogram of r9_sequence.wav with the script's phases marked
(AER-6415).  python3 spectrogram.py <dir>"""
import sys, wave
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

d = sys.argv[1] if len(sys.argv) > 1 else "."
with wave.open(d + "/r9_sequence.wav") as w:
    rate = w.getframerate()
    x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2") / 32768.0
# A floor under digital silence, so it plots black rather than blank.
x = x + np.random.default_rng(0).normal(0, 1e-6, x.size)
fig, ax = plt.subplots(figsize=(12, 4), dpi=110)
ax.specgram(x, NFFT=1024, Fs=rate, noverlap=768, cmap="magma", vmin=-110)
ax.set_ylim(0, 4000)
ax.set_xlabel("seconds")
ax.set_ylabel("Hz")
phases = [(0.0, "caution"), (0.5, "+ warning: cuts the chime"),
          (2.9, "+ AP disconnect: turns with the warning"),
          (7.5, "disconnect acked"), (8.7, "warning acked: caution"),
          (14.2, "caution acked")]
for k, (t, label) in enumerate(phases):
    ax.axvline(t, color="cyan", lw=1, ls="--")
    ax.text(t + 0.05, 3850 - 350 * (k % 2), label, color="cyan", fontsize=8,
            va="top")
ax.set_title("CAS4 tones, r9_sequence.wav: the bytes the player writes")
fig.tight_layout()
fig.savefig(d + "/r9_sequence_spectrogram.png")
