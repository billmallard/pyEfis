"""Render the pyEfis HSI for the wiki's HSI page.

The real HSI widget (pyEfis dev), offscreen, with the option values the bench
panel uses (screens/managed.yaml), connected over netfix to a real
fix-gateway (dev) running only netfix + compute + flightplan. A kinematic
aircraft flies the flight-plan engine's own guidance (desired track plus a
cross-track correction, 120 kt, turns at up to 3 deg/s), so heading, track,
course, deviation and sequencing are consistent with each other. The NAV
radio scenes write the radio keys an X-Plane or CAN-FIX source would publish.

    QT_QPA_PLATFORM=offscreen PYTHONPATH=<pyEfis>/src python3 hsi_docs.py <outdir>
"""
import math
import os
import sys
import time

from PyQt6.QtGui import QColor, QImage, QPainter
from PyQt6.QtWidgets import QApplication

app = QApplication(sys.argv)
import glob  # noqa: E402
from PyQt6.QtGui import QFontDatabase  # noqa: E402
for _ttf in glob.glob(os.path.join(os.environ.get("RENDER_FONT_DIR", "/usr/share/fonts/truetype/dejavu"), "*.ttf")):
    QFontDatabase.addApplicationFont(_ttf)
import pyavtools.fix as fix  # noqa: E402

fix.initialize({"main": {"FixServer": "127.0.0.1", "FixPort": os.environ.get("FIXPORT", "3490")}})
from pyefis.instruments.hsi import HSI  # noqa: E402
from pyefis.screens.screenbuilder_options import apply_options  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fixio import Fix  # noqa: E402

OUT = sys.argv[1]
os.makedirs(OUT, exist_ok=True)
io = Fix()
R_NM = 3440.065
MAGVAR = -11.449  # mag = true + MAGVAR (fix-gateway wrap360(TRACK, MAGVAR)); Santa Barbara area
GS = 120.0
SIZE = (420, 420)
BENCH_OPTIONS = {  # the bench panel's HSI options, as the configurator writes them
    "bg_opacity": "30", "heading_bug_enabled": True, "needle_width": "2",
    "track_indicator_enabled": True, "track_min_speed": "20",
    "orientation": "heading_up", "bearing1_enabled": True, "bearing2_enabled": True,
    "depth_rings": False, "shadow_enabled": True, "readout_layout": "top_panel",
}
BACKDROP = "#1c2a1c"  # stands in for the SVS the bench HSI sits over


def wrap(a):
    return a % 360.0


def brg(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    y = math.sin(lo2 - lo1) * math.cos(la2)
    x = math.cos(la1) * math.sin(la2) - math.sin(la1) * math.cos(la2) * math.cos(lo2 - lo1)
    return math.degrees(math.atan2(y, x)) % 360


def dest(p, bearing, nm):
    la, lo, b, d = math.radians(p[0]), math.radians(p[1]), math.radians(bearing), nm / R_NM
    la2 = math.asin(math.sin(la) * math.cos(d) + math.cos(la) * math.sin(d) * math.cos(b))
    lo2 = lo + math.atan2(math.sin(b) * math.sin(d) * math.cos(la), math.cos(d) - math.sin(la) * math.sin(la2))
    return math.degrees(la2), math.degrees(lo2)


HELD = {}
_last_refresh = [0.0]


def w(key, value):
    """Write a sensor/radio key and keep it fresh: these keys time out
    (old flag) unless rewritten, as a live source would."""
    HELD[key] = value
    io.w(key, value)


def pump(sec):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents()
        if time.time() - _last_refresh[0] > 0.25:
            _last_refresh[0] = time.time()
            for k, v in HELD.items():
                io.w(k, v)
        time.sleep(0.02)


def make_hsi(**over):
    h = HSI(font_percent=None, cdi_enabled=True, gsi_enabled=True, font_family="B612")
    # The screen builder's own option path (type coercion included).
    screen = type("S", (), {"instruments": [h], "encoder_list": []})()
    apply_options(screen, 0, {"type": "horizontal_situation_indicator",
                              "options": dict(BENCH_OPTIONS, **over)})
    h.resize(*SIZE)
    h.show()
    pump(0.3)
    return h


def shot(h, name):
    pump(0.6)
    img = QImage(SIZE[0], SIZE[1], QImage.Format.Format_ARGB32)
    img.fill(QColor(BACKDROP))
    p = QPainter(img)
    p.drawPixmap(0, 0, h.grab())
    p.end()
    img.save(os.path.join(OUT, name + ".png"))
    keys = ("NAVSRC", "COURSE", "CDI", "TOFROM", "HEAD", "HEADBUG", "TRACKM", "BRG1", "BRG2",
            "FPLACTLEG", "FPLPHASE", "CDISCALE", "WPNAME", "FPLMSG", "GSI", "GSV", "CDIV", "NAVTYPE")
    print(name, {k: io.r(k)[0] for k in keys}, flush=True)


def publish(route, name):
    """route: list of dicts id, lat, lon, type, and optional pt/crs/dst/turn."""
    for i, wp in enumerate(route, 1):
        io.w("FPL%dID" % i, wp["id"])
        io.w("FPL%dLAT" % i, wp["lat"])
        io.w("FPL%dLON" % i, wp["lon"])
        io.w("FPL%dTYPE" % i, wp["type"])
        io.w("FPL%dPT" % i, wp.get("pt", "TF"))
        io.w("FPL%dCRS" % i, wp.get("crs", 0.0))
        io.w("FPL%dDST" % i, wp.get("dst", 0.0))
        io.w("FPL%dTURN" % i, wp.get("turn", ""))
        io.w("FPL%dSGI" % i, i)  # one waypoint segment per slot (RS1)
        io.w("FPLS%dKIND" % i, 0)
        io.w("FPLS%dID" % i, "")
        io.w("FPLS%dENT" % i, wp["id"])
        io.w("FPLS%dEXT" % i, wp["id"])
        io.w("FPLS%dFIRST" % i, i)
        io.w("FPLS%dLAST" % i, i)
    io.w("FPLSEGCNT", len(route))
    io.w("FPLCOUNT", len(route))
    io.w("FPLNAME", name)
    io.w("FPLSEQ", int(float(io.r("FPLSEQ")[0] or 0)) + 1)
    pump(0.8)
    print("published", name, "FPLMSG", io.r("FPLMSG")[0], "FPLCOUNT", io.r("FPLCOUNT")[0], flush=True)


_cmd = [500]


def cmd(verb):
    _cmd[0] += 1
    io.w("FPLCMD", "%d %s" % (_cmd[0], verb))
    pump(0.5)
    return io.r("FPLCMDACK")[0], io.r("FPLMSG")[0]


class Aircraft:
    def __init__(self, pos, track_true):
        self.pos = pos
        self.trk = track_true
        self.write()

    def write(self):
        w("GPS_FIX_TYPE", 3)  # these time out like position does
        w("GPS_ACCURACY_HORIZ", 15.0)
        w("MAGVAR", MAGVAR)
        w("GS", GS)
        w("TRACK", self.trk)
        w("HEAD", wrap(self.trk + MAGVAR))
        w("LAT", self.pos[0])
        w("LONG", self.pos[1])

    def step(self, dt=1.0, k=40.0):
        dtk_mag = float(io.r("FPLCRS")[0] or 0.0)
        xtk = float(io.r("FPLXTK")[0] or 0.0)  # + = right of course
        want = wrap(dtk_mag - MAGVAR - max(-30.0, min(30.0, k * xtk)))
        d = (want - self.trk + 540.0) % 360.0 - 180.0
        self.trk = wrap(self.trk + max(-3.0 * dt, min(3.0 * dt, d)))
        self.pos = dest(self.pos, self.trk, GS * dt / 3600.0)
        self.write()
        pump(0.22)  # the engine runs at 5 Hz


def warm(ac, n=6):
    for _ in range(n):
        ac.write()
        pump(0.25)


def check_live():
    v, fl = io.r("FPLCRS")
    print("FPLCRS", v, fl, "WPNAME", io.r("WPNAME")[0], "FPLMSG", io.r("FPLMSG")[0], flush=True)
    if fl[3:4] != "0":
        raise SystemExit("engine guidance not live")


def nav_defaults():
    w("GPSSRC", 0)
    w("NAVSRC", 2)
    w("GPS_FIX_TYPE", 3)
    w("GPS_ACCURACY_HORIZ", 15.0)
    w("BRG1SRC", 2)
    w("BRG2SRC", 0)


# --- Fixes (FAA CIFP; as the bench's V27 golden route) ----------------------
KSBA = (34.42621, -119.84037)
GVO = (34.53131944, -120.09108889)
DEANO = (34.31666389, -119.41645)
HENER = (34.33106389, -119.22768889)
VTU = (34.11506389, -119.0495)

ROUTE = [
    {"id": "KSBA", "lat": KSBA[0], "lon": KSBA[1], "type": 1},
    {"id": "DEANO", "lat": DEANO[0], "lon": DEANO[1], "type": 4},
    {"id": "HENER", "lat": HENER[0], "lon": HENER[1], "type": 4},
    {"id": "VTU", "lat": VTU[0], "lon": VTU[1], "type": 2},
]


def vor1(pos, station=VTU, radial_crs=None):
    """What a NAV1 receiver tuned to `station` would publish at `pos`."""
    b_true = brg(pos, station)
    w("VOR1BRG", wrap(b_true + MAGVAR))
    w("NAV1DH", 1)


def scene_gps_leg_and_flyby():
    nav_defaults()
    publish(ROUTE, "KSBA-VTU DOCS")
    leg = brg(DEANO, HENER)
    start = dest(dest(HENER, wrap(leg + 180), 8.0), wrap(leg + 90), 0.4)
    ac = Aircraft(start, leg)
    warm(ac)
    print("ACT", cmd("ACT 3"), flush=True)
    check_live()
    w("HEADBUG", round(wrap(leg + MAGVAR + 10)))
    h = make_hsi()
    vor1(ac.pos)
    shot(h, "gps_leg_right_of_course")
    # Fly toward HENER; capture around the fly-by turn.
    seen = {"leg": io.r("FPLACTLEG")[0]}
    turned = False
    for i in range(900):
        ac.step()
        vor1(ac.pos)
        if not turned and _dist(ac.pos, HENER) < 2.0 and "before" not in seen:
            seen["before"] = 1
            shot(h, "gps_flyby_1_before_turn")
        trk_err = abs((ac.trk - leg + 540) % 360 - 180)
        if "in" not in seen and trk_err > 25:
            seen["in"] = 1
            shot(h, "gps_flyby_2_in_turn")
        leg_now = io.r("FPLACTLEG")[0]
        if leg_now != seen["leg"]:
            print("sequenced", seen["leg"], "->", leg_now, io.r("FPLMSG")[0], flush=True)
            seen["leg"] = leg_now
            turned = True
            shot(h, "gps_flyby_3_sequenced")
        if turned and "after" not in seen and abs((ac.trk - brg(HENER, VTU) + 540) % 360 - 180) < 2:
            seen["after"] = 1
            shot(h, "gps_flyby_4_on_next_leg")
            break
    h.hide()
    # Arc orientation on the next leg.
    ha = make_hsi(orientation="arc")
    shot(ha, "gps_arc_orientation")
    ha.hide()
    return ac


def _dist(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    return R_NM * 2 * math.asin(math.sqrt(math.sin((la2 - la1) / 2) ** 2
                                          + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2))


def scene_hold():
    nav_defaults()
    inbound_mag = round(wrap(brg(DEANO, HENER) + MAGVAR))
    route = ROUTE[:3] + [{"id": "HENER", "lat": HENER[0], "lon": HENER[1], "type": 4,
                          "pt": "HM", "crs": inbound_mag, "dst": 4.0, "turn": "R"}]
    publish(route, "HOLD HENER DOCS")
    leg = brg(DEANO, HENER)
    ac = Aircraft(dest(HENER, wrap(leg + 180), 4.0), leg)
    warm(ac)
    print("ACT", cmd("ACT 3"), flush=True)
    check_live()
    h = make_hsi()
    shots = {}
    last_phase = None
    for i in range(1500):
        ac.step()
        vor1(ac.pos)
        ph = io.r("FPLPHASE")[0]
        leg_now = io.r("FPLACTLEG")[0]
        crs = float(io.r("FPLCRS")[0] or 0)
        if ph != last_phase:
            print("phase", last_phase, "->", ph, "leg", leg_now, flush=True)
            last_phase = ph
        if ph == "HOLD":
            out_err = abs((crs - wrap(inbound_mag + 180) + 540) % 360 - 180)
            in_err = abs((crs - inbound_mag + 540) % 360 - 180)
            trk_out = abs((wrap(ac.trk + MAGVAR) - wrap(inbound_mag + 180) + 540) % 360 - 180)
            if "outbound" not in shots and out_err < 1 and trk_out < 3:
                shots["outbound"] = 1
                shot(h, "gps_hold_outbound")
            elif "outbound" in shots and "turn_in" not in shots and 60 < in_err < 120:
                shots["turn_in"] = 1
                shot(h, "gps_hold_turn_inbound")
            elif "turn_in" in shots and "inbound" not in shots and in_err < 1 \
                    and abs((wrap(ac.trk + MAGVAR) - inbound_mag + 540) % 360 - 180) < 3:
                shots["inbound"] = 1
                shot(h, "gps_hold_inbound")
                break
    h.hide()


def scene_vor_loc():
    nav_defaults()
    pos = dest(VTU, 290.0, 12.0)  # 12 nm west-north-west of VTU
    w("NAVSRC", 0)
    w("NAVTYPE", 1)
    b_mag = wrap(brg(pos, VTU) + MAGVAR)
    w("NAV1CRS", round(b_mag + 6))
    w("NAV1CDI", 0.55)  # 2 dots right: course is right of the aircraft
    w("NAV1TF", 1)
    w("NAV1DH", 1)
    w("NAV1GSF", 1)  # no glideslope on a VOR
    w("VOR1BRG", b_mag)
    w("HEAD", round(b_mag))
    w("TRACK", wrap(b_mag - MAGVAR))
    w("HEADBUG", round(b_mag))
    h = make_hsi()
    shot(h, "vor1_to")
    w("NAV1TF", 2)
    w("NAV1CRS", round(wrap(b_mag + 180)))
    w("NAV1CDI", -0.3)
    w("HEAD", round(wrap(b_mag + 180)))
    w("TRACK", wrap(b_mag + 180 - MAGVAR))
    w("HEADBUG", round(wrap(b_mag + 180)))
    shot(h, "vor1_from")
    # Localizer with glideslope.
    w("NAVTYPE", 2)
    w("NAV1CRS", 251)
    w("NAV1CDI", -0.2)
    w("NAV1TF", 0)
    w("NAV1GSI", 0.35)
    w("NAV1GSF", 0)
    w("HEAD", 254)
    w("TRACK", wrap(251 - MAGVAR))
    w("HEADBUG", 251)
    shot(h, "loc1_glideslope")
    # Localizer tuned, not received: no localizer and no glideslope.
    w("NAV1DH", 0)
    w("NAV1GSF", 1)
    shot(h, "loc1_no_signal")
    w("NAV1DH", 1)
    h.hide()


def scene_edit():
    """CRS selected for the knob on a VLOC1 source (what a touch on CRS does)."""
    nav_defaults()
    pos = dest(VTU, 290.0, 12.0)
    b_mag = wrap(brg(pos, VTU) + MAGVAR)
    for k, v in (("NAVSRC", 0), ("NAV1CRS", round(b_mag + 6)), ("NAV1CDI", 0.55), ("NAV1TF", 1),
                 ("NAV1DH", 1), ("NAV1GSF", 1), ("VOR1BRG", b_mag), ("HEAD", round(b_mag)),
                 ("TRACK", wrap(b_mag - MAGVAR)), ("HEADBUG", round(b_mag)), ("BRG1SRC", 0)):
        w(k, v)
    h = make_hsi()
    h._edit_pending = "crs"
    print("enc_select", h.enc_select(), flush=True)
    h._edit_pending = None
    shot(h, "vor1_crs_selected")
    h.enc_highlight(False)
    h.hide()


if __name__ == "__main__":
    which = sys.argv[2:] or ["gps", "hold", "vor", "edit"]
    if "edit" in which:
        scene_edit()
    if "gps" in which:
        scene_gps_leg_and_flyby()
    if "hold" in which:
        scene_hold()
    if "vor" in which:
        scene_vor_loc()
    os._exit(0)
