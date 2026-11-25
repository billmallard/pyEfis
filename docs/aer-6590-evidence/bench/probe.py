"""Pulse the TESS1 spike page's keys over netfix and read each target back."""
import socket
import sys
import time

PORT = int(sys.argv[1])
s = socket.create_connection(("127.0.0.1", PORT))
f = s.makefile("r")


def cmd(line):
    # Skip the replies to earlier writes; answer with this command's own.
    s.sendall((line + "\n").encode())
    prefix = line.split(";")[0] + ";"
    while True:
        r = f.readline().strip()
        if r.startswith(prefix):
            return r


def read(key):
    return float(cmd("@r" + key).split(";")[1])


def pulse(key):
    # Both writes in one send: True then False back to back, as the plugin's
    # in-process {pulse: KEY} does.
    s.sendall(("@w%s;True\n@w%s;False\n" % (key, key)).encode())
    time.sleep(1.5)


PAGE = [  # (panel key id, label, pulsed key, target)
    (2, "BARO -", "TSBTN11", "BARO"),
    (3, "BARO +", "TSBTN12", "BARO"),
    (5, "HDG -", "TSBTN129", "HEADBUG"),
    (6, "HDG +", "TSBTN131", "HEADBUG"),
    (7, "HDG SYNC", "TSBTN130", "HEADBUG"),
    (9, "CDI SRC", "TSBTN133", "NAVSRC"),
]
print("time %s" % time.strftime("%FT%TZ", time.gmtime()))
changed = 0
for kid, label, key, target in PAGE:
    if key == "TSBTN130":
        # Move the bug well off the heading first, so a sync is visible.
        cmd("@wHEADBUG;%.1f" % ((read("HEAD") + 50) % 360))
        time.sleep(1.0)
    before = read(target)
    pulse(key)
    after = read(target)
    extra = " HEAD=%.1f" % read("HEAD") if key == "TSBTN130" else ""
    ok = after != before
    changed += ok
    print("key %d %-8s pulse %-9s %s %.2f -> %.2f %s%s"
          % (kid, label, key, target, before, after,
             "CHANGED" if ok else "unchanged", extra))
print("changed %d of %d" % (changed, len(PAGE)))
