"""G42 (AER-4237, pyEfis #325): capture the FPL page beside the HSI with a
KSBA-GVO-RZS plan active, to show the FPL page's DTK column agrees with the
HSI's CRS (both magnetic).

No sim needed. With X-Plane idle on the bench, this script feeds a static
position over netfix (LAT/LONG/GS/MAGVAR/HEAD/TRACK at 2 Hz) on each leg in
turn, publishes the plan as plain TF legs (CRS derived, so the page has to
apply MAGVAR itself), opens the Flight Plan tab, and grabs the screen.

Before it publishes, it snapshots the bench's existing route block, and it
republishes that block and reopens the Map tab when it is done.

    python3 g42_dtk_mag.py <outdir>     (run under the bench lock)
"""
import json
import os
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
# A point on each leg, 1/3 of the way along, and the heading to fly there.
POSES = {
    "leg1": (34.4612, -119.9247, 297.0 + MAGVAR),
    "past_gvo": (34.5360, -120.1030, 297.0 + MAGVAR),   # beyond GVO: sequences leg 1
    "leg2": (34.5240, -119.9844, 95.0 + MAGVAR),
}
SLOT = ("ID", "LAT", "LON", "TYPE", "PT", "CRS", "DST", "ALT", "SPD", "SGI",
        "FLAGS", "CTRLAT", "CTRLON", "TURN")
SEG = ("KIND", "ID", "ENT", "EXT", "FIRST", "LAST")
BLANK_SLOT = dict(ID="", LAT=0.0, LON=0.0, TYPE=0, PT="TF", CRS=0.0, DST=0.0, ALT="",
                  SPD=0, SGI=0, FLAGS=0, CTRLAT=0.0, CTRLON=0.0, TURN="")
BLANK_SEG = dict(KIND=0, ID="", ENT="", EXT="", FIRST=0, LAST=0)
KEYS = ["FPLSTATE", "FPLACTLEG", "WPFROM", "WPNAME", "WPDIS", "FPLCRS", "COURSE",
        "NAVSRC", "GPSSRC", "MAGVAR", "LAT", "LONG", "FPLMSG"]
TAB_FPL = (1345, 12)    # 1920x1080 kiosk: right panel's "Flight Plan" tab
TAB_MAP = (1278, 12)

c = NFX()
pose = {"p": None}
stop = threading.Event()


def feeder():
    f = NFX()
    while not stop.is_set():
        p = pose["p"]
        if p:
            lat, lon, hdg = p
            for k, v in (("MAGVAR", MAGVAR), ("GS", 110.0), ("HEAD", hdg % 360),
                         ("TRACK", hdg % 360), ("LAT", lat), ("LONG", lon)):
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
    """Appendix C ``ACT <slot>``: fly the leg into *slot*."""
    seq = max(int(float(c.read("FPLCMDACK")[0] or 0)), int(time.time()) % 1000000) + 1
    c.write("FPLCMD", f"{seq} ACT {slot}")
    time.sleep(1.0)
    return c.read("FPLCMDACK")[0], c.read("FPLMSG")[0]


def click(xy):
    subprocess.run(["xdotool", "mousemove", str(xy[0]), str(xy[1]), "click", "1"],
                   env=dict(os.environ, DISPLAY=":0"), check=False)


def shot(outdir, name):
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "x11grab", "-i", ":0",
                    "-frames:v", "1", f"{outdir}/{name}.png"],
                   env=dict(os.environ, DISPLAY=":0"), check=True)
    keys = {k: c.read(k) for k in KEYS}
    line = "%s %s %s" % (time.strftime("%H:%M:%SZ", time.gmtime()), name, json.dumps(keys))
    print(line)
    with open(f"{outdir}/keys.log", "a") as fh:
        fh.write(line + "\n")


def main(outdir):
    os.makedirs(outdir, exist_ok=True)
    snap = snapshot()
    with open(f"{outdir}/snapshot.json", "w") as fh:
        json.dump(snap, fh, indent=1)
    width = max(snap["FPLCOUNT"], snap["FPLSEGCNT"], 3)
    t = threading.Thread(target=feeder, daemon=True)
    pose["p"] = POSES["leg1"]
    t.start()
    try:
        time.sleep(2)
        slots = []
        for i, (ident, lat, lon, typ) in enumerate(ROUTE, start=1):
            s = dict(BLANK_SLOT, ID=ident, LAT=lat, LON=lon, TYPE=typ, SGI=i)
            slots.append(s)
        # One waypoint segment per fix; the engine wants ENT/EXT = that fix's ID.
        segs = [dict(BLANK_SEG, ENT=r[0], EXT=r[0], FIRST=i, LAST=i)
                for i, r in enumerate(ROUTE, start=1)]
        publish(slots, segs, "KSBA-RZS G42", "", "", width)
        time.sleep(2)
        print("ACT 2 ->", act(2))
        time.sleep(3)
        click(TAB_FPL)
        time.sleep(3)
        shot(outdir, "g42_leg1_ksba_gvo")
        pose["p"] = POSES["past_gvo"]
        time.sleep(5)
        pose["p"] = POSES["leg2"]
        time.sleep(5)
        shot(outdir, "g42_leg2_gvo_rzs")
    finally:
        pose["p"] = None
        stop.set()
        t.join(2)
        # Restore the bench's plan as it was (values are the bus strings;
        # the server coerces them back to each key's type).
        publish(snap["slots"], snap["segs"], snap["FPLNAME"], snap["FPLAPRTYPE"],
                snap["FPLDBCYC"], width)
        time.sleep(2)
        if snap["FPLSTATE"] == "1" and int(float(snap["FPLACTLEG"] or 0)) > 0:
            print("re-ACT", snap["FPLACTLEG"], "->", act(int(float(snap["FPLACTLEG"]))))
        click(TAB_MAP)
        print("restored", snap["FPLNAME"], "count", c.read("FPLCOUNT")[0],
              "segcnt", c.read("FPLSEGCNT")[0], "msg", c.read("FPLMSG")[0])


if __name__ == "__main__":
    main(sys.argv[1])
