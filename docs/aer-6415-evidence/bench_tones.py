"""Drive the CAS4 tones on a bench through the real gateway (AER-6415).

Runs ON the bench, beside a running fix-gateway and pyEfis, with the
standard library only:

    python3 bench_tones.py <out_dir> [disconnect|warning]

It samples the playback device's ALSA status every 0.1 s (state and
hw_ptr, from /proc/asound/card<N>/pcm0p/sub0/status) while it walks the
alert states over netfix (127.0.0.1:3490):

  1. quiet: every CAS alert acknowledged (CASACK = CASSEQ).
  2. a CAS caution: whatever caution the gateway holds is re-raised
     unacknowledged... the bench's live HDG FAIL, if it has one, is used as it
     is; the script only reads CASTOP.
  3. an autopilot disconnect: the AFC1 state keys written the way a source
     writes them (every key, 2 Hz), with APDISC set. It is at warning level,
     so it must cut the caution off.
  4. the disconnect acknowledged (APDISC cleared, as the source does on
     APCMD DISC): the caution must come back.
  5. CASACK = CASSEQ: silence.

The ``warning`` scenario instead raises CAS warnings through the real
plugin: the AFC1 keys written with APENG true, then stopped, so the ``cas``
plugin raises AP LINK LOST at warning level (engaged at the loss); that is
acknowledged; then fix-gateway is stopped for 8 s (needs sudo), so pyEfis
raises its own GATEWAY LINK LOST warning, which must sound with no bus at
all, and clears when the gateway returns.

Each phase line in phases.log carries the wall-clock time, so the status log
and pyEfis's "aural:" log lines line up against it.
"""

import os
import socket
import sys
import threading
import time

OUT = sys.argv[1] if len(sys.argv) > 1 else "."
SCENARIO = sys.argv[2] if len(sys.argv) > 2 else "disconnect"
STATUS = "/proc/asound/card0/pcm0p/sub0/status"

AP_STATE = {"APENG": "False", "YDENG": "False", "APLAT": "", "APLATARM": "",
            "APVERT": "", "APVERTARM": "", "APALTCAP": "False"}


class Fix:
    def __init__(self):
        self.s = socket.create_connection(("127.0.0.1", 3490), timeout=3)
        self.f = self.s.makefile("rb")
        self.lock = threading.Lock()

    def read(self, key):
        with self.lock:
            self.s.sendall("@r{}\n".format(key).encode())
            while True:
                line = self.f.readline().decode().strip()
                if line.startswith("@r" + key):
                    return line[len(key) + 3:].split(";")

    def write(self, key, value):
        with self.lock:
            self.s.sendall("{};{}\n".format(key, value).encode())


def sampler(stop, path):
    with open(path, "w") as out:
        while not stop.is_set():
            try:
                with open(STATUS) as f:
                    st = dict((k.strip(), v) for k, v in (
                        l.split(":", 1) for l in f.read().splitlines()
                        if ":" in l))
                state = st.get("state", "?").strip()
                hw = st.get("hw_ptr", "").strip()
            except OSError:
                state, hw = "closed", ""
            out.write("{:.2f} {} {}\n".format(time.time(), state, hw))
            out.flush()
            time.sleep(0.1)


def ap_writer(fix, stop, disc, engaged=False):
    while not stop.is_set():
        for k, v in AP_STATE.items():
            fix.write(k, v)
        fix.write("APENG", "True" if engaged else "False")
        fix.write("APDISC", "True" if disc["on"] else "False")
        time.sleep(0.5)


def main():
    os.makedirs(OUT, exist_ok=True)
    fix = Fix()
    log = open(os.path.join(OUT, "phases.log"), "w")

    def phase(name):
        line = "{:.2f} {} CASTOP={} CASSEQ={} APDISC={}".format(
            time.time(), name, fix.read("CASTOP"), fix.read("CASSEQ"),
            fix.read("APDISC"))
        print(line)
        log.write(line + "\n")
        log.flush()

    stop = threading.Event()
    t = threading.Thread(target=sampler, args=(stop, os.path.join(
        OUT, "pcm_status.log")), daemon=True)
    t.start()
    phase("start")
    time.sleep(6)
    phase("caution (as held)")
    if SCENARIO == "warning":
        aps = threading.Event()
        w = threading.Thread(target=ap_writer, args=(fix, aps, {"on": False},
                                                     True), daemon=True)
        w.start()
        time.sleep(8)
        phase("autopilot engaged, link good")
        aps.set()
        time.sleep(6)
        phase("autopilot link stopped")
        fix.write("CASACK", fix.read("CASSEQ")[0])
        time.sleep(3)
        phase("CAS acknowledged")
        os.system("sudo -n systemctl stop fixgw")
        time.sleep(8)
        phase_t = time.time()
        log.write("{:.2f} gateway stopped 8 s\n".format(phase_t))
        os.system("sudo -n systemctl start fixgw")
        time.sleep(12)
        fix = Fix()
        phase("gateway back")
    else:
        disc = {"on": True}
        aps = threading.Event()
        w = threading.Thread(target=ap_writer, args=(fix, aps, disc),
                             daemon=True)
        w.start()
        time.sleep(6)
        phase("disconnect raised")
        disc["on"] = False
        time.sleep(6)
        phase("disconnect acknowledged")
        fix.write("CASACK", fix.read("CASSEQ")[0])
        time.sleep(4)
        phase("CAS acknowledged")
        aps.set()
        time.sleep(1)
    stop.set()
    t.join()
    phase("end")

if __name__ == "__main__":
    main()
