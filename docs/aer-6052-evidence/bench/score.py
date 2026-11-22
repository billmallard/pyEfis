"""Score the AFC5 sim-bench frames: are the FD bars drawn exactly when the
inputs say they should be, and do they move with the command?

    python3 score.py <run dir with frames/ and frames.jsonl>

A frame "should draw" when FDENG is True and FDENG, FDPITCH, FDROLL, PITCH and
ROLL are all fresh (flag string starting 0000). "Drawn" is more than 300 pure
magenta pixels (R>230, G<40, B>230) in a panel: the left panel (x < 1056) is
the SVS virtual_vfr with single_cue, the right panel the plain AI with
cross_pointer. For the cross_pointer frames it also fits the roll bar's x
against FDROLL - ROLL and the pitch bar's y against FDPITCH - PITCH.
"""
import collections
import json
import os
import sys

import numpy as np
from PIL import Image

run = sys.argv[1]
KEYS = ("FDENG", "FDPITCH", "FDROLL", "PITCH", "ROLL")
counts = collections.Counter()
wrong = []
xs, ys, re, pe = [], [], [], []
for line in open(os.path.join(run, "frames.jsonl")):
    r = json.loads(line)
    b = r["bus"]
    should = all(b.get(k) and b[k][1][:4] == "0000" for k in KEYS) \
        and b["FDENG"][0] == "True"
    a = np.asarray(Image.open(os.path.join(run, "frames", r["frame"])).convert("RGB")).astype(int)
    m = (a[:, :, 0] > 230) & (a[:, :, 1] < 40) & (a[:, :, 2] > 230)
    left, right = m[:, :1056], m[:, 1056:]
    drawn = (int(left.sum()) > 300, int(right.sum()) > 300)
    counts[(should, drawn)] += 1
    if drawn != (should, should):
        wrong.append((r["frame"], should, drawn))
    if should and drawn[1]:
        col, row = right.sum(0), right.sum(1)
        xs.append(np.average(np.nonzero(col >= 0.6 * col.max())[0]))
        ys.append(np.average(np.nonzero(row >= 0.6 * row.max())[0]))
        re.append(float(b["FDROLL"][0]) - float(b["ROLL"][0]))
        pe.append(float(b["FDPITCH"][0]) - float(b["PITCH"][0]))

print("frames by (should draw, (drawn SVS, drawn AI)):", dict(counts))
print("frames where drawn != should:", len(wrong), wrong[:10])
xs, ys, re, pe = map(np.array, (xs, ys, re, pe))
print("cross_pointer fit over %d frames:" % len(xs))
print("  roll bar x = %.2f px/deg * (FDROLL-ROLL) + %.1f, r = %.3f, error %.1f..%.1f deg"
      % (*np.polyfit(re, xs, 1), np.corrcoef(xs, re)[0, 1], re.min(), re.max()))
print("  pitch bar y = %.2f px/deg * (FDPITCH-PITCH) + %.1f, r = %.3f, error %.1f..%.1f deg"
      % (*np.polyfit(pe, ys, 1), np.corrcoef(ys, pe)[0, 1], pe.min(), pe.max()))
