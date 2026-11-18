import json, sys, collections
d = json.load(open(sys.argv[1])); F = d["shared"]["frames"]; DT = 4.0
def fid(name, part): return {i for i, f in enumerate(F) if f["name"] == name and part in (f.get("file") or "")}
CATS = [("notify", fid("_notify", "flightplan/fixbridge.py")),
        ("map_paint", fid("paintEvent", "instruments/map/__init__.py")),
        ("ai_paint", fid("paintEvent", "ai/ai_widget.py")),
        ("ai_tick", fid("_frame_tick", "ai/ai_widget.py")),
        ("hsi_paint", fid("paintEvent", "instruments/hsi/__init__.py")),
        ("fpl_paint", fid("paintEvent", "instruments/flight_plan/__init__.py"))]
main_ids = fid("main", "pyefis/main.py")
prof = max((p for p in d["profiles"] if "MainThread" in p["name"]), key=lambda p: len(p["samples"]))
S = prof["samples"]; N = len(S); secs = N * DT / 1000
seq = []
for s in S:
    c = "idle_or_qt" if (not s or s[-1] in main_ids) else "other_py"
    for name, ids in CATS:
        if any(f in ids for f in s): c = name; break
    seq.append(c)
cnt = collections.Counter(seq)
print(f"main thread: {N} samples = {secs:.1f}s timeline")
for k, v in cnt.most_common(): print(f"  {k:11s} {100*v/N:5.1f}%  ({v*DT/secs:6.1f} ms per second)")
def runs(cat):
    out = []; i = 0
    while i < N:
        if seq[i] == cat:
            j = i
            while j < N and seq[j] == cat: j += 1
            out.append((i, j - i)); i = j
        else: i += 1
    return out
for cat in ("ai_paint", "map_paint", "hsi_paint", "fpl_paint", "notify"):
    r = runs(cat)
    if not r: print(f"{cat}: none"); continue
    starts = [i * DT for i, _ in r]; gaps = sorted(b - a for a, b in zip(starts, starts[1:])); lens = sorted(l * DT for _, l in r)
    q = lambda a, p: a[min(len(a) - 1, int(p * len(a)))]
    print(f"{cat:10s} {len(r)/secs:5.1f}/s  dur ms med={q(lens,.5):.0f} p90={q(lens,.9):.0f} max={lens[-1]:.0f} | start-to-start ms med={q(gaps,.5):.0f} p90={q(gaps,.9):.0f} max={gaps[-1]:.0f}")
# longest stretches with the GUI thread not in the event loop
busy = []; i = 0
while i < N:
    if seq[i] != "idle_or_qt":
        j = i
        while j < N and seq[j] != "idle_or_qt": j += 1
        busy.append(((j - i) * DT, i)); i = j
    else: i += 1
busy.sort(reverse=True)
print("longest uninterrupted python stretches on the GUI thread (ms): ", [int(b) for b, _ in busy[:12]])
print("stretches >=50ms per second:", sum(1 for b, _ in busy if b >= 50) / secs, " >=33ms:", sum(1 for b, _ in busy if b >= 33) / secs)
for b, i in busy[:3]:
    print(f"  {int(b)}ms stretch composition:", dict(collections.Counter(seq[i:i + int(b / DT)])))
# what follows each ai_paint: was the GUI thread idle between consecutive ai paints?
r = runs("ai_paint"); idle_between = []
for (a, la), (b, _) in zip(r, r[1:]):
    seg = seq[a + la:b]; idle_between.append(100 * seg.count("idle_or_qt") / max(1, len(seg)))
idle_between.sort()
print(f"between consecutive SVS paints the GUI thread is idle/in-Qt: median {idle_between[len(idle_between)//2]:.0f}% of the gap")
