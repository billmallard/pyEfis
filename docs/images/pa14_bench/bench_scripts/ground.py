"""ground.py: PA14 ground check of FLOUT5.RW15B's vector leg (AER-1613).
Feeds a synthetic position over netfix (no X-Plane), activates the VA leg,
grabs the glass, climbs out on the VA heading, RESUMEs, grabs again.
Run under the bench lock. Leaves the route loaded, the engine as it ends."""
import subprocess, threading, time, math
from nfx import NFX
MAGVAR = -11.9                      # positive west (12 E at KSBA)
RW15 = (34.4285, -119.8455)         # near the KSBA RW15L threshold
c = NFX(); pose = {"p": None}; stop = threading.Event()
def feeder():
    f = NFX()
    while not stop.is_set():
        p = pose["p"]
        if p:
            lat, lon, trk_m, gs, alt = p
            for k, v in (("MAGVAR", MAGVAR), ("GS", gs), ("HEAD", trk_m % 360), ("TRACK", (trk_m - MAGVAR) % 360),
                         ("ALT", alt), ("LAT", lat), ("LONG", lon)):
                f.write(k, v)
        time.sleep(0.5)
def dest(lat, lon, brg_t, nm):
    R = 3440.065; d = nm / R; b = math.radians(brg_t); p1 = math.radians(lat); l1 = math.radians(lon)
    p2 = math.asin(math.sin(p1)*math.cos(d) + math.cos(p1)*math.sin(d)*math.cos(b))
    l2 = l1 + math.atan2(math.sin(b)*math.sin(d)*math.cos(p1), math.cos(d) - math.sin(p1)*math.sin(p2))
    return math.degrees(p2), math.degrees(l2)
KEYS = ["FPLSTATE", "FPLACTLEG", "FPLPHASE", "WPFROM", "WPNAME", "WPDIS", "FPLCRS", "FPLXTK", "FPLCDI", "FPLMSG", "FPLCMDACK", "CDISCALE", "FPLAPR", "LAT", "LONG"]
def keys(tag):
    line = "%s %s %s" % (time.strftime("%H:%M:%SZ", time.gmtime()), tag, {k: c.read(k)[0] for k in KEYS})
    print(line, flush=True); open("ground_keys.log", "a").write(line + "\n")
def cmd(verb):
    seq = max(int(float(c.read("FPLCMDACK")[0] or 0)), int(time.time()) % 1000000) + 1
    c.write("FPLCMD", "%d %s" % (seq, verb)); time.sleep(1.5)
    keys("after " + verb)
def tap(x, y):
    subprocess.run(["xdotool", "mousemove", str(x), str(y), "click", "1"], env={"DISPLAY": ":0"})
def grab(name):
    for n in ("_tmp", name):
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "x11grab", "-video_size", "1920x1080", "-i", ":0",
                        "-frames:v", "1", "shots/%s.png" % n], env={"DISPLAY": ":0"}); time.sleep(1)
threading.Thread(target=feeder, daemon=True).start()
try:
    pose["p"] = (RW15[0], RW15[1], 152.0, 0.0, 30.0); time.sleep(4)
    keys("on runway")
    cmd("ACT 2"); time.sleep(3); keys("VA active")
    tap(1326, 9); time.sleep(3); grab("g1_vectors_fpl")
    tap(1272, 9); time.sleep(4); grab("g1_vectors_map")
    # climb out on the VA heading (152 M = 140 T), 2 nm, 1,500 ft, 90 kt
    for i in range(1, 9):
        la, lo = dest(RW15[0], RW15[1], (152.0 - MAGVAR) % 360, 0.25 * i)
        pose["p"] = (la, lo, 152.0, 90.0, 30 + 190 * i); time.sleep(1.2)
    time.sleep(2); keys("climbed 2 nm on HDG 152")
    cmd("RESUME"); time.sleep(4); keys("resumed")
    tap(1326, 9); time.sleep(3); grab("g2_resumed_fpl")
    tap(1272, 9); time.sleep(4); grab("g2_resumed_map")
finally:
    stop.set(); tap(1326, 9)
