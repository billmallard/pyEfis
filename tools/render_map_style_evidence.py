#!/usr/bin/env python3
#  SPDX-License-Identifier: GPL-2.0-or-later
"""Render the moving map offscreen at a fixed pose, once per ``map_style``.

G12 (billmallard/pyEfis#135) evidence: the real ``MovingMap`` widget, the
real layer workers and real data packs, with the in-memory mock FIX database
from render_instrument.py (no fix-gateway). It waits until every enabled
layer reports ``is_settled`` before it grabs, so two runs at the same pose
are comparable byte for byte. That is how the "standard renders
byte-identical to dev" claim is checked: run this on dev and on the branch
with ``--styles standard`` and compare the PNGs.

Run it where the data and the fonts are (the Beelink, under
``~/bench-scratch/<issue>``)::

    QT_QPA_PLATFORM=offscreen ~/pyefis-venv/bin/python \\
        tools/render_map_style_evidence.py --data /data/makerplane-data \\
        --lat 34.4262 --lon -119.8404 --track 250 --range 20 \\
        --styles standard nav_only --out out/

Writes ``<out>/map_<style>.png`` and prints each file's sha256.
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


def _paths(data):
    """The packs' installed locations under the makerplane-data root."""
    j = lambda *p: os.path.join(data, *p)  # noqa: E731
    return {
        "tile_path": j("terrain", "tiles"),
        "water_db_path": j("water", "current", "water.sqlite"),
        "highway_db_path": j("highways", "current", "highways.sqlite"),
        "river_db_path": j("rivers", "current", "rivers.sqlite"),
        "nasr_db_path": j("navdata", "current", "airports.sqlite"),
        "navaid_db_path": j("navaids", "current", "navaids.sqlite"),
    }


def render(style, args, app):
    from pyavtools import fix
    from pyefis.instruments.map import MovingMap

    # render_instrument's auto-define gives unknown keys a 0..100 range,
    # which would clamp a western longitude to 0 -- define real ranges.
    for key, lo, hi in (("LAT", -90.0, 90.0), ("LONG", -180.0, 180.0),
                        ("TRACKM", 0.0, 360.0), ("ALT", -1000.0, 60000.0)):
        fix.db.define_item(key, key, "float", lo, hi, "", 50000, "")
    for key, val in (("LAT", args.lat), ("LONG", args.lon),
                     ("TRACKM", args.track), ("ALT", args.alt)):
        it = fix.db.get_item(key)
        fix.db.set_value(key, val)
        it.bad = it.fail = it.old = False

    w = MovingMap()
    for k, v in _paths(args.data).items():
        if os.path.exists(v):
            setattr(w, k, v)
        else:
            print("  missing %s: %s" % (k, v), file=sys.stderr)
    w.map_style = style
    w.range_nm = args.range
    w.ownship_position = args.ownship
    w.layer_fixes = args.fixes
    w.layer_airways = args.airways
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
    # Two more frames so the last published image is the one painted.
    for _ in range(2):
        w.repaint()
        app.processEvents()
    out = os.path.join(args.out, "map_%s.png" % style)
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
    ap.add_argument("--lat", type=float, required=True)
    ap.add_argument("--lon", type=float, required=True)
    ap.add_argument("--track", type=float, default=0.0)
    ap.add_argument("--alt", type=float, default=3500.0)
    ap.add_argument("--range", type=float, default=20.0)
    ap.add_argument("--ownship", type=float, default=50.0)
    ap.add_argument("--width", type=int, default=800)
    ap.add_argument("--height", type=int, default=480)
    ap.add_argument("--fixes", action="store_true")
    ap.add_argument("--airways", action="store_true")
    ap.add_argument("--styles", nargs="+", default=["standard", "nav_only"])
    ap.add_argument("--timeout", type=float, default=60.0)
    ap.add_argument("--out", default=".")
    args = ap.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)

    app = QApplication.instance() or QApplication(sys.argv[:1])
    ri._load_fonts()
    ri._setup_fix()
    ok = all([render(s, args, app) for s in args.styles])
    sys.stdout.flush()
    # Skip interpreter teardown: the layers' daemon workers and the mock
    # FIX scheduler's timers do not shut down cleanly at exit.
    os._exit(0 if ok else 3)


if __name__ == "__main__":
    main()
