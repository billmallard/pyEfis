#  SPDX-License-Identifier: GPL-2.0-or-later
"""Bench check for the altimeter tape baro box (pyEfis #311, AER-3914).

Builds an offscreen ALT tape wired to the LIVE fix-gateway on localhost:3490,
touches the box and drives the knob through the real EncoderController, and
after every step reads BARO back over an independent raw netfix socket (@r),
so the value checked is the gateway's, not this process's echo. BARO is put
back to its starting value at the end. It does not touch the display.

    QT_QPA_PLATFORM=offscreen <venv>/bin/python tools/bench_baro_roundtrip.py
"""
import os, socket, sys, time
sys.path.insert(0, "src")
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtTest import QTest
app = QApplication(sys.argv[:1])
import pyavtools.fix as fix
fix.initialize({"main": {"FixServer": "localhost", "FixPort": "3490"}})
fix.db.wait_for_initialization(10)
import pyefis.hmi as hmi
hmi.initialize({})
from pyefis.instruments import altimeter
from pyefis.screens import screenbuilder_options
from pyefis.screens.screenbuilder_encoder import EncoderController

def gw_read():
    s = socket.create_connection(("localhost", 3490), timeout=3)
    s.sendall(b"@rBARO\n"); buf = b""
    while b"\n" not in buf: buf += s.recv(256)
    s.close()
    return float(buf.decode().split(";")[1])

def pump(t=0.6):
    end = time.time() + t
    while time.time() < end: app.processEvents(); time.sleep(0.02)

class Host(QWidget):
    def __init__(s):
        super().__init__()
        s.instruments = {}; s.encoder_list = []; s.encoder_list_sorted = []
        s.encoder_current_selection = None; s.encoder_timeout = 600000
        s.encoder_timestamp = 0; s.encoder_control = False
        s.encoder_timer = QTimer(s); s.encoder = None; s.encoder_button = None
        s.encoder_controller = EncoderController(s)
    def encoderChanged(s, v=0): s.encoder_controller.changed(v)

orig = gw_read()
print("BARO on gateway before:", orig)
h = Host(); h.resize(144, 1200)
t = altimeter.Altimeter_Tape(h); t.setGeometry(0, 0, 144, 1200)
h.instruments[0] = t
screenbuilder_options.configure_tape_baro(h)
h.encoder_controller.configure_inputs(fix); h.show(); pump()
ctl = h.encoder_controller
try:
    QTest.mouseClick(t.viewport(), Qt.MouseButton.LeftButton, pos=t.baro_box_rect().center().toPoint())
    print("focused by touch:", t.encoder_selected)
    ctl.button_changed(True); pump(); print("push (STD): gw", gw_read(), "box", t.baro_text())
    ctl.changed(1); pump(); print("inner +1: gw", gw_read(), "box", t.baro_text())
    ctl.outer_changed(1); pump(); print("outer +1: gw", gw_read(), "box", t.baro_text())
    hmi.actions.trigger("Set Instrument Units", "Pressure:hPa")
    for i in range(3):
        ctl.changed(-1); pump(); v = gw_read()
        print("hPa inner -1: gw %.6f inHg = %.6f hPa, box %s" % (v, v * altimeter.HPA_PER_INHG, t.baro_text()))
    ctl.outer_changed(-1); pump(); v = gw_read()
    print("hPa outer -1: gw %.6f inHg = %.6f hPa, box %s" % (v, v * altimeter.HPA_PER_INHG, t.baro_text()))
finally:
    ctl.release_focus()
    it = fix.db.get_item("BARO"); it.value = orig; it.output_value(); pump()
    print("restored, gw:", gw_read())
os._exit(0)
