"""FP8 session 2 orchestrator (AER-809). Runs unattended on the Beelink:
waits for the sim bench to start session SID, arms the bench (RREF feed,
recorder, logger, procedure route), activates the plan at the profile's start
fix, then drives the bench-side checks off the engine's own state:

  LNAV          -> GPSSRC 0/1/0 swap with screenshots (the A/B itself is in the log)
  1 nm from FAF -> ramp screenshot
  MAP auto-SUSP -> screenshots, RESUME 8 s later (TERM scale, guidance to HANNU)
  missed +30 s  -> fixgw restart #1: does the active leg survive?
  1 nm to HANNU -> SUSP; 0.3 nm past -> screenshots (no sequence, FROM), RESUME
  in the hold   -> SCALE 0.3 / AUTO, GPS_ACCURACY_HORIZ write (LOI attempt),
                   pyEfis restart #2
  session over  -> flags reverted, artifacts tarred, DONE marker

Never touches X-Plane. Every action is logged to events.log with a UTC stamp.
"""
import calendar
import json
import math
import os
import subprocess
import time
import urllib.request

from nfx import NFX

SID = "bb8dad527936"
D = os.path.expanduser("~/bench-scratch/aer809")
OUT = os.path.join(D, "s2")
HEALTH = "http://10.110.10.167:8770/health"
DEADLINE = calendar.timegm(time.strptime("2026-10-29 12:00", "%Y-%m-%d %H:%M"))  # UTC; window ends 11:00Z
FIX = json.load(open(os.path.join(D, "fixes.json")))
os.makedirs(OUT, exist_ok=True)
os.makedirs(os.path.join(D, "shots"), exist_ok=True)


def log(*a):
    line = time.strftime("%Y-%m-%dT%H:%M:%SZ ", time.gmtime()) + " ".join(str(x) for x in a)
    with open(os.path.join(OUT, "events.log"), "a") as f:
        f.write(line + "\n")
    print(line, flush=True)


def sh(cmd, timeout=400):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    log("sh:", cmd, "rc=%d" % r.returncode, (r.stdout + r.stderr).strip().replace("\n", " | ")[-600:])
    return r


def shot(name):
    sh("sh %s/shot.sh s2_%s" % (D, name), timeout=60)


def health():
    try:
        return json.load(urllib.request.urlopen(HEALTH, timeout=8))
    except Exception as e:
        return {"error": str(e)}


_NFX = NFX()
_xp_seen = [0.0]


def in_window():
    # The driver flies 23:00-06:00 America/Chicago only (processes/sim_bench.md).
    from datetime import datetime
    from zoneinfo import ZoneInfo
    hh = datetime.now(ZoneInfo("America/Chicago")).hour
    return hh >= 23 or hh < 6


def xp_live():
    # X-Plane's own RREF data on this bus: HEADBUG is always subscribed, LAT in the session block.
    for k in ("HEADBUG", "LAT"):
        try:
            if _NFX.read(k)[1][1:2] == "0":
                _xp_seen[0] = time.time()
                return True
        except Exception:
            pass
    return False


def ours_flying(h):
    # AER-4111: the driver's firewall admits the QNAP only, so /health is
    # unreachable from this box. Fall back on X-Plane itself: the service
    # launches X-Plane per session and quits it after, so inside the flying
    # window "X-Plane is feeding this bus" is our session (position 1 in the
    # FIFO). Ended = no X-Plane data for 60 s (rides out a fixgw restart).
    if not h.get("error"):
        return SID in json.dumps(h.get("flying") or "")
    if xp_live():
        return in_window()
    return _xp_seen[0] > 0 and time.time() - _xp_seen[0] < 60


def nm(a, b):
    return math.hypot((a[0] - b[0]) * 60, (a[1] - b[1]) * 60 * math.cos(math.radians(a[0])))


def main():
    log("armed, waiting for", SID)
    last = None
    gone = 0
    while True:
        h = health()
        s = json.dumps({k: h.get(k) for k in ("flying", "queue", "in_window_now", "hands_off", "xplane_running", "error")})
        if s != last:
            log("health", s[:900])
            last = s
        if ours_flying(h):
            break
        gone = gone + 1 if (not h.get("error") and not h.get("flying")
                            and SID not in json.dumps(h.get("queue") or "")) else 0
        if time.time() > DEADLINE or gone >= 3:
            log("session not flying and not queued (or past deadline); giving up")
            open(os.path.join(OUT, "NOT_FLOWN"), "w").write(s)
            return
        time.sleep(15)

    log("session flying -> arming bench")
    open(os.path.join(OUT, "ARMED"), "w").write(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    sh("sh %s/session2.sh flags-on" % D)
    sh("sh %s/session2.sh logger s2" % D)
    c = NFX()
    sh("cd %s && ~/pyefis-venv/bin/python fp8_proc_route.py publish" % D, timeout=120)
    act = sh("cd %s && ~/pyefis-venv/bin/python fp8_proc_route.py actslot" % D, timeout=60).stdout.strip()

    # Activate once X-Plane's position is live and near the air start.
    pamji = FIX["PAMJI"]
    t0 = time.time()
    while True:
        la, fl = c.read("LAT")
        lo, _ = c.read("LONG")
        try:
            p = (float(la), float(lo))
            near = nm(p, pamji) < 6.0 and fl[1:2] == "0"  # flags a,o,b,f,s: o = old
        except ValueError:
            near = False
        if near:
            break
        if not ours_flying(health()) and time.time() - t0 > 120:
            log("session ended before the aircraft reached the start; stopping")
            return finish(c)
        time.sleep(2)
    ack = int(float(c.read("FPLCMDACK")[0] or 0))
    c.write("FPLCMD", "%d ACT %s" % (ack + 100, act))
    time.sleep(1.5)
    log("ACT", act, {k: c.read(k)[0] for k in ("FPLCMDACK", "FPLMSG", "FPLSTATE", "FPLACTLEG", "WPNAME", "FPLPHASE", "FPLAPR", "CDISCALE")})
    shot("activated")

    st = {"leg": None, "phase": None, "state": None, "apr": None}
    done = set()
    t_resume = t_hold = t_susp_hannu = None
    cs = ack + 200
    last_health = 0
    hannu = FIX["HANNU"]

    def cmd(c_, verb):
        nonlocal cs
        cs += 1
        c_.write("FPLCMD", "%d %s" % (cs, verb))
        time.sleep(1.0)
        log("FPLCMD", verb, "ack", c_.read("FPLCMDACK")[0], "msg", c_.read("FPLMSG")[0],
            "state", c_.read("FPLSTATE")[0], "leg", c_.read("FPLACTLEG")[0], "wp", c_.read("WPNAME")[0])

    while True:
        now = time.time()
        if now - last_health > 20:
            last_health = now
            if not ours_flying(health()):
                log("session no longer flying")
                break
        if now - t0 > 75 * 60:
            log("75 min safety stop")
            break
        r = {k: c.read(k)[0] for k in ("FPLACTLEG", "FPLPHASE", "FPLSTATE", "FPLAPR", "WPNAME", "WPDIS", "LAT", "LONG", "FPLTF")}
        leg, phase, state, apr = r["FPLACTLEG"], r["FPLPHASE"], r["FPLSTATE"], r["FPLAPR"]
        if leg.startswith("ERR"):
            time.sleep(1)
            continue
        if leg != st["leg"] and st["leg"] is not None:
            log("sequence", st["leg"], "->", leg, r["WPNAME"])
            shot("seq_leg%s_%s" % (leg, r["WPNAME"]))
        if phase != st["phase"]:
            log("phase", st["phase"], "->", phase, "apr", apr)
        if phase == "LNAV" and "ab" not in done:
            done.add("ab")
            shot("lnav_gpssrc0")
            c.write("GPSSRC", 1)
            time.sleep(3)
            shot("lnav_gpssrc1")
            time.sleep(10)
            shot("lnav_gpssrc1_t13")
            c.write("GPSSRC", 0)
            time.sleep(1)
            log("GPSSRC A/B done, back to", c.read("GPSSRC")[0])
        try:
            pos = (float(r["LAT"]), float(r["LONG"]))
        except ValueError:
            pos = None
        if r["WPNAME"] == "CIMSO" and "ramp1" not in done and r["WPDIS"] not in ("", None):
            try:
                if float(r["WPDIS"]) <= 1.0:
                    done.add("ramp1")
                    shot("ramp_1nm_from_faf")
            except ValueError:
                pass
        if state == "3" and st["state"] != "3" and "map" not in done:
            done.add("map")
            log("auto-SUSP", r)
            shot("susp_at_map")
            time.sleep(4)
            shot("susp_at_map_plus4s")
            time.sleep(4)
            cmd(c, "RESUME")
            t_resume = time.time()
            time.sleep(2)
            shot("resume_missed")
        if t_resume and "rst1" not in done:  # run 2: skipped -- restart #1 verdict already FAIL (plan lost with live position)
            done.add("rst1")
            log("fixgw restart #1 skipped on run 2")
        if False:
            done.add("rst1")
            pre = {k: c.read(k)[0] for k in ("FPLACTLEG", "WPNAME", "FPLAPR", "FPLPHASE", "CDISCALE", "FPLCOUNT")}
            log("fixgw restart #1, before", pre)
            sh("flock -w 120 /tmp/pyefis-bench.lock sudo -n systemctl restart fixgw; sleep 8; systemctl is-active fixgw", timeout=200)
            for _ in range(30):
                if c.read("LAT")[1][1:2] == "0" and not c.read("FPLACTLEG")[0].startswith("ERR"):
                    break
                time.sleep(1)
            post = {k: c.read(k)[0] for k in ("FPLACTLEG", "WPNAME", "FPLAPR", "FPLPHASE", "CDISCALE", "FPLCOUNT", "FPLSTATE")}
            log("fixgw restart #1, after", post)
            shot("after_fixgw_restart")
            continue
        if "rst1" in done and r["WPNAME"] == "HANNU" and pos and "susp_h" not in done and nm(pos, hannu) < 1.0:
            done.add("susp_h")
            cmd(c, "SUSP")
            t_susp_hannu = time.time()
            shot("susp_before_hannu")
        if t_susp_hannu and "susp_h_past" not in done and pos and (
                r["FPLTF"] == "2" or (nm(pos, hannu) > 0.3 and time.time() - t_susp_hannu > 25)):
            done.add("susp_h_past")
            time.sleep(3)
            log("past HANNU while SUSP", {k: c.read(k)[0] for k in ("FPLSTATE", "FPLACTLEG", "WPNAME", "FPLTF", "WPDIS")})
            shot("susp_past_hannu")
            cmd(c, "RESUME")
            shot("resume_after_hannu")
        if r["WPNAME"] == "WINCH" and t_hold is None and pos and nm(pos, FIX["WINCH"]) < 1.0:
            t_hold = time.time()
            log("at WINCH", r)
        if t_hold and "scale" not in done and time.time() - t_hold > 60:
            done.add("scale")
            cmd(c, "SCALE 0.3")
            time.sleep(3)
            log("CDISCALE manual", c.read("CDISCALE")[0])
            shot("scale_0p3")
            time.sleep(15)
            cmd(c, "SCALE AUTO")
            time.sleep(3)
            log("CDISCALE auto", c.read("CDISCALE")[0])
            shot("scale_auto")
        if "scale" in done and "loi" not in done:
            done.add("loi")
            for v in (2000, 200):
                tend = time.time() + 12
                while time.time() < tend:
                    c.write("GPS_ACCURACY_HORIZ", v)
                    time.sleep(0.5)
                log("GPS_ACCURACY_HORIZ write", v, {k: c.read(k) for k in ("GPS_ACCURACY_HORIZ", "FPLINTEG", "FPLPHASE", "FPLAPR", "FPLMSG")})
                shot("loi_write_%d" % v)
            time.sleep(4)  # tol 2000 ms: the key goes old again, accuracy -> None
            log("GPS_ACCURACY_HORIZ released", {k: c.read(k) for k in ("GPS_ACCURACY_HORIZ", "FPLINTEG", "FPLPHASE")})
        if "loi" in done and "rst2" not in done:
            done.add("rst2")
            log("pyEfis restart #2")
            sh("sudo -n systemctl restart pyefis; sleep 30; systemctl is-active pyefis", timeout=200)
            sh("DISPLAY=:0 xdotool mousemove 403 972 click 1; sleep 8; DISPLAY=:0 xdotool mousemove 1919 1079", timeout=60)
            shot("after_pyefis_restart")
        st = {"leg": leg, "phase": phase, "state": state, "apr": apr}
        time.sleep(0.5)
    finish(c)


def finish(c):
    shot("end")
    log("final", {k: c.read(k)[0] for k in ("FPLSTATE", "FPLACTLEG", "WPNAME", "FPLAPR", "FPLPHASE")})
    sh("sh %s/session2.sh stop" % D)
    sh("cd %s && tar czf s2/fp8_s2_artifacts.tgz fp8_s2.csv logger_s2.out shots/s2_* shots/keys.log s2/events.log" % D)
    open(os.path.join(OUT, "DONE"), "w").write(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    log("done")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        log("CRASH", repr(e), traceback.format_exc().replace("\n", " | "))
        try:
            sh("sh %s/session2.sh stop" % D)
        except Exception:
            pass
        raise
