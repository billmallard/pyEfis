"""Design-pass renders of the target-bank bug (AER-5149, ATT1 item 2).

Run from the repo root (offscreen Qt):
    QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. \
        python docs/images/aer5149_bank_bug/render.py

Top row: bug at 45 deg (Private steep turn), bank -45 / -48 / +38 / +55.
Bottom row: bug at 50 (Commercial), bank -50 / +50, and bug at 60, bank
+60 / +66 (past the de-clutter: bug and band hidden).
"""
import os
import sys

from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
import tools.render_instrument as ri  # noqa: E402

_orig_setup = ri._setup_fix


def _setup_fix():
    # render_instrument auto-defines unknown keys as 0..100, which would
    # flatten every left bank to wings level: give ROLL/PITCH signed ranges.
    _orig_setup()
    for key, lo, hi in (("ROLL", -180.0, 180.0), ("PITCH", -90.0, 90.0)):
        ri.fix.db.define_item(key, key, "float", lo, hi, "deg", 50000, "")


ri._setup_fix = _setup_fix

HERE = os.path.dirname(os.path.abspath(__file__))
W, H = 480, 360
ROWS = [
    [(45, -45), (45, -48), (45, 38), (45, 55)],
    [(50, -50), (50, 50), (60, 60), (60, 66)],
]
sheet = Image.new("RGB", (W * 4 + 3 * 4, H * 2 + 4), "black")
for ri_, row in enumerate(ROWS):
    for ci, (bug, roll) in enumerate(row):
        out = os.path.join(HERE, f"_tile_{ri_}{ci}.png")
        ri.render_instrument("atitude_indicator",
                             options={"bankBug": bug},
                             seed={"ROLL": roll, "PITCH": 0, "TAS": 110},
                             width=W, height=H, out_path=out)
        sheet.paste(Image.open(out).convert("RGB"),
                    (ci * (W + 4), ri_ * (H + 4)))
        os.remove(out)
sheet.save(os.path.join(HERE, "sheet.png"))
print("wrote", os.path.join(HERE, "sheet.png"))
