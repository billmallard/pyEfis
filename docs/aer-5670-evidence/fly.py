"""AER-5670 (FPLWRITE2): a synthetic flight for the _notify A/B. Runs ON the
Beelink with X-Plane not running. Flies the first 80% of the bench route's
active leg (FPL10 DARTS -> FPL11 MOVVE on KSBA-KSMO) at 120 kt, 4500 ft,
wings level, over and over, writing the keys X-Plane's standing RREF block
writes, at 10 Hz. The engine and pyEfis are live; only the aircraft is
synthetic. Refuses to start if LAT is already moving (another writer).

    python3 fly.py <seconds>     (pidfile fly.pid, log fly.log)
"""
import math, os, sys, time
sys.path.insert(0, os.path.expanduser("~/bench-scratch/aer4464"))
from nfx import NFX

dur = float(sys.argv[1])
open("fly.pid", "w").write(str(os.getpid()))
log = open("fly.log", "a")
def say(*a):
    log.write(time.strftime("%FT%TZ ", time.gmtime()) + " ".join(map(str, a)) + "\n"); log.flush()

c = NFX(port=int(os.environ.get("NFX_PORT", "3490")))
v1 = c.read("LAT"); time.sleep(3); v2 = c.read("LAT")
if v1 != v2 and "Old" not in v2[1]:
    say("refused: LAT is being written", v1, v2); sys.exit(3)
la1, lo1 = float(c.read("FPL10LAT")[0]), float(c.read("FPL10LON")[0])
la2, lo2 = float(c.read("FPL11LAT")[0]), float(c.read("FPL11LON")[0])
dy = (la2 - la1) * 60.0; dx = (lo2 - lo1) * 60.0 * math.cos(math.radians(la1))
leg_nm = math.hypot(dx, dy); trk = math.degrees(math.atan2(dx, dy)) % 360
say("start", c.read("FPL10ID")[0], "->", c.read("FPL11ID")[0], "leg %.2f nm trk %.1f" % (leg_nm, trk))
gs = 120.0; span = 0.8 * leg_nm
t0 = time.time(); n = 0
while time.time() - t0 < dur:
    d = (gs * (time.time() - t0) / 3600.0) % span
    f = d / leg_nm
    for k, val in (("LAT", la1 + f * (la2 - la1)), ("LONG", lo1 + f * (lo2 - lo1)),
                   ("ALT", 4500), ("AGL", 3800), ("GS", gs), ("IAS", 112), ("TAS", 120),
                   ("VS", 0), ("PITCH", 1.5), ("ROLL", 0.0), ("HEAD", trk), ("TRACK", trk),
                   ("MAGVAR", -14.0), ("ALAT", 0.0)):
        c.write(k, "%.7f" % val if k in ("LAT", "LONG") else val)
    n += 1
    time.sleep(max(0.0, t0 + n * 0.1 - time.time()))
say("end", n, "cycles")
os.remove("fly.pid")
