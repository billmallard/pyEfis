"""Measure and compose the AER-5125 evidence.

For each side (base = #423's branch, branch = this one) and each case
(horizon_position 50 at pitch -20 and +20, 75 at +20; at 75 and -20 the
horizon is above the glass), in 240 columns clear of the centre symbols:

- sea edge: the first row of the renderer's red far-edge band
  (176, 35, 0) in the --terrain-only frame;
- zero-pitch line: the mean row of the white attitude line in the composed
  frame, within 60 rows of that edge. (--symbology-only runs with the SVS
  disabled, so it shows the no-SVS linear ladder on both sides; it is not
  used.)

Prints the gap and builds horizon_crops_4x.png (one row per case, base
left, branch right; 48 rows centred on the edge x cols 40-295 of the
composed frame, 4x nearest-neighbour) and composite_pairs.png (whole
composed frames, base left, branch right, 50%).

    python3 docs/aer-5125-evidence/compose.py <capture dir> docs/aer-5125-evidence
"""
import sys
import numpy as np
from PIL import Image

src, dst = sys.argv[1], sys.argv[2]
PDS = 50.0
CASES = [(50, -20), (50, 20), (75, 20)]
COLS = list(range(40, 160)) + list(range(1024 - 160, 1024 - 40))
rows = []
for hp, pitch in CASES:
    tiles = []
    for side in ("base", "branch"):
        stem = f"{src}/{side}_hp{hp}_p{pitch}"
        t = np.asarray(Image.open(f"{stem}_terrain-only.png").convert("RGB")).astype(int)
        c = np.asarray(Image.open(f"{stem}_composite.png").convert("RGB")).astype(int)
        h = t.shape[0]
        edges, lines = [], []
        for x in COLS:
            red = np.nonzero((t[:, x, 0] > 150) & (t[:, x, 1] < 60)
                             & (t[:, x, 2] < 30))[0]
            if not len(red):
                continue
            e = int(red[0])
            lo, hi = max(0, e - 60), min(h, e + 60)
            white = np.nonzero(np.all(c[lo:hi, x] > 230, axis=1))[0]
            if len(white):
                edges.append(e)
                lines.append(lo + float(np.mean(white)))
        edge, line = float(np.median(edges)), float(np.median(lines))
        below = edge - line
        print(f"hp {hp:2d} pitch {pitch:+3d} {side:6s}: sea edge y={edge:6.1f} "
              f"zero-pitch line y={line:6.1f}  edge below line {below:+5.1f} px "
              f"= {below * PDS / h:+.2f} deg  ({len(edges)} cols)")
        y0 = int(max(0, min(h - 48, round(edge) - 24)))
        crop = c[y0:y0 + 48, 40:296].astype(np.uint8)
        tiles.append(Image.fromarray(crop).resize((256 * 4, 48 * 4),
                                                  Image.Resampling.NEAREST))
    rows.append(tiles)
tw, th = rows[0][0].size
out = Image.new("RGB", (tw * 2 + 16, th * len(rows) + 16 * (len(rows) - 1)),
                "black")
for r, (a, b) in enumerate(rows):
    out.paste(a, (0, r * (th + 16)))
    out.paste(b, (tw + 16, r * (th + 16)))
out.save(f"{dst}/horizon_crops_4x.png")

pairs = []
for hp, pitch in [(50, -20), (75, 20)]:
    a, b = (Image.open(f"{src}/{side}_hp{hp}_p{pitch}_composite.png")
            .convert("RGB") for side in ("base", "branch"))
    w, h = a.size
    p = Image.new("RGB", (w * 2 + 16, h), "black")
    p.paste(a, (0, 0))
    p.paste(b, (w + 16, 0))
    pairs.append(p.resize(((w * 2 + 16) // 2, h // 2), Image.Resampling.LANCZOS))
out = Image.new("RGB", (pairs[0].width, sum(p.height for p in pairs) + 16),
                "black")
out.paste(pairs[0], (0, 0))
out.paste(pairs[1], (0, pairs[0].height + 16))
out.save(f"{dst}/composite_pairs.png")
