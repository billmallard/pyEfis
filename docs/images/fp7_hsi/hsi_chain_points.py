import math
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


def points():
    a, b = ROUTE[0][1:3], ROUTE[1][1:3]
    leg = brg(a, b); mid = frac(a, b, 0.5)
    c, d = ROUTE[2][1:3], ROUTE[3][1:3]
    leg4 = brg(c, d)
    return [
        ("KSBA-GVO on track", mid, leg),
        ("KSBA-GVO 0.5 nm RIGHT", dest(mid, leg + 90, 0.5), leg),
        ("KSBA-GVO 0.5 nm LEFT", dest(mid, leg - 90, 0.5), leg),
        ("RZS-KSMX 1 nm before KSMX", dest(d, (leg4 + 180) % 360, 1.0), leg4),
        ("1 nm PAST KSMX", dest(d, leg4, 1.0), leg4),
        ("1 nm past KSMX 0.5 nm RIGHT", dest(dest(d, leg4, 1.0), leg4 + 90, 0.5), leg4),
    ]
