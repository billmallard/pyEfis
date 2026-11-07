"""Docs capture follower (AER-4904): in-flight pictures for the pyEfis wiki.

Runs ON the Beelink, detached. Waits until sim-bench session SID is the one
flying (/health), waits for the bench's standing RREF position (AER-4970) to be
live, then flies the pilot's part of the FP8 profile on the bench's flight-plan
engine: publishes the KSMX RNAV 30 via GVO route (pyEfis
docs/images/fp8_bench/bench_scripts/fp8_proc_route.py), ACT at PAMJI near the
air start, RESUME 5 s after the MAP auto-SUSP. It grabs the panel every 30 s,
3 s after each sequence, phase or state change, and once on the Flight Plan tab
in the hold (then back to Map).

It never changes config and never restarts fixgw or pyEfis. At the end it puts
the route block back to what it found (empty: FPLCOUNT 0) and NAVSRC/GPSSRC to
their found values. Markers: ARMED, DONE, NOT_FLOWN; every step in events.log.

    setsid nohup ~/pyefis-venv/bin/python docs_flight.py <SID> <BENCH_URL> > follow.out 2>&1 < /dev/null &

BENCH_URL is the sim-bench service's base URL, http://<host>:<port>.
"""
import calendar
import json
import math
import os
import subprocess
import sys
import time
import urllib.request

D = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, D)
from nfx import NFX  # noqa: E402

if len(sys.argv) != 3:
    sys.exit("usage: docs_flight.py <SID> <BENCH_URL>")
SID = sys.argv[1]
HEALTH = sys.argv[2].rstrip("/") + "/health"
LOCK = "/tmp/pyefis-bench.lock"
DEADLINE = calendar.timegm(time.strptime("2026-11-07 12:00", "%Y-%m-%d %H:%M"))  # 06:00 CST
PAMJI = (34.780069, -120.368208)
WINCH = (35.073481, -120.6628)
TAB_MAP, TAB_FPL = (1278, 13), (1345, 13)
KEYS = ["LAT", "LONG", "ALT", "GS", "HEAD", "TRACK", "NAVSRC", "GPSSRC", "FPLSTATE", "FPLACTLEG",
        "FPLPHASE", "FPLAPR", "CDISCALE", "WPFROM", "WPNAME", "WPDIS", "FPLCRS", "FPLXTK", "FPLCDI",
        "FPLTF", "COURSE", "CDI", "TOFROM", "FPLMSG"]
SLOT_F = ("ID", "LAT", "LON", "TYPE", "PT", "CRS", "DST", "ALT", "SPD", "SGI", "FLAGS", "CTRLAT", "CTRLON", "TURN")
SEG_F = ("KIND", "ID", "ENT", "EXT", "FIRST", "LAST")
os.makedirs(os.path.join(D, "shots"), exist_ok=True)
c = NFX()


def utc():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def log(*a):
    line = utc() + " " + " ".join(str(x) for x in a)
    with open(os.path.join(D, "events.log"), "a") as f:
        f.write(line + "\n")
    print(line, flush=True)


def mark(name, body=""):
    with open(os.path.join(D, name), "w") as f:
        f.write(utc() + " " + body + "\n")


def keys():
    return {k: c.read(k)[0] for k in KEYS}


def grab(name):
    p = os.path.join(D, "shots", "%s_%s.png" % (time.strftime("%H%M%S", time.gmtime()), name))
    r = subprocess.run(["flock", "-w", "30", LOCK, "sh", "-c",
                        "DISPLAY=:0 ffmpeg -loglevel error -y -f x11grab -draw_mouse 0 "
                        "-video_size 1920x1080 -i :0 -frames:v 1 " + p],
                       capture_output=True, text=True, timeout=90)
    with open(os.path.join(D, "shots", "keys.jsonl"), "a") as f:
        f.write(json.dumps({"t": utc(), "file": os.path.basename(p), "rc": r.returncode, "keys": keys()}) + "\n")
    if r.returncode:
        log("grab failed", name, r.returncode, (r.stdout + r.stderr)[-200:])


def tap(xy):
    subprocess.run(["sh", "-c", "DISPLAY=:0 xdotool mousemove %d %d click 1; sleep 0.3; "
                    "DISPLAY=:0 xdotool mousemove 1919 1079" % xy], timeout=20)


def flying():
    """-> True (ours), False (not ours / gone), None (health unreachable)."""
    try:
        h = json.load(urllib.request.urlopen(HEALTH, timeout=8))
    except Exception:
        return None
    return (h.get("flying") or {}).get("id") == SID, h


def nm(a, b):
    return math.hypot((a[0] - b[0]) * 60, (a[1] - b[1]) * 60 * math.cos(math.radians(a[0])))


def pos():
    la, fl = c.read("LAT")
    lo, _ = c.read("LONG")
    try:
        return (float(la), float(lo)) if fl[1:2] == "0" else None
    except ValueError:
        return None


def fplcmd(verb):
    ack = abs(int(float(c.read("FPLCMDACK")[0] or 0)))
    c.write("FPLCMD", "%d %s" % (ack + 1, verb))
    time.sleep(1.0)
    log("FPLCMD", verb, "ack", c.read("FPLCMDACK")[0], "msg", c.read("FPLMSG")[0],
        "state", c.read("FPLSTATE")[0], "leg", c.read("FPLACTLEG")[0], "wp", c.read("WPNAME")[0])


def found_state():
    return {"NAVSRC": c.read("NAVSRC")[0], "GPSSRC": c.read("GPSSRC")[0],
            "FPLCOUNT": c.read("FPLCOUNT")[0], "FPLSEGCNT": c.read("FPLSEGCNT")[0],
            "FPLNAME": c.read("FPLNAME")[0], "FPLDBCYC": c.read("FPLDBCYC")[0]}


def restore(found, ours_count, ours_segs):
    # The route was empty when armed (checked before publishing): clear our slots,
    # then commit an empty block. Any FPLSEQ change drops the activation.
    for i in range(1, ours_count + 1):
        for f in SLOT_F:
            c.write("FPL%d%s" % (i, f), "" if f in ("ID", "PT", "ALT", "TURN") else 0)
    for k in range(1, ours_segs + 1):
        for f in SEG_F:
            c.write("FPLS%d%s" % (k, f), "" if f in ("ID", "ENT", "EXT") else 0)
    c.write("FPLSEGCNT", 0)
    c.write("FPLCOUNT", 0)
    c.write("FPLNAME", found["FPLNAME"])
    c.write("FPLDBCYC", found["FPLDBCYC"])
    c.write("FPLSEQ", int(float(c.read("FPLSEQ")[0] or 0)) + 1)
    time.sleep(1.5)
    c.write("NAVSRC", int(float(found["NAVSRC"] or 2)))
    c.write("GPSSRC", int(float(found["GPSSRC"] or 0)))
    tap(TAB_MAP)
    time.sleep(1)
    log("restored", found_state(), "FPLSTATE", c.read("FPLSTATE")[0])


def main():
    log("armed, waiting for", SID)
    mark("ARMED", SID)
    while True:
        r = flying()
        if r and r[0]:
            break
        if r and not r[0]:
            h = r[1]
            if SID not in json.dumps(h.get("queue") or []):
                log("not flying and not queued", json.dumps(h)[:600])
                mark("NOT_FLOWN", json.dumps(h)[:600])
                return
        if time.time() > DEADLINE:
            log("past deadline")
            mark("NOT_FLOWN", "deadline")
            return
        time.sleep(15)
    log("session flying")
    found = found_state()
    log("found", found)
    if found["FPLCOUNT"] not in ("0", "0.0"):
        log("route block not empty; publishing nothing, grabbing only")
        found = None
    t0 = time.time()
    while pos() is None:
        if time.time() - t0 > 300:
            log("no live position after 5 min; standing RREF block did not drive the bus")
            grab("no_position")
            mark("DONE", "no position")
            return
        time.sleep(2)
    log("position live", pos())
    grab("position_live")
    ours = (0, 0)
    if found:
        r = subprocess.run("cd %s && ~/pyefis-venv/bin/python fp8_proc_route.py publish" % D, shell=True,
                           capture_output=True, text=True, timeout=120)
        log("publish rc", r.returncode, (r.stdout + r.stderr).strip()[-800:])
        ours = (int(float(c.read("FPLCOUNT")[0] or 0)), int(float(c.read("FPLSEGCNT")[0] or 0)))
        act = subprocess.run("cd %s && ~/pyefis-venv/bin/python fp8_proc_route.py actslot" % D, shell=True,
                             capture_output=True, text=True, timeout=60).stdout.strip()
        t1 = time.time()
        while True:
            p = pos()
            if p and nm(p, PAMJI) < 6.0:
                break
            if time.time() - t1 > 240:
                log("aircraft not near PAMJI after 4 min; activating anyway", p)
                break
            time.sleep(2)
        fplcmd("ACT %s" % act)
        time.sleep(2)
        grab("activated")
    last = {}
    t_last_grab = time.time()
    t_hold = None
    done = set()
    t_health = 0
    try:
        while True:
            now = time.time()
            if now - t_health > 20:
                t_health = now
                r = flying()
                if r is not None and not r[0]:
                    log("session no longer flying")
                    break
            if now - t0 > 50 * 60:
                log("50 min safety stop")
                break
            k = {x: c.read(x)[0] for x in ("FPLACTLEG", "FPLPHASE", "FPLSTATE", "FPLAPR", "WPNAME", "TOFROM", "NAVSRC")}
            if any(v.startswith("ERR") for v in k.values()):
                time.sleep(1)
                continue
            changed = [x for x in k if last and k[x] != last.get(x)]
            if changed:
                log("change", {x: (last.get(x), k[x]) for x in changed})
                time.sleep(3)
                grab("chg_" + "_".join(changed) + "_" + k["WPNAME"])
                t_last_grab = time.time()
                if "FPLSTATE" in changed and k["FPLSTATE"] == "3" and "map" not in done:
                    done.add("map")
                    time.sleep(2)
                    fplcmd("RESUME")
                    time.sleep(3)
                    grab("resume_missed")
            p = pos()
            if t_hold is None and k["WPNAME"] == "WINCH" and p and nm(p, WINCH) < 1.0:
                t_hold = time.time()
                log("at WINCH")
            if t_hold and "fpltab" not in done and time.time() - t_hold > 90:
                done.add("fpltab")
                tap(TAB_FPL)
                time.sleep(3)
                grab("hold_fpl_tab")
                time.sleep(5)
                grab("hold_fpl_tab_2")
                tap(TAB_MAP)
                time.sleep(2)
                grab("hold_map_back")
            if time.time() - t_last_grab >= 30:
                grab("tick")
                t_last_grab = time.time()
            last = k
            time.sleep(1)
    finally:
        grab("end")
        if found:
            restore(found, *ours)
        mark("DONE")
        log("done")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        log("CRASH", repr(e), traceback.format_exc().replace("\n", " | "))
        raise
