"""G82: toggle -> X image latency. argv: app.jsonl rec.jsonl [label]"""
import json, sys
app = [json.loads(l) for l in open(sys.argv[1])]
rec = [json.loads(l) for l in open(sys.argv[2])]
label = sys.argv[3] if len(sys.argv) > 3 else ""
start = next(r for r in app if r["k"] == "start")
tog = [r for r in app if r["k"] == "toggle"]
fl = [r for r in app if r["k"] == "flush"]
fr = [r for r in rec if r["k"] == "frame"]
gaps = [r for r in rec if r["k"] == "gap"]
rows = []
for j, t in enumerate(tog):
    t0 = t["w"]; t1 = tog[j + 1]["w"] if j + 1 < len(tog) else t0 + 3
    want = "light" if t["on"] else "dark"
    g = next((f for f in fr if t0 <= f["w"] < t1 + 3 and f["st"] == want), None)
    lat = None if g is None else round(g["w"] - t0, 3)
    fls = [round(f["w"] - t0, 3) for f in fl if t0 <= f["w"] < (g["w"] if g else t1)]
    gp = [x["gap"] for x in gaps if t0 <= x["w"] < (g["w"] if g else t1) + 0.1]
    rows.append(dict(i=t["i"], lat=lat, flushes=fls[:6], gaps=gp))
lat = sorted(r["lat"] for r in rows if r["lat"] is not None)
late = [r for r in rows if r["lat"] is None or r["lat"] > 0.2]
bgfl = [b["w"] - a["w"] for a, b in zip(fl, fl[1:])]
print("%s opts=%s qt=%s plat=%s" % (label, start.get("opts"), start.get("qt"), start.get("platform")))
print("  toggles=%d median=%.3f p90=%.3f max=%.3f  late(>0.2s)=%d  missing=%d  rec_gaps=%d  flushes=%d (median gap %.2fs)" % (
    len(rows), lat[len(lat) // 2], lat[int(len(lat) * .9)], lat[-1], len(late),
    sum(r["lat"] is None for r in rows), len(gaps), len(fl), sorted(bgfl)[len(bgfl) // 2] if bgfl else 0))
for r in late:
    print("  LATE", r)
json.dump(rows, open(sys.argv[1].replace(".jsonl", "") + ".rows.json", "w"))
