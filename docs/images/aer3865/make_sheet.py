"""AER-3865: lay out the Pi 5 captures as one row per attitude,
current dev on the left, screen-space-roll prototype on the right."""
import sys
from PIL import Image, ImageDraw, ImageFont

SRC = sys.argv[1]
OUT = sys.argv[2]
ROWS = [(0, 0), (0, 15), (0, 30), (0, -30), (0, 45), (0, 60), (0, -60),
        (0, 90), (0, 120), (0, 180), (20, 60), (-20, 60)]
if len(sys.argv) > 3:
    ROWS = [r for r in ROWS if f"{r[0]},{r[1]}" in sys.argv[3].split(";")]
SCALE = 0.5
GAP, LABEL_H, HEAD_H = 12, 34, 56


def font(sz):
    for f in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"):
        try:
            return ImageFont.truetype(f, sz)
        except OSError:
            pass
    return ImageFont.load_default(size=sz)


f_lab, f_head = font(22), font(24)
probe = Image.open(f"{SRC}/p0_r0_dev.png")
fw, fh = int(probe.width * SCALE), int(probe.height * SCALE)
W = 2 * fw + 3 * GAP
H = HEAD_H + len(ROWS) * (LABEL_H + fh + GAP)
sheet = Image.new("RGB", (W, H), (24, 24, 24))
d = ImageDraw.Draw(sheet)
d.text((GAP, 14), "CURRENT dev f1ef6ae", fill="white", font=f_head)
d.text((2 * GAP + fw, 14), "FIX prototype a4c1fe4 (screen-space roll)",
       fill="white", font=f_head)
y = HEAD_H
for pitch, roll in ROWS:
    for i, b in enumerate(("dev", "proto")):
        x = GAP + i * (fw + GAP)
        lab = f"bank {roll:+d} deg, pitch {pitch:+d} deg  -  " + (
            "current" if b == "dev" else "fix")
        d.text((x, y + 5), lab, fill="white", font=f_lab)
        im = Image.open(f"{SRC}/p{pitch}_r{roll}_{b}.png").convert("RGB")
        sheet.paste(im.resize((fw, fh), Image.LANCZOS), (x, y + LABEL_H))
    y += LABEL_H + fh + GAP
sheet.save(OUT, optimize=True)
print(OUT, sheet.size)
