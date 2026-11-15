"""Feed fix-gateway's onspeed plugin from tools/onspeed_sim.py (AER-5086).

Uses the simulator's own profile (onspeed_sim.state_at) and the plugin's
sprintf copy (sentence.encode), unchanged. The only addition is the clock:
the control file CTL holds "live" (the simulator's real-time sweep) or
"hold <t>" (the profile frozen at t seconds), so a frame can be grabbed
without the AOA moving under it. Prints the pty path on the first line.
"""
import os, pty, sys, time, tty
sys.path.insert(0, os.path.expanduser("~/src/fix-gateway/tools"))
sys.path.insert(0, os.path.expanduser("~/src/fix-gateway/src"))
import onspeed_sim
from fixgw.plugins.onspeed.sentence import encode

ctl = sys.argv[1]
master, slave = pty.openpty()
tty.setraw(slave)
print(os.ttyname(slave), flush=True)
t0 = time.monotonic()
while True:
    try:
        mode = open(ctl).read().split()
    except OSError:
        mode = ["live"]
    t = float(mode[1]) if mode and mode[0] == "hold" else time.monotonic() - t0
    os.write(master, (encode(onspeed_sim.state_at(t)) + "\r\n").encode("ascii"))
    time.sleep(1.0 / onspeed_sim.RATE_HZ)
