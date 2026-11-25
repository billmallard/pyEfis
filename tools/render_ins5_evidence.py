#!/usr/bin/env python3
#  SPDX-License-Identifier: GPL-2.0-or-later
"""Render the INS5 widgets (wind, HSI, AI, moving map) with a good and a
stale or bad source, offscreen (INS5, AER-6588).

The real widgets and, for the map, the real layer workers and data packs,
fed by the in-memory mock FIX database from render_instrument.py (no
fix-gateway). Each stale scene sets one key's flag after the widget is
built, through the FIX item, so the widget's own subscription decides what
it draws. Run it from a dev tree and from the
branch tree and compare: the good scenes must match byte for byte.

Run it where the data and the fonts are (the Beelink, under
``~/bench-scratch/<issue>``)::

    QT_QPA_PLATFORM=offscreen ~/pyefis-venv/bin/python \\
        tools/render_ins5_evidence.py --data /data/makerplane-data --out out/

The AI has no GL offscreen, so its SVS is a stand-in renderer that reports
ready and drawing, as tests/instruments/ai/test_svs_position_quality.py
uses: what is rendered is the AI's own overlay pass (FPM, SVS UNAVAIL).

Writes ``<out>/<widget>_<scene>.png`` and prints each sha256.
"""

import argparse
import hashlib
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_REPO_ROOT, os.path.join(_REPO_ROOT, "src"),
           os.path.join(_REPO_ROOT, "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import render_instrument as ri  # noqa: E402  (mock FIX swap happens here)

from PyQt6.QtWidgets import QApplication  # noqa: E402

# 5 NM south of Aspen (KASE) tracking 330 at 11,500 ft: the Elk Mountains
# around it rise into every caution band. The Beelink's terrain pack covers
# N39W107; it stops short of KSBA (W120).
POSE = {"LAT": 39.150, "LONG": -106.850, "TRACK": 330.0, "TRACKM": 322.0,
        "ALT": 11500.0}

# widget -> {scene: (key, flag) or None}
SCENES = {
    "wind": {"good": None, "hwind_old": ("HWIND", "old")},
    "hsi": {"good": None, "headbug_old": ("HEADBUG", "old"),
            "headbug_fail": ("HEADBUG", "fail"), "gs_old": ("GS", "old")},
    "ai": {"good": None, "track_old": ("TRACK", "old"),
           "magvar_bad": ("MAGVAR", "bad")},
    "map": {"good": None, "lat_bad": ("LAT", "bad"),
            "track_fail": ("TRACK", "fail")},
    "mapcaution": {"good": None, "alt_old": ("ALT", "old")},
}

VALUES = {
    "HWIND": 12.0, "XWIND": -6.0,
    # Consistent with POSE: MAGVAR -8 (8 deg east), so TRACKM = TRACK + MAGVAR
    # and the true heading HEAD - MAGVAR = 333, a 3 deg crab left of track.
    "HEAD": 325.0, "HEADBUG": 350.0, "COURSE": 340.0, "GS": 112.0,
    "PITCH": 3.0, "ROLL": 0.0, "ALAT": 0.0, "TAS": 118.0, "VS": -300.0,
    "MAGVAR": -8.0,
}


def _set(fix, key, value, flags=None):
    # Always (re)define with real bounds: render_instrument's auto-define
    # gives an unknown key 0..100, which clamps LONG, ALT, TRACK and GS.
    lo, hi = ((-90.0, 90.0) if key == "LAT" else
              (-180.0, 180.0) if key in ("LONG", "MAGVAR") else
              (-1e6, 1e6))
    fix.db.define_item(key, key, "float", lo, hi, "", 50000, "")
    fix.db.set_value(key, value)
    it = fix.db.get_item(key)
    it.bad = it.fail = it.old = False
    for k, v in (flags or {}).items():
        setattr(it, k, v)


def _seed(fix):
    for key, value in {**POSE, **VALUES}.items():
        _set(fix, key, value)


def _paths(data):
    j = lambda *p: os.path.join(data, *p)  # noqa: E731
    return {
        "tile_path": j("terrain", "tiles"),
        "water_db_path": j("water", "current", "water.sqlite"),
        "highway_db_path": j("highways", "current", "highways.sqlite"),
        "nasr_db_path": j("navdata", "current", "airports.sqlite"),
    }


def _build(kind, args):
    if kind == "wind":
        from pyefis.instruments.wind import WindDisplay
        from PyQt6.QtGui import QColor, QPalette
        w = WindDisplay(font_family=args.font)
        # The widget paints no background; on the PFD it sits over dark
        # glass, so give the frame black rather than Qt's light window grey.
        pal = w.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor(0, 0, 0))
        w.setPalette(pal)
        w.setAutoFillBackground(True)
        w.resize(200, 90)
        return w
    if kind == "hsi":
        from pyefis.instruments.hsi import HSI
        w = HSI(cdi_enabled=False, gsi_enabled=False)
        w.heading_bug_enabled = True
        w.track_indicator_enabled = True
        w.resize(420, 420)
        return w
    if kind == "ai":
        from unittest import mock
        from pyefis.instruments.ai import AI
        w = AI()
        w.show_fpm = True
        w.horizon_heading_marks = True
        w.resize(480, 360)
        renderer = mock.Mock(enabled=True, ready=True, gl_failed=False,
                             drew_terrain=True)
        w._svs_renderer = renderer
        return w
    from pyefis.instruments.map import MovingMap
    w = MovingMap(font_family=args.font)
    for k, v in _paths(args.data).items():
        if os.path.exists(v):
            setattr(w, k, v)
    w.range_nm = 10.0
    if kind == "map":
        w.nd_mode = "expanded"
    else:
        w.terrain_mode = "caution"
    w.resize(800, 480)
    return w


def _settle(w, kind, app, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        w.repaint()
        if not kind.startswith("map"):
            return True
        if w._layers_built:
            x = w._transform()
            if all(not lay.enabled or lay.is_settled(x) for lay in w._layers):
                return True
        time.sleep(0.05)
    return False


def render(kind, scene, flag, args, app):
    from pyavtools import fix
    _seed(fix)
    w = _build(kind, args)
    for key, value in {**POSE, **VALUES}.items():
        assert fix.db.get_item(key).value == value, key
    w.show()
    if flag is not None:
        key, name = flag
        setattr(fix.db.get_item(key), name, True)
    settled = _settle(w, kind, app, args.timeout)
    for _ in range(2):
        w.repaint()
        app.processEvents()
    out = os.path.join(args.out, "%s_%s.png" % (kind, scene))
    w.grab().save(out)
    w.close()
    with open(out, "rb") as fh:
        digest = hashlib.sha256(fh.read()).hexdigest()
    print("%s  %s%s" % (digest, out, "" if settled else "  (NOT SETTLED)"))
    return settled


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--data", default="/data/makerplane-data")
    ap.add_argument("--font", default="DejaVu Sans Condensed")
    ap.add_argument("--widgets", nargs="+", default=list(SCENES))
    ap.add_argument("--timeout", type=float, default=60.0)
    ap.add_argument("--out", default=".")
    args = ap.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)

    app = QApplication.instance() or QApplication(sys.argv[:1])
    ri._load_fonts()
    ri._setup_fix()
    ok = all([render(kind, scene, flag, args, app)
              for kind in args.widgets
              for scene, flag in SCENES[kind].items()])
    sys.stdout.flush()
    # Skip interpreter teardown: the map's daemon workers and the mock FIX
    # scheduler's timers do not shut down cleanly at exit.
    os._exit(0 if ok else 3)


if __name__ == "__main__":
    main()
