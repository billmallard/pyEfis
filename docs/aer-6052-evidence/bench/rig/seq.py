#!/usr/bin/env python3
"""AER-6052 (AFC5) bench sequencer: fly X-Plane's autopilot through a HDG to
NAV capture with an intercept turn and a VS to ALT capture, via a private
fixgw (the AFC2 adapter on fix-gateway dev), while a private pyEfis (the AFC5
branch) on Xvfb draws the flight director. Built from aer5806/run3/seq.py.

    python3 seq.py <dir> [--port 3593] [--display :6] [--fast]

Logs the bus (bus.jsonl), each step (steps.jsonl), and grabs the virtual
display once a second and at every step (frames/, frames.jsonl carries the
bus values at the moment of each grab). The last step is the AP disconnect:
the driver's servo guard pauses the sim, X-Plane stops replying, and the FD
keys go old, so the frames after it show whether the bars are removed.
"""
import json
import os
import socket
import subprocess
import sys
import threading
import time

D = sys.argv[1]


def arg(name, default):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


PORT = int(arg("--port", 3593))
DISP = arg("--display", ":6")
FAST = "--fast" in sys.argv
STOP = os.path.join(D, "STOP")
FR = os.path.join(D, "frames")
os.makedirs(FR, exist_ok=True)

AP_KEYS = ["APENG", "FDENG", "APLAT", "APLATARM", "APVERT", "APVERTARM",
           "APALTCAP", "APALTREF", "FDPITCH", "FDROLL", "APCAPS", "APMSG", "APDISC"]
OTHER = ["APCMD", "APCMDSEQ", "ALTSEL", "VSSEL", "HEADBUG", "XPHSISRC",
         "PITCH", "ROLL", "ALT", "IAS", "VS", "HEAD", "TRACK", "EXTCRS", "EXTCDI",
         "LAT", "LONG"]
SNAP = ["FDENG", "FDPITCH", "FDROLL", "PITCH", "ROLL", "APENG", "APLAT",
        "APLATARM", "APVERT", "APVERTARM", "HEADBUG", "HEAD", "EXTCRS",
        "EXTCDI", "ALT", "ALTSEL", "VS"]


def now():
    return time.time()


def connect():
    for _ in range(60):          # netfix refuses back-to-back connects
        try:
            return socket.create_connection(("127.0.0.1", PORT), timeout=5)
        except OSError:
            time.sleep(1)
    raise SystemExit("no gateway on port %d" % PORT)


class Bus:
    def __init__(self):
        self.s = connect()
        self.buf = b""
        self.lock = threading.Lock()

    def q(self, line):
        with self.lock:
            self.s.sendall((line + "\n").encode())
            while b"\n" not in self.buf:
                chunk = self.s.recv(4096)
                if not chunk:
                    raise SystemExit("gateway closed")
                self.buf += chunk
            out, _, self.buf = self.buf.partition(b"\n")
            return out.decode()

    def read(self, key):
        parts = self.q("@r" + key)[2:].split(";")
        if len(parts) < 3:
            return None, None
        return parts[1], parts[2]

    def val(self, key):
        return self.read(key)[0]

    def fval(self, key):
        return float(self.val(key))

    def write(self, key, value):
        return self.q("@w%s;%s" % (key, value))


steps = open(os.path.join(D, "steps.jsonl"), "a")
frames = open(os.path.join(D, "frames.jsonl"), "a")
latest = {}
tag = ["boot"]
nframe = [0]
glock = threading.Lock()


def note(step, msg, **kw):
    row = dict(t=round(now(), 3), step=step, msg=msg, **kw)
    steps.write(json.dumps(row) + "\n")
    steps.flush()
    print(json.dumps(row), flush=True)


def logger():
    """Subscribe to every key; log each update with its flags."""
    s = connect()
    f = open(os.path.join(D, "bus.jsonl"), "a")
    for k in AP_KEYS + OTHER:
        s.sendall(("@s%s\n" % k).encode())
        time.sleep(0.02)
    buf = b""
    while not os.path.exists(STOP):
        try:
            s.settimeout(1.0)
            chunk = s.recv(65536)
        except socket.timeout:
            continue
        if not chunk:
            break
        buf += chunk
        while b"\n" in buf:
            line, _, buf = buf.partition(b"\n")
            line = line.decode(errors="replace")
            if line.startswith("@"):
                continue
            parts = line.split(";")
            if len(parts) >= 3:
                latest[parts[0]] = (parts[1], parts[2], round(now(), 3))
                f.write(json.dumps({"t": round(now(), 3), "k": parts[0],
                                    "v": parts[1], "f": parts[2]}) + "\n")
    f.flush()


def grab(label=None):
    """One frame of the virtual display, with the bus values at that moment."""
    with glock:
        nframe[0] += 1
        name = "f%05d%s.png" % (nframe[0], "-" + label if label else "")
        snap = {k: latest.get(k) for k in SNAP}
        t = round(now(), 3)
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "x11grab",
                        "-video_size", "1920x1080", "-i", DISP, "-frames:v", "1",
                        os.path.join(FR, name)], check=False, timeout=10)
        frames.write(json.dumps({"t": t, "frame": name, "step": tag[0],
                                 "bus": snap}) + "\n")
        frames.flush()


def grabber():
    while not os.path.exists(STOP):
        t0 = now()
        try:
            grab()
        except Exception as e:            # never let a grab stop the run
            note("grab", "error %r" % (e,))
        time.sleep(max(0.0, 1.0 - (now() - t0)))


def state(bus):
    return {k: bus.val(k) for k in SNAP + ["APMSG", "IAS"]}


def press(bus, step, verb):
    bus.write("APCMD", verb)
    seq = int(bus.val("APCMDSEQ")) + 1
    bus.write("APCMDSEQ", seq)
    note(step, "pressed", verb=verb, seq=seq)


def wait(bus, step, what, cond, timeout, steady=0.0):
    t0 = now()
    since = None
    if FAST:
        timeout, steady = min(timeout, 20), min(steady, 1)
    while now() - t0 < timeout and not os.path.exists(STOP):
        try:
            ok = cond(bus)
        except (TypeError, ValueError):
            ok = False
        if ok:
            since = since or now()
            if now() - since >= steady:
                note(step, "PASS " + what, after_s=round(now() - t0, 2), state=state(bus))
                return True
        else:
            since = None
        time.sleep(0.1)
    note(step, "FAIL " + what, after_s=round(now() - t0, 2), state=state(bus))
    return False


def pause(seconds):
    t0 = now()
    if FAST:
        seconds = min(seconds, 3)
    while now() - t0 < seconds and not os.path.exists(STOP):
        time.sleep(0.2)


def lat(v):
    return lambda b: b.val("APLAT") == v


def vert(v):
    return lambda b: b.val("APVERT") == v


def angdiff(a, b):
    return (a - b + 180.0) % 360.0 - 180.0


def step(name):
    tag[0] = name
    grab(name)


def main():
    threading.Thread(target=logger, daemon=True).start()
    bus = Bus()
    threading.Thread(target=grabber, daemon=True).start()

    step("0-live")
    note("0-live", "waiting for the driver to couple (APENG, APLAT GPS)")
    wait(bus, "0-live", "AP engaged on GPS",
         lambda b: b.val("APENG") == "True" and b.val("APLAT") == "GPS", 1200, steady=15)
    # Let the leg the driver is on settle: the start is just before a fix.
    c0 = bus.fval("EXTCRS")
    wait(bus, "0-live", "EXTCRS within 2 deg for 20 s",
         lambda b: abs(angdiff(b.fval("EXTCRS"), c0)) < 2.0, 120, steady=20)
    note("0-live", "FD state", fdeng=bus.val("FDENG"), caps=bus.val("APCAPS"))
    if bus.val("FDENG") != "True":
        press(bus, "0-live", "FD")
        wait(bus, "0-live", "FDENG True", lambda b: b.val("FDENG") == "True", 5)

    # 1. HDG, with the bug synced to the heading first so the press does not
    #    turn the aircraft.
    step("1-hdg")
    bus.write("HEADBUG", "%.1f" % (bus.fval("HEAD") % 360.0))
    pause(2)
    press(bus, "1-hdg", "HDG")
    wait(bus, "1-hdg", "APLAT HDG", lat("HDG"), 5)
    pause(5)

    # 2. Offset: 40 deg right of the course for 60 s, so the course is to the
    #    left and the NAV capture needs an intercept turn.
    step("2-offset")
    crs = bus.fval("EXTCRS")
    bug = (crs + 40.0) % 360.0
    bus.write("HEADBUG", "%.1f" % bug)
    note("2-offset", "bug course+40", crs=crs, bug=bug)
    wait(bus, "2-offset", "HEAD within 5 deg of the bug",
         lambda b: abs(angdiff(b.fval("HEAD"), bug)) < 5.0, 60)
    pause(60)
    crs2 = bus.fval("EXTCRS")
    cdi = bus.fval("EXTCDI")
    note("2-offset", "after offset", crs=crs2, cdi=cdi, leg_changed=abs(angdiff(crs2, crs)) > 3.0)

    # 3. Intercept and NAV capture. Right of an unchanged leg, the intercept is
    #    course-30. If the leg changed, take the side from the needle
    #    (EXTCDI > 0: needle right, course to the right).
    step("3-nav")
    if abs(angdiff(crs2, crs)) <= 3.0:
        side = -1.0
    else:
        side = 1.0 if cdi > 0 else -1.0
    bug = (crs2 + 30.0 * side) % 360.0
    bus.write("HEADBUG", "%.1f" % bug)
    note("3-nav", "intercept bug", crs=crs2, bug=bug, side=side)
    wait(bus, "3-nav", "HEAD within 10 deg of the intercept",
         lambda b: abs(angdiff(b.fval("HEAD"), bug)) < 10.0, 60)
    press(bus, "3-nav", "NAV")
    wait(bus, "3-nav", "GPS armed or captured",
         lambda b: b.val("APLATARM") == "GPS" or b.val("APLAT") == "GPS", 5)
    note("3-nav", "after the press", aplat=bus.val("APLAT"), arm=bus.val("APLATARM"))
    wait(bus, "3-nav", "APLAT GPS (captured)", lat("GPS"), 300)
    wait(bus, "3-nav", "HEAD within 8 deg of the course",
         lambda b: abs(angdiff(b.fval("HEAD"), b.fval("EXTCRS"))) < 8.0, 120, steady=5)
    pause(15)

    # 4. VS to ALT capture, 500 ft up at 500 fpm.
    step("4-vs")
    alt = bus.fval("ALT")
    target = int(round(alt / 100.0)) * 100 + 500
    bus.write("ALTSEL", target)
    bus.write("VSSEL", 500)
    note("4-vs", "targets", altsel=target, vssel=500, alt=alt)
    pause(1.5)
    press(bus, "4-vs", "VS")
    wait(bus, "4-vs", "APVERT VS, ALT armed",
         lambda b: b.val("APVERT") == "VS" and "ALT" in b.val("APVERTARM").split(","), 5)
    wait(bus, "4-vs", "APVERT ALT (captured)", vert("ALT"), 240)
    note("4-vs", "captured", alt=bus.val("ALT"), altsel=bus.val("ALTSEL"))
    pause(15)

    # 5. AP disconnect. The servo guard pauses the sim and replies stop: the
    #    FD keys go old and the bars must go.
    step("5-disc")
    press(bus, "5-disc", "DISC")
    wait(bus, "5-disc", "APENG False", lambda b: b.val("APENG") == "False", 5)
    note("5-disc", "logging until the stop hook; frames show the bars going")
    while not os.path.exists(STOP):
        time.sleep(1)
    note("5-disc", "stopped")


if __name__ == "__main__":
    main()
