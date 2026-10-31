"""G12 (AER-4462, pyEfis #135): grab the live Beelink map tab with a plan
active, once per map_style (the caller flips the screen yaml and restarts
pyEfis between runs).

No sim needed (the G42 recipe, docs/images/fp8_bench/bench_scripts/
g42_dtk_mag.py): a static position is fed over netfix at 2 Hz on leg 1 of a
KSBA-GVO-RZS plan published as plain TF legs and activated with ``ACT 2``,
so the map shows a past waypoint, an active leg and a future leg. The
bench's own route block is snapshotted first and republished at the end.

The grab is pyEfis's own SIGUSR1 screenshot (/tmp/pyefis_screenshot.png),
which renders the Qt window fresh; the map is QPainter, so it is in the
grab (only the GL SVS panel is blank in it, as always on this box).

    python3 g12_glass.py <outdir> <label>     (run under the bench lock)
"""
import json
import os
import shutil
import subprocess
import sys
import threading
import time

from nfx import NFX

MAGVAR = -11.9          # positive west; the bench's last X-Plane value near KSBA
ROUTE = [               # (ID, lat, lon, FPLTYPE) from the bench's own navdata
    ("KSBA", 34.42619166, -119.84149277, 1),
    ("GVO", 34.53132016, -120.09108827, 2),
    ("RZS", 34.50953197, -119.77098813, 2),
]
POSE = (34.4612, -119.9247, 297.0 + MAGVAR)     # 1/3 along KSBA-GVO
SLOT = ("ID", "LAT", "LON", "TYPE", "PT", "CRS", "DST", "ALT", "SPD", "SGI",
        "FLAGS", "CTRLAT", "CTRLON", "TURN")
SEG = ("KIND", "ID", "ENT", "EXT", "FIRST", "LAST")
BLANK_SLOT = dict(ID="", LAT=0.0, LON=0.0, TYPE=0, PT="TF", CRS=0.0, DST=0.0, ALT="",
                  SPD=0, SGI=0, FLAGS=0, CTRLAT=0.0, CTRLON=0.0, TURN="")
BLANK_SEG = dict(KIND=0, ID="", ENT="", EXT="", FIRST=0, LAST=0)
KEYS = ["FPLSTATE", "FPLACTLEG", "WPFROM", "WPNAME", "LAT", "LONG", "TRACK", "FPLMSG"]
TAB_MAP = (1278, 12)    # 1920x1080 kiosk: right panel's "Map" tab
SHOT = "/tmp/pyefis_screenshot.png"

c = NFX()
stop = threading.Event()


def feeder():
    f = NFX()
    lat, lon, hdg = POSE
    while not stop.is_set():
        for k, v in (("MAGVAR", MAGVAR), ("GS", 110.0), ("HEAD", hdg % 360),
                     ("TRACK", hdg % 360), ("TRACKM", (hdg + MAGVAR) % 360),
                     ("ALT", 3500.0), ("LAT", lat), ("LONG", lon)):
            f.write(k, v)
        time.sleep(0.5)


def snapshot():
    count = int(float(c.read("FPLCOUNT")[0] or 0))
    segcnt = int(float(c.read("FPLSEGCNT")[0] or 0))
    snap = {"FPLCOUNT": count, "FPLSEGCNT": segcnt}
    for k in ("FPLNAME", "FPLAPRTYPE", "FPLDBCYC", "FPLSEQ", "FPLSTATE", "FPLACTLEG"):
        snap[k] = c.read(k)[0]
    snap["slots"] = [{f: c.read(f"FPL{i}{f}")[0] for f in SLOT} for i in range(1, count + 1)]
    snap["segs"] = [{f: c.read(f"FPLS{k}{f}")[0] for f in SEG} for k in range(1, segcnt + 1)]
    return snap


def publish(slots, segs, name, aprtype, cycle, width):
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


def act(slot):
    seq = max(int(float(c.read("FPLCMDACK")[0] or 0)), int(time.time()) % 1000000) + 1
    c.write("FPLCMD", f"{seq} ACT {slot}")
    time.sleep(1.0)
    return c.read("FPLCMDACK")[0], c.read("FPLMSG")[0]


def click(xy):
    subprocess.run(["xdotool", "mousemove", str(xy[0]), str(xy[1]), "click", "1"],
                   env=dict(os.environ, DISPLAY=":0"), check=False)


def grab(outdir, label):
    pid = subprocess.run(["pgrep", "-f", "pyefis-venv/bin/pyefis"], capture_output=True,
                         text=True).stdout.split()[0]
    before = os.path.getmtime(SHOT) if os.path.exists(SHOT) else 0
    subprocess.run(["kill", "-USR1", pid], check=True)
    for _ in range(50):
        time.sleep(0.2)
        if os.path.exists(SHOT) and os.path.getmtime(SHOT) > before:
            break
    time.sleep(0.5)
    shutil.copy(SHOT, f"{outdir}/glass_{label}.png")
    keys = {k: c.read(k) for k in KEYS}
    line = "%s %s pid=%s %s" % (time.strftime("%H:%M:%SZ", time.gmtime()), label, pid,
                                json.dumps(keys))
    print(line)
    with open(f"{outdir}/keys.log", "a") as fh:
        fh.write(line + "\n")


def main(outdir, label):
    os.makedirs(outdir, exist_ok=True)
    snap = snapshot()
    with open(f"{outdir}/snapshot_{label}.json", "w") as fh:
        json.dump(snap, fh, indent=1)
    width = max(snap["FPLCOUNT"], snap["FPLSEGCNT"], 3)
    t = threading.Thread(target=feeder, daemon=True)
    t.start()
    try:
        time.sleep(2)
        slots = [dict(BLANK_SLOT, ID=i, LAT=la, LON=lo, TYPE=ty, SGI=n)
                 for n, (i, la, lo, ty) in enumerate(ROUTE, start=1)]
        segs = [dict(BLANK_SEG, ENT=r[0], EXT=r[0], FIRST=n, LAST=n)
                for n, r in enumerate(ROUTE, start=1)]
        publish(slots, segs, "KSBA-RZS G12", "", "", width)
        time.sleep(2)
        print("ACT 2 ->", act(2))
        click(TAB_MAP)
        time.sleep(8)       # map layer workers render the new window
        grab(outdir, label)
        time.sleep(3)
        grab(outdir, label + "_2")      # settle check: should match the first
    finally:
        stop.set()
        t.join(2)
        publish(snap["slots"], snap["segs"], snap["FPLNAME"], snap["FPLAPRTYPE"],
                snap["FPLDBCYC"], width)
        time.sleep(2)
        if snap["FPLSTATE"] == "1" and int(float(snap["FPLACTLEG"] or 0)) > 0:
            print("re-ACT", snap["FPLACTLEG"], "->", act(int(float(snap["FPLACTLEG"]))))
        print("restored", snap["FPLNAME"], "count", c.read("FPLCOUNT")[0],
              "segcnt", c.read("FPLSEGCNT")[0], "msg", c.read("FPLMSG")[0])


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
