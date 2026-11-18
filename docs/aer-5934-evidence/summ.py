import json, sys, statistics as st
p = sys.argv[1]; w0 = float(open(p + ".win").read())
rows = [json.loads(l) for l in open(p) if '"ticks_s"' in l]
import os
w1 = float(open(p + ".end").read()) if os.path.exists(p + ".end") else w0 + 61
win = [r for r in rows if r["t"] - r["secs"] >= w0 - 0.5 and r["t"] <= w1 + 2.5]
inst = [json.loads(l) for l in open(p) if '"installed"' in l]
print("installed:", inst[:1], "reports in window:", len(win))
keys = ["ticks_s", "ticks_upd_s", "paints_s", "ur_s", "ur_with_ai_s", "tick_gap_med", "tick_gap_p90", "tick_gap_max",
        "tick_ms_med", "tick_ms_p90", "paint_ms_med", "paint_ms_p90", "paint_gap_med", "paint_gap_p90",
        "ur_ms_med", "ur_ms_p90", "ur_busy_pct", "tick_busy_pct"]
for k in keys:
    v = [r[k] for r in win if r.get(k) is not None]
    if v: print(f"  {k:14s} mean {st.mean(v):7.1f}  min {min(v):7.1f}  max {max(v):7.1f}")
