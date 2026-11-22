#  SPDX-License-Identifier: GPL-2.0-or-later
"""AER-5808: composite AFC4's widgets over an AFC5 GL frame (README.md here).

The GL frame is the SVS/AI widget alone, from tools/svs_capture.py --offscreen
(flight director bars included). Everything the live screen lays OVER that
widget is then built by the real screen builder (pyefis.screens.screenbuilder)
at the bench's live MAP_CTL_TEST geometry and options, plus ap_annunciator,
rendered children-only onto a transparent image, and drawn over the frame.

Usage: python joint.py <scene> <gl_frame.png> <out.png> [live screens yaml]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("REPO") or os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path[:0] = [os.path.join(ROOT, "src"), ROOT]

import tests.mock_db.client  # noqa: E402
import tests.mock_db.scheduler  # noqa: E402
sys.modules["pyavtools.fix.client"] = tests.mock_db.client
sys.modules["pyavtools.scheduler"] = tests.mock_db.scheduler

import yaml  # noqa: E402
from PyQt6.QtCore import QPoint, Qt  # noqa: E402
from PyQt6.QtGui import QImage, QPainter, QRegion  # noqa: E402
from PyQt6.QtWidgets import QApplication, QWidget  # noqa: E402

import pyavtools.fix as fix  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)
fix.initialize({"main": {"FixServer": "localhost", "FixPort": "3490"}})
db = fix.db

from tests.instruments.autopilot.conftest import AFC1_KEYS, INITIAL  # noqa: E402

for key, dtype, lo, hi, tol in AFC1_KEYS:
    db.define_item(key, key, dtype, lo, hi, "", tol, "")
for key, dtype, lo, hi, units, aux in (
        ("IAS", "float", 0, 2000.0, "knots", "Min,Max,V1,V2,Vne,Vfe,Vmc,Va,Vno,Vs,Vs0,Vx,Vy"),
        ("TAS", "float", 0, 2000.0, "knots", ""),
        ("GS", "float", 0, 2000.0, "knots", ""),
        ("VS", "float", -10000, 10000, "ft/min", ""),
        ("ALT", "float", -2000, 60000, "ft", ""),
        ("ALTSEL", "int", -1000, 60000, "ft", ""),
        ("BARO", "float", 0, 35, "inHg", ""),
        ("HEAD", "float", 0, 360, "deg", ""),
        ("TRACK", "float", 0, 360, "deg", ""),
        ("HEADBUG", "float", 0, 360, "deg", ""),
        ("COURSE", "float", 0, 360, "deg", "")):
    db.define_item(key, key, dtype, lo, hi, units, 50000, aux)
ias = db.get_item("IAS")
for aux, v in (("Vs0", 48), ("Vs", 55), ("Vfe", 85), ("Vno", 128), ("Vne", 160)):
    ias.set_aux_value(aux, v)

_orig_get = db.get_item


def _get_item(key, *a, **kw):
    # Any other key a widget asks for (the HSI's nav keys): define it, fresh,
    # the render_instrument.py way, so the screen builds without a gateway.
    try:
        return _orig_get(key, *a, **kw)
    except Exception:
        db.define_item(key, key, "float", 0, 100, "", 50000, "")
        item = _orig_get(key, *a, **kw)
        item.bad = item.fail = item.old = False
        return item


db.get_item = _get_item


def put(key, value):
    item = db.get_item(key)
    item.value = value
    item.old = item.bad = item.fail = False


# Scene states. "before" is the reading the screen is built on; "after" is
# applied once it is up, so a mode that changed there is boxed and flashing.
COMMON = {"APENG": True, "YDENG": True, "FDENG": True, "BARO": 29.92}
SCENES = {
    "ksba_final": dict(
        caption="KSBA final, 700 ft: GPS just captured, VS -500",
        air={"IAS": 75.0, "TAS": 76.0, "GS": 72.0, "ALT": 700.0, "VS": -480.0,
             "HEAD": 75.0, "TRACK": 75.0, "HEADBUG": 75.0, "COURSE": 74.0,
             "ALTSEL": 2000},
        before={"APLAT": "HDG", "APLATARM": "GPS", "APVERT": "VS",
                "APVERTARM": "", "VSSEL": -500},
        after={"APLAT": "GPS", "APLATARM": ""}),
    "mtn_climb": dict(
        caption="Climb at 8500 ft: HDG (GPS armed), IAS 90 (ALT armed)",
        air={"IAS": 92.0, "TAS": 104.0, "GS": 100.0, "ALT": 8500.0, "VS": 650.0,
             "HEAD": 270.0, "TRACK": 270.0, "HEADBUG": 255.0, "COURSE": 270.0,
             "ALTSEL": 10500},
        before={"APLAT": "HDG", "APLATARM": "GPS", "APVERT": "IAS",
                "APVERTARM": "ALT", "IASSEL": 90.0},
        after={}),
    "bank_turn": dict(
        caption="Banked 25 right at 8500 ft: HDG, ALT 8500 (held)",
        air={"IAS": 110.0, "TAS": 124.0, "GS": 118.0, "ALT": 8500.0, "VS": 0.0,
             "HEAD": 200.0, "TRACK": 200.0, "HEADBUG": 230.0, "COURSE": 200.0,
             "ALTSEL": 8500},
        before={"APLAT": "HDG", "APLATARM": "", "APVERT": "ALT",
                "APVERTARM": "", "APALTREF": 8500},
        after={}),
    "ksba_disc": dict(
        caption="KSBA, AP disconnected (FD still on): red AP until acknowledged",
        air={"IAS": 80.0, "TAS": 81.0, "GS": 78.0, "ALT": 700.0, "VS": 0.0,
             "HEAD": 75.0, "TRACK": 75.0, "HEADBUG": 75.0, "COURSE": 74.0,
             "ALTSEL": 2000},
        before={"APLAT": "GPS", "APLATARM": "", "APVERT": "PIT",
                "APVERTARM": ""},
        after={"APENG": False, "APDISC": True}),
}

# Where the strip goes: across the top of the attitude display, from the
# airspeed tape's left edge to the trend tape's right edge, above the tapes
# (which start at row 6). Not in the live file: the live screen has no strip.
STRIP = {"type": "ap_annunciator", "row": 0, "column": 15,
         "span": {"rows": 5, "columns": 109},
         "options": {"font_family": "B612"}}
# What the live screen draws over the virtual_vfr (columns 0-130).
OVERLAY_TYPES = ("airspeed_tape", "altimeter_tape", "altimeter_trend_tape",
                 "horizontal_situation_indicator")


def main():
    scene, frame_path, out_path = sys.argv[1:4]
    live_path = sys.argv[4] if len(sys.argv) > 4 else os.path.expanduser(
        "~/makerplane/pyefis/config/screens/managed.yaml")
    live = yaml.safe_load(open(live_path))["MAP_CTL_TEST"]
    vvfr = next(i for i in live["instruments"] if i["type"] == "virtual_vfr")
    insts = [i for i in live["instruments"] if i["type"] in OVERLAY_TYPES]
    insts.append(STRIP)
    s = SCENES[scene]

    for key, dtype, *_ in AFC1_KEYS:
        put(key, INITIAL[dtype])
    for k, v in {**COMMON, **s["air"], **s["before"]}.items():
        put(k, v)

    from pyefis.screens.screenbuilder import Screen
    import pyefis.hmi as hmi
    hmi.initialize({})

    cfg = {"layout": live["layout"], "encoder": None, "encoder_button": None,
           "encoder_timeout": None, "instruments": insts}

    class Parent(QWidget):
        config_path = ""
        nodeID = 1
        preferences = {"style": {}, "styles": {}, "gauges": {}, "enabled": {},
                       "includes": {}, "buttons": {}}

        def get_config_item(self, child, key):
            return cfg.get(key)

        def getRunningScreen(self):
            return "MAP_CTL_TEST"

    W, H = 1920, 1200
    screen = Screen(Parent())
    screen.resize(W, H)
    screen.init_screen()
    screen.show()
    app.processEvents()
    # Freeze the strip's clock on a flash ON phase (whole seconds), so a mode
    # that changes below is boxed WITH its text, not caught mid-blink.
    for w in screen.findChildren(QWidget):
        if type(w).__name__ == "ModeAnnunciator":
            w.model.clock = lambda: 1000.0
    for k, v in s["after"].items():
        put(k, v)
    app.processEvents()

    overlay = QImage(W, H, QImage.Format.Format_ARGB32_Premultiplied)
    overlay.fill(Qt.GlobalColor.transparent)
    # Each instrument at its own place, children included: rendering the
    # Screen itself would run its paintEvent, which fills the panel black
    # where the SVS shows on the live screen.
    insts_built = (list(screen.instruments.values())
                   if isinstance(screen.instruments, dict)
                   else list(screen.instruments))
    p = QPainter(overlay)
    for w in insts_built:
        # QWidget.render, not the override a QGraphicsView tape carries.
        QWidget.render(w, p, QPoint(w.x(), w.y()), QRegion(),
                       QWidget.RenderFlag.DrawChildren)
    p.end()

    frame = QImage(frame_path).convertToFormat(QImage.Format.Format_ARGB32)
    cols, rows = live["layout"]["columns"], live["layout"]["rows"]
    vw = round(vvfr["span"]["columns"] * W / cols)
    vh = round(vvfr["span"]["rows"] * H / rows)
    if (frame.width(), frame.height()) != (vw, vh):
        sys.exit(f"GL frame is {frame.width()}x{frame.height()}, the live "
                 f"virtual_vfr is {vw}x{vh}")
    p = QPainter(frame)
    p.drawImage(0, 0, overlay, 0, 0, vw, vh)
    p.end()
    if not frame.save(out_path):
        sys.exit("PNG write failed")
    geo = {type(i).__name__: [i.x(), i.y(), i.width(), i.height()]
           for i in insts_built}
    json.dump({"scene": scene, "caption": s["caption"], "gl_frame": frame_path,
               "state": {**COMMON, **s["air"], **s["before"], **s["after"]},
               "geometry": geo, "live_screen": live_path},
              open(out_path + ".json", "w"), indent=1, default=str)
    print(out_path, geo)


main()
