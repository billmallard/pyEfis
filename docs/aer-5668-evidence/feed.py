"""MAPPAINT1 bench feed: the keys the X-Plane plugin writes, at the rate the
bench delivered from X-Plane (7.6 Hz), over netfix. Same start point and the
same smooth flight every run, so the dev and branch measurements see the same
inputs. Usage: feed.py SECONDS [pidfile]"""
import math
import os
import socket
import sys
import time

secs = float(sys.argv[1])
if len(sys.argv) > 2:
    open(sys.argv[2], "w").write(str(os.getpid()))
LAT0, LON0, TRK0, GS0 = 35.70793, -83.38941, 307.76, 136.0
DT = 1.0 / 7.6
s = socket.create_connection(("127.0.0.1", 3490), timeout=3)
s.setblocking(False)
lat, lon = LAT0, LON0
t0 = time.monotonic()
n = 0
while True:
    t = n * DT
    if t > secs:
        break
    trk = TRK0 + 1.0 * math.sin(2 * math.pi * t / 40.0)
    gs = GS0 + 1.5 * math.sin(2 * math.pi * t / 25.0)
    d = (gs * DT / 3600.0) / 60.0
    lat += d * math.cos(math.radians(trk))
    lon += d * math.sin(math.radians(trk)) / math.cos(math.radians(lat))
    alt = 4500.0 + 20.0 * math.sin(2 * math.pi * t / 30.0)
    vals = dict(
        LAT=lat, LONG=lon, ALT=alt, AGL=alt - 1500.0, GS=gs,
        IAS=120.0 + 1.0 * math.sin(2 * math.pi * t / 25.0),
        TAS=128.0 + 1.0 * math.sin(2 * math.pi * t / 25.0),
        VS=20.0 * 2 * math.pi / 30.0 * 60.0 * math.cos(2 * math.pi * t / 30.0),
        PITCH=2.0 + 0.8 * math.sin(2 * math.pi * t / 7.0),
        ROLL=3.0 * math.sin(2 * math.pi * t / 11.0),
        HEAD=(trk + 6.0) % 360.0, MAGVAR=-6.0, TRACK=trk % 360.0,
        ALAT=0.01 * math.sin(2 * math.pi * t / 5.0))
    msg = "".join("%s;%.6f;0000\n" % (k, v) for k, v in vals.items())
    s.sendall(msg.encode())
    try:
        while s.recv(65536):
            pass
    except BlockingIOError:
        pass
    n += 1
    wait = t0 + n * DT - time.monotonic()
    if wait > 0:
        time.sleep(wait)
s.close()
