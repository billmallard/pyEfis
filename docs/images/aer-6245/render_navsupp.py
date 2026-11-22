"""Render the served HSI (Beelink managed.yaml options, 528x403) with NAVSUPP
absent, 0 and 1, VOR and LOC, valid and flagged (SDRVOR3, AER-6245).

Usage: python render_navsupp.py <pyEfis src dir> <out dir>
Env: QT_QPA_PLATFORM=offscreen, LD_LIBRARY_PATH to Qt's libs, FONTCONFIG_FILE.
The HSI is drawn over a flat terrain-colour fill standing in for the SVS that
sits behind it on the served screen (bg_opacity 30)."""
import sys, os
src, out = sys.argv[1], sys.argv[2]
sys.path.insert(0, src)
sys.path.insert(0, os.path.dirname(os.path.abspath(src)))  # the repo, for tests.mock_db
import tests.mock_db.client, tests.mock_db.scheduler  # in-memory FIX db, no server
sys.modules["pyavtools.fix.client"] = tests.mock_db.client
sys.modules["pyavtools.scheduler"] = tests.mock_db.scheduler
os.makedirs(out, exist_ok=True)
from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtGui import QColor, QPainter, QImage
from PyQt6.QtCore import Qt
app = QApplication([])
import pyavtools.fix as fix
fix.initialize({"main": {"FixServer": "localhost", "FixPort": "3490"}})

KEYS = {  # key: (min, max)
    "HEAD": (0, 360), "COURSE": (0, 360), "CDI": (-1, 1), "GSI": (-1, 1),
    "GS": (0, 500), "ROT": (-100, 100), "TRACKM": (0, 360), "HEADBUG": (0, 360),
    "NAVSRC": (0, 2), "NAVTYPE": (0, 3), "CDIV": (0, 1), "GSV": (0, 1),
    "TOFROM": (0, 2), "FPLSTATE": (0, 10), "GPSSRC": (0, 2),
    "NAV1CRS": (0, 360), "NAV2CRS": (0, 360), "VOR1BRG": (0, 360),
    "VOR2BRG": (0, 360), "GPSBRG": (0, 360),
    "BRG1": (0, 360), "BRG2": (0, 360), "BRG1SRC": (0, 3), "BRG2SRC": (0, 3),
}


def setup(navsupp):
    db = fix.db
    for k, (lo, hi) in KEYS.items():
        db.define_item(k, k, "float", lo, hi, "", 0, "")
    if navsupp is not None:
        db.define_item("NAVSUPP", "NAVSUPP", "float", 0, 1, "", 0, "")


def put(k, v, fail=False, old=False):
    fix.db.set_value(k, v)
    it = fix.db.get_item(k)
    it.old = old; it.bad = False; it.fail = fail


OPTIONS = dict(font_family="B612", bg_opacity=30, heading_bug_enabled=True,
               needle_width=2, track_indicator_enabled=True, track_min_speed=20,
               orientation="heading_up", bearing1_enabled=True,
               bearing2_enabled=True, depth_rings=False, shadow_enabled=True,
               readout_layout="top_panel", cdi_enabled=True, gsi_enabled=True)


def render(name, navsupp, navtype, valid):
    setup(navsupp)
    put("HEAD", 290.0); put("HEADBUG", 300.0); put("TRACKM", 288.0); put("GS", 110.0)
    put("COURSE", 303.0); put("NAV2CRS", 303.0); put("NAVSRC", 1.0)
    put("NAVTYPE", float(navtype)); put("GSV", 0.0); put("GSI", 0.0, old=True)  # as the gateway: NAV2GSI has no writer, so GSI reads old
    put("CDIV", 1.0 if valid else 0.0)
    put("CDI", 0.35 if valid else 0.0, fail=not valid)
    put("TOFROM", (1.0 if navtype == 1 else 0.0) if valid else 0.0)
    put("VOR2BRG", 305.0, fail=not (valid and navtype == 1))
    if navsupp is not None:
        put("NAVSUPP", float(navsupp))
    from pyefis.instruments import hsi
    import pyefis.instruments.helpers  # noqa
    w = hsi.HSI(cdi_enabled=True, gsi_enabled=True)
    for k, v in OPTIONS.items():
        if k in ("cdi_enabled", "gsi_enabled"):
            continue
        setattr(w, k, v)
    w.resize(528, 403)
    w.show(); app.processEvents()
    w.resize(529, 403); w.resize(528, 403); app.processEvents()
    grab = w.grab().toImage()
    img = QImage(528, 403, QImage.Format.Format_ARGB32)
    img.fill(QColor(92, 74, 52))   # terrain stand-in behind bg_opacity 30
    p = QPainter(img)
    p.drawImage(0, 0, grab)
    p.end()
    img.save(os.path.join(out, name + ".png"))
    w.close(); w.deleteLater(); app.processEvents()


# NAVSUPP absent must be first: once defined, the key stays in the db.
render("absent_vor_valid", None, 1, True)
render("absent_loc_valid", None, 2, True)
render("absent_vor_flagged", None, 1, False)
for supp in (0, 1):
    render(f"supp{supp}_vor_valid", supp, 1, True)
    render(f"supp{supp}_loc_valid", supp, 2, True)
    render(f"supp{supp}_vor_flagged", supp, 1, False)
    render(f"supp{supp}_loc_flagged", supp, 2, False)
print("done")
