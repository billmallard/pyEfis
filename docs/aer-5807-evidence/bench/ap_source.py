#  SPDX-License-Identifier: GPL-2.0-or-later
"""A scripted autopilot source for the AFC3 bench run (AER-5807).

Not an autopilot: a stand-in for AFC2 that speaks the AFC1 contract over
netfix. It takes APCMDSEQ as its baseline on connect (a restarted source
never replays the last request), answers each later change after a short
delay, rewrites every state and health key twice a tol, and refuses on
purpose:

- NAV: "NAV: NO NAV SOURCE" (the brief's negative test, section 8);
- VNAV: not in APCAPS, "VNAV: NOT AVAILABLE".

APR arms LOC and GS, then captures both 3 s later. After --run-s seconds it
stops writing entirely, so the state keys go old (stale is removed).

    python3 ap_source.py --port 3492 --run-s 60 --log source.jsonl
"""

import argparse
import json
import socket
import threading
import time

CAPS = "AP,FD,YD,LVL,HDG,NAV,APR,IAS,VS,ALT,DISC"
REPLY_S = 0.4
REFRESH_S = 0.5


class Source:
    def __init__(self, host, port, log):
        self.sock = socket.create_connection((host, port), timeout=5)
        self.sock.settimeout(0.2)
        self.log = open(log, "a")
        self.lock = threading.Lock()
        self.s = dict(APENG=False, FDENG=False, YDENG=False, APLAT="",
                      APLATARM="", APVERT="", APVERTARM="", APALTCAP=False,
                      APCAPS=CAPS, APMSG="")
        self.buf = b""
        self.baseline = None
        self.pending = []          # (due, fn)
        self.t0 = time.monotonic()

    def note(self, **kw):
        kw["t"] = round(time.monotonic() - self.t0, 3)
        self.log.write(json.dumps(kw) + "\n")
        self.log.flush()

    def send(self, line):
        self.sock.sendall((line + "\n").encode())

    def write_all(self):
        with self.lock:
            for k, v in self.s.items():
                if isinstance(v, bool):
                    v = "1" if v else "0"
                self.send("%s;%s;0000" % (k, v))

    def read(self, key):
        self.send("@r" + key)

    def lines(self):
        try:
            data = self.sock.recv(4096)
        except socket.timeout:
            return []
        self.buf += data
        out = []
        while b"\n" in self.buf:
            line, self.buf = self.buf.split(b"\n", 1)
            out.append(line.decode().strip())
        return out

    def later(self, fn, delay=REPLY_S):
        self.pending.append((time.monotonic() + delay, fn))

    def set(self, **kw):
        with self.lock:
            self.s.update(kw)
        self.write_all()
        self.note(event="state", **{k: self.s[k] for k in self.s})

    def command(self, cmd):
        self.note(event="request", cmd=cmd)
        s = self.s
        if cmd == "AP":
            if s["APENG"]:
                self.later(lambda: self.set(APENG=False, APMSG=""))
            else:
                self.later(lambda: self.set(
                    APENG=True, FDENG=True, APMSG="",
                    APLAT=s["APLAT"] or "ROL", APVERT=s["APVERT"] or "PIT"))
        elif cmd == "FD":
            self.later(lambda: self.set(FDENG=not s["FDENG"]))
        elif cmd == "YD":
            self.later(lambda: self.set(YDENG=not s["YDENG"]))
        elif cmd == "HDG":
            self.later(lambda: self.set(
                APLAT="ROL" if s["APLAT"] == "HDG" else "HDG", APMSG=""))
        elif cmd == "NAV":
            self.later(lambda: self.set(APMSG="NAV: NO NAV SOURCE"))
        elif cmd == "VNAV":
            self.later(lambda: self.set(APMSG="VNAV: NOT AVAILABLE"))
        elif cmd == "APR":
            self.later(lambda: self.set(APLATARM="LOC", APVERTARM="GS",
                                        APMSG=""))
            self.later(lambda: self.set(APLAT="LOC", APLATARM="",
                                        APVERT="GS", APVERTARM=""), 3.4)
        elif cmd in ("VS", "IAS", "ALT"):
            arm = "ALT" if cmd != "ALT" else ""
            self.later(lambda: self.set(APVERT=cmd, APVERTARM=arm,
                                        APMSG=""))
        elif cmd == "LVL":
            self.later(lambda: self.set(APENG=True, FDENG=True, APLAT="LVL",
                                        APVERT="LVL", APLATARM="",
                                        APVERTARM="", APMSG=""), 0.2)
        elif cmd == "DISC":
            self.later(lambda: self.set(APENG=False))
        else:
            self.later(lambda: self.set(APMSG="%s: UNKNOWN" % cmd))

    def run(self, run_s):
        self.send("@sAPCMDSEQ")
        self.read("APCMDSEQ")
        self.write_all()
        self.note(event="start", caps=CAPS)
        last_refresh = time.monotonic()
        waiting_cmd = False
        while time.monotonic() - self.t0 < run_s:
            for line in self.lines():
                if line.startswith("@rAPCMDSEQ;"):
                    seq = line.split(";")[1]
                    if self.baseline is None:
                        self.baseline = seq
                        self.note(event="baseline", seq=seq)
                elif line.startswith("APCMDSEQ;"):
                    seq = line.split(";")[1]
                    if self.baseline is not None and seq != self.baseline:
                        self.baseline = seq
                        waiting_cmd = True
                        self.read("APCMD")
                elif line.startswith("@rAPCMD;") and waiting_cmd:
                    waiting_cmd = False
                    self.command(line.split(";")[1])
            now = time.monotonic()
            for item in [p for p in self.pending if p[0] <= now]:
                self.pending.remove(item)
                item[1]()
            if now - last_refresh >= REFRESH_S:
                self.write_all()
                last_refresh = now
        self.note(event="stopped_writing")
        self.sock.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=3492)
    ap.add_argument("--run-s", type=float, default=60.0)
    ap.add_argument("--log", default="source.jsonl")
    a = ap.parse_args()
    Source(a.host, a.port, a.log).run(a.run_s)


if __name__ == "__main__":
    main()
