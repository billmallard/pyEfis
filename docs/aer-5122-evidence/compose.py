"""Compose the AER-5122 evidence crop and print the measurement.

For each side: take the --terrain-only frame, find the first non-sky row
(the sea edge) and the --symbology-only frame's white zero-pitch line, in
440 columns clear of the centre symbols. Crop rows 0-79 x cols 128-383,
draw the zero-pitch line in magenta, scale 4x nearest-neighbour, and put
dev (left) beside the branch (right) in horizon_crop_4x.png.

    python3 docs/aer-5122-evidence/compose.py docs/aer-5122-evidence
"""
import sys
import numpy as np
from PIL import Image

d = sys.argv[1]
PDS = 50.0
tiles = []
for side in ("dev", "branch"):
    t = np.asarray(Image.open(f"{d}/{side}_terrain-only.png").convert("RGB"))
    s = np.asarray(Image.open(f"{d}/{side}_symbology-only.png").convert("RGB"))
    h, w, _ = t.shape
    edges, lines = [], []
    for c in list(range(80, 300)) + list(range(w - 300, w - 80)):
        col = t[:200, c].astype(int)
        sky = (col[:, 2] > 235) & (col[:, 1] > 140) & (col[:, 0] < 60)
        edges.append(int(np.argmin(sky)))
        white = np.all(s[:200, c] > 230, axis=1)
        if white.any():
            lines.append(float(np.mean(np.nonzero(white)[0])))
    edge, line = float(np.median(edges)), float(np.median(lines))
    up = line - edge
    print(f"{side:7s} sea edge y={edge:.1f}  zero-pitch line y={line:.1f}  "
          f"edge above line {up:+.1f} px = {up * PDS / h:+.2f} deg")
    crop = t[0:80, 128:384].copy()
    for y in range(int(np.floor(line)), int(np.ceil(line)) + 1):
        crop[y, :] = (255, 0, 255)
    tiles.append(Image.fromarray(crop).resize((256 * 4, 80 * 4),
                                              Image.Resampling.NEAREST))
out = Image.new("RGB", (tiles[0].width * 2 + 16, tiles[0].height), "black")
out.paste(tiles[0], (0, 0))
out.paste(tiles[1], (tiles[0].width + 16, 0))
out.save(f"{d}/horizon_crop_4x.png")
