"""Before/after renders of the excessive-bank caution (AER-5149).

Run from the repo root (offscreen Qt):
    QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. \
        python docs/images/aer5149_excessive_bank/render.py

Renders the plain attitude indicator at +/-45 and +/-55 deg bank with
excessiveBankDeg 45 (the old default, "before") and 60 (the new default,
"after"), then tiles them into sheet.png. ROLL/PITCH are pre-defined with
signed ranges: render_instrument's auto-define clamps unknown keys to 0..100,
which would flatten every left bank to wings level.
"""
import os
import sys

from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
import tools.render_instrument as ri  # noqa: E402

_orig_setup = ri._setup_fix


def _setup_fix():
    _orig_setup()
    for key, lo, hi in (("ROLL", -180.0, 180.0), ("PITCH", -90.0, 90.0)):
        ri.fix.db.define_item(key, key, "float", lo, hi, "deg", 50000, "")


ri._setup_fix = _setup_fix

HERE = os.path.dirname(os.path.abspath(__file__))
ROLLS = (-55, -45, 45, 55)
W, H = 360, 270
tiles = {}
for before, thr in (("before", 45), ("after", 60)):
    for roll in ROLLS:
        out = os.path.join(HERE, f"{before}_bank{roll:+d}.png")
        ri.render_instrument("atitude_indicator",
                             options={"excessiveBankDeg": thr},
                             seed={"ROLL": roll, "PITCH": 0, "TAS": 100},
                             width=W, height=H, out_path=out)
        tiles[(before, roll)] = out

sheet = Image.new("RGB", (W * len(ROLLS), H * 2), "black")
for row, before in enumerate(("before", "after")):
    for col, roll in enumerate(ROLLS):
        sheet.paste(Image.open(tiles[(before, roll)]).convert("RGB"),
                    (col * W, row * H))
sheet.save(os.path.join(HERE, "sheet.png"))
for path in tiles.values():
    os.remove(path)
print("wrote", os.path.join(HERE, "sheet.png"))
