#  SPDX-License-Identifier: GPL-2.0-or-later
"""Renders the HOLDENT2 (AER-6016) evidence images: the moving map's
flight_plan layer alone, offscreen, at the WINCH hold of the KSMX RNAV (GPS)
RWY 30 missed approach. See README.md beside this file.

The engine outputs on the bus are not made up: fix-gateway's own flight-plan
engine (``FIX_GATEWAY_SRC``, a checkout with HOLDENT1) is loaded with the
same route block and flown to each pose, and what it publishes is written to
the FIX keys the map reads. Works on any pyEfis checkout, so running it on
origin/dev gives the "before" images.
"""

import importlib.util
import json
import os
import types
import sys
from pathlib import Path

from PyQt6.QtGui import QColor, QImage, QPainter
from PyQt6.QtWidgets import QApplication, QWidget

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

# The in-memory FIX client the test suite uses (conftest.py): no gateway.
import tests.mock_db.client  # noqa: E402
import tests.mock_db.scheduler  # noqa: E402

sys.modules["pyavtools.fix.client"] = tests.mock_db.client
sys.modules["pyavtools.scheduler"] = tests.mock_db.scheduler

import pyavtools.fix as fix  # noqa: E402

from pyefis.flightplan import fixbridge  # noqa: E402
from pyefis.instruments import map as moving_map  # noqa: E402
from pyefis.instruments.map.layers import flight_plan as fp_layer  # noqa: E402


def _load_engine():
    """fix-gateway's engine.py and the fixgw/geo.py it imports, alone (the
    rest of the gateway and its dependencies are not needed)."""
    root = Path(os.environ["FIX_GATEWAY_SRC"]) / "src" / "fixgw"
    pkg = types.ModuleType("fixgw")
    mods = []
    for name, path in (("fixgw.geo", root / "geo.py"),
                       ("_holdent2_engine", root / "plugins" / "flightplan" / "engine.py")):
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        if name == "fixgw.geo":
            pkg.geo = mod
            sys.modules["fixgw"], sys.modules["fixgw.geo"] = pkg, mod
        spec.loader.exec_module(mod)
        mods.append(mod)
    return mods


fgeo, engine = _load_engine()

FIXTURE = json.loads((REPO / "tests/flightplan/fixtures/fplroute_blocks.json").read_text())
KSMX = FIXTURE["profiles"]["fp8-ksmx-rnav30-missed"]
MAGVAR = KSMX["magvar_deg"]
BG = QColor("#202830")
GS_KT = 120.0

ENGINE = {
    "FPLSTATE": ("int", 0), "FPLACTLEG": ("int", 0), "FPLPHASE": ("str", ""),
    "FPLAPR": ("int", 0), "FPLINTEG": ("bool", False), "CDISCALE": ("float", 0.0),
    "FPLCRS": ("float", 0.0), "FPLXTK": ("float", 0.0), "FPLCDI": ("float", 0.0),
    "FPLTF": ("int", 0), "FPLFRLAT": ("float", 0.0), "FPLFRLON": ("float", 0.0),
    "WPNAME": ("str", ""), "WPLAT": ("float", 0.0), "WPLON": ("float", 0.0),
    "WPFROM": ("str", ""), "WPNEXT": ("str", ""), "WPDIS": ("float", 0.0),
    "WPETE": ("int", 0), "FPLREMDIS": ("float", 0.0), "FPLREMETE": ("int", 0),
    "FPLALERT": ("bool", False), "GPSSRC": ("int", 0), "FPLACTSEG": ("int", 0),
    "FPLSEGREM": ("float", 0.0), "FPLAPRTYPE": ("str", ""), "MAGVAR": ("float", 0.0),
    "FPLLDSEQ": ("int", 0),
    # HOLDENT1. A pre-HOLDENT2 pyEfis reads none of them.
    "FPLHOLDSLOT": ("int", 0), "FPLHOLDENT": ("str", ""), "FPLHOLDCOMMIT": ("bool", False),
}
BOUNDS = {"float": (-1e9, 1e9), "int": (-1_000_000, 1_000_000), "bool": (None, None),
          "str": (None, None)}
# Engine output -> FIX key, for the keys this layer draws from.
OUT_KEYS = {"state": "FPLSTATE", "act_leg": "FPLACTLEG", "phase": "FPLPHASE", "apr": "FPLAPR",
            "fr_lat": "FPLFRLAT", "fr_lon": "FPLFRLON", "wp_lat": "WPLAT", "wp_lon": "WPLON",
            "crs": "FPLCRS", "act_seg": "FPLACTSEG", "hold_slot": "FPLHOLDSLOT",
            "hold_ent": "FPLHOLDENT", "hold_commit": "FPLHOLDCOMMIT"}


def define(key, dtype, value):
    mn, mx = BOUNDS[dtype]
    fix.db.define_item(key, key, dtype, mn, mx, "", 0, "")
    fix.db.set_value(key, value)
    fix.db.get_item(key).bad = False
    fix.db.get_item(key).fail = False


def reset_bus():
    for key, dtype, blank in fixbridge.route_key_specs():
        define(key, dtype, blank)
    for key, (dtype, value) in ENGINE.items():
        define(key, dtype, value)
    fix.db.set_value("MAGVAR", MAGVAR)
    for key, value in KSMX["writes"]:
        fix.db.set_value(key, value)
    fix.db.set_value("FPLLDSEQ", 1)


def engine_route():
    """The engine's own view of the same block: Waypoints and Segments from
    the FPL* keys exactly as written."""
    w = dict(KSMX["writes"])
    wps = [engine.Waypoint(w[f"FPL{n}ID"], w[f"FPL{n}LAT"], w[f"FPL{n}LON"], w[f"FPL{n}TYPE"],
                           w[f"FPL{n}PT"], w[f"FPL{n}CRS"], w[f"FPL{n}DST"], w[f"FPL{n}ALT"],
                           w[f"FPL{n}SPD"], w[f"FPL{n}SGI"], w[f"FPL{n}FLAGS"],
                           w[f"FPL{n}CTRLAT"], w[f"FPL{n}CTRLON"], w[f"FPL{n}TURN"])
           for n in range(1, w["FPLCOUNT"] + 1)]
    segs = [engine.Segment(w[f"FPLS{k}KIND"], w[f"FPLS{k}ID"], w[f"FPLS{k}ENT"], w[f"FPLS{k}EXT"],
                           w[f"FPLS{k}FIRST"], w[f"FPLS{k}LAST"])
            for k in range(1, w["FPLSEGCNT"] + 1)]
    return wps, segs


def fly(command, start, track_true, distances):
    """A fresh engine with the route, *command* given at *start*, then
    updated at each distance (nm) flown from *start* on *track_true*.
    Returns the last outputs."""
    e = engine.Engine()
    wps, segs = engine_route()
    e.load_route(wps, "KSMX", 1, segs)
    e.handle_command(f"1 {command}", (*start, True))
    out = None
    for i, d in enumerate(distances):
        pos = fgeo.destination_point(*start, track_true, d)
        out = e.update(*pos, GS_KT, MAGVAR, True, None, None, 1000.0 + i)
    return out, pos


def publish(out):
    for key, fkey in OUT_KEYS.items():
        fix.db.set_value(fkey, out[key])
    print("   engine:", {k: out[k] for k in ("act_leg", "hold_slot", "hold_ent", "hold_commit")})


def render(owner, centre, range_nm, out, size=(640, 640)):
    layer = fp_layer.FlightPlanLayer()
    layer.configure(owner)
    x = moving_map.MapTransform(centre[0], centre[1], range_nm, 0.0, size[0], size[1], 0.5)
    img = QImage(size[0], size[1], QImage.Format.Format_RGB32)
    img.fill(BG)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    layer.paint(p, x)
    p.end()
    img.save(str(out))
    print("wrote", out)


def main(outdir):
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])  # noqa: F841 (must outlive the renders)
    fix.initialize({"main": {"FixServer": "localhost", "FixPort": "3490"}})
    owner = QWidget()
    owner.perf = None
    wps, _segs = engine_route()
    hannu, winch = wps[8], wps[9]
    centre = fgeo.destination_point(winch.lat, winch.lon, 315.0, 1.5)
    arrival = fgeo.bearing_deg(hannu.lat, hannu.lon, winch.lat, winch.lon)

    # 1. The planned missed approach, HANNU -> WINCH, 6 NM before WINCH:
    #    arrival on the TF leg's track, a parallel entry (predicted).
    reset_bus()
    out, _ = fly("ACT 10", (hannu.lat, hannu.lon), arrival,
                 [0.0, 0.5, fgeo.distance_nm(hannu.lat, hannu.lon, winch.lat, winch.lon) - 6.0])
    publish(out)
    render(owner, centre, 6.0, outdir / "1_planned_parallel_predicted.png")

    # 2. The same, flown on into WINCH: the entry is being flown (committed).
    reset_bus()
    d = fgeo.distance_nm(hannu.lat, hannu.lon, winch.lat, winch.lon)
    out, _ = fly("ACT 10", (hannu.lat, hannu.lon), arrival, [0.0, 0.5, d - 6.0, d - 1.0, d - 0.1, d + 0.05])
    publish(out)
    render(owner, centre, 6.0, outdir / "2_planned_parallel_committed.png")

    # 3. Direct-to WINCH from 10 NM south of it: arrival on 000 true, a
    #    teardrop entry (predicted).
    reset_bus()
    start = fgeo.destination_point(winch.lat, winch.lon, 180.0, 10.0)
    out, _ = fly("DTO 10", start, 0.0, [0.0, 4.0])
    publish(out)
    render(owner, centre, 6.0, outdir / "3_dto_south_teardrop_predicted.png")

    # 4. Direct-to WINCH from 10 NM west of it: arrival on about 090, a
    #    direct entry -- the name only, nothing more drawn.
    reset_bus()
    start = fgeo.destination_point(winch.lat, winch.lon, 270.0, 10.0)
    out, _ = fly("DTO 10", start, 90.0, [0.0, 4.0])
    publish(out)
    render(owner, centre, 6.0, outdir / "4_dto_west_direct_predicted.png")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).parent)
