# Steady HSI inputs over netfix for the AER-5548 capture; runs until killed.
import socket, time, sys
# Inputs of the gateway's selects (COURSE/CDI/CDIV/TOFROM), never their
# outputs: a select republishes its output and overwrites a direct write.
VALS = {"HEAD": 87.0, "NAV1CRS": 70.0, "NAV2CRS": 70.0, "EXTCRS": 70.0,
        "NAV1CDI": -0.3, "NAV2CDI": -0.3, "EXTCDI": -0.3,
        "NAV1CDIV": 1.0, "NAV2CDIV": 1.0, "NAV1TF": 1.0, "NAV2TF": 1.0,
        "GPSBRG": 72.0, "VOR1BRG": 40.0, "VOR2BRG": 301.0, "GS": 110.0,
        "TRACKM": 89.0, "HEADBUG": 120.0}
s = socket.create_connection(("127.0.0.1", 3490))
end = time.time() + float(sys.argv[1])
while time.time() < end:
    s.sendall("".join("%s;%s;0000\n" % kv for kv in VALS.items()).encode())
    time.sleep(0.4)
