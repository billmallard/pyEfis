# CERT1b (AER-5269): print value and flags (a o b f s) of FIX keys as the
# gateway holds them, over netfix @r, plus each key's TOL (@q), with a UTC stamp.
# Usage: fixflags.py [--tol] KEY...
import socket, sys, time
keys = [k for k in sys.argv[1:] if not k.startswith("--")]
s = socket.create_connection(("127.0.0.1", 3490)); s.settimeout(1.0)
s.sendall("".join(("@q%s\n" % k if "--tol" in sys.argv else "") + "@r%s\n" % k for k in keys).encode())
buf, want = b"", len(keys) * (2 if "--tol" in sys.argv else 1)
end = time.monotonic() + 2
while buf.count(b"\n") < want and time.monotonic() < end:
    try:
        buf += s.recv(4096)
    except socket.timeout:
        break
lines = [l for l in buf.decode().splitlines() if l.startswith(("@r", "@q"))]
print(time.strftime("%H:%M:%S", time.gmtime()) + "." + "%03d" % (time.time() % 1 * 1000), " ".join(lines))
