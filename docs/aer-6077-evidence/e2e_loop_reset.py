#  SPDX-License-Identifier: GPL-2.0-or-later
"""DEMO12 (AER-6077) end-to-end check: a real fix-gateway running the demo
(with DEMOLOOP), a real pyavtools client, and the kiosk's visitor reset.

The visitor's VLOC tap is the HSI source tab's own write path
(HSI._send_key). The gateway's NAVSRC is read on a separate raw netfix
socket, so the result is what fix-gateway holds, not pyEfis's local copy.

    python3 e2e_loop_reset.py HOST PORT OUTDIR
"""

import socket
import sys
import time

from PyQt6.QtWidgets import QApplication, QWidget

from pyavtools import fix
import pyefis.kiosk as kiosk
from pyefis.instruments.hsi import HSI

HOST, PORT, OUT = sys.argv[1], int(sys.argv[2]), sys.argv[3]
SRC = {0.0: "NAV1 (VLOC)", 1.0: "NAV2", 2.0: "GPS"}
T0 = time.monotonic()


def say(msg):
    print("t={:6.1f}s {}".format(time.monotonic() - T0, msg), flush=True)


def gateway(key):
    s = socket.create_connection((HOST, PORT), timeout=3)
    s.sendall("@r{}\n".format(key).encode())
    reply = s.recv(1024).decode().strip()
    s.close()
    return reply.split(";")[1]


def pump(seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.02)


class Win(QWidget):
    def showScreen(self, name):
        pass


app = QApplication(sys.argv)
fix.initialize({"main": {"FixServer": HOST, "FixPort": PORT, "FixInitTimeout": 20}})
pump(2)
hsi = HSI(None, font_percent=0.06, cdi_enabled=True)
hsi.resize(320, 320)
win = Win()
kiosk.configure({"enabled": True, "idle_return_s": 600,
                 "defaults": {"NAVSRC": 2, "BARO": 29.92, "ALTSEL": 3000, "MAPRANGE": 2}})
kiosk.initialize(win, fix, [])
pump(1)


def frame(name, label):
    pump(0.5)
    hsi.grab().save("{}/{}.png".format(OUT, name))
    say("{}: gateway NAVSRC={} ({}) DEMOLOOP={}  -> {}.png".format(
        label, gateway("NAVSRC"), SRC.get(float(gateway("NAVSRC"))), gateway("DEMOLOOP"), name))


frame("1_show_default", "kiosk up, demo live")
HSI._send_key("NAVSRC", 0.0)
pump(2)
frame("2_visitor_vloc", "visitor taps VLOC")
loop0 = gateway("DEMOLOOP")
say("waiting for the demo's next loop (DEMOLOOP {} -> ?)".format(loop0))
while gateway("DEMOLOOP") == loop0:
    pump(1)
    if time.monotonic() - T0 > 600:
        say("FAIL: no loop restart within 600 s")
        sys.exit(2)
pump(1.5)
frame("3_next_loop", "next loop")
ok = float(gateway("NAVSRC")) == 2.0
say("resets={} result={}".format(getattr(getattr(kiosk, "resetter", None), "resets", "n/a"), "PASS" if ok else "FAIL"))
sys.exit(0 if ok else 1)
