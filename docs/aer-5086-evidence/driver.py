"""Fly the composed PFD while the onspeed feeder drives AOA (AER-5086).

Attitude and position go over netfix at 10 Hz (no simulator on this bench).
PITCH follows the bus AOA at the simulator's own constant -3 deg flight
path (onspeed_sim: pitch = aoa + flight_path), so the scene is consistent
and the limit sits at a fixed ladder pitch, AOA.Warn - 3. Each frame is a
1920x1080 x11grab of the real glass; the bus values read before and after
the grab go into frames.json.
"""
import json, os, socket, subprocess, sys, threading, time

D, CTL = sys.argv[1], sys.argv[2]
SCENE = dict(LAT=34.42721, LONG=-119.87481, ALT=611.0, HEAD=89.0, TRACK=89.0,
             GS=70.0, VS=-370.0, IAS=70.0, TAS=72.0, ALAT=0.0)
state = {"roll": 1.0, "stop": False}  # a real change first: pyEfis may hold a stale ROLL across a fixgw restart

r = socket.create_connection(("127.0.0.1", 3490), timeout=3)
rf = r.makefile("rb")
lock = threading.Lock()

def read(key):
    with lock:
        r.sendall(f"@r{key}\n".encode())
        parts = rf.readline().decode().strip().split(";")
    return parts

def aoa_now():
    p = read("AOA"); w = read("AOA.Warn")
    flags = p[2] if len(p) > 2 else "?????"
    pi = read("PITCH")
    return {"AOA": float(p[1]), "flags_aobfs": flags, "AOA.Warn": w[1] if len(w) > 1 else None,
            "PITCH": float(pi[1])}

def writer():
    w = socket.create_connection(("127.0.0.1", 3490), timeout=3)
    w.setblocking(False)
    while not state["stop"]:
        a = aoa_now()
        bad = a["flags_aobfs"][1:4] != "000"
        pitch = 2.0 if bad else a["AOA"] - 3.0
        msg = f"PITCH;{pitch:.2f};0000\nROLL;{state['roll']:.1f};0000\n"
        msg += "".join(f"{k};{v};0000\n" for k, v in SCENE.items())
        w.sendall(msg.encode())
        try:
            while w.recv(65536):
                pass
        except BlockingIOError:
            pass
        time.sleep(0.1)

def grab(name):
    before = aoa_now()
    out = os.path.join(D, name + ".png")
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "x11grab", "-draw_mouse", "0",
                    "-video_size", "1920x1080", "-i", ":0", "-frames:v", "1", out], check=True)
    after = aoa_now()
    rec = {"frame": name, "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "roll": state["roll"], "before": before, "after": after}
    print(json.dumps(rec), flush=True)
    return rec

def ctl(s):
    open(CTL, "w").write(s)

threading.Thread(target=writer, daemon=True).start()
frames = []
time.sleep(1.0)
HOLDS = [("6-flaps40", 29.6015, 0.0)]
for name, t, roll in HOLDS:
    ctl(f"hold {t}")
    state["roll"] = roll
    time.sleep(5.0)
    frames.append(grab(name + "-a"))
    time.sleep(1.0)
    frames.append(grab(name + "-b"))
# Live: frames through the simulator's flaps-40 sweep (its own clock).
ctl("live")
t0 = time.monotonic()
while True:
    a = aoa_now()
    if a["AOA.Warn"] == "11.5" and a["AOA"] < 2.0:
        break
    time.sleep(0.05)
for i in range(16):
    frames.append(grab(f"8-live-flaps40-{i:02d}"))
    time.sleep(0.4)
state["roll"] = 0.0
ctl("live")
json.dump(frames, open(os.path.join(D, "frames.json"), "w"), indent=1)
state["stop"] = True
