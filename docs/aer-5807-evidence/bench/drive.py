#  SPDX-License-Identifier: GPL-2.0-or-later
"""Drive the real autopilot_panel against a gateway (AER-5807 bench run).

pyEfis's own FIX client connects to the gateway on --port; the panel sits in
a screen stand-in with a real EncoderController. Each step clicks a key or a
box with a synthetic mouse press, waits, checks what the panel shows against
what the source should have answered, and saves the frame.

    QT_QPA_PLATFORM=offscreen PYTHONPATH=<pyEfis>/src python3 drive.py \
        --port 3492 --out frames --layout full
"""

import argparse
import json
import os
import sys
import time

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QColor, QImage
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QWidget

import pyavtools.fix as fix

from pyefis.instruments import autopilot as ap
from pyefis.screens.screenbuilder_encoder import EncoderController


class Host(QWidget):
    def __init__(self):
        super().__init__()
        self.instruments = {}
        self.encoder_list = []
        self.encoder_list_sorted = []
        self.encoder_current_selection = None
        self.encoder_timeout = 10_000
        self.encoder_timestamp = 0
        self.encoder_control = False
        self.encoder_timer = QTimer()
        self.encoder = None
        self.encoder_button = None
        self.encoder_controller = EncoderController(self)

    def encoderChanged(self, value=0):
        self.encoder_controller.changed(value)


def pump(seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QApplication.processEvents()
        time.sleep(0.01)


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--port", default="3492")
    a.add_argument("--out", default="frames")
    a.add_argument("--layout", default="full")
    a.add_argument("--size", default="640x260")
    args = a.parse_args()
    os.makedirs(args.out, exist_ok=True)
    app = QApplication(sys.argv)
    fix.initialize({"main": {"FixServer": "127.0.0.1",
                             "FixPort": str(args.port)}})
    pump(2.0)
    host = Host()
    w, h = (int(v) for v in args.size.split("x"))
    panel = ap.AutopilotPanel(host, font_family="DejaVu Sans")
    panel.setPanelLayout(args.layout)
    host.instruments[0] = panel
    host.resize(w, h)
    panel.resize(w, h)
    host.show()
    host.encoder_controller.configure_inputs(None)
    log = open(os.path.join(args.out, "drive.jsonl"), "w")
    results = []
    t0 = time.monotonic()
    n = [0]

    def shot(name):
        n[0] += 1
        img = QImage(panel.size(), QImage.Format.Format_ARGB32)
        img.fill(QColor(0, 0, 0))
        panel.render(img)
        path = os.path.join(args.out, "%02d_%s.png" % (n[0], name))
        img.save(path)
        return path

    def states():
        return {b: panel.display_state(b) for b in panel.button_widgets}

    def check(step, ok, **detail):
        rec = dict(t=round(time.monotonic() - t0, 2), step=step,
                   result="PASS" if ok else "FAIL",
                   states=states(), message=panel.message()[0],
                   frame=shot(step), **detail)
        log.write(json.dumps(rec) + "\n")
        log.flush()
        results.append(rec["result"])
        print(rec["result"], step, rec["message"], detail)

    def click(widget):
        QTest.mouseClick(widget, Qt.MouseButton.LeftButton,
                         pos=widget.rect().center())

    def btn(name):
        return panel.button_widgets[name]

    pump(1.5)
    st = states()
    check("01_source_up", panel.has_data()
          and all(v in (ap.OFF, ap.UNAVAILABLE) for v in st.values())
          and st["VNAV"] == ap.UNAVAILABLE)

    click(btn("AP"))
    pump(0.1)
    early = panel.display_state("AP")
    pump(1.0)
    check("02_AP_engages", early == ap.PENDING
          and panel.display_state("AP") == ap.ACTIVE, at_100ms=early)

    click(btn("HDG"))
    pump(1.0)
    check("03_HDG_active", panel.display_state("HDG") == ap.ACTIVE)

    click(btn("NAV"))
    seen = set()
    for _ in range(15):
        pump(0.1)
        seen.add(panel.display_state("NAV"))
    pend = panel.display_state("NAV")
    shot("04a_NAV_pending")
    pump(1.0)
    check("04_NAV_refused_never_active",
          pend == ap.PENDING and panel.display_state("NAV") == ap.REFUSED
          and ap.ACTIVE not in seen
          and panel.message()[0] == "NAV: NO NAV SOURCE",
          seen=sorted(seen))

    pump(3.0)
    click(btn("APR"))
    pump(1.0)
    check("05_APR_armed", panel.display_state("APR") == ap.ARMED
          and panel.display_state("NAV") == ap.ARMED)
    pump(3.5)
    check("06_APR_captured", panel.display_state("APR") == ap.ACTIVE
          and panel.display_state("NAV") == ap.ACTIVE)

    click(btn("VS"))
    pump(1.0)
    check("07_VS_active_box_accent", panel.display_state("VS") == ap.ACTIVE
          and panel.display_state("ALT") == ap.ARMED
          and panel.box_accent(ap.BOX_VS))

    ctl = host.encoder_controller
    click(panel.boxes[ap.BOX_ALT])
    ctl.changed(3)
    pump(0.3)
    focused = ctl.focused_instrument() is panel \
        and panel.boxes[ap.BOX_ALT].focused
    sel = fix.db.get_item("ALTSEL").value
    shot("08a_ALTSEL_focused")
    click(btn("LVL"))
    pump(0.8)
    check("08_LVL_with_ALTSEL_focus", focused
          and panel.display_state("LVL") == ap.ACTIVE, altsel=sel,
          focus_released=ctl.focused_instrument() is None)

    pump(3.0)
    click(btn("VNAV"))
    pump(2.4)
    check("09_VNAV_unavailable_refused",
          panel.display_state("VNAV") == ap.REFUSED
          and panel.message()[0] == "VNAV: NOT AVAILABLE")

    # The source stops writing at --run-s; wait for the tol to lapse.
    deadline = time.monotonic() + 40
    while panel.has_data() and time.monotonic() < deadline:
        pump(0.1)
    lost = time.monotonic()
    check("10_source_stops_no_data", not panel.has_data()
          and panel.message()[0] == ap.NO_DATA_TEXT
          and all(v == ap.NO_DATA for v in states().values()))
    log.write(json.dumps({"summary": results.count("PASS"),
                          "of": len(results)}) + "\n")
    print("SUMMARY %d/%d PASS" % (results.count("PASS"), len(results)))
    fix.stop()
    return 0 if all(r == "PASS" for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
