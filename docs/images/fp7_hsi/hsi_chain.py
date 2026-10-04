"""FP7 HSI chain check against a live fix-gateway: route block -> flightplan
engine -> GPSSRC select -> NAVSRC select -> COURSE/CDI/TOFROM (the HSI's
keys). Synthetic positions offset from the active leg by a known cross-track.
"""
import math, sys, time
sys.path.insert(0, sys.argv[1] if len(sys.argv) > 1 else ".")
from fixio import Fix

R = 3440.065
ROUTE = [("KSBA", 34.42621, -119.84037, 1), ("GVO", 34.53142, -120.09106, 2),
         ("RZS", 34.50953, -119.77089, 2), ("KSMX", 34.89892, -120.45758, 1)]

def brg(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    y = math.sin(lo2 - lo1) * math.cos(la2)
    x = math.cos(la1) * math.sin(la2) - math.sin(la1) * math.cos(la2) * math.cos(lo2 - lo1)
    return math.degrees(math.atan2(y, x)) % 360

def dest(p, bearing, nm):
    la, lo, b, d = math.radians(p[0]), math.radians(p[1]), math.radians(bearing), nm / R
    la2 = math.asin(math.sin(la) * math.cos(d) + math.cos(la) * math.sin(d) * math.cos(b))
    lo2 = lo + math.atan2(math.sin(b) * math.sin(d) * math.cos(la), math.cos(d) - math.sin(la) * math.sin(la2))
    return math.degrees(la2), math.degrees(lo2)

def frac(a, b, t):  # point a fraction t along a->b (small legs: linear is fine for picking points)
    return a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t

f = Fix()
for i, (ident, la, lo, ty) in enumerate(ROUTE, 1):
    f.w("FPL%dID" % i, ident); f.w("FPL%dLAT" % i, la); f.w("FPL%dLON" % i, lo); f.w("FPL%dTYPE" % i, ty)
f.w("FPLCOUNT", len(ROUTE)); f.w("FPLNAME", "KSBA-KSMX")
seq = int(float(f.r("FPLSEQ")[0] or 0)) + 1
f.w("FPLSEQ", seq)
f.w("MAGVAR", 0.0); f.w("GS", 120.0); f.w("GPSSRC", 0); f.w("NAVSRC", 2)
time.sleep(0.5)

cmdseq = [100]
def cmd(verb):
    cmdseq[0] += 1
    f.w("FPLCMD", "%d %s" % (cmdseq[0], verb)); time.sleep(0.4)
    return f.r("FPLCMDACK")[0]

KEYS = ["FPLSTATE", "FPLACTLEG", "FPLPHASE", "CDISCALE", "WPFROM", "WPNAME", "WPNEXT",
        "FPLCRS", "FPLXTK", "FPLCDI", "FPLTF", "GPSCRS", "GPSCDI", "GPSTF",
        "COURSE", "CDI", "TOFROM", "WPDIS", "WPETE"]

def at(label, pos):
    f.w("LAT", pos[0]); f.w("LONG", pos[1]); time.sleep(0.6)
    f.w("LAT", pos[0] + 1e-9); time.sleep(0.6)  # second update past the 5 Hz limiter
    vals = {k: f.r(k) for k in KEYS}
    print("|", label, "|", " | ".join("%s" % vals[k][0] for k in KEYS), "|",
          ",".join("%s=%s" % (k, v[1]) for k, v in vals.items() if v[1] not in ("00000", "")), "|")
    return vals

print("| point | " + " | ".join(KEYS) + " | non-zero flags |")
print("|" + "---|" * (len(KEYS) + 2))
a, b = ROUTE[0][1:3], ROUTE[1][1:3]
print("ACT 2 ack", cmd("ACT 2"), file=sys.stderr)
leg = brg(a, b)
mid = frac(a, b, 0.5)
at("KSBA-GVO on track", mid)
at("KSBA-GVO 0.5 nm RIGHT", dest(mid, leg + 90, 0.5))
at("KSBA-GVO 0.5 nm LEFT", dest(mid, leg - 90, 0.5))
at("KSBA-GVO 1.0 nm RIGHT", dest(mid, leg + 90, 1.0))
at("KSBA-GVO 2.0 nm RIGHT (pegged)", dest(mid, leg + 90, 2.0))
# Last leg: RZS -> KSMX, then past KSMX (no sequencing: TO flips to FROM).
print("ACT 4 ack", cmd("ACT 4"), file=sys.stderr)
c, d = ROUTE[2][1:3], ROUTE[3][1:3]
leg4 = brg(c, d)
at("RZS-KSMX 1.0 nm before KSMX", dest(d, (leg4 + 180) % 360, 1.0))
at("RZS-KSMX 1.0 nm PAST KSMX", dest(d, leg4, 1.0))
at("RZS-KSMX 1.0 nm past, 0.5 nm RIGHT", dest(dest(d, leg4, 1.0), leg4 + 90, 0.5))
# Engine-side failure: position flagged bad for > 5 s -> guidance fail.
