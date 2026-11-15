#!/usr/bin/env python3
#  SPDX-License-Identifier: GPL-2.0-or-later
"""Render the moving map with a loaded route, offscreen, at KSBA and GVO.

G59 (billmallard/pyEfis#375) evidence: route waypoints that are also an
airport or a VOR must draw once. This is render_map_style_evidence.py's
real ``MovingMap`` (real layer workers, real data packs, the mock FIX db)
with a route published through the real ``FixBridge``: KSBA RZS GVO KSMX,
coordinates read from the packs, the leg to GVO active. One PNG per
``<scene>_<range>``, track 0, the aircraft a third of the range south of
the scene's point. Run it on dev and on the branch and compare.

    QT_QPA_PLATFORM=offscreen ~/pyefis-venv/bin/python \\
        tools/render_route_drawn_once_evidence.py --data /data/makerplane-data \\
        --ranges 2 20 --out out/
"""

import argparse
import os
import sqlite3
import sys

import render_map_style_evidence as rm   # sets up sys.path and the mock FIX

from PyQt6.QtWidgets import QApplication  # noqa: E402

ROUTE = (("KSBA", "airport"), ("RZS", "vor"), ("GVO", "vor"), ("KSMX", "airport"))
#: scene -> the route point it looks at. North up-track, the aircraft a
#: third of the range south of it, so the ownship arrow does not cover it.
SCENES = {"ksba": "KSBA", "gvo": "GVO"}
_BEHIND = 1.0 / 3.0

_ENGINE = {
    "FPLSTATE": ("int", 1), "FPLACTLEG": ("int", 3), "FPLPHASE": ("str", "ENR"),
    "FPLAPR": ("int", 0), "FPLINTEG": ("bool", True), "CDISCALE": ("float", 2.0),
    "FPLCRS": ("float", 0.0), "FPLXTK": ("float", 0.0), "FPLCDI": ("float", 0.0),
    "FPLTF": ("int", 1), "FPLFRLAT": ("float", 0.0), "FPLFRLON": ("float", 0.0),
    "WPNAME": ("str", "GVO"), "WPLAT": ("float", 0.0), "WPLON": ("float", 0.0),
    "WPFROM": ("str", "RZS"), "WPNEXT": ("str", "KSMX"), "WPDIS": ("float", 0.0),
    "WPETE": ("int", 0), "FPLREMDIS": ("float", 0.0), "FPLREMETE": ("int", 0),
    "FPLALERT": ("bool", False), "GPSSRC": ("int", 0), "FPLACTSEG": ("int", 0),
    "FPLSEGREM": ("float", 0.0),
}
_BOUNDS = {"float": (-1e9, 1e9), "int": (-1_000_000, 1_000_000),
           "bool": (None, None), "str": (None, None)}


def _lookup(data):
    """ident -> (lat, lon) from the installed airports and navaids packs."""
    paths = rm._paths(data)
    out = {}
    con = sqlite3.connect(paths["nasr_db_path"])
    for ident, kind in ROUTE:
        if kind == "airport":
            # The pack keeps the FAA id (SBA); NASRAirportDB adds the K.
            out[ident] = con.execute("SELECT lat, lon FROM airports WHERE icao IN (?, ?)",
                                     (ident, ident[1:])).fetchone()
    con = sqlite3.connect(paths["navaid_db_path"])
    for ident, kind in ROUTE:
        if kind == "vor":
            out[ident] = con.execute(
                "SELECT lat, lon FROM navaids WHERE id=? AND type NOT LIKE '%VOT%'",
                (ident,)).fetchone()
    missing = [i for i, v in out.items() if v is None]
    if missing:
        sys.exit("not in the packs: %s" % ", ".join(missing))
    return out


def _publish(coords):
    from pyavtools import fix
    from pyefis.flightplan import fixbridge
    from pyefis.flightplan import model as fp_model

    def define(key, dtype, value):
        lo, hi = _BOUNDS[dtype]
        fix.db.define_item(key, key, dtype, lo, hi, "", 50000, "")
        fix.db.set_value(key, value)
        it = fix.db.get_item(key)
        it.bad = it.fail = it.old = False

    for key, dtype, blank in fixbridge.route_key_specs():
        define(key, dtype, blank)
    for key, (dtype, value) in _ENGINE.items():
        define(key, dtype, value)
    fixbridge.FixBridge(fix).publish(fp_model.FlightPlan(name="G59", waypoints=[
        fp_model.Waypoint(id=i, type=k, lat=coords[i][0], lon=coords[i][1])
        for i, k in ROUTE]))
    # The engine has loaded this route (else the layer draws only the
    # active leg); the mock db would otherwise auto-define FPLLDSEQ as 0.
    define("FPLLDSEQ", "int", fix.db.get_item("FPLSEQ").value)
    # The active leg RZS -> GVO, from the engine's own FROM/TO outputs.
    for key, ident in (("FPLFR", "RZS"), ("WP", "GVO")):
        fix.db.set_value(key + "LAT", coords[ident][0])
        fix.db.set_value(key + "LON", coords[ident][1])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--data", default="/data/makerplane-data")
    ap.add_argument("--ranges", type=float, nargs="+", default=[2.0, 20.0])
    ap.add_argument("--scenes", nargs="+", default=sorted(SCENES))
    ap.add_argument("--width", type=int, default=800)
    ap.add_argument("--height", type=int, default=480)
    ap.add_argument("--timeout", type=float, default=60.0)
    ap.add_argument("--out", default=".")
    args = ap.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)

    app = QApplication.instance() or QApplication(sys.argv[:1])
    rm.ri._load_fonts()
    rm.ri._setup_fix()
    coords = _lookup(args.data)
    _publish(coords)
    ok = True
    for scene in args.scenes:
        ident = SCENES[scene]
        for rng in args.ranges:
            a = argparse.Namespace(
                data=args.data, lat=coords[ident][0] - rng * _BEHIND / 60.0,
                lon=coords[ident][1], track=0.0, alt=3500.0, range=rng, ownship=50.0,
                width=args.width, height=args.height, fixes=False,
                airways=False, timeout=args.timeout, out=args.out)
            ok = rm.render("standard", a, app) and ok
            src = os.path.join(args.out, "map_standard.png")
            dst = os.path.join(args.out, "%s_%gnm.png" % (scene, rng))
            os.replace(src, dst)
            print("  -> %s" % dst)
    sys.stdout.flush()
    os._exit(0 if ok else 3)


if __name__ == "__main__":
    main()
