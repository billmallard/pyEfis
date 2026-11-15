"""PA15 (AER-2087) bench driver: put a route longer than the FPL pane on the
bus, and drive the Flight Plan tab with real X11 pointer input (xdotool), so
the list scrolls through the same mouse path a touchscreen synthesises.

No sim needed (see g42_dtk_mag.py in ../../fp8_bench/bench_scripts). Run each
step under the bench lock, from the bench, with nfx.py beside it:

    python3 pa15_bench.py snapshot <dir>      save the bench's route block
    python3 pa15_bench.py publish <dir> [n]   publish an n-fix route (default 24)
    python3 pa15_bench.py act <slot>          FPLCMD ACT <slot>
    python3 pa15_bench.py feed <seconds>      feed a static position (foreground)
    python3 pa15_bench.py restore <dir>       republish the snapshot (re-ACT)
    python3 pa15_bench.py shot <dir> <name>   x11grab the whole screen
    python3 pa15_bench.py click <x> <y>
    python3 pa15_bench.py drag <x> <y0> <y1> <steps> <step_s> <pause_s>
        press at (x, y0), move to y1 in <steps> moves <step_s> apart, wait
        <pause_s> with the button down, release (pause 0 = a fling)
"""
import json
import os
import subprocess
import sys
import time

from nfx import NFX

SLOT = ("ID", "LAT", "LON", "TYPE", "PT", "CRS", "DST", "ALT", "SPD", "SGI",
        "FLAGS", "CTRLAT", "CTRLON", "TURN")
SEG = ("KIND", "ID", "ENT", "EXT", "FIRST", "LAST")
BLANK_SLOT = dict(ID="", LAT=0.0, LON=0.0, TYPE=0, PT="TF", CRS=0.0, DST=0.0, ALT="",
                  SPD=0, SGI=0, FLAGS=0, CTRLAT=0.0, CTRLON=0.0, TURN="")
BLANK_SEG = dict(KIND=0, ID="", ENT="", EXT="", FIRST=0, LAST=0)
ENV = dict(os.environ, DISPLAY=":0")
MAGVAR = -11.9
POSE = (34.46, -119.92, 300.0 + MAGVAR)     # near KSBA, on the first leg

c = NFX()


def route(n):
    """KSBA then n-1 fixes stepping up the coast, 8-10 NM apart."""
    pts = [("KSBA", 34.42619166, -119.84149277, 1)]
    for i in range(1, n):
        lat = 34.43 + 0.13 * i
        lon = -119.95 - 0.05 * i - (0.04 if i % 2 else 0.0)
        pts.append((f"PA{i:03d}", round(lat, 5), round(lon, 5), 4))
    return pts


def snapshot(outdir):
    count = int(float(c.read("FPLCOUNT")[0] or 0))
    segcnt = int(float(c.read("FPLSEGCNT")[0] or 0))
    snap = {"FPLCOUNT": count, "FPLSEGCNT": segcnt}
    for k in ("FPLNAME", "FPLAPRTYPE", "FPLDBCYC", "FPLSEQ", "FPLSTATE", "FPLACTLEG"):
        snap[k] = c.read(k)[0]
    snap["slots"] = [{f: c.read(f"FPL{i}{f}")[0] for f in SLOT} for i in range(1, count + 1)]
    snap["segs"] = [{f: c.read(f"FPLS{k}{f}")[0] for f in SEG} for k in range(1, segcnt + 1)]
    os.makedirs(outdir, exist_ok=True)
    path = f"{outdir}/snapshot.json"
    if os.path.exists(path):
        sys.exit("refusing to overwrite an existing snapshot: " + path)
    with open(path, "w") as fh:
        json.dump(snap, fh, indent=1)
    print("snapshot", snap["FPLNAME"], "count", count, "segcnt", segcnt,
          "state", snap["FPLSTATE"], "actleg", snap["FPLACTLEG"])


def publish_block(slots, segs, name, aprtype, cycle, width):
    for i in range(1, max(len(slots), width) + 1):
        s = slots[i - 1] if i <= len(slots) else BLANK_SLOT
        for f in SLOT:
            c.write(f"FPL{i}{f}", s[f])
    for k in range(1, max(len(segs), width) + 1):
        s = segs[k - 1] if k <= len(segs) else BLANK_SEG
        for f in SEG:
            c.write(f"FPLS{k}{f}", s[f])
    seq = int(float(c.read("FPLSEQ")[0] or 0)) + 1
    for k, v in (("FPLSEGCNT", len(segs)), ("FPLCOUNT", len(slots)), ("FPLNAME", name),
                 ("FPLAPRTYPE", aprtype), ("FPLDBCYC", cycle), ("FPLSEQ", seq)):
        c.write(k, v)


def width_for(outdir, n):
    with open(f"{outdir}/snapshot.json") as fh:
        snap = json.load(fh)
    return snap, max(snap["FPLCOUNT"], snap["FPLSEGCNT"], n)


def publish(outdir, n):
    _snap, width = width_for(outdir, n)
    pts = route(n)
    slots = [dict(BLANK_SLOT, ID=p[0], LAT=p[1], LON=p[2], TYPE=p[3], SGI=i)
             for i, p in enumerate(pts, start=1)]
    segs = [dict(BLANK_SEG, ENT=p[0], EXT=p[0], FIRST=i, LAST=i)
            for i, p in enumerate(pts, start=1)]
    publish_block(slots, segs, f"PA15 {n} FIXES", "", "", width)
    time.sleep(1.5)
    print("published", c.read("FPLNAME")[0], "count", c.read("FPLCOUNT")[0],
          "msg", c.read("FPLMSG")[0])


def act(slot):
    seq = max(int(float(c.read("FPLCMDACK")[0] or 0)), int(time.time()) % 1000000) + 1
    c.write("FPLCMD", f"{seq} ACT {slot}")
    time.sleep(1.0)
    print("ACT", slot, "ack", c.read("FPLCMDACK")[0], "msg", c.read("FPLMSG")[0],
          "state", c.read("FPLSTATE")[0], "actleg", c.read("FPLACTLEG")[0])


def feed(seconds):
    lat, lon, hdg = POSE
    end = time.time() + seconds
    while time.time() < end:
        for k, v in (("MAGVAR", MAGVAR), ("GS", 110.0), ("HEAD", hdg % 360),
                     ("TRACK", hdg % 360), ("LAT", lat), ("LONG", lon)):
            c.write(k, v)
        time.sleep(0.2)


def restore(outdir):
    snap, width = width_for(outdir, 24)
    publish_block(snap["slots"], snap["segs"], snap["FPLNAME"], snap["FPLAPRTYPE"],
                  snap["FPLDBCYC"], width)
    time.sleep(2)
    if snap["FPLSTATE"] == "1" and int(float(snap["FPLACTLEG"] or 0)) > 0:
        act(int(float(snap["FPLACTLEG"])))
    print("restored", c.read("FPLNAME")[0], "count", c.read("FPLCOUNT")[0],
          "segcnt", c.read("FPLSEGCNT")[0], "state", c.read("FPLSTATE")[0],
          "actleg", c.read("FPLACTLEG")[0])


def shot(outdir, name):
    os.makedirs(outdir, exist_ok=True)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "x11grab", "-i", ":0",
                    "-frames:v", "1", f"{outdir}/{name}.png"], env=ENV, check=True)
    print("shot", name, time.strftime("%H:%M:%SZ", time.gmtime()))


def xdo(*args):
    subprocess.run(["xdotool", *map(str, args)], env=ENV, check=True)


def drag(x, y0, y1, steps, step_s, pause_s):
    xdo("mousemove", x, y0)
    time.sleep(0.1)
    xdo("mousedown", 1)
    for k in range(1, steps + 1):
        time.sleep(step_s)
        xdo("mousemove", x, round(y0 + (y1 - y0) * k / steps))
    time.sleep(pause_s)
    xdo("mouseup", 1)


if __name__ == "__main__":
    cmd, a = sys.argv[1], sys.argv[2:]
    if cmd == "snapshot":
        snapshot(a[0])
    elif cmd == "publish":
        publish(a[0], int(a[1]) if len(a) > 1 else 24)
    elif cmd == "act":
        act(int(a[0]))
    elif cmd == "feed":
        feed(float(a[0]))
    elif cmd == "restore":
        restore(a[0])
    elif cmd == "shot":
        shot(a[0], a[1])
    elif cmd == "click":
        xdo("mousemove", a[0], a[1], "click", 1)
    elif cmd == "drag":
        drag(int(a[0]), int(a[1]), int(a[2]), int(a[3]), float(a[4]), float(a[5]))
    else:
        sys.exit(__doc__)
