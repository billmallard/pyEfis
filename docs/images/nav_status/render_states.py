#  SPDX-License-Identifier: GPL-2.0-or-later
"""Render the nav_status chip (FP7) in each state from synthetic engine
outputs, using the in-memory mock FIX database (no fix-gateway needed).

    QT_QPA_PLATFORM=offscreen PYTHONPATH=src python docs/images/nav_status/render_states.py

On a host with no system fonts, set RENDER_FONT_DIR to a directory of .ttf
files (e.g. matplotlib's mpl-data/fonts/ttf, which carries DejaVu Sans) and
they are registered with Qt before rendering.

Writes <state>_<w>x<h>.png beside this file, plus a 3x nearest-neighbour
contact sheet (contact_sheet_3x.png) of the 600x48 renders.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..", "..")))
import tests.mock_db.client  # noqa: E402
import tests.mock_db.scheduler  # noqa: E402

sys.modules["pyavtools.fix.client"] = tests.mock_db.client
sys.modules["pyavtools.scheduler"] = tests.mock_db.scheduler

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtGui import QColor, QFontDatabase, QImage, QPainter  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

import pyavtools.fix as fix  # noqa: E402

app = QApplication(sys.argv)
if os.environ.get("RENDER_FONT_DIR"):
    import glob
    for ttf in glob.glob(os.path.join(os.environ["RENDER_FONT_DIR"], "*.ttf")):
        QFontDatabase.addApplicationFont(ttf)
fix.initialize({"main": {"FixServer": "localhost", "FixPort": "3490"}})
DTYPES = {"FPLSTATE": "int", "FPLPHASE": "str", "WPFROM": "str", "WPNAME": "str",
          "WPNEXT": "str", "WPDIS": "float", "WPETE": "int"}
for key, dtype in DTYPES.items():
    lo, hi = (None, None) if dtype == "str" else (0, 1000000)
    fix.db.define_item(key, key, dtype, lo, hi, "", 0, "")

from pyefis.instruments.nav_status import NavStatus  # noqa: E402

CASES = [
    ("no_plan", dict(FPLSTATE=0, FPLPHASE="", WPFROM="", WPNAME="", WPNEXT="",
                     WPDIS=0.0, WPETE=0), {}),
    ("leg_term", dict(FPLSTATE=1, FPLPHASE="TERM", WPFROM="KSBA", WPNAME="GVO",
                      WPNEXT="RZS", WPDIS=12.4, WPETE=372), {}),
    ("direct_enr", dict(FPLSTATE=2, FPLPHASE="ENR", WPFROM="", WPNAME="RZS",
                        WPNEXT="KSMX", WPDIS=31.7, WPETE=951), {}),
    ("susp_lnav_at_map", dict(FPLSTATE=3, FPLPHASE="LNAV", WPFROM="CEGIT",
                              WPNAME="RW12", WPNEXT="", WPDIS=0.3, WPETE=12), {}),
    ("loi_ete_bad", dict(FPLSTATE=1, FPLPHASE="LOI", WPFROM="KSBA", WPNAME="GVO",
                         WPNEXT="RZS", WPDIS=12.4, WPETE=372), {"WPETE": "bad"}),
    ("position_fail", dict(FPLSTATE=1, FPLPHASE="", WPFROM="", WPNAME="",
                           WPNEXT="", WPDIS=0.0, WPETE=0),
     {"WPDIS": "fail", "WPETE": "fail"}),
]

sheet_rows = []
for size in [(600, 48), (300, 32)]:
    for name, values, flags in CASES:
        for key in DTYPES:
            item = fix.db.get_item(key)
            item.old = item.bad = item.fail = False
        for key, value in values.items():
            fix.db.set_value(key, value)
        for key, flag in flags.items():
            setattr(fix.db.get_item(key), flag, True)
        widget = NavStatus()
        widget.resize(*size)
        image = QImage(widget.size(), QImage.Format.Format_ARGB32)
        image.fill(QColor("#000000"))
        widget.render(image)
        image.save(os.path.join(HERE, "%s_%dx%d.png" % (name, size[0], size[1])))
        if size == (600, 48):
            sheet_rows.append(image)

gap = 6
sheet = QImage(600, len(sheet_rows) * (48 + gap), QImage.Format.Format_ARGB32)
sheet.fill(QColor("#303030"))
p = QPainter(sheet)
for i, row in enumerate(sheet_rows):
    p.drawImage(0, i * (48 + gap), row)
p.end()
sheet.scaled(sheet.width() * 3, sheet.height() * 3,
             transformMode=Qt.TransformationMode.FastTransformation).save(
    os.path.join(HERE, "contact_sheet_3x.png"))
print("wrote", len(CASES) * 2 + 1, "images to", HERE, flush=True)
os._exit(0)  # the mock FIX client leaves a non-daemon thread behind
