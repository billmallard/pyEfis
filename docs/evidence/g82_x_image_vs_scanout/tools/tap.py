"""Tap a flight_plan target by callback-name substring (or 'xy:X,Y'), using
the probe's latest fp_targets record. Logs the send time. argv: name [dump]"""
import json, subprocess, sys, time, os
def targets():
    t = None
    for l in open("/tmp/g79_probe.log"):
        if '"fp_targets"' in l:
            t = json.loads(l)
    return t
def tap(name, log=None):
    t = targets()
    if name.startswith("xy:"):
        gx, gy = map(int, name[3:].split(","))
    else:
        hits = [x for x in t["t"] if name in x[4]]
        if not hits:
            raise SystemExit("no target %r on page %s: %s" % (name, t["page"], sorted({x[4] for x in t["t"]})))
        x, y, w, h, _ = hits[0]
        gx, gy = t["ox"] + x + w // 2, t["oy"] + y + h // 2
    env = dict(os.environ, DISPLAY=":0")
    subprocess.run(["xdotool", "mousemove", str(gx), str(gy)], env=env, check=True)
    time.sleep(0.05)
    ts = time.time()
    subprocess.run(["xdotool", "click", "1"], env=env, check=True)
    rec = {"k": "send", "w": round(ts, 4), "name": name, "gx": gx, "gy": gy, "page": t["page"]}
    if log:
        log.write(json.dumps(rec) + "\n"); log.flush()
    return rec
if __name__ == "__main__":
    print(tap(sys.argv[1]))
    if len(sys.argv) > 2:
        time.sleep(1.5)
        t = targets(); print(t["page"], repr(t["msg"]))
        for x in t["t"]: print(x)
