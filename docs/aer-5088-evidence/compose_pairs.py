#!/usr/bin/env python3
#  SPDX-License-Identifier: GPL-2.0-or-later
"""Side-by-side dev | branch with a 4x nearest-neighbour inset of the
scene's route point (G59 evidence). Usage: compose_pairs.py DEV_DIR BRANCH_DIR OUT_DIR"""
import sys

from PIL import Image

dev, branch, out = sys.argv[1:4]
for s in ("ksba_2nm", "ksba_20nm", "gvo_2nm", "gvo_20nm"):
    a = Image.open(f"{dev}/{s}.png").convert("RGB")
    b = Image.open(f"{branch}/{s}.png").convert("RGB")
    w, h = a.size
    # The point is a third of the range above the ownship anchor (h/2).
    cx, cy = w // 2, h // 2 - (h // 2) // 3
    box = (cx - 50, cy - 30, cx + 50, cy + 50)
    im = Image.new("RGB", (w * 2 + 10, h + 330), (0, 0, 0))
    im.paste(a, (0, 0))
    im.paste(b, (w + 10, 0))
    im.paste(a.crop(box).resize((400, 320), Image.NEAREST), ((w - 400) // 2, h + 10))
    im.paste(b.crop(box).resize((400, 320), Image.NEAREST), (w + 10 + (w - 400) // 2, h + 10))
    im.save(f"{out}/{s}.png")
