"""G79 live-data feeder: a moving aircraft near KSBA over netfix at 10 Hz
(position, attitude, air data), so the display repaints the way it does with
a simulator connected. Runs until killed. argv: seconds"""
import math, socket, sys, time
dur = float(sys.argv[1])
s = socket.create_connection(("127.0.0.1", 3490), timeout=3)
t0 = time.time(); end = t0 + dur
lat0, lon0 = 34.30, -119.95
while time.time() < end:
    t = time.time() - t0
    trk = (60 + 2 * t) % 360   # slow standard-ish turn so every instrument moves
    lat = lat0 + 0.0004 * t * math.cos(math.radians(60))
    lon = lon0 + 0.0004 * t * math.sin(math.radians(60))
    v = {"LAT": "%.6f" % lat, "LONG": "%.6f" % lon, "ALT": "%.0f" % (3000 + 50 * math.sin(t / 7)),
         "IAS": "%.1f" % (110 + 3 * math.sin(t / 5)), "TAS": "115", "GS": "112",
         "VS": "%.0f" % (300 * math.cos(t / 7)), "PITCH": "%.2f" % (2 * math.sin(t / 6)),
         "ROLL": "%.2f" % (15 * math.sin(t / 9)), "HEAD": "%.1f" % trk, "TRACK": "%.1f" % trk,
         "TRACKM": "%.1f" % ((trk - 12) % 360), "ALAT": "0.0", "AGL": "2500"}
    s.sendall("".join("%s;%s;0000\n" % kv for kv in v.items()).encode())
    time.sleep(0.1)
