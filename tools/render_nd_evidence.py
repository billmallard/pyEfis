#!/usr/bin/env python3
#  SPDX-License-Identifier: GPL-2.0-or-later
"""Render the moving map's ND mode offscreen at a fixed pose (G11a, #134).

The real ``MovingMap`` widget, real layer workers and real data packs, with
the in-memory mock FIX database from render_instrument.py (no fix-gateway),
seeded with the ND's inputs for each scene. Like render_map_style_evidence.py
it waits until every enabled layer reports ``is_settled`` before it grabs,
so ``--scenes off`` on dev and on the branch can be compared byte for byte.

Run it where the data and the fonts are (the Beelink, under
``~/bench-scratch/<issue>``)::

    QT_QPA_PLATFORM=offscreen ~/pyefis-venv/bin/python \\
        tools/render_nd_evidence.py --data /data/makerplane-data \\
        --width 650 --height 1000 --font B612 --out out/

Scenes (all at the same pose: 9 NM west of KSBA, tracking 072 toward it):

- ``approach``: plan active to KSBA, glidepath valid, GSI +0.4;
- ``gsflag``:   as approach, GSI bad (red GS flag, no pointer);
- ``noglide``:  no plan (FPLSTATE 0), GSV 0 (no scale, no waypoint block);
- ``off``:      ``nd_mode`` off -- the plain map, for the dev comparison.

Writes ``<out>/nd_<scene>_<style>.png`` (+ sidecar) and prints each sha256.
"""

import argparse
import hashlib
import math
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

KSBA = (34.4262, -119.8404)
POSE = {"lat": 34.380, "lon": -120.000, "track": 72.0, "alt": 2500.0}
GS_KT = 112.0


def _dist_nm(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    c = (math.sin(la1) * math.sin(la2)
         + math.cos(la1) * math.cos(la2) * math.cos(lo2 - lo1))
    return math.degrees(math.acos(max(-1.0, min(1.0, c)))) * 60.0


def _scene(name):
    """(nd_mode, {key: (dtype, value, flags)}) for scene *name*."""
    dis = _dist_nm((POSE["lat"], POSE["lon"]), KSBA)
    keys = {
        "GS": ("float", GS_KT, {}), "TAS": ("float", 118.0, {}),
        "WINDDIR": ("float", 300.0, {}), "WINDSPD": ("float", 14.0, {}),
        "FPLSTATE": ("int", 1, {}), "FPLPHASE": ("str", "TERM", {}),
        "WPNAME": ("str", "KSBA", {}), "WPDIS": ("float", dis, {}),
        "WPETE": ("int", int(dis / GS_KT * 3600.0), {}),
        "GSI": ("float", 0.4, {}), "GSV": ("float", 1.0, {}),
    }
    mode = "expanded"
    if name == "gsflag":
        keys["GSI"] = ("float", 0.4, {"bad": True})
    elif name == "noglide":
        keys.update(FPLSTATE=("int", 0, {}), WPNAME=("str", "", {}),
                    WPDIS=("float", 0.0, {}), WPETE=("int", 0, {}),
                    GSV=("float", 0.0, {}))
    elif name == "off":
        mode = "off"
    return mode, keys


def _paths(data):
    j = lambda *p: os.path.join(data, *p)  # noqa: E731
    return {
        "tile_path": j("terrain", "tiles"),
        "water_db_path": j("water", "current", "water.sqlite"),
        "highway_db_path": j("highways", "current", "highways.sqlite"),
        "river_db_path": j("rivers", "current", "rivers.sqlite"),
        "nasr_db_path": j("navdata", "current", "airports.sqlite"),
        "navaid_db_path": j("navaids", "current", "navaids.sqlite"),
    }


def _define(fix, key, dtype, value, flags):
    lo, hi = {"float": (-1e6, 1e6), "int": (0, 1_000_000),
              "str": (None, None)}[dtype]
    if key in ("LAT", "LONG"):
        lo, hi = (-90.0, 90.0) if key == "LAT" else (-180.0, 180.0)
    fix.db.define_item(key, key, dtype, lo, hi, "", 50000, "")
    fix.db.set_value(key, value)
    it = fix.db.get_item(key)
    it.bad = it.fail = it.old = False
    for k, v in flags.items():
        setattr(it, k, v)


def render(scene, style, args, app):
    from pyavtools import fix
    from pyefis.instruments.map import MovingMap

    mode, keys = _scene(scene)
    for key, val in (("LAT", POSE["lat"]), ("LONG", POSE["lon"]),
                     ("TRACKM", POSE["track"]), ("ALT", POSE["alt"])):
        _define(fix, key, "float", val, {})
    for key, (dtype, val, flags) in keys.items():
        _define(fix, key, dtype, val, flags)

    w = MovingMap(font_family=args.font)
    for k, v in _paths(args.data).items():
        if os.path.exists(v):
            setattr(w, k, v)
    w.map_style = style
    w.range_nm = args.range
    w.layer_fixes = True
    w.layer_airways = True
    w.nd_mode = mode
    w.resize(args.width, args.height)
    w.show()
    deadline = time.monotonic() + args.timeout
    settled = False
    while time.monotonic() < deadline:
        app.processEvents()
        w.repaint()
        if w._layers_built:
            x = w._transform()
            if all(not lay.enabled or lay.is_settled(x) for lay in w._layers):
                settled = True
                break
        time.sleep(0.05)
    for _ in range(2):
        w.repaint()
        app.processEvents()
    out = os.path.join(args.out, "nd_%s_%s.png" % (scene, style))
    w.grab().save(out)
    w.close()
    try:
        from evidence_sidecar import write_sidecar
        write_sidecar(out)
    except Exception as exc:                    # noqa: BLE001
        print("  no sidecar: %s" % exc, file=sys.stderr)
    with open(out, "rb") as fh:
        digest = hashlib.sha256(fh.read()).hexdigest()
    print("%s  %s%s" % (digest, out, "" if settled else "  (NOT SETTLED)"))
    return settled


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--data", default="/data/makerplane-data")
    ap.add_argument("--range", type=float, default=10.0)
    ap.add_argument("--width", type=int, default=800)
    ap.add_argument("--height", type=int, default=480)
    ap.add_argument("--font", default="DejaVu Sans Condensed")
    ap.add_argument("--scenes", nargs="+",
                    default=["approach", "gsflag", "noglide", "off"])
    ap.add_argument("--styles", nargs="+", default=["standard", "nav_only"])
    ap.add_argument("--timeout", type=float, default=60.0)
    ap.add_argument("--out", default=".")
    args = ap.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)

    app = QApplication.instance() or QApplication(sys.argv[:1])
    ri._load_fonts()
    ri._setup_fix()
    ok = all([render(sc, st, args, app)
              for sc in args.scenes for st in args.styles])
    sys.stdout.flush()
    # Skip interpreter teardown: the layers' daemon workers and the mock
    # FIX scheduler's timers do not shut down cleanly at exit.
    os._exit(0 if ok else 3)


if __name__ == "__main__":
    main()
