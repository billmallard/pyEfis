"""AER-6052 rehearsal feeder: write attitude + FD keys into the private
gateway for N seconds (no X-Plane), so the private glass can be checked."""
import socket, sys, time
port, secs, fdeng = int(sys.argv[1]), float(sys.argv[2]), sys.argv[3]
s = socket.create_connection(("127.0.0.1", port), timeout=5)
f = s.makefile("rwb")
vals = dict(PITCH=2.0, ROLL=10.0, ALAT=0.0, TAS=110, IAS=105, ALT=7500, AGL=3000,
            HEAD=120.0, TRACK=120.0, MAGVAR=-12.0, LAT=34.65, LONG=-120.35, VS=0, GS=110,
            FDENG=fdeng, FDPITCH=6.0, FDROLL=-5.0)
t0 = time.time()
while time.time() - t0 < secs:
    for k, v in vals.items():
        f.write(("@w%s;%s\n" % (k, v)).encode()); f.flush(); f.readline()
    time.sleep(0.1)
print("fed", secs, "s, FDENG", fdeng)
