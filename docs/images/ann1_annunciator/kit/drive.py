"""AER-6347 driver: plays a flight-ish background on the private gateway at
2 Hz, steps the six tile keys through their states, and grabs :47 at each."""
import socket, subprocess, sys, threading, time, os
D = os.path.dirname(os.path.abspath(__file__))
s = socket.create_connection(("127.0.0.1", 3497))
lock = threading.Lock()
bg = {"PITCH": 2.0, "ROLL": 0.0, "IAS": 105.0, "TAS": 110.0, "ALT": 5500.0,
      "HEAD": 87.0, "TRACK": 88.0, "GS": 108.0, "LAT": 34.4275,
      "LONG": -119.8546, "ALAT": 0.0, "AGL": 5400.0, "BARO": 29.92,
      "OAT": 10.0}
tiles = {"APENG": 0, "YDENG": 0, "APALTCAP": 0, "NAVSRC": 2, "ALTSEL": 6000,
         "VS": 0}
ann = {"ALTSEL": 0}
stale = set()
live = {"tiles": False}

def send(line):
    s.sendall((line + "\n").encode())

def writer():
    while not os.path.exists(f"{D}/STOP"):
        with lock:
            for k, v in bg.items():
                send(f"{k};{v};0000")
            if live["tiles"]:
                for k, v in tiles.items():
                    if k in stale:
                        continue
                    send(f"{k};{v};{ann.get(k, 0)}000")
        time.sleep(0.5)

def drain():
    s.settimeout(0.2)
    while not os.path.exists(f"{D}/STOP"):
        try:
            s.recv(65536)
        except Exception:
            pass

threading.Thread(target=writer, daemon=True).start()
threading.Thread(target=drain, daemon=True).start()

def grab(name, settle=3.0):
    time.sleep(settle)
    out = f"{D}/cap_{name}.png"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "x11grab",
                    "-video_size", "1920x1080", "-i", ":47", "-frames:v", "1",
                    out], check=False)
    print(time.strftime("%H:%M:%S"), "grab", name, os.path.exists(out),
          flush=True)

grab("0_before_first_data", 2.0)
with lock:
    live["tiles"] = True
grab("1_all_fresh_off")
steps = [
    ("2_ap_on", lambda: tiles.update(APENG=1)),
    ("3_yd_on", lambda: tiles.update(YDENG=1)),
    ("4_altcap_on", lambda: tiles.update(APALTCAP=1)),
    ("5_nav_vloc1", lambda: tiles.update(NAVSRC=0)),
    ("6_altsel_annunciate", lambda: ann.update(ALTSEL=1)),
    ("7_vs_2000_local_red_is_advisory", lambda: tiles.update(VS=2000)),
]
for name, fn in steps:
    with lock:
        fn()
    grab(name, 1.0 if name == "2_ap_on" else 3.0)
with lock:
    stale.add("APENG")
    send("@fAPENG;o;1")
grab("8_ap_stale_old", 3.0)
with lock:
    stale.add("NAVSRC")
    send("@fNAVSRC;f;1")
grab("9_nav_failed", 2.0)
open(f"{D}/STOP", "w").close()
