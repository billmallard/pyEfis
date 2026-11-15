#!/usr/bin/env python3
"""Compose the AER-5086 contact sheet, zoom and live strip from the bench frames.

    python3 docs/aer-5086-evidence/compose.py      (needs Pillow)

Crops the attitude area (x 330-920, y 60-560 of the 1920x1080 glass) and
captions each tile with the bus values read at the grab (frames.json).
"""
import json, os
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
BOX = (330, 60, 920, 560)
FRAMES = {f["frame"]: f for f in json.load(open(os.path.join(HERE, "frames.json")))}


def caption(name):
    b = FRAMES[name]["before"]
    ok = b["flags_aobfs"][1:4] == "000"
    margin = float(b["AOA.Warn"]) - b["AOA"] if ok else None
    roll = FRAMES[name]["roll"]
    txt = f"{name}  AOA {b['AOA']:.1f} {'' if ok else '(bad) '}Warn {b['AOA.Warn']}"
    txt += f"  margin {margin:+.1f}" if margin is not None else "  margin --"
    return txt + (f"  roll {roll:.0f}" if roll else "")


def sheet(names, src, out, cols):
    tiles = [Image.open(os.path.join(HERE, src, n + ".png")).crop(BOX) for n in names]
    w, h = tiles[0].size
    rows = (len(tiles) + cols - 1) // cols
    img = Image.new("RGB", (w * cols, (h + 22) * rows), "black")
    d = ImageDraw.Draw(img)
    for i, (n, t) in enumerate(zip(names, tiles)):
        x, y = (i % cols) * w, (i // cols) * (h + 22)
        img.paste(t, (x, y + 22))
        d.text((x + 6, y + 5), caption(n), fill="white")
    img.save(os.path.join(HERE, out))


sheet(["1-taxi", "2-cruise", "3-amber6", "4-amber3", "5-red", "6-flaps40", "7-amber3-bank20"],
      ".", "sheet.png", 4)
sheet([f"8-live-flaps40-{i:02d}" for i in (3, 5, 7, 9, 11, 13)], "live", "live_strip.png", 3)

# 2x nearest-neighbour zoom of the left bar and the symbol, 4-amber3 and 5-red.
z = []
for n in ("4-amber3", "5-red"):
    z.append(Image.open(os.path.join(HERE, n + ".png")).crop((370, 190, 640, 420))
             .resize((540, 460), Image.NEAREST))
img = Image.new("RGB", (1090, 460), "black")
img.paste(z[0], (0, 0)); img.paste(z[1], (550, 0))
img.save(os.path.join(HERE, "zoom_2x.png"))
