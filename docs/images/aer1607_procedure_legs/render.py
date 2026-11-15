#  SPDX-License-Identifier: GPL-2.0-or-later
"""Renders the PA8 (AER-1607) evidence images: the moving map's
flight_plan layer alone, offscreen, on a plain dark background. See
README.md beside this file for the exact command and what each image shows.

Works on any checkout (it only drives the layer through the FIX keys), so
running it on origin/dev gives the "before" images.
"""

import json
import os
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

from pyefis.flightplan import fixbridge, geo  # noqa: E402
from pyefis.instruments import map as moving_map  # noqa: E402
from pyefis.instruments.map.layers import flight_plan as fp_layer  # noqa: E402

FIXTURE = json.loads((REPO / "tests/flightplan/fixtures/fplroute_blocks.json").read_text())
KSSF = FIXTURE["profiles"]["qa1-missed-coded-turn-kssf-r28"]
BG = QColor("#202830")

# KABQ RNAV (GPS) Y RWY 21, FOXRR transition: the constants fix-gateway's
# tests/plugins/flightplan/test_engine_golden_procedures.py decodes (and
# re-decodes against its committed FAACIFP18 excerpt).
KABQ_BGEYE = (35.12695833, -106.65031667)
KABQ_CFDXH = (35.08599722, -106.62291667)
KABQ_KEIFR = (35.125675, -106.59285556)
KABQ_KAGNE = (35.09366667, -106.56681944)

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
}
BOUNDS = {"float": (-1e9, 1e9), "int": (-1_000_000, 1_000_000), "bool": (None, None),
          "str": (None, None)}


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


def write(pairs):
    for key, value in pairs:
        fix.db.set_value(key, value)


def kabq_writes(seq):
    pts = [("BGEYE", KABQ_BGEYE, "TF", "", 0.0), ("KEIFR", KABQ_KEIFR, "RF", "R", 0.0),
           ("KAGNE", KABQ_KAGNE, "RF", "R", 0.0)]
    out = []
    for i, (ident, (lat, lon), pt, turn, _) in enumerate(pts, start=1):
        radius = geo.distance_nm(*KABQ_CFDXH, lat, lon) if pt == "RF" else 0.0
        out += [(f"FPL{i}ID", ident), (f"FPL{i}LAT", lat), (f"FPL{i}LON", lon),
                (f"FPL{i}TYPE", 4), (f"FPL{i}PT", pt), (f"FPL{i}DST", radius),
                (f"FPL{i}TURN", turn), (f"FPL{i}SGI", 1), (f"FPL{i}FLAGS", 0x20),
                (f"FPL{i}CTRLAT", KABQ_CFDXH[0] if pt == "RF" else 0.0),
                (f"FPL{i}CTRLON", KABQ_CFDXH[1] if pt == "RF" else 0.0)]
    out += [("FPLS1KIND", 4), ("FPLS1ID", "RNAVY21.FOXRR"), ("FPLS1ENT", "BGEYE"),
            ("FPLS1EXT", "KAGNE"), ("FPLS1FIRST", 1), ("FPLS1LAST", 3),
            ("FPLSEGCNT", 1), ("FPLCOUNT", 3), ("FPLNAME", "KABQ RNAV Y21"), ("FPLSEQ", seq)]
    return out


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
    kssf_centre = (29.22, -98.40)

    # 1. KSSF RNAV (GPS) 28 via XTEND with the missed approach, loaded, and
    #    flying the final (FPLACTLEG is the TO slot, RW28).
    reset_bus()
    fix.db.set_value("MAGVAR", KSSF["magvar_deg"])
    write([(k, v) for k, v in KSSF["writes"]])
    fix.db.set_value("FPLLDSEQ", 1)
    route = fixbridge.FixBridge(fix).read_route()
    act = next(i for i, s in enumerate(route.waypoints, start=1) if s.id == "RW28")
    frm = route.waypoints[act - 2]
    to = route.waypoints[act - 1]
    write([("FPLSTATE", 1), ("FPLACTLEG", act), ("FPLFRLAT", frm.lat), ("FPLFRLON", frm.lon),
           ("WPLAT", to.lat), ("WPLON", to.lon)])
    render(owner, kssf_centre, 10.0, outdir / "kssf_rnav28_missed.png")

    # 2. The same procedure, but the commit was rejected by the engine
    #    (FPLLDSEQ stays at the previously loaded commit, 0 here) while the
    #    engine keeps flying the active leg it had.
    fix.db.set_value("FPLSEQ", 2)
    render(owner, kssf_centre, 10.0, outdir / "kssf_rejected.png")

    # 3. KABQ RNAV (GPS) Y RWY 21, FOXRR: two chained RF arcs about CFDXH.
    reset_bus()
    write(kabq_writes(1))
    fix.db.set_value("FPLLDSEQ", 1)
    render(owner, (35.11, -106.605), 3.0, outdir / "kabq_rf_arcs.png")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).parent)
