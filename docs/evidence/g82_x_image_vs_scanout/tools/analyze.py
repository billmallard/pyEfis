"""Per-tap latency chain for G79. argv: data_dir label"""
import glob, json, os, sys
import numpy as np
d, label = sys.argv[1], sys.argv[2]
sends = [json.loads(l) for l in open(os.path.join(d, "sends_%s.jsonl" % label))]
probe = [json.loads(l) for l in open(os.path.join(d, "probe.log"))]
glass = [json.loads(l) for l in open(os.path.join(d, "glass_%s/glass.jsonl" % label))]
gch = [g for g in glass if "changed_px" in g]
def frame(n):
    return np.load(os.path.join(d, "glass_%s/f%06d.npy" % (label, n))).astype(int)
rows = []
for i, s in enumerate(sends):
    t0 = s["w"]
    t1 = sends[i + 1]["w"] if i + 1 < len(sends) else t0 + 3
    win = [r for r in probe if t0 - 0.05 <= r["w"] < t1]
    def first(k, after=None):
        for r in win:
            if r["k"] == k and (after is None or r["w"] >= after):
                return r
    press = first("press"); rel = first("release")
    cb = first("fp_press_cb") or first("fp_release_cb")
    paint = first("fp_paint", cb["w"] if cb else None) if cb else None
    upd = first("upd", paint["w"] if paint else None) if paint else None
    stalls = [r["gap"] for r in win if r["k"] == "stall"]
    # glass: frames before t0 and in window
    before = [g for g in gch if g["w"] < t0]
    inwin = [g for g in gch if t0 <= g["w"] < t1]
    onset = None
    if before and inwin:
        base = frame(before[-1]["n"]); final = frame(inwin[-1]["n"])
        total = np.abs(final - base).sum()
        for g in inwin:
            if total and np.abs(frame(g["n"]) - base).sum() >= 0.5 * total:
                onset = g; break
    rel_ = lambda r: None if r is None else round(r["w"] - t0, 3)
    rows.append(dict(i=i, name=s["name"][:22], page=s["page"], press=rel_(press), rel=rel_(rel),
                     cb=rel_(cb), paint=rel_(paint), flush=None if upd is None else round(upd["w"] - t0, 3),
                     flushdur=None if upd is None else upd["dur"], glass=rel_(onset),
                     nchg=len(inwin), stalls=stalls, cbname=cb["cb"][:30] if cb else None))
for r in rows:
    print(r)
def stat(k):
    v = sorted(x[k] for x in rows if x[k] is not None)
    if not v: return "%s: none" % k
    return "%s: n=%d median=%.3f p90=%.3f max=%.3f" % (k, len(v), v[len(v)//2], v[int(len(v)*0.9)], v[-1])
for k in ("press", "cb", "paint", "flush", "glass"):
    print(stat(k))
print("missing glass:", [r["i"] for r in rows if r["glass"] is None])
print("stalls >0.06 s in any window:", sum(len(r["stalls"]) for r in rows), max([max(r["stalls"]) for r in rows if r["stalls"]] or [0]))
json.dump(rows, open(os.path.join(d, "rows_%s.json" % label), "w"), indent=0)
