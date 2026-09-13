#!/usr/bin/env python3
#  SPDX-License-Identifier: GPL-2.0-or-later
"""fp-font-scale evidence renderer (flight_plan text sizing).

Two subcommands, both run from the root of the pyEfis checkout whose ``src``
you want to render (so "before" is run from a pristine origin/dev tree and
"after" from the fix branch):

  render <outdir> <tag> [font_percent] [--sizes 657x1003,1000x600]
      Paints the FPL page (and the Entry page) offscreen and writes
      <outdir>/<tag>_<w>x<h>.png and <outdir>/<tag>_entry_<w>x<h>.png.
  compose <out.png> "<label>=<img>" ...
      Side-by-side strip of already-rendered PNGs with captions.

Environment: QT_QPA_PLATFORM=offscreen, PYTHONPATH="<pyavtools>:src:."

The FIX db is the test harness's in-memory one (``tests.mock_db``, as
``conftest.py`` and ``tools/render_instrument.py`` do) -- importing the real
``pyavtools.fix`` client starts a non-daemon network thread and the process
never exits. The plan is published through the real ``FixBridge`` with
FPLSTATE=DIRECT, FPLREMDIS=55, FPLREMETE=0: the header state in the Beelink
bench report ("KSBA-KSMX", "DIRECT", "55 NM 0:00"). The widget is built the
way the screen builder does it: the factory builder gets the normalised
``font_percent``, then ``apply_options`` setattr's it again.
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.getcwd()
for _p in (ROOT, os.path.join(ROOT, "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from PyQt6.QtCore import QRect, Qt  # noqa: E402
from PyQt6.QtGui import (  # noqa: E402
    QColor, QFont, QFontDatabase, QFontMetrics, QImage, QPainter, QPen)
from PyQt6.QtWidgets import QApplication  # noqa: E402

_FONT_DIRS = ("C:/Windows/Fonts", "/usr/share/fonts/truetype/dejavu")


def _load_fonts():
    # Condensed faces ONLY. Qt reports these files' family as "DejaVu Sans"
    # (style "Condensed"); if the regular-width DejaVuSans.ttf is loaded too,
    # QFont("DejaVu Sans Condensed") -- what the widget asks for -- resolves
    # to the regular-width face and the renders stop matching the bench.
    for d in _FONT_DIRS:
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            if name.lower().startswith("dejavusanscondensed"):
                QFontDatabase.addApplicationFont(os.path.join(d, name))
    # 40 px "KSBA-KSMX": ~212 px condensed, ~231 px regular width, ~360 px for
    # the offscreen no-font fallback.
    probe = QFont("DejaVu Sans Condensed")
    probe.setPixelSize(40)
    adv = QFontMetrics(probe).horizontalAdvance("KSBA-KSMX")
    print("font probe: 40px 'KSBA-KSMX' advance =", adv)
    if not 205 <= adv <= 220:
        print("WARNING: DejaVu Sans Condensed did not resolve to the condensed face")


def render(outdir, tag, raw_fp=None, sizes=((657, 1003), (1000, 600))):
    import tests.mock_db.client
    import tests.mock_db.scheduler
    sys.modules["pyavtools.fix.client"] = tests.mock_db.client
    sys.modules["pyavtools.scheduler"] = tests.mock_db.scheduler
    import pyavtools.fix as fix
    fix.initialize({"main": {"FixServer": "localhost", "FixPort": "3490"}})

    from pyefis.flightplan import model as fp_model
    from pyefis.screens import screenbuilder_factory as factory
    from pyefis.screens import screenbuilder_preferences as prefs
    from tests.instruments.flight_plan.test_flight_plan import _define_all_fp1_keys

    _define_all_fp1_keys(fix)
    fix.db.define_item("LAT", "LAT", "float", -90.0, 90.0, "deg", 0, "")
    fix.db.define_item("LONG", "LONG", "float", -180.0, 180.0, "deg", 0, "")
    for key, value in (("FPLSTATE", 2), ("FPLREMDIS", 55.0), ("FPLREMETE", 0),
                       ("FPLACTLEG", 2), ("FPLINTEG", True),
                       ("LAT", 34.40), ("LONG", -119.80)):
        fix.db.set_value(key, value)
        fix.db.get_item(key).bad = False
        fix.db.get_item(key).fail = False

    waypoints = [
        fp_model.Waypoint(id="KSBA", type="airport", lat=34.42621, lon=-119.84037),
        fp_model.Waypoint(id="GVO", type="vor", lat=34.53142, lon=-120.09106),
        fp_model.Waypoint(id="RZS", type="vor", lat=34.02, lon=-119.55),
        fp_model.Waypoint(id="KSMX", type="airport", lat=34.89892, lon=-120.45758),
    ]

    def build():
        options, font_percent = {}, None
        if raw_fp is not None:
            options["font_percent"] = float(raw_fp)
            font_percent = prefs.normalize_font_percent(float(raw_fp))
        w = factory.build_flight_plan(
            None, {"type": "flight_plan", "options": options},
            font_percent=font_percent, font_family="DejaVu Sans Condensed")
        if font_percent is not None:
            w.font_percent = font_percent  # screenbuilder_options.apply_options
        w._plan = fp_model.FlightPlan(name="KSBA-KSMX", waypoints=list(waypoints))
        w._commit()
        assert w._bridge.available, "FP1 keys not visible to the bridge"
        return w

    os.makedirs(outdir, exist_ok=True)
    for width, height in sizes:
        w = build()
        w.resize(width, height)
        path = os.path.join(outdir, f"{tag}_{width}x{height}.png")
        w.grab().save(path)
        print("wrote", path)

        w = build()
        w.resize(width, height)
        w._footer_add()
        for ch in "KS":
            w._entry_key(ch)
        path = os.path.join(outdir, f"{tag}_entry_{width}x{height}.png")
        w.grab().save(path)
        print("wrote", path)


def compose(out, items):
    imgs = [(label, QImage(path)) for label, path in (i.split("=", 1) for i in items)]
    gap, cap = 16, 44
    width = sum(img.width() for _, img in imgs) + gap * (len(imgs) + 1)
    height = max(img.height() for _, img in imgs) + cap + gap
    canvas = QImage(width, height, QImage.Format.Format_RGB32)
    canvas.fill(QColor("#3a3f47"))
    p = QPainter(canvas)
    f = QFont("DejaVu Sans")
    f.setPixelSize(22)
    p.setFont(f)
    x = gap
    for label, img in imgs:
        p.setPen(QPen(QColor("#ffffff")))
        p.drawText(QRect(x, 0, img.width(), cap), Qt.AlignmentFlag.AlignCenter, label)
        p.drawImage(x, cap, img)
        x += img.width() + gap
    p.end()
    canvas.save(out)
    print("wrote", out)


def main(argv):
    app = QApplication(argv[:1])  # noqa: F841 -- must outlive the renders
    _load_fonts()
    if argv[1] == "render":
        args = argv[2:]
        sizes = ((657, 1003), (1000, 600))
        if "--sizes" in args:
            i = args.index("--sizes")
            sizes = tuple(tuple(int(v) for v in s.split("x"))
                          for s in args[i + 1].split(","))
            del args[i:i + 2]
        render(args[0], args[1], args[2] if len(args) > 2 else None, sizes)
    elif argv[1] == "compose":
        compose(argv[2], argv[3:])
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv)
    sys.stdout.flush()
    os._exit(0)  # never wait on a stray non-daemon thread
