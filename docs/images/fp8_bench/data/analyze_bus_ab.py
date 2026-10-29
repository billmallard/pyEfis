"""FP8 session 2 analysis (AER-809): section 2 A/B of the internal plan
(FPL*) against X-Plane's FMS (EXT* on the same bus row, and the sim bench's
5 Hz truth.jsonl aligned on the fix sequence).

    python3 analyze.py <run_dir> <fixes.json>
"""
import csv
import json
import math
import statistics
import sys

RUN, FIXES = sys.argv[1], sys.argv[2]
FIX = json.load(open(FIXES))


def f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def w180(a):
    return (a + 180.0) % 360.0 - 180.0


def nm(a, b):
    return math.hypot((a[0] - b[0]) * 60, (a[1] - b[1]) * 60 * math.cos(math.radians(a[0])))


rows = [r for r in csv.DictReader(open(f"{RUN}/fp8_s2.csv"))]
for r in rows:
    r["t"] = float(r["t"])
T = [json.loads(l) for l in open(f"{RUN}/truth.jsonl")]

# --- our sequence events (WPNAME / FPLACTLEG changes) -------------------------
ours = []
prev = None
for r in rows:
    k = (r["FPLACTLEG"], r["WPNAME"])
    if prev and k != prev and not r["FPLACTLEG"].startswith("ERR"):
        ours.append((r["t"], prev[1], r["WPNAME"], (f(r["LAT"]), f(r["LONG"])), r["FPLACTLEG"]))
    prev = k

# --- X-Plane's sequence events from truth ----------------------------------------
xp = []
prev = None
for r in T:
    k = (r["gps_id"], r["app_dest"])
    if prev and k != prev:
        xp.append((r["t"], prev[0], r["gps_id"], (r["lat"], r["lon"]), r["app_dest"]))
    prev = k

print("== our sequence events (bus, 1 Hz)")
for e in ours:
    print("  %s  %-6s -> %-6s leg %-3s at %.5f %.5f" % (e[0], e[1], e[2], e[4], *e[3]))
print("== X-Plane sequence events (truth, 5 Hz)")
for e in xp:
    print("  %8.1f  %-6s -> %-6s dest %-3s at %.5f %.5f" % (e[0], e[1], e[2], e[4], *e[3]))

# --- align truth time to bus time on matching transitions --------------------------
pairs = []
for e in xp:
    m = [o for o in ours if o[1] == e[1] and o[2] == e[2]]
    if m:
        pairs.append(m[0][0] - e[0])
off = statistics.median(pairs) if pairs else None
print("== truth->bus time offset (median over %d matching transitions): %.1f s, spread %s"
      % (len(pairs), off or 0, [round(p - off, 1) for p in pairs]))

# --- sequencing point: where each system switched, as distance before/after the fix --
print("== sequence points (distance from the fix being sequenced; + = before it, along track)")
seqrows = []
for o in ours:
    fx = o[1]
    if fx not in FIX or o[2] == "":
        continue
    x = [e for e in xp if e[1] == fx and (e[2] == o[2] or (o[2] == "" and True))]
    d_ours = nm(o[3], FIX[fx])
    line = "  %-6s ours %.3f nm from fix" % (fx, d_ours)
    if x:
        d_xp = nm(x[0][3], FIX[fx])
        sep = nm(o[3], x[0][3])
        line += ", X-Plane %.3f nm from fix, ours-vs-X-Plane %.3f nm" % (d_xp, sep)
        seqrows.append((fx, d_ours, d_xp, sep))
    print(line)

# --- per-leg A/B on the same bus rows ----------------------------------------------
seq_t = [o[0] for o in ours] + ([e[0] + off for e in xp] if off is not None else [])
print("== per-leg DTK / CDI agreement (bus rows, EXT* fresh, +/-5 s around any sequence excluded)")
legs = {}
for r in rows:
    if r["flags_EXTCRS"][1:2] != "0" or r["FPLSTATE"] not in ("1", "3"):
        continue
    if any(abs(r["t"] - s) <= 5 for s in seq_t):
        continue
    a, b = f(r["FPLCRS"]), f(r["EXTCRS"])
    c, d = f(r["FPLCDI"]), f(r["EXTCDI"])
    if None in (a, b, c, d):
        continue
    key = "%s>%s" % (r["WPFROM"] or "?", r["WPNAME"] or "?")
    L = legs.setdefault(key, {"n": 0, "dcrs": [], "dcdi": [], "signbad": 0, "maxcdi": 0.0, "xtk": [], "gpssrc1": 0})
    L["n"] += 1
    L["dcrs"].append(abs(w180(a - b)))
    L["dcdi"].append(abs(c - d))
    if abs(c) > 0.05 and abs(d) > 0.05 and (c > 0) != (d > 0):
        L["signbad"] += 1
    L["maxcdi"] = max(L["maxcdi"], abs(c))
    L["xtk"].append(abs(f(r["FPLXTK"]) or 0))
    L["gpssrc1"] += r["GPSSRC"] == "1"
print("  %-14s %4s %9s %9s %9s %8s %8s" % ("leg", "n", "maxdDTK", "maxdCDI", "p95dCDI", "signbad", "maxXTK"))
for k, L in legs.items():
    s = sorted(L["dcdi"])
    print("  %-14s %4d %9.3f %9.4f %9.4f %8d %8.3f" % (k, L["n"], max(L["dcrs"]), max(L["dcdi"]),
                                                      s[int(0.95 * (len(s) - 1))], L["signbad"], max(L["xtk"])))

# --- 1 nm cross-track points (the offset events) -------------------------------------
print("== rows with |FPLXTK| >= 0.9 nm (the +/-1 nm offsets)")
for r in rows:
    x = f(r["FPLXTK"])
    if x is not None and abs(x) >= 0.9 and r["flags_EXTCRS"][1:2] == "0":
        print("  %s %s>%s xtk %+.3f  FPLCDI %+.3f EXTCDI %+.3f  scale %s phase %s" % (
            r["t"], r["WPFROM"], r["WPNAME"], x, f(r["FPLCDI"]), f(r["EXTCDI"]), r["CDISCALE"], r["FPLPHASE"]))

# --- truth cross-check: our FPLCRS / FPLXTK vs X-Plane navigator at the same instant ---
if off is not None:
    import bisect
    tt = [r["t"] + off for r in T]
    worst = {}
    for r in rows:
        if r["FPLSTATE"] != "1" or r["flags_EXTCRS"][1:2] != "0":
            continue
        i = bisect.bisect_left(tt, r["t"])
        if i <= 0 or i >= len(T) or abs(tt[i] - r["t"]) > 0.25:
            continue
        x = T[i]
        if x["gps_id"] != r["WPNAME"]:
            continue
        a = f(r["FPLCRS"])
        if a is None:
            continue
        k = r["WPNAME"]
        W = worst.setdefault(k, [0, 0.0, 0.0])
        W[0] += 1
        W[1] = max(W[1], abs(w180(a - x["gps_crs_mag"])))
        W[2] = max(W[2], abs(abs(f(r["FPLXTK"])) - abs(x["gps_xtk_nm"])))
    print("== truth cross-check (same TO fix, |dt|<=0.25 s): n, max|dCRS| deg, max||xtk|-|xtk_xp|| nm")
    for k, W in worst.items():
        print("  %-6s %4d %7.3f %7.3f" % (k, *W))
print("== wind (truth): %s" % sorted({(round(r["wind_dir"]), round(r["wind_kt"])) for r in T[::300]}))
