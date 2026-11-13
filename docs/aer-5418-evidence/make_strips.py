"""Build hsi_map_through_hener.png from the bench grabs (see README.md):
the HSI and the moving map at each hold, side by side, from the same frame.

    python3 make_strips.py <shots dir> <events.log>
"""
import ast
import sys

from PIL import Image, ImageDraw, ImageFont

S, EVENTS = sys.argv[1], sys.argv[2]
STATES = [("1_before_turn", "before turn start"), ("2_turn_start", "just past turn start"),
          ("3_in_turn", "in the turn, before the bisector"), ("4_past_bisector", "past the bisector")]
HSI = (450, 640, 810, 1045)     # the HSI, left of the PFD
MAP = (1430, 300, 1830, 760)    # the map around HENER, 2.1 nm range
FONT = ImageFont.load_default(size=24)
SMALL = ImageFont.load_default(size=20)

holds = {}
for line in open(EVENTS):
    if " HOLD " in line:
        name = line.split(" HOLD ")[1].split()[0]
        holds[name] = ast.literal_eval(line[line.index("{"):].strip())

tiles = []
for name, label in STATES:
    im = Image.open(f"{S}/{name}_map.png").convert("RGB")
    parts = [im.crop(HSI), im.crop(MAP)]
    t = Image.new("RGB", (sum(p.width for p in parts) + 10, max(p.height for p in parts) + 70), "black")
    x = 0
    for p in parts:
        t.paste(p, (x, 70))
        x += p.width + 10
    h = holds[name]
    d = ImageDraw.Draw(t)
    d.text((10, 6), label, fill="white", font=FONT)
    d.text((10, 38), "FPLCDI %+.3f   FPLACTLEG %s (%s)   FPL6TA %s nm" % (
        float(h["FPLCDI"]), h["FPLACTLEG"], h["WPNAME"], h["FPL6TA"]), fill=(200, 200, 200), font=SMALL)
    tiles.append(t)

tw, th = tiles[0].width, tiles[0].height
out = Image.new("RGB", (2 * tw + 20, 2 * th + 20), (40, 40, 40))
for i, t in enumerate(tiles):
    out.paste(t, ((i % 2) * (tw + 20), (i // 2) * (th + 20)))
out.save("hsi_map_through_hener.png", optimize=True)
