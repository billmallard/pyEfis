#!/usr/bin/env python3
"""pa14_follow.py -- bench side of PA14 (AER-1613): KSBA FLOUT5.RW15B.VTU V485
OHIGH FERN7.OHIGH KSMO RNAV 21, flown against X-Plane in three sim-bench slices.

Runs ON the Beelink, detached, for one night (stdlib + ./nfx.py only). For each
slice, when /health says its session is flying and X-Plane's own position (RREF
probe, independent of fixgw) is near the slice's air start:
  1. wait for fixgw's LAT to be live and agree with X-Plane (the standing RREF
     block, AER-4970, carries position; fixgw is restarted only if it does not);
  2. make sure the bus holds the route pyEfis's PROC page published this
     morning (route_ksba_ksmo.json, captured off the bus); republish it only if
     the live block differs (someone used the bench in between);
  3. GPSSRC 0, NAVSRC 2, then the slice's pilot actions (ACT, RESUME) driven off
     the engine's own state;
  4. log the bus at 2 Hz to <slice>_bus.csv and grab the panel on events: the
     slice start, every FPLACTLEG change, VECTORS, RESUME, FPLAPR changes, the
     CDI scale ramp, the MAP suspend and the missed approach.
At the end of the night GPSSRC/NAVSRC are restored. The route stays loaded
(it is this item's own). Markers: ARMED, <slice>_START, <slice>_DONE, FINISHED.

    setsid nohup python3 pa14_follow.py --dir . --until 2026-11-15T06:05-06:00 \
        > follow.out 2>&1 < /dev/null &
    python3 pa14_follow.py --dir . --dry C     # rehearse slice C's start, synthetic position
"""
import argparse
import csv
import json
import math
import os
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from nfx import NFX  # noqa: E402

XP = ("10.110.10.167", 49000)
HEALTH = "http://10.110.10.167:8770/health"
LOCK = "/tmp/pyefis-bench.lock"
ROUTE = os.path.join(HERE, "route_ksba_ksmo.json")
START_NM, GONE_S = 8.0, 60

FIXES = {  # FAA CIFP 2611 (the bench's procedures pack); KSBA as pyEfis publishes it
    "KSBA": (34.42619166, -119.84149277), "FLOUT": (34.25758889, -119.95320278),
    "VTU": (34.11506389, -119.0495), "HENER": (34.33106389, -119.22768889),
    "OHIGH": (34.43135278, -119.31081944), "CANYN": (34.39113889, -119.07830556),
    "FIM": (34.35669444, -118.88129167), "VNY": (34.22345833, -118.491675),
}
# name, session id (filled at submit), start fix, the fix before it, start alt,
# before_nm, ACT slot, max_s
SLICES = [
    {"k": "A", "sid": None, "fix": "FLOUT", "prev": "KSBA", "alt": 6000, "before": 3.0, "act": 2, "max_s": 2500},
    {"k": "B", "sid": None, "fix": "HENER", "prev": "VTU", "alt": 9000, "before": 4.0, "act": 6, "max_s": 2400},
    {"k": "C", "sid": None, "fix": "VNY", "prev": "FIM", "alt": 4500, "before": 4.0, "act": 10, "max_s": 2500},
]
SLOT_F = ("ID", "LAT", "LON", "TYPE", "PT", "CRS", "DST", "ALT", "SPD", "SGI", "FLAGS", "CTRLAT", "CTRLON", "TURN")
SEG_F = ("KIND", "ID", "ENT", "EXT", "FIRST", "LAST")
STR_F = ("ID", "PT", "ALT", "TURN", "ENT", "EXT")
LOG_KEYS = ["LAT", "LONG", "ALT", "GS", "TRACK", "MAGVAR", "HEAD", "GPSSRC", "NAVSRC",
            "FPLSTATE", "FPLACTLEG", "FPLACTSEG", "FPLPHASE", "FPLAPR", "CDISCALE", "FPLSUSPMAP",
            "FPLCRS", "FPLXTK", "FPLCDI", "FPLTF", "FPLALERT", "FPLTURN", "FPLINTEG",
            "EXTCRS", "EXTCDI", "EXTTF", "WPFROM", "WPNAME", "WPNEXT", "WPDIS", "FPLSEGREM",
            "FPLMSG", "FPLCMDACK", "FPLCOUNT", "FPLSEQ", "FPLLDSEQ", "GPS_FIX_TYPE"]


def utc():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def nm(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 3440.065 * 2 * math.asin(math.sqrt(h))


def bearing(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    y = math.sin(lo2 - lo1) * math.cos(la2)
    x = math.cos(la1) * math.sin(la2) - math.sin(la1) * math.cos(la2) * math.cos(lo2 - lo1)
    return math.degrees(math.atan2(y, x)) % 360


def offset(p, brg, d):
    la1, lo1, t, r = math.radians(p[0]), math.radians(p[1]), math.radians(brg), d / 3440.065
    la2 = math.asin(math.sin(la1) * math.cos(r) + math.cos(la1) * math.sin(r) * math.cos(t))
    lo2 = lo1 + math.atan2(math.sin(t) * math.sin(r) * math.cos(la1), math.cos(r) - math.sin(la1) * math.sin(la2))
    return math.degrees(la2), math.degrees(lo2)


def start_point(sl):
    a, b = FIXES[sl["prev"]], FIXES[sl["fix"]]
    return offset(b, (bearing(a, b) + 180) % 360, sl["before"])


def fnum(s, default=0.0):
    try:
        return float(s)
    except (TypeError, ValueError):
        return default


class XPlaneProbe:
    """X-Plane's own position over RREF from an ephemeral port (as v27_follow.py)."""
    REFS = ("sim/flightmodel/position/latitude", "sim/flightmodel/position/longitude",
            "sim/flightmodel/position/elevation")

    def __init__(self):
        self.s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.s.bind(("", 0))
        self.s.settimeout(0.5)
        self.v, self.t_last, self.t_sub = {}, 0.0, 0.0

    def _sub(self, freq):
        for i, ref in enumerate(self.REFS):
            msg = b"RREF\x00" + struct.pack("<ii", freq, 700 + i) + ref.encode().ljust(400, b"\x00")
            try:
                self.s.sendto(msg, XP)
            except OSError:
                pass

    def poll(self):
        now = time.time()
        if now - self.t_sub > 10:
            self._sub(2)
            self.t_sub = now
        end = now + 1.0
        while time.time() < end:
            try:
                data, _ = self.s.recvfrom(2048)
            except (socket.timeout, OSError):
                continue
            if data[:4] != b"RREF":
                continue
            for j in range(5, len(data) - 7, 8):
                idx, val = struct.unpack("<if", data[j:j + 8])
                self.v[idx] = val
            self.t_last = time.time()
        if time.time() - self.t_last > 5 or not all(700 + i in self.v for i in range(3)):
            return None
        lat, lon, elev = self.v[700], self.v[701], self.v[702]
        if lat == 0 and lon == 0:
            return None
        return lat, lon, elev * 3.28084

    def close(self):
        self._sub(0)


def flying_id():
    try:
        h = json.load(urllib.request.urlopen(HEALTH, timeout=8))
        return True, (h.get("flying") or {}).get("id")
    except Exception:
        return False, None


class Follower:
    def __init__(self, a):
        self.a = a
        self.dir = os.path.abspath(a.dir)
        self.c = NFX()
        self.xp = XPlaneProbe()
        self.done = set()
        self.saved_src = None
        self.route = json.load(open(ROUTE))

    def log(self, *x):
        line = utc() + " " + " ".join(str(v) for v in x)
        with open(os.path.join(self.dir, "events.log"), "a") as f:
            f.write(line + "\n")
        print(line, flush=True)

    def mark(self, name, body=""):
        with open(os.path.join(self.dir, name), "w") as f:
            f.write(utc() + " " + body + "\n")

    def locked(self, cmd, wait=600):
        r = subprocess.run(["flock", "-w", str(wait), LOCK, "sh", "-c", cmd], capture_output=True, text=True)
        return r.returncode, (r.stdout + r.stderr).strip()

    def grab(self, name):
        p = os.path.join(self.dir, "shots", name + ".png")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        # two grabs, keep the second: the first after a change can be stale (AER-5086)
        rc, out = self.locked("DISPLAY=:0 ffmpeg -loglevel error -y -f x11grab -draw_mouse 0 "
                              f"-video_size 1920x1080 -i :0 -frames:v 1 {p}.tmp.png; sleep 1; "
                              "DISPLAY=:0 ffmpeg -loglevel error -y -f x11grab -draw_mouse 0 "
                              f"-video_size 1920x1080 -i :0 -frames:v 1 {p}; rm -f {p}.tmp.png", wait=20)
        keys = {k: self.c.read(k)[0] for k in ("FPLSTATE", "FPLACTLEG", "FPLPHASE", "FPLAPR", "CDISCALE",
                                               "WPNAME", "WPDIS", "FPLCRS", "FPLXTK", "EXTCRS", "FPLMSG")}
        self.log("grab", name, "rc", rc, out[:200], keys)

    def grab_later(self, name, s=3.0):
        threading.Timer(s, self.grab, args=(name,)).start()

    def tap(self, x, y):
        self.locked(f"DISPLAY=:0 xdotool mousemove {x} {y} click 1", wait=20)

    def cmd(self, verb):
        ack = abs(int(fnum(self.c.read("FPLCMDACK")[0])))
        seq = max(ack, int(time.time()) % 1000000) + 1
        self.c.write("FPLCMD", "%d %s" % (seq, verb))
        time.sleep(2.0)
        self.log("FPLCMD", seq, verb, {k: self.c.read(k)[0] for k in (
            "FPLCMDACK", "FPLMSG", "FPLSTATE", "FPLACTLEG", "FPLPHASE", "WPNAME", "FPLCRS", "FPLXTK")})

    # -- the route ------------------------------------------------------------
    def live_matches(self):
        r = self.route
        if int(fnum(self.c.read("FPLCOUNT")[0])) != r["FPLCOUNT"]:
            return False
        if int(fnum(self.c.read("FPLSEGCNT")[0])) != r["FPLSEGCNT"]:
            return False
        if self.c.read("FPLLDSEQ")[0] != self.c.read("FPLSEQ")[0]:
            return False
        for i, s in enumerate(r["slots"], 1):
            for f in ("ID", "PT", "SGI", "FLAGS", "ALT"):
                if self.c.read(f"FPL{i}{f}")[0] != s[f]:
                    return False
        for k, s in enumerate(r["segs"], 1):
            for f in SEG_F:
                if self.c.read(f"FPLS{k}{f}")[0] != s[f]:
                    return False
        return True

    def ensure_route(self):
        if self.live_matches():
            self.log("route on the bus is the PROC-page route (FPLSEQ", self.c.read("FPLSEQ")[0], ")")
            return
        r = self.route
        old_n = int(fnum(self.c.read("FPLCOUNT")[0]))
        old_m = int(fnum(self.c.read("FPLSEGCNT")[0]))
        for i in range(1, max(r["FPLCOUNT"], old_n) + 1):
            s = r["slots"][i - 1] if i <= r["FPLCOUNT"] else None
            for f in SLOT_F:
                self.c.write(f"FPL{i}{f}", s[f] if s else ("" if f in STR_F else 0))
        for k in range(1, max(r["FPLSEGCNT"], old_m) + 1):
            s = r["segs"][k - 1] if k <= r["FPLSEGCNT"] else None
            for f in SEG_F:
                self.c.write(f"FPLS{k}{f}", s[f] if s else ("" if f in STR_F else 0))
        for key in ("FPLSEGCNT", "FPLCOUNT", "FPLNAME", "FPLAPRTYPE", "FPLDBCYC"):
            self.c.write(key, r[key])
        self.c.write("FPLSEQ", int(fnum(self.c.read("FPLSEQ")[0])) + 1)
        time.sleep(2.0)
        self.log("route REPUBLISHED from", ROUTE, "FPLSEQ", self.c.read("FPLSEQ")[0], "FPLLDSEQ",
                 self.c.read("FPLLDSEQ")[0], "FPLMSG", self.c.read("FPLMSG")[0], "match", self.live_matches())

    # -- logging --------------------------------------------------------------
    def logger(self, sl, stop):
        k = sl["k"]
        path = os.path.join(self.dir, f"{k}_bus.csv")
        with open(path, "a", newline="") as f:
            w = csv.writer(f)
            if f.tell() == 0:
                w.writerow(["t"] + LOG_KEYS + ["ACTID", "flags_LAT", "flags_FPLCRS", "flags_EXTCRS"])
            c = NFX()
            last = {}
            ramp = set()
            while not stop.is_set():
                t = time.time()
                row, fl = [], {}
                for key in LOG_KEYS:
                    v, flags = c.read(key)
                    row.append(v)
                    fl[key] = flags
                v = dict(zip(LOG_KEYS, row))
                n = int(fnum(v["FPLACTLEG"]))
                actid = c.read(f"FPL{n}ID")[0] if n else ""
                w.writerow(["%.2f" % t] + row + [actid, fl["LAT"], fl["FPLCRS"], fl["EXTCRS"]])
                f.flush()
                for key in ("FPLACTLEG", "FPLPHASE", "FPLAPR", "FPLSTATE", "FPLSUSPMAP"):
                    if key in last and v[key] != last[key]:
                        self.log(f"{k} {key}", last[key], "->", v[key], "slot", n, actid, "WPDIS", v["WPDIS"],
                                 "FPLCRS", v["FPLCRS"], "EXTCRS", v["EXTCRS"], "FPLMSG", v["FPLMSG"])
                        if key in ("FPLACTLEG", "FPLAPR", "FPLSUSPMAP") or v[key] == "VECTORS":
                            self.grab_later(f"{k}_{key}_{v[key]}_{actid or n}".replace(" ", ""))
                    last[key] = v[key]
                scale = fnum(v["CDISCALE"], 9)
                for thr in (0.95, 0.65, 0.31):
                    if scale <= thr and thr not in ramp and v["FPLAPR"] in ("1", "2"):
                        ramp.add(thr)
                        self.log(f"{k} CDISCALE", scale, "<=", thr, "WPDIS", v["WPDIS"], "WPNAME", v["WPNAME"])
                        self.grab_later(f"{k}_scale_{thr}", 0.5)
                if v["FPLSUSPMAP"] == "1" and "susp" not in ramp:
                    ramp.add("susp")
                    threading.Thread(target=self.fly_missed, args=(k,), daemon=True).start()
                time.sleep(max(0.0, 0.5 - (time.time() - t)))

    def fly_missed(self, k):
        """The pilot's missed approach: RESUME 8 s after the MAP auto-suspend,
        the same lag the driver gives X-Plane (missed_after_map_s: 8)."""
        self.log(f"{k} MAP auto-suspend seen; RESUME in 8 s")
        time.sleep(8.0)
        self.cmd("RESUME")
        self.grab_later(f"{k}_missed_resumed", 3.0)

    # -- one slice -------------------------------------------------------------
    def wait_fixgw_live(self, xp_pos, timeout=120):
        end = time.time() + timeout
        while time.time() < end:
            v, fl = self.c.read("LAT")
            lo, _ = self.c.read("LONG")
            if fl[1:2] == "0":
                try:
                    d = nm((float(v), float(lo)), xp_pos[:2])
                    if d < 2.0:
                        return d
                except ValueError:
                    pass
            time.sleep(2)
            xp_pos = self.xp.poll() or xp_pos
        return None

    def start_actions(self, sl):
        self.ensure_route()
        if self.saved_src is None:
            self.saved_src = {x: self.c.read(x)[0] for x in ("GPSSRC", "NAVSRC")}
            self.log("saved", self.saved_src)
        self.c.write("GPSSRC", 0)
        self.c.write("NAVSRC", 2)
        time.sleep(1.0)
        self.cmd(f"ACT {sl['act']}")
        self.tap(1326, 9)          # Flight Plan tab
        if sl["k"] == "A":
            # the SID's VA leg: VECTORS and SUSP, nothing invented; then the pilot resumes
            t0 = time.time()
            while time.time() - t0 < 10 and self.c.read("FPLPHASE")[0] != "VECTORS":
                time.sleep(1)
            self.log("A on the VA leg:", {x: self.c.read(x)[0] for x in (
                "FPLSTATE", "FPLPHASE", "FPLCRS", "FPLXTK", "FPLCDI", "WPDIS", "WPNAME", "FPLACTLEG")})
            self.grab("A_vectors_fpl")
            self.tap(1272, 9)      # Map tab
            time.sleep(3)
            self.grab("A_vectors_map")
            time.sleep(6)
            self.cmd("RESUME")
            time.sleep(3)
            self.grab("A_resumed_map")
            self.tap(1326, 9)
            time.sleep(3)
            self.grab("A_resumed_fpl")
        # the guidance has to be live, not just fed (AER-4464 night 1)
        for _ in range(10):
            time.sleep(2)
            v_, fl_ = self.c.read("FPLCRS")
            if fl_[3:4] == "0" and v_ not in ("0.0", "ERR"):
                break
        self.log(f"{sl['k']} guidance", "LIVE" if fl_[3:4] == "0" else "FAILED", "FPLCRS", v_, fl_,
                 "WPNAME", self.c.read("WPNAME")[0], "GPS_FIX_TYPE", self.c.read("GPS_FIX_TYPE"))
        self.grab(f"{sl['k']}_start")

    def fly_slice(self, sl, pos):
        k = sl["k"]
        self.log(f"{k} recognised (session {sl['sid']})", "xplane", tuple(round(x, 4) for x in pos))
        self.mark(f"{k}_START", f"session {sl['sid']} at {pos}")
        d = self.wait_fixgw_live(pos)
        if d is None:
            rc, out = self.locked("sudo -n systemctl restart fixgw; sleep 10; systemctl is-active fixgw")
            self.log(f"{k} LAT not live after 120 s: fixgw restart rc", rc, out)
            self.c = NFX()
            d = self.wait_fixgw_live(self.xp.poll() or pos)
        self.log(f"{k} fixgw LAT live", d is not None, "agrees with X-Plane to nm", d)
        stop = threading.Event()
        th = threading.Thread(target=self.logger, args=(sl, stop), daemon=True)
        th.start()
        try:
            self.start_actions(sl)
        except Exception as e:
            self.log(f"{k} start actions FAILED", type(e).__name__, e)
        deadline = time.time() + sl["max_s"] + 900
        last_seen = time.time()
        why = "deadline"
        while time.time() < deadline:
            ok, fid = flying_id()
            if ok and fid != sl["sid"]:
                why = f"/health: flying is {fid}"
                break
            if self.xp.poll():
                last_seen = time.time()
            elif not ok and time.time() - last_seen > GONE_S:
                why = "X-Plane silent, /health unreachable"
                break
            time.sleep(3)
        self.grab(f"{k}_end")
        stop.set()
        th.join(5)
        self.log(f"{k} ended:", why)
        self.mark(f"{k}_DONE", sl["sid"])
        self.done.add(k)

    def restore(self):
        try:
            if self.saved_src:
                for k, v in self.saved_src.items():
                    self.c.write(k, v)
                self.log("restored", self.saved_src)
        except Exception as e:
            self.log("restore failed", e)
        self.xp.close()

    def run(self):
        todo = [s for s in SLICES if s["sid"]]
        self.mark("ARMED", " ".join(f"{s['k']}={s['sid']}" for s in todo))
        self.log("armed", {s["k"]: [s["sid"], s["fix"], tuple(round(x, 4) for x in start_point(s))] for s in todo})
        try:
            while len(self.done) < len(todo):
                if self.a.until and time.time() > self.a.until:
                    self.log("window closed with slices not flown:", sorted({s["k"] for s in todo} - self.done))
                    break
                ok, fid = flying_id()
                hit = next((s for s in todo if s["sid"] == fid and s["k"] not in self.done), None) if ok else None
                if not hit:
                    time.sleep(5)
                    continue
                self.log(f"/health: flying {fid} ({hit['k']}); waiting for X-Plane at the start point")
                t0, pos = time.time(), None
                while time.time() - t0 < 600:
                    p = self.xp.poll()
                    if p and abs(p[2] - hit["alt"]) < 1000 and nm(p[:2], start_point(hit)) < START_NM:
                        pos = p
                        break
                    if flying_id()[1] != fid:
                        break
                if pos is None:
                    if flying_id()[1] != fid:
                        self.log(f"{hit['k']} left the flying slot before it reached the start point")
                        self.done.add(hit["k"])
                        self.mark(f"{hit['k']}_NOT_FLOWN", fid)
                        continue
                    self.log("X-Plane probe silent or not at the start point; proceeding from /health alone")
                    pos = (*start_point(hit), float(hit["alt"]))
                self.fly_slice(hit, pos)
        finally:
            self.restore()
            self.mark("FINISHED", "done " + " ".join(sorted(self.done)))
            self.log("finished", sorted(self.done))

    def dry(self, k):
        """Rehearse one slice's start with a synthetic position at its air start
        (no X-Plane): route check, ACT, the slice's pilot actions, live guidance."""
        sl = next(s for s in SLICES if s["k"] == k)
        lat, lon = start_point(sl)
        trk = bearing(FIXES[sl["prev"]], FIXES[sl["fix"]])
        stop = threading.Event()

        def feed():
            f = NFX()
            p = (lat, lon)
            while not stop.is_set():
                for key, val in (("MAGVAR", -12.0), ("GS", 110.0), ("TRACK", trk), ("HEAD", (trk + 12) % 360),
                                 ("ALT", float(sl["alt"])), ("LAT", p[0]), ("LONG", p[1])):
                    f.write(key, val)
                p = offset(p, trk, 110.0 / 3600 * 0.5)
                time.sleep(0.5)
        th = threading.Thread(target=feed, daemon=True)
        th.start()
        time.sleep(3)
        try:
            self.start_actions(sl)
        finally:
            stop.set()
            self.restore()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=".")
    ap.add_argument("--sids", default="", help="A=<sid>,B=<sid>,C=<sid>")
    ap.add_argument("--dry", default="")
    ap.add_argument("--until", type=lambda x: datetime.fromisoformat(x).timestamp(), default=None)
    a = ap.parse_args()
    for pair in filter(None, a.sids.split(",")):
        k, sid = pair.split("=")
        next(s for s in SLICES if s["k"] == k)["sid"] = sid
    f = Follower(a)
    import signal
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    if a.dry:
        f.dry(a.dry)
        return 0
    f.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
