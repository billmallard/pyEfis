"""AER-6288 rehearsal feeder: write attitude plus a scripted autopilot state
sequence into the private gateway (no X-Plane), then stop writing, so the
private glass and score.py can be checked end to end before the session.

    python3 rehearse.py <netfix port>

Each phase holds for 14 s (longer than the 10 s mode flash). After the last
phase the feeder stops: every key goes old and the strip must read NO AP DATA.
The values are a stand-in, not a claim about what X-Plane reports."""
import socket
import sys
import time

port = int(sys.argv[1])
s = socket.create_connection(("127.0.0.1", port), timeout=5)
f = s.makefile("rwb")
air = dict(PITCH=2.0, ROLL=0.0, ALAT=0.0, TAS=110, IAS=105, ALT=7500, AGL=3000,
           HEAD=120.0, TRACK=120.0, MAGVAR=-12.0, LAT=34.65, LONG=-120.35, VS=0,
           GS=110)
base = dict(APENG=True, YDENG=False, APLAT="HDG", APLATARM="", APVERT="PIT",
            APVERTARM="", APALTCAP=False, APALTREF=7500, APDISC=False,
            VSSEL=0, IASSEL=0, ALTSEL=8000)
phases = [
    ("hdg-gps-armed", dict(APLATARM="GPS")),
    ("gps-vs-alt-armed", dict(APLAT="GPS", APVERT="VS", VSSEL=500,
                              APVERTARM="ALT")),
    ("alt-cap", dict(APLAT="GPS", APVERT="ALT", APALTCAP=True, APALTREF=8000,
                     VSSEL=500)),
    ("alt-hold", dict(APLAT="GPS", APVERT="ALT", APALTREF=8000, ALTSEL=8500)),
    ("ias-climb", dict(APLAT="GPS", APVERT="IAS", IASSEL=90, APVERTARM="ALT",
                       ALTSEL=8500, APALTREF=8000)),
    ("yd-on", dict(APLAT="GPS", APVERT="ALT", YDENG=True, APALTREF=8500)),
    ("disc", dict(APENG=False, APDISC=True, APLAT="GPS", APVERT="ALT",
                  APALTREF=8500)),
]


def w(k, v):
    f.write(("@w%s;%s\n" % (k, v)).encode())
    f.flush()
    f.readline()


for name, ph in phases:
    vals = dict(base, **ph)
    t0 = time.time()
    print(time.strftime("%H:%M:%S"), name, flush=True)
    while time.time() - t0 < 14:
        for k, v in list(air.items()) + list(vals.items()):
            w(k, v)
        time.sleep(0.2)
print(time.strftime("%H:%M:%S"), "stopped writing: keys go old", flush=True)
