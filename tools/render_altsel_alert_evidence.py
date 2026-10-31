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


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["--compose"]:
        compose(args[1])
    else:
        render(args[0] if args else "docs/images/aer4436_altsel_alert")
