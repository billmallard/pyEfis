#!/usr/bin/env python3
#  SPDX-License-Identifier: GPL-2.0-or-later
"""Render the moving map on a runway's extended centreline (P3g, AER-5459).

Ownship sits ``--back`` NM before the KSBA runway 7 threshold, on its
extended centreline, with the true track (``TRACK``) equal to the runway's
true bearing and ``TRACKM`` = ``TRACK`` + ``MAGVAR``. A map that turns and
points by true track draws the runway straight up the screen in track-up,
and parallel to the ownship arrow in north-up. A map that uses ``TRACKM``
draws both ``MAGVAR`` off.

The real ``MovingMap`` widget, real layer workers and real data packs, with
the in-memory mock FIX database from render_instrument.py (no fix-gateway),
as tools/render_nd_evidence.py does. It waits until every enabled layer
reports ``is_settled`` before it grabs. Run it where the data and the fonts
are (the Beelink, under ``~/bench-scratch/<issue>``)::

    QT_QPA_PLATFORM=offscreen ~/pyefis-venv/bin/python \\
        tools/render_track_evidence.py --data /data/makerplane-data \\
        --width 650 --height 1000 --font B612 --out out/

Scenes: ``north_up``, ``track_up`` (ND off) and ``nd`` (ND EXPANDED, whose
rose should read the magnetic runway heading under the lubber). Writes
``<out>/trk_<scene>.png`` + sidecar and prints each sha256.
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
import render_nd_evidence as nde  # noqa: E402

from PyQt6.QtWidgets import QApplication  # noqa: E402

#: KSBA runway 7/25 ends, from the bench's NASR pack (runway_ends).
RWY07 = (34.427499, -119.85464161)
RWY25 = (34.42791763, -119.83457877)
#: KSBA variation 14 E (NASR airports.mag_var); FIX MAGVAR is west-positive.
MAGVAR = -14.0
NM_DEG = 1.0 / 60.0


def _bearing(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    y = math.sin(lo2 - lo1) * math.cos(la2)
    x = (math.cos(la1) * math.sin(la2)
         - math.sin(la1) * math.cos(la2) * math.cos(lo2 - lo1))
    return math.degrees(math.atan2(y, x)) % 360.0


def _pose(back_nm):
    trk = _bearing(RWY07, RWY25)
    back = math.radians(trk + 180.0)
    lat = RWY07[0] + back_nm * NM_DEG * math.cos(back)
    lon = RWY07[1] + (back_nm * NM_DEG * math.sin(back)
                      / math.cos(math.radians(RWY07[0])))
    return lat, lon, trk


SCENES = {"north_up": ("north_up", "off"), "track_up": ("track_up", "off"),
          "nd": ("track_up", "expanded")}


def render(scene, args, app):
    from pyavtools import fix
    from pyefis.instruments.map import MovingMap

    lat, lon, trk = _pose(args.back)
    orientation, nd_mode = SCENES[scene]
    for key, val in (("LAT", lat), ("LONG", lon), ("TRACK", trk),
                     ("TRACKM", (trk + MAGVAR) % 360.0), ("MAGVAR", MAGVAR),
                     ("ALT", args.alt), ("GS", 95.0), ("TAS", 98.0),
                     ("WINDDIR", 260.0), ("WINDSPD", 8.0)):
        nde._define(fix, key, "float", val, {})
    nde._define(fix, "FPLSTATE", "int", 0, {})

    w = MovingMap(font_family=args.font)
    for k, v in nde._paths(args.data).items():
        if os.path.exists(v):
            setattr(w, k, v)
    w.range_nm = args.range
    w.orientation = orientation
    w.nd_mode = nd_mode
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
    out = os.path.join(args.out, "trk_%s.png" % scene)
    w.grab().save(out)
    w.close()
    try:
        from evidence_sidecar import write_sidecar
        write_sidecar(out)
    except Exception as exc:                    # noqa: BLE001
        print("  no sidecar: %s" % exc, file=sys.stderr)
    with open(out, "rb") as fh:
        digest = hashlib.sha256(fh.read()).hexdigest()
    print("%s  %s  TRACK %.1f TRACKM %.1f%s" % (
        digest, out, trk, (trk + MAGVAR) % 360.0,
        "" if settled else "  (NOT SETTLED)"))
    return settled


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--data", default="/data/makerplane-data")
    ap.add_argument("--range", type=float, default=5.0)
    ap.add_argument("--back", type=float, default=2.0,
                    help="NM before the runway 7 threshold")
    ap.add_argument("--alt", type=float, default=1500.0)
    ap.add_argument("--width", type=int, default=800)
    ap.add_argument("--height", type=int, default=480)
    ap.add_argument("--font", default="DejaVu Sans Condensed")
    ap.add_argument("--scenes", nargs="+", default=list(SCENES))
    ap.add_argument("--timeout", type=float, default=60.0)
    ap.add_argument("--out", default=".")
    args = ap.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)

    app = QApplication.instance() or QApplication(sys.argv[:1])
    ri._load_fonts()
    ri._setup_fix()
    ok = all([render(sc, args, app) for sc in args.scenes])
    sys.stdout.flush()
    # Skip interpreter teardown: the layers' daemon workers and the mock
    # FIX scheduler's timers do not shut down cleanly at exit.
    os._exit(0 if ok else 3)


if __name__ == "__main__":
    main()
