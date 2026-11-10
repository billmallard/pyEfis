"""AER-5149 Pi 5 sheet: rows standard rate (18 deg at 120 KTAS) / 45 / 60,
columns left-before, left-after, right-before, right-after, each frame at 50%.
Also bank_cluster_2x.png: the top of each frame (the bank scale), 2x scale.

Run from this directory after the frames are in frames/:
    python make_sheet.py
"""
import os
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
ROWS = [18, 45, 60]
COLS = [("-{}", "dev"), ("-{}", "pr"), ("{}", "dev"), ("{}", "pr")]
S = 0.5
GAP = 6


def frame(roll, build):
    return Image.open(os.path.join(HERE, "frames", f"r{roll}_{build}.png")).convert("RGB")


def build_sheet(name, crop=None, scale=S):
    tiles = []
    for bank in ROWS:
        row = []
        for fmt, build in COLS:
            im = frame(fmt.format(bank), build)
            if crop:
                im = im.crop(crop)
            im = im.resize((int(im.width * scale), int(im.height * scale)),
                           Image.Resampling.NEAREST if scale > 1 else Image.Resampling.LANCZOS)
            row.append(im)
        tiles.append(row)
    w, h = tiles[0][0].size
    sheet = Image.new("RGB", (4 * w + 3 * GAP, 3 * h + 2 * GAP), "black")
    for ri, row in enumerate(tiles):
        for ci, im in enumerate(row):
            sheet.paste(im, (ci * (w + GAP), ri * (h + GAP)))
    sheet.save(os.path.join(HERE, name))


build_sheet("sheet.png")
# The bank cluster: the arc centre is at 37% of the height (bank_position 63),
# radius 25% of the height, so the scale and arrows sit in y 0..~460.
build_sheet("bank_cluster.png", crop=(324, 40, 924, 420), scale=1.0)
print("wrote sheet.png, bank_cluster.png")
