"""CAS3 bench (AER-6346): the CAS1 brief's section 12.2 steps that involve a
display, on a private fix-gateway and this pyEfis tree under an X server.

    python3 docs/aer-6346-evidence/bench.py --fgw ../fgw --out OUT [--placement A]
    python3 docs/aer-6346-evidence/bench.py --fgw ../fgw --out OUT --render-only --placement B

Needs DISPLAY pointing at an X server with XTEST (Xvfb is enough) and
QT_QPA_PLATFORM=xcb. Nothing on a bench is touched: the gateway is
fix-gateway's shipped config tree, copied to a temp dir, netfix moved to a
private port, started the way the service starts it (``fixgw.server:main``);
pyEfis is this tree's shipped config, copied, pointed at that port, 1920x1080
windowed, with the CAS window at the chosen placement.

Faults are driven over raw netfix; touches are XTEST clicks on the X server;
frames are grabs of the X root window, so they show what the panel shows.
What pyEfis drew is also read from its own log ("CAS: CASWindow shows ...").
Every check prints PASS or FAIL; the script exits non-zero on any FAIL.

Steps the display cannot take part in (13, the gateway data path; 15, the
plugin restart) are CAS2 unit tests on the real plugin thread. Steps 5, 6 and
18 write APENG from a netfix writer, as CAS2's run did, not from ArduPlane
SITL: the plugin sees only the key and its flags.
"""

import argparse
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
W, H = 1920, 1080   # --size overrides
T0 = time.monotonic()
FAILS = []

#: The CAS window per placement option (brief 6.6), in the shipped PFD's
#: 110 x 200 grid: (row, column, rows, columns, lines). B covers the fuel and
#: radio slot while a message is active, so its fill is opaque there.
PLACEMENTS = {
    "A": (21, 16, 20, 29, 4),    # upper left of the AI, under the wind box
    "B": (70, 155, 40, 45, 4),   # right column, over the fuel/radio slot
    "C": (96, 16, 13, 95, 3),    # strip across the bottom of the AI
}


def log(msg):
    print("{:7.2f} {}".format(time.monotonic() - T0, msg), flush=True)


def check(ok, what):
    log(("PASS " if ok else "FAIL ") + what)
    if not ok:
        FAILS.append(what)
    return ok


class Netfix:
    def __init__(self, port):
        self.s = socket.create_connection(("127.0.0.1", port), timeout=3)
        self.buf = b""
        self.lock = threading.Lock()

    def line(self, prefix):
        while True:
            while b"\n" in self.buf:
                ln, self.buf = self.buf.split(b"\n", 1)
                ln = ln.decode()
                if ln.startswith(prefix):
                    return ln
            chunk = self.s.recv(4096)
            if not chunk:
                raise EOFError("netfix closed")
            self.buf += chunk

    def ask(self, cmd, prefix):
        with self.lock:
            self.s.sendall((cmd + "\n").encode())
            return self.line(prefix)

    def read(self, key):
        ln = self.ask("@r" + key, "@r" + key)
        if ln.endswith("!001"):
            return None, None
        _k, value, flags = ln[2:].split(";")
        return value, flags

    def send(self, frame):
        with self.lock:
            self.s.sendall((frame + "\n").encode())

    def slots(self):
        out = []
        for n in range(1, 13):
            v, _f = self.read("CASMSG{}".format(n))
            if v:
                out.append(v)
        return out


class Grabber:
    """A Qt process on the same X display that saves the root window."""

    CODE = r"""
import sys
from PyQt6.QtGui import QGuiApplication
app = QGuiApplication(sys.argv)
for line in sys.stdin:
    path = line.strip()
    app.primaryScreen().grabWindow(0).save(path)
    print("ok", flush=True)
"""

    def __init__(self):
        self.p = subprocess.Popen([sys.executable, "-c", self.CODE],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  text=True)

    def grab(self, path):
        self.p.stdin.write(path + "\n")
        self.p.stdin.flush()
        assert self.p.stdout.readline().strip() == "ok"
        return path

    def close(self):
        self.p.stdin.close()
        self.p.wait(5)


class Touch:
    def __init__(self):
        from Xlib import X, display
        from Xlib.ext import xtest
        self.X, self.xtest = X, xtest
        self.d = display.Display()

    def tap(self, x, y):
        self.xtest.fake_input(self.d, self.X.MotionNotify, x=int(x), y=int(y))
        self.xtest.fake_input(self.d, self.X.ButtonPress, 1)
        self.d.sync()
        time.sleep(0.05)
        self.xtest.fake_input(self.d, self.X.ButtonRelease, 1)
        self.d.sync()


class PyEfisLog:
    """pyEfis's stderr, read on a thread; keeps the CAS lines with the time
    they arrived."""

    def __init__(self, proc, path):
        self.lines = []
        self.out = open(path, "w")
        self.t = threading.Thread(target=self._read, args=(proc,), daemon=True)
        self.t.start()

    def _read(self, proc):
        for ln in proc.stdout:
            self.out.write(ln)
            self.out.flush()
            self.lines.append((time.monotonic(), ln.rstrip()))

    def window(self, since=0.0):
        """The window's drawn lists since monotonic *since*: [(t, text)]."""
        out = []
        for t, ln in list(self.lines):
            m = re.search(r"CAS: CASWindow shows (.*)$", ln)
            if m and t >= since:
                out.append((t, m.group(1)))
        return out

    def latest(self):
        w = self.window()
        return w[-1][1] if w else None

    def wait(self, pred, timeout, since):
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            for t, text in self.window(since):
                if pred(text):
                    return t - since, text
            time.sleep(0.05)
        return None, self.latest()

    def grep(self, pattern):
        return [ln for _t, ln in list(self.lines) if re.search(pattern, ln)]


def window_rect(placement):
    row, col, rows, cols, _lines = PLACEMENTS[placement]
    x0, y0 = col * W / 200.0, row * H / 110.0
    return int(x0), int(y0), int(cols * W / 200.0), int(rows * H / 110.0)


def colour_counts(path, rect):
    from PyQt6.QtGui import QImage
    img = QImage(path)
    x0, y0, w, h = rect
    red = amber = 0
    for y in range(y0, y0 + h, 2):
        for x in range(x0, x0 + w, 2):
            c = img.pixelColor(x, y)
            r, g, b = c.red(), c.green(), c.blue()
            if r > 230 and g < 40 and b < 40:
                red += 1
            elif r > 230 and 150 < g < 190 and b < 40:
                amber += 1
    return {"red": red, "amber": amber}


def flash_phases(grab, out, name, rect, colour, n=5, dt=0.3):
    """Counts of *colour* in the window over n grabs dt apart. A grab takes a
    variable time, so two grabs 0.5 s apart can land in one phase; five at
    0.3 s cannot all miss a 1 s cycle."""
    counts = []
    for k in range(n):
        f = grab.grab(os.path.join(out, "{}-{}.png".format(name, k)))
        counts.append(colour_counts(f, rect)[colour])
        time.sleep(dt)
    return counts


def crop_differs(a, b, rect):
    from PyQt6.QtGui import QImage
    x0, y0, w, h = rect
    return QImage(a).copy(x0, y0, w, h) != QImage(b).copy(x0, y0, w, h)


# -- setup --------------------------------------------------------------------

def gateway_config(fgw, tmp, port):
    cfg = os.path.join(tmp, "fgw-config")
    shutil.copytree(os.path.join(fgw, "src/fixgw/config"), cfg)
    p = os.path.join(cfg, "connections/netfix.yaml")
    s = open(p).read()
    assert s.count("port: 3490") == 1
    open(p, "w").write(s.replace("port: 3490", "port: {}".format(port)))
    p = os.path.join(cfg, "connections/cas.yaml")
    s = open(p).read()
    s = s.replace("  #fuel_no_data_tanks: [1, 2]\n  fuel_no_data_grace: 30",
                  "  fuel_no_data_tanks: [3]\n  fuel_no_data_grace: 60")
    assert "fuel_no_data_tanks: [3]" in s
    open(p, "w").write(s)
    return cfg


WRAPPER = r"""
import signal, sys
import fixgw.server as server
def stop_cas(*_):
    p = server.plugins.get("cas")
    if p is not None:
        p.shutdown()
        print("bench: cas plugin stopped", flush=True)
signal.signal(signal.SIGUSR2, stop_cas)
server.main()
"""


def start_gateway(fgw, cfg, tmp):
    env = dict(os.environ, PYTHONPATH=os.path.join(fgw, "src"))
    out = open(os.path.join(tmp, "gateway.log"), "a")
    return subprocess.Popen(
        [sys.executable, "-c", WRAPPER, "--config-file",
         os.path.join(cfg, "default.yaml")],
        stdout=out, stderr=subprocess.STDOUT, env=env)


def pyefis_config(tmp, port, placement, status_path, no_window=False):
    cfg = os.path.join(tmp, "pyefis-config")
    shutil.copytree(os.path.join(REPO, "src/pyefis/config"), cfg)
    p = os.path.join(cfg, "main/default.yaml")
    s = open(p).read()
    s = s.replace("FixPort: 3490", "FixPort: {}".format(port))
    s = s.replace("screenFullSize: True", "screenFullSize: False")
    s = s.replace("  #screenWidth: 1280\n", "  screenWidth: {}\n".format(W), 1)
    s = s.replace("  #screenHeight: 720\n", "  screenHeight: {}\n".format(H), 1)
    s = re.sub(r"defaultScreen: \S+", "defaultScreen: PFD", s)
    open(p, "w").write(s)
    p = os.path.join(cfg, "screens/pfd.yaml")
    s = open(p).read()
    row, col, rows, cols, lines = PLACEMENTS[placement]
    i = s.index("    - type: cas_window")
    block = ("    - type: cas_window\n      row: {}\n      column: {}\n"
             "      span:\n        rows: {}\n        columns: {}\n"
             "      options:\n        lines: {}\n        status_path: {}\n"
             ).format(row, col, rows, cols, lines, status_path)
    if placement == "B":
        block += "        background_opacity: 1.0\n"
    s = s[:i] + ("" if no_window else block)
    open(p, "w").write(s)
    if no_window:
        for name in ("pfd_ai_only", "radio", "ems", "ems2", "flightplan"):
            q = os.path.join(cfg, "screens/{}.yaml".format(name))
            t = open(q).read()
            j = t.find("    # Crew alerting")
            if j >= 0:
                open(q, "w").write(t[:j])
    return cfg


def start_pyefis(cfg, tmp):
    env = dict(os.environ, PYTHONPATH=os.path.join(REPO, "src"))
    return subprocess.Popen(
        [sys.executable, "-c",
         "import sys; from pyefis.main import main; sys.exit(main())",
         "--config-file", os.path.join(cfg, "default.yaml"), "--verbose"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env,
        cwd=tmp)


def connect(port):
    for _ in range(150):
        try:
            return Netfix(port)
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("netfix never came up")


def stop(proc, name):
    if proc.poll() is None:
        proc.send_signal(signal.SIGCONT)
        proc.terminate()
        try:
            proc.wait(15)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(5)
    log("{} exit {}".format(name, proc.returncode))


# -- the run ------------------------------------------------------------------

#: Plausible cruise values, so the PFD around the window is not a wall of
#: failed instruments. HEAD is fed, so HDG FAIL never shows.
FLIGHT = ["PITCH;2.0", "ROLL;-4.0", "IAS;112", "TAS;118", "ALT;4500",
          "VS;0", "HEAD;95", "GS;114", "TRACK;93", "ALAT;0.0", "BARO;29.92",
          "OAT;12"]


class Feeder:
    """Keeps NAV1 and the autopilot alive, as CAS2's run did (inputs only,
    never a compute output)."""

    def __init__(self, nf):
        self.nf = nf
        self.state = {"nav_fail": "0", "nav": True, "ap": True,
                      "flap": False, "stop": False}
        self.t = threading.Thread(target=self.run, daemon=True)
        self.t.start()

    def run(self):
        n = 0
        while not self.state["stop"]:
            st = self.state
            try:
                if st["nav"]:
                    self.nf.send("NAVSRC;0")
                    self.nf.send("NAV1CRS;90")
                    self.nf.send("NAV1CDI;0.1;00{}0".format(st["nav_fail"]))
                    self.nf.send("NAV1DH;1")
                for frame in FLIGHT:
                    self.nf.send(frame)
                # 3 s on, 3 s off: longer than APENG's 2 s tol, so the
                # link really drops in each off phase.
                ap = st["ap"] and not (st["flap"] and (n // 9) % 2)
                if ap:
                    self.nf.send("APENG;1")
            except OSError:
                pass
            n += 1
            time.sleep(0.33)


def run_steps(args, tmp, nf, gw, pe, plog, grab, touch, out):
    rect = window_rect(args.placement)
    row, col, rows, cols, lines = PLACEMENTS[args.placement]
    line_h = rect[3] / float(lines)
    tap_xy = (rect[0] + rect[2] / 2.0, rect[1] + line_h / 2.0)

    def frame(name):
        return grab.grab(os.path.join(out, name + ".png"))

    # 14 (first half) and 1. CAS TEST at boot, then quiet.
    t, text = plog.wait(lambda s: "CAS TEST" in s, 15, args._gw_start)
    shown = [tt for tt, x in plog.window() if "CAS TEST" in x]
    log("CAS TEST on the glass from {} to {} s after the gateway started".format(
        round(shown[0] - args._gw_start, 2) if shown else None,
        round(shown[-1] - args._gw_start, 2) if shown else None))
    check(t is not None, "step 14: CAS TEST drawn in the window after the "
          "gateway starts (proves plugin, bus, widget and glass)")
    if t is not None:
        frame("14a-cas-test-at-boot")
    t, text = plog.wait(lambda s: s == "nothing", 15, args._gw_start + 1.0)
    check(t is not None, "step 1: window draws nothing once CAS TEST clears")
    check(nf.read("CASCNT")[0] == "0", "step 1: CASCNT 0 over raw netfix")
    f1 = frame("01-quiet")
    c = colour_counts(f1, rect)
    check(c["red"] == 0 and c["amber"] == 0,
          "step 1: no red or amber in the window area ({})".format(c))

    feed = Feeder(nf)
    time.sleep(1.5)

    # 2. NAV FAIL amber, flashing, within 1 s.
    since = time.monotonic()
    feed.state["nav_fail"] = "1"
    t, text = plog.wait(lambda s: "caution unacked NAV FAIL" in s, 4, since)
    check(t is not None and t < 1.0,
          "step 2: NAV FAIL drawn within 1 s of the CDI fail ({} s)".format(
              None if t is None else round(t, 2)))
    counts = flash_phases(grab, out, "02-nav-fail", rect, "amber")
    check(max(counts) > 100, "step 2: amber in the window ({})".format(counts))
    check(min(counts) < 0.6 * max(counts), "step 2: the line flashes (amber "
          "fill comes and goes over five grabs 0.3 s apart: {})".format(counts))

    # 3. Touch: flash stops, line stays, CASACK equals CASSEQ.
    since = time.monotonic()
    touch.tap(*tap_xy)
    t, text = plog.wait(lambda s: "caution NAV FAIL" in s and "unacked" not in s,
                        3, since)
    check(t is not None, "step 3: after the touch NAV FAIL is drawn "
          "acknowledged ({})".format(text))
    time.sleep(0.4)
    ack, seq = nf.read("CASACK")[0], nf.read("CASSEQ")[0]
    log("CASACK {} CASSEQ {}".format(ack, seq))
    check(ack is not None and int(ack) <= int(seq) and int(ack) >= int(seq) - 1,
          "step 3: CASACK written by the touch, at the CASSEQ drawn")
    a = frame("03-acked-a")
    time.sleep(0.5)
    b = frame("03-acked-b")
    ca, cb = colour_counts(a, rect), colour_counts(b, rect)
    later = [x for tt, x in plog.window(since) if "unacked NAV FAIL" in x]
    check(not later and ca["amber"] > 100 and
          abs(ca["amber"] - cb["amber"]) <= 0.05 * ca["amber"],
          "step 3: the acknowledged line is steady: never redrawn unacked, "
          "amber the same 0.5 s apart ({}, {})".format(ca, cb))

    # 12. A new caution after the acknowledge flashes; the old one does not.
    since = time.monotonic()
    feed.state["ap"] = False      # APENG goes old: AP LINK LOST (engaged)
    t, text = plog.wait(lambda s: "warning unacked AP LINK LOST" in s, 5, since)
    check(t is not None and t < 3.0, "step 5: AP LINK LOST (warning, "
          "engaged) drawn within 3 s of the last APENG ({})".format(
              None if t is None else round(t, 2)))
    check(text is not None and "caution NAV FAIL" in text
          and "caution unacked NAV FAIL" not in text,
          "step 12: the new alert flashes while the acknowledged NAV FAIL "
          "stays steady ({})".format(text))
    a = frame("05-ap-link-lost-a")
    time.sleep(0.5)
    frame("05-ap-link-lost-b")
    check(colour_counts(a, rect)["red"] + colour_counts(
        os.path.join(out, "05-ap-link-lost-b.png"), rect)["red"] > 200,
        "step 5: red in the window")

    # 18. Intermittent link, 3 s on and 3 s off (APENG's tol is 2 s, so each
    # off phase is a real loss): one alert, no flapping; it clears about 5 s
    # after the link is steady.
    since = time.monotonic()
    feed.state["ap"] = True
    feed.state["flap"] = True
    time.sleep(13.0)
    gaps = [x for _t, x in plog.window(since) if "AP LINK LOST" not in x]
    check(not gaps, "step 18: no gap in AP LINK LOST while the link drops "
          "every 3 s ({} gaps)".format(len(gaps)))
    feed.state["ap"] = False
    feed.state["flap"] = False
    time.sleep(3.0)
    since = time.monotonic()
    feed.state["ap"] = True
    t, text = plog.wait(lambda s: "AP LINK LOST" not in s, 10, since)
    check(t is not None and 4.5 <= t <= 7.0, "step 18: AP LINK LOST cleared "
          "{} s after the link went steady (5 s clear delay)".format(
              None if t is None else round(t, 2)))

    # 4. Clear the CDI flag: line gone.
    since = time.monotonic()
    feed.state["nav_fail"] = "0"
    t, text = plog.wait(lambda s: "NAV FAIL" not in s, 4, since)
    check(t is not None, "step 4: NAV FAIL gone when the flag clears")

    # 6. Autopilot disengaged, link stops: caution.
    since = time.monotonic()
    feed.state["ap"] = False
    nf.send("APENG;0")
    time.sleep(0.4)
    t, text = plog.wait(lambda s: "caution unacked AP LINK LOST" in s, 6, since)
    check(t is not None, "step 6: AP LINK LOST is a caution when the autopilot "
          "was disengaged ({})".format(text))
    frame("06-ap-link-lost-caution")
    feed.state["ap"] = True

    # 7. FUEL QTY 3 NO DATA after the 60 s grace, not before.
    t, text = plog.wait(lambda s: "FUEL QTY 3 NO DATA" in s, 75, 0.0)
    first = [tt for tt, x in plog.window() if "FUEL QTY 3 NO DATA" in x]
    check(bool(first), "step 7: FUEL QTY 3 NO DATA drawn")
    if first:
        after = first[0] - args._gw_start
        check(60.0 <= after <= 63.0, "step 7: after the 60 s grace, not before "
              "({:.1f} s after gateway start)".format(after))
    frame("07-fuel-no-data")

    nf.send("CASACK;{}".format(nf.read("CASSEQ")[0]))
    time.sleep(0.5)
    return feed


def run_failures(args, tmp, nf, gw, pe, plog, grab, out, feed):
    rect = window_rect(args.placement)

    def frame(name):
        return grab.grab(os.path.join(out, name + ".png"))

    # 10. An older signed manifest refused: CATALOG REFUSED, white.
    since = time.monotonic()
    json.dump({"ok": True, "packs": [
        {"id": "catalog", "name": "Catalog", "status": "CATALOG REFUSED",
         "severity": "white",
         "detail": "older catalog 2026-11-01 refused; kept 2026-11-20"}]},
        open(args._status, "w"))
    t, text = plog.wait(lambda s: "advisory unacked CATALOG REFUSED" in s,
                        15, since)
    check(t is not None, "step 10: CATALOG REFUSED (advisory) drawn from "
          "status.json ({})".format(text))
    frame("10-catalog-refused")

    # 9. SIGSTOP the gateway: GATEWAY LINK LOST within 2.5 s, no gateway line.
    feed.state["stop"] = True
    time.sleep(0.5)
    since = time.monotonic()
    gw.send_signal(signal.SIGSTOP)
    t, text = plog.wait(lambda s: "GATEWAY LINK LOST" in s, 6, since)
    trips = [tt for tt, ln in list(plog.lines)
             if "No frame from FIX gateway" in ln and tt >= since]
    trip = trips[0] - since if trips else None
    log("watchdog trip logged {} s after SIGSTOP; CAS drew the link alert {} s "
        "after SIGSTOP".format(None if trip is None else round(trip, 2),
                               None if t is None else round(t, 2)))
    check(t is not None and trip is not None and t - trip <= 0.5,
          "step 9: GATEWAY LINK LOST drawn within 0.5 s of the watchdog trip "
          "(the CAS3 leg)")
    check(t is not None and t <= 2.5, "step 9: GATEWAY LINK LOST within 2.5 s "
          "of SIGSTOP end to end (brief; the watchdog leg is CERT1's, here on "
          "software GL)")
    time.sleep(1.0)
    text = plog.latest()
    allowed = ("GATEWAY LINK LOST", "CATALOG REFUSED")
    during = [x for tt, x in plog.window(since)
              if tt <= time.monotonic() and "GATEWAY LINK LOST" in x]
    check(not any("CAS FAIL" in x for x in during),
          "step 9: no CAS FAIL beside the link alert ({})".format(during))
    shown = [p.split(" ", 2)[-1] for p in text.split("; ")]
    check(all(any(a in x for a in allowed) for x in shown),
          "step 9: only local alerts drawn during link loss ({})".format(text))
    frame("09-gateway-link-lost")
    since = time.monotonic()
    gw.send_signal(signal.SIGCONT)
    t, text = plog.wait(lambda s: "GATEWAY LINK LOST" not in s, 15, since)
    check(t is not None, "step 9: SIGCONT recovers ({} after {} s)".format(
        text, None if t is None else round(t, 2)))
    os.remove(args._status)

    # 16 and 8. Two messages active, then stop the cas plugin: CAS FAIL
    # within 4 s and neither old message drawn.
    feed.state.update(stop=False, nav_fail="1", ap=False)
    feed.t = threading.Thread(target=feed.run, daemon=True)
    feed.t.start()
    plog.wait(lambda s: "NAV FAIL" in s and "AP LINK LOST" in s, 8,
              time.monotonic() - 8)
    log("before the plugin stop: {}".format(plog.latest()))
    check("NAV FAIL" in (plog.latest() or "") and
          "AP LINK LOST" in (plog.latest() or ""),
          "step 16: two gateway messages drawn before the stop")
    frame("16a-two-messages")
    since = time.monotonic()
    gw.send_signal(signal.SIGUSR2)
    t, text = plog.wait(lambda s: "CAS FAIL" in s, 8, since)
    check(t is not None and t < 4.0, "step 8: CAS FAIL within 4 s of the plugin "
          "stopping ({} s)".format(None if t is None else round(t, 2)))
    check(text is not None and "NAV FAIL" not in text
          and "AP LINK LOST" not in text,
          "step 16: neither old message drawn with CAS FAIL ({})".format(text))
    time.sleep(1.0)
    f = frame("16b-cas-fail")
    c = colour_counts(f, rect)
    check(c["red"] == 0 and c["amber"] > 100,
          "step 16: amber CAS FAIL, no red (the old warning) ({})".format(c))
    feed.state["stop"] = True

    # 14 (display side). CAS TEST reaches the glass when the display is
    # already drawing: restart the gateway under the running display.
    stop(gw, "gateway (for the restart)")
    gw2 = start_gateway(os.path.abspath(args.fgw), args._gcfg, args._tmp)
    since = time.monotonic()
    t, text = plog.wait(lambda s: "CAS TEST" in s, 20, since)
    check(t is not None, "step 14: after a gateway restart under a running "
          "display, CAS TEST drawn ({} s after the restart)".format(
              None if t is None else round(t, 2)))
    shown = [tt for tt, x in plog.window(since) if "CAS TEST" in x]
    if t is not None:
        frame("14a-cas-test-after-gateway-restart")
        t2, _ = plog.wait(lambda s: "CAS TEST" not in s, 15, shown[0])
        log("CAS TEST on the glass for {} s".format(
            None if t2 is None else round(t2, 2)))
    return gw2


def run_render(args, nf, plog, grab, out):
    """The look for the placement card: the same three messages in each
    placement, a warning and a caution unacknowledged, one caution
    acknowledged, at 1920 x 1080."""
    feed = Feeder(nf)
    time.sleep(2.0)
    plog.wait(lambda s: "FUEL QTY 3 NO DATA" in s, 75, 0.0)
    # The startup notice banner covers the bottom of the panel for 20 s
    # from when the window shows, several seconds after the process starts.
    while time.monotonic() - args._pe_start < 36.0:
        time.sleep(0.2)
    nf.send("CASACK;{}".format(nf.read("CASSEQ")[0]))
    time.sleep(0.6)
    feed.state["nav_fail"] = "1"
    feed.state["ap"] = False
    plog.wait(lambda s: "AP LINK LOST" in s and "NAV FAIL" in s, 8,
              time.monotonic() - 8)
    time.sleep(1.0)
    log("drawn: {}".format(plog.latest()))
    from PyQt6.QtGui import QImage  # noqa: F401  (import check)
    for k in range(2):
        time.sleep(0.25 + 0.5 * k)
        grab.grab(os.path.join(out, "render-{}-{}.png".format(
            args.placement, "ab"[k])))
    feed.state["stop"] = True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fgw", required=True, help="fix-gateway checkout")
    ap.add_argument("--out", required=True)
    ap.add_argument("--placement", default="A", choices=sorted(PLACEMENTS))
    ap.add_argument("--port", type=int, default=34990)
    ap.add_argument("--render-only", action="store_true")
    ap.add_argument("--size", default="1920x1080",
                    help="panel size; the timed steps run smaller, because "
                         "software GL at full size stalls the GUI thread")
    ap.add_argument("--display-lead", type=float, default=10.0,
                    help="seconds pyEfis runs before the gateway starts")
    ap.add_argument("--no-window", action="store_true",
                    help="step 14, second half: no CAS widget on any screen")
    args = ap.parse_args()
    global W, H
    W, H = (int(v) for v in args.size.split("x"))
    os.makedirs(args.out, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="cas3-")
    args._status = os.path.join(tmp, "status.json")
    gcfg = gateway_config(os.path.abspath(args.fgw), tmp, args.port)
    args._gcfg, args._tmp = gcfg, tmp
    pcfg = pyefis_config(tmp, args.port, args.placement, args._status,
                         no_window=args.no_window)
    # The display starts first and waits for the gateway, as on a box whose
    # gateway service is slower: the CAS TEST check then measures how much of
    # the power-up test reaches the glass after the gateway starts.
    pe = start_pyefis(pcfg, tmp)
    args._pe_start = time.monotonic()
    log("pyefis pid {} (pyEfis {}{}), placement {}".format(
        pe.pid, subprocess.run(["git", "-C", REPO, "rev-parse", "--short",
                                "HEAD"], capture_output=True,
                               text=True).stdout.strip(),
        " + working tree" if subprocess.run(
            ["git", "-C", REPO, "status", "--porcelain"], capture_output=True,
            text=True).stdout.strip() else "", args.placement))
    time.sleep(args.display_lead)
    gw = start_gateway(os.path.abspath(args.fgw), gcfg, tmp)
    args._gw_start = time.monotonic()
    log("gateway pid {} (fix-gateway {}), {:.0f} s after the display".format(
        gw.pid, subprocess.run(["git", "-C", args.fgw, "rev-parse", "--short",
                                "HEAD"], capture_output=True,
                               text=True).stdout.strip(), args.display_lead))
    nf = connect(args.port)
    plog = PyEfisLog(pe, os.path.join(args.out, "pyefis-{}.log".format(
        "nowindow" if args.no_window else args.placement)))
    grab = Grabber()
    try:
        time.sleep(1.0)
        if args.no_window:
            time.sleep(12.0)
            hits = plog.grep(r"CAS NOT SHOWN")
            check(bool(hits), "step 14: CAS NOT SHOWN logged as an error "
                  "with no window or marker ({})".format(hits[:1]))
            grab.grab(os.path.join(args.out, "14b-cas-not-shown.png"))
            from PyQt6.QtGui import QImage
            img = QImage(os.path.join(args.out, "14b-cas-not-shown.png"))
            bw, bh = max(int(W * 0.22), 7 * 54), max(22, int(H * 0.05))
            x0, y0 = (W - bw) // 2, H - bh - 4
            white = sum(1 for y in range(y0, y0 + bh, 2)
                        for x in range(x0, x0 + bw, 2)
                        if min(img.pixelColor(x, y).getRgb()[:3]) > 230)
            check(white > 50, "step 14: the cue is drawn bottom centre "
                  "({} white samples)".format(white))
        elif args.render_only:
            run_render(args, nf, plog, grab, args.out)
        else:
            touch = Touch()
            feed = run_steps(args, tmp, nf, gw, pe, plog, grab, touch, args.out)
            gw = run_failures(args, tmp, nf, gw, pe, plog, grab, args.out,
                              feed) or gw
    finally:
        grab.close()
        stop(pe, "pyefis")
        stop(gw, "gateway")
        tb = plog.grep(r"Traceback|CAS: poll failed")
        check(not tb, "no traceback and no CAS poll failure in the pyEfis log "
              "({})".format(tb[:2]))
        shutil.copy(os.path.join(tmp, "gateway.log"), os.path.join(
            args.out, "gateway-{}.log".format(
                "nowindow" if args.no_window else args.placement)))
    log("RESULT {} checks failed: {}".format(len(FAILS), FAILS) if FAILS
        else "RESULT all checks passed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
