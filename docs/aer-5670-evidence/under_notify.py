"""under_notify.py <speedscope.json>: on the thread with the most samples
(the GUI thread), the share of wall samples inside FixBridge._notify, and
what is under it (the frame after _notify and the leaf)."""
import collections, json, os, sys
DEPTH = int(os.environ.get("DEPTH", "4"))
d = json.load(open(sys.argv[1]))
frames = d["shared"]["frames"]
def name(i):
    f = frames[i]; return "%s (%s)" % (f["name"], f.get("file", "").split("/src/")[-1])
prof = max(d["profiles"], key=lambda p: len(p["samples"]))
tot = len(prof["samples"]); inside = 0
child = collections.Counter(); leaf = collections.Counter()
for st in prof["samples"]:
    names = [frames[i]["name"] for i in st]
    files = [frames[i].get("file", "") for i in st]
    idx = [k for k, (n, f) in enumerate(zip(names, files)) if n == "_notify" and f.endswith("flightplan/fixbridge.py")]
    if not idx:
        continue
    inside += 1
    k = idx[0]
    path = " > ".join(name(i) for i in st[k + 1:k + DEPTH]) or "(self)"
    child[path] += 1; leaf[name(st[-1])] += 1
print("GUI thread samples %d, inside _notify %d = %.2f%%" % (tot, inside, 100.0 * inside / tot))
print("-- under _notify (next 3 frames)")
for k, v in child.most_common(15): print("%5d %5.2f%%  %s" % (v, 100.0 * v / tot, k))
print("-- leaves")
for k, v in leaf.most_common(12): print("%5d %5.2f%%  %s" % (v, 100.0 * v / tot, k))
