#!/usr/bin/env python3
#  SPDX-License-Identifier: GPL-2.0-or-later
"""Evidence for the ALTSEL deviation alert on the altimeter tape (EFIS-ALTSEL-006).

Same tape, size, font and sky as ``render_altsel_evidence.py`` (the Pi panel's
115 x 655 px). ALTSEL is 4500 in every frame; the ``ALTSEL`` annunciate flag
is set by hand here, as fix-gateway sets it on the bus:

    level     ALT 4500, flag clear: cyan box and bug (the shipped look)
    amber     ALT 4780, flag set: box and bug amber (the default)
    bugonly   ALT 4780, flag set: bug amber, box left cyan
    red       ALT 4780, flag set: box and bug red (alt_bug_alert_color #ff0000)
    cleared   ALT 4560, flag cleared again: back to cyan

``bugonly`` and ``red`` are the alternatives offered for the call on the
glass; the code ships ``amber``. Writes a contact sheet and a 2x
nearest-neighbour zoom of the box-and-bug region of the first four frames.

    QT_QPA_PLATFORM=offscreen PYTHONPATH=src python3 tools/render_altsel_alert_evidence.py OUTDIR

Without Pillow (the bench venv) only the frames are written; compose the
sheet and the zoom elsewhere with ``--compose OUTDIR``.

``--live HOST:PORT OUTDIR`` is the hardware check. A tape connected to a
running fix-gateway through pyavtools (the panel's own path) watches while
this script flies ALT over a separate netfix socket, at 5 Hz so the item stays
fresh. ALTSEL is set to 4500 from ALT 4000, ALT climbs through it, holds, drifts
to 4750, and returns to 4560. At each stop it prints the gateway's ALTSEL
annunciate flag (read over a third socket), the tape's local flag and the
painted bug and box colours, and saves the frame. The gateway alone decides
the flag (arm on capture, threshold, deadband); this script never sets it.
ALTSEL is restored at the end; ALT is left to go old again.

    QT_QPA_PLATFORM=offscreen PYTHONPATH=src python3 tools/render_altsel_alert_evidence.py --live 127.0.0.1:3490 OUTDIR
"""

import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "tools"))

import render_altsel_evidence as base  # noqa: E402

STATES = [
    ("level", dict(alt=4500.0, flag=False)),
    ("amber", dict(alt=4780.0, flag=True)),
    ("bugonly", dict(alt=4780.0, flag=True, box_alert=False)),
    ("red", dict(alt=4780.0, flag=True, alert="#ff0000")),
    ("cleared", dict(alt=4560.0, flag=False)),
]


def render(outdir):
    from PyQt6.QtGui import QColor
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    fix = base._mock_fix()
    from pyefis.instruments import edit_focus
    edit_focus.set_at_rest_hint(False)

    os.makedirs(outdir, exist_ok=True)
    files = []
    for name, st in STATES:
        sel = fix.db.get_item("ALTSEL")
        sel.value = 4500
        sel.annunciate = st["flag"]
        fix.db.get_item("ALT").value = st["alt"]
        host = base._make_host(app)
        tape = base._tape(app, host)
        if "alert" in st:
            tape.alt_bug_alert_color = st["alert"]
            tape.altsel_display.alert_color = QColor(st["alert"])
        if st.get("box_alert") is False:
            tape.altsel_display.alert_color = QColor(tape.alt_bug_color)
        tape.setAltimeter(st["alt"])
        tape.redraw()
        app.processEvents()
        path = os.path.join(outdir, f"{name}_1x.png")
        host.grab().save(path)
        files.append(path)
        host.close()
    try:
        compose(outdir)
    except ImportError:
        print("no Pillow: frames only; run --compose", outdir)


def compose(outdir):
    from PIL import Image
    files = [os.path.join(outdir, f"{name}_1x.png") for name, _ in STATES]
    ims = [Image.open(f).convert("RGB") for f in files]
    gap = 12
    sheet = Image.new("RGB", (sum(i.width for i in ims) + gap * (len(ims) - 1),
                              base.H), "white")
    x = 0
    for im in ims:
        sheet.paste(im, (x, 0))
        x += im.width + gap
    sheet.save(os.path.join(outdir, "sheet_1x.png"))

    # Box at the top through the bug (ALTSEL 4500 is 280 ft, about 183 px,
    # under the ALT 4780 read pointer).
    crop_h = 560
    z = 2
    crops = [im.crop((0, 0, base.W, crop_h)) for im in ims[:4]]
    zoom = Image.new("RGB", (base.W * z * 4 + gap * 3, crop_h * z), "white")
    for i, c in enumerate(crops):
        zoom.paste(c.resize((base.W * z, crop_h * z), Image.NEAREST),
                   (i * (base.W * z + gap), 0))
    zoom.save(os.path.join(outdir, "alert_zoom2x.png"))
    print("wrote", outdir)


# Stops of the live check: (name, ALT to fly to, seconds to hold there,
# expected gateway flag). ALTSEL is 4500 throughout.
LIVE_STOPS = [
    ("climbing", 4100.0, 2.0, False),    # 400 ft off, not yet captured
    ("captured", 4500.0, 3.0, False),    # within threshold: arms, no alert
    ("deviated", 4750.0, 3.0, True),     # 250 ft off a captured altitude
    ("returned", 4560.0, 3.0, False),    # inside threshold - deadband
]


def live(hostport, outdir):
    import time
    from PyQt6.QtGui import QColor
    from PyQt6.QtWidgets import QApplication
    host_, port = hostport.rsplit(":", 1)
    port = int(port)
    app = QApplication.instance() or QApplication([])
    import pyavtools.fix as fix
    fix.initialize({"main": {"FixServer": host_, "FixPort": str(port)}})
    from pyefis.instruments import edit_focus
    edit_focus.set_at_rest_hint(False)
    os.makedirs(outdir, exist_ok=True)

    def read(key):
        line = base._netfix_read(host_, port, key)
        return line

    def read_flags(key):
        with base._netfix_connect(host_, port) as s:
            s.sendall(f"@r{key}\n".encode())
            buf = b""
            while not buf.endswith(b"\n"):
                buf += s.recv(256)
        _k, value, flags = buf.decode().strip().split(";")[-3:]
        return value, flags

    original = read("ALTSEL")
    print(f"gateway before: ALTSEL={original}  ALT={read_flags('ALT')}")
    writer = base._netfix_connect(host_, port)
    writer.setblocking(False)
    state = {"alt": 4000.0, "target": 4000.0}

    def drain():
        try:
            while writer.recv(4096):
                pass
        except (BlockingIOError, InterruptedError):
            pass

    def send(key, value):
        writer.sendall(f"{key};{value};0000\n".encode())
        drain()

    def run(seconds, rate_fpm=3000.0):
        # Fly ALT toward the target at rate_fpm, writing at 5 Hz.
        end = time.time() + seconds
        next_w = 0.0
        while time.time() < end:
            now = time.time()
            if now >= next_w:
                step = rate_fpm / 60.0 * 0.2
                d = state["target"] - state["alt"]
                state["alt"] += max(-step, min(step, d))
                send("ALT", round(state["alt"], 1))
                next_w = now + 0.2
            app.processEvents()
            time.sleep(0.02)

    host = base._make_host(app)
    tape = base._tape(app, host)
    ok = True
    try:
        run(2.0)                                  # ALT good at 4000
        send("ALTSEL", 4500)                      # a new target disarms
        run(1.0)
        for name, alt, hold, want in LIVE_STOPS:
            state["target"] = alt
            run(abs(alt - state["alt"]) / 50.0 + hold)
            _v, flags = read_flags("ALTSEL")
            gw = flags[0] == "1"
            local = bool(tape._altsel.item.annunciate)
            img = host.grab().toImage()
            path = os.path.join(outdir, f"live_{name}_1x.png")
            img.save(path)
            placed = tape.alt_bug_y()
            w = tape.width()
            bug = None
            if placed is not None:
                y = placed[0]
                bug = img.pixelColor(int(w - max(5.0, w * 0.12) / 2),
                                     int(y - max(10.0, w * 0.26) * 0.4))
            box = tape.altsel_display
            border = box.binding.color(box.color, box.alert_color)
            want_rgb = (tape.alt_bug_alert_color if want else tape.alt_bug_color)
            want_c = QColor(want_rgb)
            good = (gw == want and local == want and bug is not None
                    and bug.rgb() == want_c.rgb() and border.rgb() == want_c.rgb())
            ok &= good
            print(f"{name:9s} ALT={state['alt']:7.1f}  gateway ALTSEL flags={flags}"
                  f"  tape flag={int(local)}  bug={bug.name() if bug else None}"
                  f"  box={border.name()}  want {want_c.name()}"
                  f"  {'ok' if good else 'MISMATCH'}")
    finally:
        writer.close()
        base._netfix_write(host_, port, "ALTSEL", original)
        print("restored ALTSEL:", read("ALTSEL"))
        # No fix.stop(): its timers live on pyavtools' scheduler thread, and
        # stopping them from here segfaulted at exit on the Pi. os._exit ends
        # the process anyway.
    print("LIVE CHECK", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["--compose"]:
        compose(args[1])
    elif args[:1] == ["--live"]:
        try:
            rc = live(args[1], args[2])
        except Exception:
            import traceback
            traceback.print_exc()
            rc = 2
        # pyavtools leaves non-daemon threads running (see the sister tool).
        sys.stdout.flush()
        os._exit(rc)
    else:
        render(args[0] if args else "docs/images/aer4436_altsel_alert")
