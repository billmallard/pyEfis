#!/usr/bin/env python3
#  SPDX-License-Identifier: GPL-2.0-or-later
"""Evidence for the altimeter tape's selected-altitude box and bug (pyEfis #310).

Renders the tape at the Pi panel's live size (115 x 655 px: 12 x 60 cells of
the 200 x 110 grid at 1920 x 1200, font B612) in five states, over the PFD sky
colour, and writes a contact sheet plus a 4x nearest-neighbour zoom of the box:

    rest      ALTSEL 4500, ALT 4130, at-rest edit hint on
    focused   the same, focused by a real touch through EncoderController
    above     ALTSEL 9000, beyond the top of the visible tape
    below     ALTSEL 1000, beyond the bottom
    novalue   ALTSEL failed: dashes, no bug

The tape is QPainter-drawn (a QGraphicsView, not GL), so an offscreen render
is the same pixels the panel draws.

``--live HOST:PORT`` instead checks the bus: it connects to a running
fix-gateway, focuses the box, turns the inner knob +1 and the outer ring +1,
pushes, and after each step reads ALTSEL back over a SEPARATE netfix socket,
so what is reported is the gateway's value, not pyEfis's local copy. The
original ALTSEL is restored at the end.

    QT_QPA_PLATFORM=offscreen PYTHONPATH=src python3 tools/render_altsel_evidence.py OUTDIR
    QT_QPA_PLATFORM=offscreen PYTHONPATH=src python3 tools/render_altsel_evidence.py --live 127.0.0.1:3490
"""

import argparse
import os
import socket
import sys
import time

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)

W, H = 115, 655
FONT = "B612"
SKY = "#3b6ea8"


def _mock_fix():
    import tests.mock_db.client
    import tests.mock_db.scheduler
    sys.modules["pyavtools.fix.client"] = tests.mock_db.client
    sys.modules["pyavtools.scheduler"] = tests.mock_db.scheduler
    import pyavtools.fix as fix
    fix.initialize({"main": {"FixServer": "localhost", "FixPort": "3490"}})

    def define(key, dtype, lo, hi, value):
        fix.db.define_item(key, key, dtype, lo, hi, "ft", 50000, "")
        fix.db.set_value(key, value)
        item = fix.db.get_item(key)
        item.old = item.bad = item.fail = False
        return item

    define("ALT", "float", -2000, 60000, 4130.0)
    define("ALTSEL", "int", -1000, 60000, 4500)
    return fix




def _make_host(app):
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QWidget
    from pyefis.screens.screenbuilder_encoder import EncoderController

    class Host(QWidget):
        def __init__(self):
            super().__init__()
            self.instruments = {}
            self.encoder_list = []
            self.encoder_list_sorted = []
            self.encoder_current_selection = None
            self.encoder_timeout = 60_000
            self.encoder_timestamp = 0
            self.encoder_control = False
            self.encoder_timer = QTimer()
            self.encoder = None
            self.encoder_button = None
            self.encoder_controller = EncoderController(self)
            self.setStyleSheet(f"background: {SKY}")

        def encoderChanged(self, value=0):
            self.encoder_controller.changed(value)

    host = Host()
    host.resize(W, H)
    return host


def _tape(app, host):
    from pyefis.instruments import altimeter
    t = altimeter.Altimeter_Tape(host, font_family=FONT)
    t.resize(W, H)
    host.instruments[0] = t
    host.show()
    app.processEvents()
    host.encoder_controller.configure_inputs(None)
    return t


def _touch(app, tape):
    from PyQt6.QtCore import QPoint, QPointF, Qt
    from PyQt6.QtGui import QMouseEvent
    box = tape.altsel_display
    c = box.rect().center()
    ev = QMouseEvent(QMouseEvent.Type.MouseButtonPress, QPointF(c),
                     QPointF(box.mapToGlobal(c)), Qt.MouseButton.LeftButton,
                     Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    box.mousePressEvent(ev)
    app.processEvents()


def render(outdir):
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    fix = _mock_fix()
    from pyefis.instruments import edit_focus
    from PIL import Image

    os.makedirs(outdir, exist_ok=True)
    states = [
        ("rest", dict(sel=4500)),
        ("focused", dict(sel=4500, touch=True)),
        ("above", dict(sel=9000)),
        ("below", dict(sel=1000)),
        ("novalue", dict(fail=True)),
    ]
    files = []
    for name, st in states:
        edit_focus.set_at_rest_hint(True)
        sel = fix.db.get_item("ALTSEL")
        sel.fail = sel.bad = bool(st.get("fail"))
        if not st.get("fail"):
            sel.value = st["sel"]
        host = _make_host(app)
        tape = _tape(app, host)
        tape.setAltimeter(4130.0)
        tape.redraw()
        if st.get("touch"):
            _touch(app, tape)
            assert tape.altsel_display.focused, "touch did not focus the box"
        app.processEvents()
        path = os.path.join(outdir, f"{name}_1x.png")
        host.grab().save(path)
        files.append(path)
        owner = edit_focus.owner()
        if owner is not None:
            owner.release_focus()
        host.close()

    ims = [Image.open(f).convert("RGB") for f in files]
    gap = 12
    sheet = Image.new("RGB", (sum(i.width for i in ims) + gap * (len(ims) - 1),
                              H), "white")
    x = 0
    for im in ims:
        sheet.paste(im, (x, 0))
        x += im.width + gap
    sheet.save(os.path.join(outdir, "sheet_1x.png"))

    crops = [Image.open(os.path.join(outdir, f"{n}_1x.png")).convert("RGB")
             .crop((0, 0, W, 90)) for n in ("rest", "focused", "novalue")]
    z = 4
    zoom = Image.new("RGB", (W * z * 3 + gap * 2, 90 * z), "white")
    for i, c in enumerate(crops):
        zoom.paste(c.resize((W * z, 90 * z), Image.NEAREST),
                   (i * (W * z + gap), 0))
    zoom.save(os.path.join(outdir, "box_zoom4x.png"))
    print("wrote", outdir)


def _netfix_read(host, port, key):
    with socket.create_connection((host, port), timeout=3) as s:
        s.sendall(f"@r{key}\n".encode())
        buf = b""
        while not buf.endswith(b"\n"):
            buf += s.recv(256)
    line = buf.decode().strip()
    if "!" in line:
        raise RuntimeError(f"gateway refused read: {line}")
    return line.split(";")[1]


def _netfix_write(host, port, key, value):
    with socket.create_connection((host, port), timeout=3) as s:
        s.sendall(f"{key};{value};0000\n".encode())
        time.sleep(0.2)


def live(hostport):
    host_, port = hostport.rsplit(":", 1)
    port = int(port)
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    import pyavtools.fix as fix
    fix.initialize({"main": {"FixServer": host_, "FixPort": str(port)}})
    original = _netfix_read(host_, port, "ALTSEL")
    alt_now = float(_netfix_read(host_, port, "ALT"))
    print(f"gateway ALTSEL before: {original}   ALT: {alt_now}")

    def settle():
        end = time.time() + 1.0
        while time.time() < end:
            app.processEvents()
            time.sleep(0.02)

    host = _make_host(app)
    tape = _tape(app, host)
    settle()
    ctl = host.encoder_controller
    ok = True
    try:
        _touch(app, tape)
        print("focused by touch:", ctl.focused_instrument() is tape)
        start = int(float(original))
        steps = [("inner +1", lambda: ctl.changed(1), start + 100),
                 ("outer +1", lambda: ctl.outer_changed(1), start + 1100)]
        for label, act, want in steps:
            act()
            settle()
            got = int(float(_netfix_read(host_, port, "ALTSEL")))
            print(f"{label:9s} gateway ALTSEL = {got}  (want {want})")
            ok &= got == want
        alt_now = float(_netfix_read(host_, port, "ALT"))
        want = int(round(alt_now / 100.0)) * 100 if alt_now >= 0 else \
            -int(round(-alt_now / 100.0)) * 100
        ctl.button_changed(True)
        settle()
        got = int(float(_netfix_read(host_, port, "ALTSEL")))
        print(f"push      gateway ALTSEL = {got}  (ALT {alt_now}, want {want})")
        ok &= got == want
        print("focus cleared after push:", ctl.focused_instrument() is None)
    finally:
        _netfix_write(host_, port, "ALTSEL", original)
        print("restored ALTSEL:", _netfix_read(host_, port, "ALTSEL"))
        fix.stop()
    print("LIVE CHECK", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("outdir", nargs="?")
    ap.add_argument("--live", metavar="HOST:PORT")
    a = ap.parse_args()
    if a.live:
        sys.exit(live(a.live))
    if not a.outdir:
        ap.error("OUTDIR is required unless --live is given")
    render(a.outdir)


if __name__ == "__main__":
    main()
