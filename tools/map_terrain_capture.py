#!/usr/bin/env python3
#  SPDX-License-Identifier: GPL-2.0-or-later
"""Capture the moving map at a fixed pose to a PNG (SVSSHADE2, AER-6401).

The map twin of ``tools/svs_capture.py``: the real ``MovingMap`` widget,
fed a mock FIX pose, rendered offscreen (QPainter only, no GL) once every
layer's worker has published the image for that pose. Used for the
side-by-side SVS / map evidence strips of the shared terrain shading.

Example (the KSBA final preview pose, caution mode)::

    QT_QPA_PLATFORM=offscreen python tools/map_terrain_capture.py \\
        --out final_map.png --lat 34.42721 --lon -119.87481 --alt 611 \\
        --track 89 --tiles /data/makerplane-data/terrain/tiles \\
        --nasr /data/makerplane-data/nasr/current/airports.sqlite \\
        --terrain-mode caution
"""

import argparse
import os
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "src"))
sys.path.insert(0, os.path.join(_ROOT, "tests"))

# Run against the mock FIX db, as svs_capture.py does -- no gateway.
import mock_db.client  # noqa: E402
import mock_db.scheduler  # noqa: E402

sys.modules["pyavtools.fix.client"] = mock_db.client
sys.modules["pyavtools.scheduler"] = mock_db.scheduler

import pyavtools.fix as fix  # noqa: E402


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--out", required=True)
    p.add_argument("--lat", type=float, required=True)
    p.add_argument("--lon", type=float, required=True)
    p.add_argument("--alt", type=float, required=True, help="feet MSL")
    p.add_argument("--track", type=float, default=0.0, help="degrees")
    p.add_argument("--range", type=float, default=15.0, dest="range_nm",
                   help="NM from ownship to the top edge")
    p.add_argument("--width", type=int, default=480)
    p.add_argument("--height", type=int, default=480)
    p.add_argument("--tiles", default="")
    p.add_argument("--nasr", default="")
    p.add_argument("--water", default="")
    p.add_argument("--terrain-mode", choices=("relief", "caution"),
                   default="caution")
    p.add_argument("--terrain-palette",
                   choices=("clearance", "subdued", "high_contrast"),
                   default="clearance")
    p.add_argument("--timeout", type=float, default=60.0,
                   help="seconds to wait for the layer workers")
    return p.parse_args(argv)


def seed_mock_fix(args):
    fix.initialize({"main": {"FixServer": "localhost", "FixPort": "3490"}})
    values = {"LAT": args.lat, "LONG": args.lon, "ALT": args.alt,
              "TRACKM": args.track % 360.0, "TRACK": args.track % 360.0,
              "HEAD": args.track % 360.0, "GS": 0.0, "MAGVAR": 0.0}
    ranges = {"LAT": (-90, 90), "LONG": (-180, 180), "ALT": (-2000, 60000),
              "TRACKM": (0, 359.9), "TRACK": (0, 359.9), "HEAD": (0, 359.9),
              "GS": (0, 2000), "MAGVAR": (-30, 30)}
    for key, value in values.items():
        lo, hi = ranges[key]
        fix.db.define_item(key, key, "float", lo, hi, "", 50000, "")
        item = fix.db.get_item(key)
        item.bad = item.fail = item.old = False
        fix.db.set_value(key, value)
    return values


def main(argv=None):
    args = parse_args(argv)
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    seed_mock_fix(args)
    from pyefis.instruments import map as moving_map

    w = moving_map.MovingMap()
    w.tile_path = args.tiles
    w.nasr_db_path = args.nasr
    w.water_db_path = args.water
    w.terrain_mode = args.terrain_mode
    w.terrain_palette = args.terrain_palette
    w.range_nm = args.range_nm
    w.orientation = "track_up"
    w._lat, w._lon, w._alt_ft = args.lat, args.lon, args.alt
    w._track = args.track % 360.0
    w.resize(args.width, args.height)
    w._build_layers()
    terrain = next(lay for lay in w._layers if lay.id == "terrain")

    deadline = time.monotonic() + args.timeout
    img = None
    while time.monotonic() < deadline:
        img = w.grab()
        app.processEvents()
        with terrain._lock:
            have = terrain._img
        if have is not None and have[1] == terrain._key(w._layer_x) \
                and terrain._job is not None and terrain._job[0] == have[1]:
            time.sleep(0.5)          # let the other layers land too
            app.processEvents()
            img = w.grab()
            break
        time.sleep(0.1)
    else:
        print("map: terrain did not settle", file=sys.stderr)
        return 3
    img.save(args.out)
    print(f"map: wrote {args.out} ({args.terrain_mode}, gate "
          f"{terrain._apt_gate})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
