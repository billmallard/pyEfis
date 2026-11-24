"""CERT20b (AER-6451) flight feed: a synthetic orbit written to fix-gateway over
netfix, so the PFD and SVS have moving data, and a log of every ROLL write for
the data-to-glass measurement. Bench tool; run it only where nothing else
writes these keys (the Pi 5 bench with no position or attitude source enabled).

  soak_feed.py --out roll_writes.csv --until <unix-seconds> [--host H --port P]

Writes ROLL and PITCH at 25 Hz; LAT, LONG, ALT, HEAD, TRACK, GS, IAS, TAS and
VS at 5 Hz. The aircraft flies a 3 NM-radius left orbit at 120 kt and
5500 ft about --lat/--lon, rolling +-15 deg on a 7 s sine and pitching +-4 deg
on an 11 s sine, so every 33 ms frame clock tick sees a changed pose.
Every ROLL write is logged as ``<monotonic_ns>,<value as sent>`` before the
send, line-buffered. Stops itself at --until (a deadline, not a flag a wedged
path can ignore: the main loop checks it every iteration and
the caller also runs it under RuntimeMaxSec).
"""
import argparse
import math
import socket
import time

NM_DEG = 1.0 / 60.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--until", type=float, required=True)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=3490)
    ap.add_argument("--lat", type=float, default=34.4275)
    ap.add_argument("--lon", type=float, default=-119.8546)
    a = ap.parse_args()

    s = socket.create_connection((a.host, a.port), timeout=5)
    s.setblocking(False)
    log = open(a.out, "a", buffering=1)
    radius_nm, gs = 3.0, 120.0
    omega = gs / (2 * math.pi * radius_nm) * 2 * math.pi / 3600.0  # rad/s
    t_start = time.monotonic()
    period = 0.04
    n = 0
    while time.time() < a.until:
        t = time.monotonic() - t_start
        roll = 15.0 * math.sin(2 * math.pi * t / 7.0)
        pitch = 4.0 * math.sin(2 * math.pi * t / 11.0)
        rtxt = "%.4f" % roll
        lines = ["ROLL;%s\n" % rtxt, "PITCH;%.4f\n" % pitch]
        if n % 5 == 0:
            ang = omega * t          # angle from the centre, counter-clockwise
            lat = a.lat + radius_nm * NM_DEG * math.sin(ang)
            lon = a.lon + radius_nm * NM_DEG * math.cos(ang) / math.cos(math.radians(a.lat))
            trk = (math.degrees(-ang)) % 360.0   # tangent of a left (CCW) orbit
            lines += ["LAT;%.7f\n" % lat, "LONG;%.7f\n" % lon, "ALT;5500.0\n",
                      "HEAD;%.2f\n" % trk, "TRACK;%.2f\n" % trk, "GS;%.1f\n" % gs,
                      "IAS;%.1f\n" % 110.0, "TAS;%.1f\n" % gs, "VS;0.0\n"]
        log.write("%d,%s\n" % (time.monotonic_ns(), rtxt))
        s.sendall("".join(lines).encode())
        try:
            while s.recv(4096):
                pass
        except BlockingIOError:
            pass
        n += 1
        nxt = t_start + n * period
        d = nxt - time.monotonic()
        if d > 0:
            time.sleep(d)
    s.close()


if __name__ == "__main__":
    main()
