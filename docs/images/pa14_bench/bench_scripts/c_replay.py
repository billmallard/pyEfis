"""c_replay.py: replay PA14 slice C's X-Plane truth (session 2c89084d9ebf) into the live
bench gateway at 2x, Map tab up, grabbing on engine events. No X-Plane running.
Run under the bench lock. Leaves the route loaded, LAT/LONG going old when it ends."""
import csv, gzip, subprocess, time
from nfx import NFX
MAGVAR = -11.34
c = NFX()
rows = [r for r in csv.DictReader(gzip.open("pa14_c_xplane_2026-11-15.csv.gz", "rt")) if 530.0 <= float(r["t"]) <= 1000.0]
def tap(x, y): subprocess.run(["xdotool", "mousemove", str(x), str(y), "click", "1"], env={"DISPLAY": ":0"})
def grab(name):
    for n in ("_tmp", name):
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "x11grab", "-video_size", "1920x1080", "-i", ":0",
                        "-frames:v", "1", "shots/r_%s.png" % n], env={"DISPLAY": ":0"})
def keys(tag):
    line = "%s %s %s" % (time.strftime("%H:%M:%SZ", time.gmtime()), tag, {k: c.read(k)[0][:9] for k in (
        "FPLSTATE", "FPLACTLEG", "FPLPHASE", "FPLAPR", "CDISCALE", "WPNAME", "WPDIS", "FPLCRS", "FPLXTK", "FPLMSG")})
    print(line, flush=True); open("c_replay_keys.txt", "a").write(line + "\n")
def write(r):
    for k, v in (("MAGVAR", MAGVAR), ("GS", r["gs_kt"]), ("TRACK", r["trk"]), ("HEAD", (float(r["trk"]) + MAGVAR) % 360),
                 ("ALT", r["alt_ft"]), ("LAT", r["lat"]), ("LONG", r["lon"])):
        c.write(k, v)
write(rows[0]); time.sleep(2)
seq = abs(int(float(c.read("FPLCMDACK")[0] or 0))) + 1000
c.write("FPLCMD", "%d ACT 10" % seq); time.sleep(2); keys("ACT 10")
tap(1272, 9); time.sleep(2)
shots = {"apr2": False, "half": False, "mipte": False, "susp": False, "missed": False}
t_susp = None
for r in rows:
    t0 = time.time(); write(r)
    apr, leg, st = c.read("FPLAPR")[0], c.read("FPLACTLEG")[0], c.read("FPLSTATE")[0]
    dis = float(c.read("WPDIS")[0] or 0)
    if apr == "2" and leg == "11" and not shots["apr2"]:
        shots["apr2"] = True; keys("approach active"); grab("map_apr_active")
    if apr == "2" and leg == "11" and dis < 1.0 and not shots["half"]:
        shots["half"] = True; keys("1 nm to FAF"); grab("map_ramp_1nm")
    if leg == "13" and st == "1" and dis < 1.5 and not shots["mipte"]:
        shots["mipte"] = True; keys("final, 0.3"); grab("map_final")
    if st == "3" and leg == "13" and not shots["susp"]:
        shots["susp"] = True; t_susp = float(r["t"]); keys("MAP suspend"); grab("map_susp_at_map")
    if t_susp and not shots["missed"] and float(r["t"]) - t_susp >= 8:
        c.write("FPLCMD", "%d RESUME" % (seq + 1)); time.sleep(2); keys("RESUME"); shots["missed"] = True
    if shots["missed"] and float(r["t"]) - t_susp >= 30:
        keys("missed"); grab("map_missed"); break
    time.sleep(max(0.0, 0.1 - (time.time() - t0)))
tap(1326, 9)
