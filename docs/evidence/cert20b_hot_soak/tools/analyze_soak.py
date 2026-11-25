"""CERT20b (AER-6451) analysis of one soak run directory.

  analyze_soak.py <run-dir> [--window 600] [--settle 2.0] [--json out.json]

Windows: ``cool`` is the first --window seconds after the feed started (T0);
``hot`` is the last --window seconds before the stop. Within each:

* Frame interval: time between consecutive paintEvent starts of the visible AI,
  per screen, inside a screen's dwell. The first --settle seconds after each
  screen switch are reported separately (``switch``), because a switch builds
  that screen's SVS GL renderer and heightmap again; they are not hidden.
* Paint time: paintEvent duration. Compose: duration of the top-level
  UpdateRequest that contained the paint (Qt composes and swaps there);
  ``composed_in`` counts paints composed inside an UpdateRequest and paints
  composed by the next one.
* Data-to-glass on ROLL: from the feed's timestamp just before it sent a ROLL
  value to fix-gateway, to the end of the UpdateRequest that composed the
  visible AI's first paint of that value (buffer swap submitted; scanout follows at the
  next vblank, up to 16.7 ms at 60 Hz, which this does not measure). Only writes
  made while a screen with an AI was showing (past --settle) count; a value
  never painted because a newer one arrived first is counted, not timed.
* Thermal: SoC temperature, the firmware ARM clock, the get_throttled now
  bits, CPU use of the pyEfis and fix-gateway processes and of the whole box.

Every timestamp is CLOCK_MONOTONIC; thermal rows carry wall and monotonic
time, which gives the wall/monotonic offset for T0.
"""
import argparse
import bisect
import gzip
import json
import os
import statistics as st

THROTTLE_NOW = {0: "under_voltage", 1: "arm_freq_capped", 2: "throttled", 3: "soft_temp_limit"}


def q(a, p):
    if not a:
        return None
    a = sorted(a)
    return a[min(len(a) - 1, int(round(p * (len(a) - 1))))]


def dist(ms):
    if not ms:
        return {"n": 0}
    return {"n": len(ms), "median": round(q(ms, .5), 2), "p99": round(q(ms, .99), 2),
            "max": round(max(ms), 2), "mean": round(st.mean(ms), 2)}


def _open(d, name):
    """A run directory keeps the big logs gzipped once it is committed."""
    p = os.path.join(d, name)
    return open(p) if os.path.exists(p) else gzip.open(p + ".gz", "rt")


def load(d):
    P, U, S, inst = [], [], [], None
    for line in _open(d, "probe.csv"):
        k, rest = line[0], line[2:].rstrip("\n")
        if k == "P":
            t, dur, roll, scr = rest.split(",", 3)
            P.append((int(t), int(dur), float(roll), scr))
        elif k == "U":
            t, dur, cls = (rest.split(",") + ["?"])[:3]
            U.append((int(t), int(dur), cls))
        elif k == "S":
            t, scr = rest.split(",", 1)
            S.append((int(t), scr))
        elif k == "I":
            inst = json.loads(rest.split(",", 1)[1])
    W = []
    for line in _open(d, "roll_writes.csv"):
        t, v = line.strip().split(",")
        W.append((int(t), float(v)))
    TH = [json.loads(ln) for ln in open(os.path.join(d, "thermal.jsonl")) if ln.strip()]
    return P, U, S, inst, W, TH


def analyze(d, window=600.0, settle=2.0):
    P, U, S, inst, W, TH = load(d)
    off = st.median(r["wall"] - r["mono_ns"] / 1e9 for r in TH)   # wall = mono + off
    t0_wall = float(open(os.path.join(d, "T0")).read())
    t0 = int((t0_wall - off) * 1e9)
    end = min(P[-1][0], W[-1][0], TH[-1]["mono_ns"])
    if os.path.exists(os.path.join(d, "STOP_REASON")):
        stop = open(os.path.join(d, "STOP_REASON")).read().strip()
    else:
        stop = None
    wn = int(window * 1e9)
    wins = {"cool": (t0, min(t0 + wn, end)), "hot": (max(end - wn, t0), end)}
    s_times = [s[0] for s in S]
    u_starts = [u[0] for u in U]

    def screen_at(t):
        i = bisect.bisect_right(s_times, t) - 1
        return (S[i][1], S[i][0], S[i + 1][0] if i + 1 < len(S) else None) if i >= 0 else (None, None, None)

    def ur_end(pt, pdur):
        """(end, duration, kind) of the UpdateRequest that put this paint on
        glass: the one containing it, else the next one to start after it
        (on some screen visits the AI paints outside an UpdateRequest and the
        next one composes it)."""
        pe = pt + pdur
        i = bisect.bisect_right(u_starts, pt) - 1
        if i >= 0 and U[i][0] + U[i][1] >= pe:
            return U[i][0] + U[i][1], U[i][1], "containing"
        j = bisect.bisect_left(u_starts, pe)
        if j < len(U) and U[j][0] - pe < 2e8:
            return U[j][0] + U[j][1], U[j][1], "next"
        return None, None, None

    out = {"run": os.path.basename(os.path.normpath(d)), "stop_reason": stop,
           "install": inst, "t0_wall": t0_wall,
           "duration_s": round((end - t0) / 1e9, 1), "windows": {}}
    for name, (a, b) in wins.items():
        rec = {"from_s": round((a - t0) / 1e9, 1), "to_s": round((b - t0) / 1e9, 1)}
        # --- frames
        per = {}
        prev = None
        for p in P:
            if not a <= p[0] <= b:
                prev = None
                continue
            scr, s_t, s_next = screen_at(p[0])
            e = per.setdefault(scr, {"gap": [], "gap_switch": [], "paint": [], "compose": [],
                                     "containing": 0, "next": 0, "lat": []})
            e["paint"].append(p[1] / 1e6)
            ue, ud, kind = ur_end(p[0], p[1])
            if kind == "containing":
                e["compose"].append(ud / 1e6)
            if kind:
                e[kind] += 1
            if prev is not None and prev[3] == scr and prev[0] >= s_t:
                g = (p[0] - prev[0]) / 1e6
                (e["gap_switch"] if p[0] - s_t < settle * 1e9 else e["gap"]).append(g)
            prev = p
        frames = {}
        allg = []
        for scr, e in sorted(per.items(), key=lambda kv: str(kv[0])):
            frames[scr] = {"interval_ms": dist(e["gap"]),
                           "interval_after_switch_ms": dist(e["gap_switch"]),
                           "paint_ms": dist(e["paint"]), "compose_ms": dist(e["compose"]),
                           "composed_in": {"containing": e["containing"], "next": e["next"]}}
            allg += e["gap"]
        rec["frames"] = frames
        rec["frames_all_ai_screens_interval_ms"] = dist(allg)
        # --- data to glass on ROLL
        pv = {}
        for p in P:
            if a <= p[0] <= b + int(2e9):
                pv.setdefault(p[2], []).append(p)
        lat_glass, lat_paint, unseen, lat_by_screen = [], [], 0, {}
        ai_screens = {p[3] for p in P}
        for wt, v in W:
            if not a <= wt <= b:
                continue
            scr, s_t, _ = screen_at(wt)
            if scr not in ai_screens or wt - s_t < settle * 1e9:
                continue
            cands = [p for p in pv.get(v, ()) if wt <= p[0] < wt + int(2e9)]
            if not cands or screen_at(cands[0][0])[0] != scr:
                unseen += 1
                continue
            p = cands[0]
            lat_paint.append((p[0] + p[1] - wt) / 1e6)
            ue, _, _ = ur_end(p[0], p[1])
            if ue is not None:
                lat_glass.append((ue - wt) / 1e6)
                lat_by_screen.setdefault(scr, []).append((ue - wt) / 1e6)
        rec["roll_data_to_glass_ms"] = dist(lat_glass)
        rec["roll_data_to_paint_end_ms"] = dist(lat_paint)
        rec["roll_data_to_glass_by_screen_ms"] = {k: dist(v) for k, v in sorted(lat_by_screen.items())}
        rec["roll_writes_not_painted"] = unseen
        rec["roll_writes_timed_or_unpainted"] = len(lat_paint) + unseen
        # --- thermal
        th = [r for r in TH if a <= r["mono_ns"] <= b]
        if th:
            flags = set()
            for r in th:
                v = int(r["throttled"].split("=")[1], 16) if r.get("throttled") else 0
                flags |= {n for bit, n in THROTTLE_NOW.items() if v & (1 << bit)}
            hz = [r["arm_hz"] for r in th if r.get("arm_hz")]
            r0, r1 = th[0], th[-1]
            secs = (r1["mono_ns"] - r0["mono_ns"]) / 1e9
            tck = r0["clk_tck"]
            cpu = {}
            for pid in r0["pids"]:
                if r0["pids"][pid] is not None and r1["pids"].get(pid) is not None:
                    cpu[pid] = round(100.0 * (r1["pids"][pid] - r0["pids"][pid]) / tck / secs, 1)
            box = 100.0 * (1 - (r1["cpu_idle"] - r0["cpu_idle"]) / max(1, r1["cpu_total"] - r0["cpu_total"]))
            rec["thermal"] = {
                "soc_c": {"min": min(r["soc_c"] for r in th), "max": max(r["soc_c"] for r in th),
                          "mean": round(st.mean(r["soc_c"] for r in th), 1)},
                "nvme_c": {"min": min((r["nvme_c"] for r in th if r["nvme_c"] is not None),
                                      default=None),
                           "max": max((r["nvme_c"] for r in th if r["nvme_c"] is not None), default=None)},
                "arm_mhz": {"min": round(min(hz) / 1e6), "median": round(q(hz, .5) / 1e6),
                            "max": round(max(hz) / 1e6)} if hz else None,
                "arm_mhz_below_2400_pct": round(100.0 * sum(1 for h in hz if h < 2.39e9) / len(hz), 1) if hz else None,
                # The firmware capping the clock below what the kernel asked for
                # is a throttle; ondemand choosing a low clock at light load is not.
                "arm_below_kernel_request_pct": round(100.0 * sum(
                    1 for r in th if r.get("arm_hz") and r.get("kernel_cur_khz")
                    and r["arm_hz"] < 0.98 * int(r["kernel_cur_khz"]) * 1000) / len(th), 1),
                "throttle_now_seen": sorted(flags),
                "get_throttled_first": r0.get("throttled"), "get_throttled_last": r1.get("throttled"),
                "process_cpu_pct_of_one_core": cpu, "box_cpu_pct_of_all_cores": round(box, 1),
                "load_first": r0["load"], "load_last": r1["load"], "samples": len(th)}
        out["windows"][name] = rec
    # temperature curve, one point a minute, for the README
    curve = {}
    for r in TH:
        m = int((r["mono_ns"] - t0) / 6e10)
        if m >= 0:
            curve.setdefault(m, []).append(r["soc_c"])
    out["soc_c_per_minute"] = {k: round(st.mean(v), 1) for k, v in sorted(curve.items())}
    for lbl in ("start_idle", "start", "end"):
        p = os.path.join(d, "platform_%s.json" % lbl)
        if os.path.exists(p):
            out["platform_" + lbl] = json.load(open(p))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--window", type=float, default=600.0)
    ap.add_argument("--settle", type=float, default=2.0)
    ap.add_argument("--json")
    a = ap.parse_args()
    r = analyze(a.run, a.window, a.settle)
    s = json.dumps(r, indent=1, sort_keys=True)
    if a.json:
        open(a.json, "w").write(s + "\n")
    print(s)


if __name__ == "__main__":
    main()
