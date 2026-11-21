"""AER-6086 bench feeder: flies the OBS1 TONIE example on the private gateway
(port 3492), steering on the engine's FPLCRS/FPLXTK like a coupled GPSS, the
way fix-gateway tests/sim/test_obs_tonie.py does. Control files in run/:
'hold' freezes the aircraft (position still written), 'enc' holds knob
detents to send (one ENC3 write each, e.g. '-40'), 'cmd' a raw FPLCMD verb."""
import csv, os, sys, time
sys.path.insert(0, os.path.expanduser("~/bench-scratch/aer6086/fgw/src"))
import fixgw.geo as geo
from fixgw.netfix import Client
from fixgw.sim.aircraft import Aircraft, Performance, State

RUN = os.path.expanduser("~/bench-scratch/aer6086/run")
MAGVAR, TAS, TONIE, START_NM = -12.0, 120.0, (34.70, -120.20), 30.0
SPEEDUP = float(sys.argv[1]) if len(sys.argv) > 1 else 8.0
c = Client("127.0.0.1", 3492); c.connect()

def rd(k):
    try:
        r = c.read(k)
        return r[1], r[2]
    except Exception as e:
        return None, str(e)

lat, lon = geo.destination_point(*TONIE, 310.0 - MAGVAR + 180.0, START_NM)
ac = Aircraft(Performance(tas_kt=TAS), State(lat, lon, 4000.0, 310.0 - MAGVAR))
seq = 1000
def cmd(text):
    global seq
    last = rd("FPLCMD")[0] or "0"
    try: seq = max(seq, int(last.split()[0]), abs(int(rd("FPLCMDACK")[0] or 0))) + 1
    except ValueError: seq += 1
    c.write("FPLCMD", f"{seq} {text}")
    return seq

f = open(os.path.join(RUN, "feed.csv"), "a", newline=""); w = csv.writer(f)
w.writerow(["wall", "lat", "lon", "dist_tonie", "FPLSTATE", "FPLCRS", "FPLXTK", "FPLTF", "COURSE", "CDI", "WPNAME", "FPLCMD", "FPLCMDACK", "FPLMSG"])
started = False; t0 = time.time()
while True:
    s = ac.s
    for k, v in (("LAT", s.lat), ("LONG", s.lon), ("ALT", 4000.0), ("GS", s.gs_kt), ("TAS", TAS), ("IAS", 110.0),
                 ("TRACK", s.track_true), ("TRACKM", geo.wrap360(s.track_true + MAGVAR)),
                 ("HEAD", geo.wrap360(s.heading_true + MAGVAR)), ("MAGVAR", MAGVAR),
                 ("GPS_ACCURACY_HORIZ", 5.0), ("PITCH", 0.0), ("ROLL", 0.0), ("VS", 0.0)):
        c.write(k, round(v, 7))
    if not started and time.time() - t0 > 3:
        cmd("ACT 2"); started = True
    p = os.path.join(RUN, "cmd")
    if os.path.exists(p):
        txt = open(p).read().strip(); os.remove(p); cmd(txt)
    p = os.path.join(RUN, "enc")
    if os.path.exists(p):
        n = int(open(p).read().strip() or 0); os.remove(p)
        key = "ENC3"
        for _ in range(abs(n)):
            c.write(key, 1 if n > 0 else -1); time.sleep(0.02)   # a fast spin: 50 detents/s
    vals = {k: rd(k)[0] for k in ("FPLSTATE", "FPLCRS", "FPLXTK", "FPLTF", "COURSE", "CDI", "WPNAME", "FPLCMD", "FPLCMDACK", "FPLMSG")}
    w.writerow([round(time.time(), 2), round(s.lat, 6), round(s.lon, 6),
                round(geo.distance_nm(s.lat, s.lon, *TONIE), 3)] + list(vals.values())); f.flush()
    if not os.path.exists(os.path.join(RUN, "hold")) and started:
        try:
            crs, xtk = float(vals["FPLCRS"]), float(vals["FPLXTK"])
            ac.step(0.2 * SPEEDUP, geo.wrap360(crs - MAGVAR), xtk, 4000.0)
        except (TypeError, ValueError):
            pass
    time.sleep(0.2)
