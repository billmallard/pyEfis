#!/usr/bin/env python3
"""SVSFLOOR1: log X-Plane's ground under the aircraft (ALT - AGL) from the
Beelink's fix-gateway at 5 Hz. ALT is sim/flightmodel/position/elevation and
AGL is sim/flightmodel/position/y_agl (standing RREF block), so ALT - AGL is
X-Plane's own terrain or runway surface at (LAT, LONG). Stops on a STOP file."""
import os, socket, sys, time
KEYS = ("LAT", "LONG", "ALT", "AGL")
out, stop = sys.argv[1], sys.argv[2]
s = socket.create_connection(("127.0.0.1", 3490), timeout=5)
f = s.makefile("rw", newline="\n")
with open(out, "a") as log:
    while not os.path.exists(stop):
        vals = {}
        for k in KEYS:
            f.write(f"@r{k}\n"); f.flush()
            line = f.readline().strip()
            parts = line.split(";")
            if parts and parts[0] == f"@r{k}" and len(parts) >= 2:
                vals[k] = (parts[1], parts[2] if len(parts) > 2 else "")
        if len(vals) == 4:
            log.write("%.2f,%s\n" % (time.time(), ",".join(
                f"{vals[k][0]},{vals[k][1]}" for k in KEYS)))
            log.flush()
        time.sleep(0.2)
