import json, sys, statistics as st
p = sys.argv[1]; w0 = float(open(p + ".win").read()); w1 = float(open(p + ".end").read())
rows = [json.loads(l) for l in open(p) if '"ticks_s"' in l]
win = [r for r in rows if r["t"] - r["secs"] >= w0 - 0.5 and r["t"] <= w1 + 2.5]
print("reports in window:", len(win))
for k in ["paints_s", "ticks_s", "ticks_upd_s", "paint_ms_med", "paint_ms_p90", "tick_gap_p90", "tick_gap_max", "ur_busy_pct", "tfc_frames", "tfc_drawn_max", "tfc_drawn_med"]:
    v = [r[k] for r in win if r.get(k) is not None]
    if v: print(f"  {k:14s} mean {st.mean(v):7.2f}  min {min(v):7.2f}  max {max(v):7.2f}")
err = [r["tfc_err"] for r in win if "tfc_err" in r]
if err: print("tfc_err", err[0])
print("SUMMARY %s paints_s_mean=%.2f n=%d tfc_drawn_max=%s" % (p.split('/')[-1], st.mean([r["paints_s"] for r in win]), len(win), max([r.get("tfc_drawn_max", 0) for r in win] or [0])))
