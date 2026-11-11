"""Build map_before_after_hener.png: the moving map around HENER at each
hold, pyEfis dev (left, square corner) against this branch (right, the
turn's arc), from the same replay on the same bench (see README.md).

    python3 make_before_after.py <dev shots dir> <branch shots dir>
"""
import sys

from PIL import Image, ImageDraw, ImageFont

BEFORE, AFTER = sys.argv[1], sys.argv[2]
STATES = [("1_before_turn", "before turn start"), ("2_turn_start", "just past turn start"),
          ("3_in_turn", "in the turn, before the bisector"), ("4_past_bisector", "past the bisector")]
MAP = (1430, 300, 1830, 760)
FONT = ImageFont.load_default(size=24)

rows = []
for name, label in STATES:
    a = Image.open(f"{BEFORE}/{name}_map.png").convert("RGB").crop(MAP)
    b = Image.open(f"{AFTER}/{name}_map.png").convert("RGB").crop(MAP)
    t = Image.new("RGB", (a.width * 2 + 10, a.height + 40), "black")
    t.paste(a, (0, 40))
    t.paste(b, (a.width + 10, 40))
    d = ImageDraw.Draw(t)
    d.text((10, 6), label + ": dev", fill="white", font=FONT)
    d.text((a.width + 20, 6), "this branch", fill="white", font=FONT)
    rows.append(t)

tw, th = rows[0].width, rows[0].height
out = Image.new("RGB", (2 * tw + 20, 2 * th + 20), (40, 40, 40))
for i, t in enumerate(rows):
    out.paste(t, ((i % 2) * (tw + 20), (i // 2) * (th + 20)))
out.save("map_before_after_hener.png", optimize=True)
