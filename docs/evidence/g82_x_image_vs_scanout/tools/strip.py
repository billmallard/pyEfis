"""G82: the X image vs the scanout around one tap, from the two recorders'
changed-frame dumps (glass_<L>/ and glass_<L>k/). Run in the bench data dir.
argv: label tap_index out.png"""
import json, sys
import numpy as np
from PIL import Image, ImageDraw
L, i, out = sys.argv[1], int(sys.argv[2]), sys.argv[3]
s = [json.loads(l) for l in open("sends_%s.jsonl" % L)]
def frames(d):
    return [r for r in map(json.loads, open(d + "/glass.jsonl")) if "changed_px" in r]
def at(d, t):
    r = [f for f in frames(d) if f["w"] <= t][-1]
    return np.load("%s/f%06d.npy" % (d, r["n"]))
t0 = s[i]["w"]; X, K = "glass_" + L, "glass_%sk" % L
panels = [("before tap\nX image", X, -0.05), ("X image (x11grab)\nstill the old page", X, 0.75),
          ("scanout (kmsgrab)\nClear dialog on panel", K, 0.75), ("X image (x11grab)\nfinally changes", X, 1.55)]
h, w = at(X, t0).shape; S, pad, top = 2, 8, 34
img = Image.new("L", (len(panels) * (w * S + pad) + pad, h * S + top + pad), 40)
dr = ImageDraw.Draw(img)
for j, (lab, d, dt) in enumerate(panels):
    x = pad + j * (w * S + pad)
    img.paste(Image.fromarray(at(d, t0 + dt)).resize((w * S, h * S), Image.NEAREST), (x, top))
    for k, line in enumerate((lab + " +%.2f s" % dt).split("\n")):
        dr.text((x, 4 + k * 13), line, fill=255)
img.save(out)
