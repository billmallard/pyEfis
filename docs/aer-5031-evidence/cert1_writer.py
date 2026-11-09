# CERT1 (AER-5031) bench feed: drive the primary flight keys at 10 Hz over
# netfix so the PFD shows fresh, good data, with roll swinging +-20 deg on
# an 8 s period so a frozen frame is visible as a frozen bank angle.
import math, socket, sys, time
end = time.monotonic() + float(sys.argv[1])
s = socket.create_connection(("127.0.0.1", 3490))
s.settimeout(0.5)
t0 = time.monotonic()
while time.monotonic() < end:
    t = time.monotonic() - t0
    vals = {"PITCH": 3.0, "ROLL": 20.0 * math.sin(2 * math.pi * t / 8.0),
            "ALT": 4500 + 50 * math.sin(2 * math.pi * t / 20.0), "IAS": 110.0,
            "HEAD": 90.0, "VS": 0.0, "ALAT": 0.0, "TAS": 118.0}
    msg = "".join("{0};{1:.2f};000\n".format(k, v) for k, v in vals.items())
    try:
        s.sendall(msg.encode())
    except OSError:
        pass  # gateway stopped: the kernel buffer is full; keep the clock going
    time.sleep(0.1)
