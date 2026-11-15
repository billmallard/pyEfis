"""Render the FPL page in the suspend states for G49 (pyEfis #330).

Runs under pytest so it gets the repo's ``fix`` fixture (an in-process FIX
database); from the repo root:

    QT_QPA_PLATFORM=offscreen PYTHONPATH=src python -m pytest --no-cov \
        -p no:cacheprovider docs/images/g49/render_g49.py

The pictures are the real widget's own paint at 800x480, not a mock-up.
"""
import glob
import os

from PyQt6.QtGui import QFontDatabase

from tests.instruments.flight_plan.test_flight_plan import (
    _approach_plan, _define, _define_all_fp1_keys)
from pyefis.instruments import flight_plan

HERE = os.path.dirname(os.path.abspath(__file__))

# name, FPLSTATE, FPLSUSPMAP, FPLACTLEG, FPLTF, menu open
SHOTS = (
    ("map_auto_susp", 3, 1, 4, 2, False),       # engine auto-suspend past the MAP
    ("map_auto_susp_menu", 3, 1, 4, 2, True),   # same, MENU open
    ("pilot_susp_final", 3, 0, 4, 1, True),     # pilot SUSP on final, short of the MAP
    ("pilot_susp_past_map", 3, 0, 4, 2, True),  # pilot SUSP held past the MAP
)


def _register_font():
    """Offscreen Qt has no fontconfig setup here; load a font file directly
    (FONT_FILE, else any DejaVuSans.ttf under /usr/share/fonts)."""
    path = os.environ.get("FONT_FILE") or next(
        iter(glob.glob("/usr/share/fonts/**/DejaVuSans.ttf", recursive=True)), None)
    if not path:
        return None
    fid = QFontDatabase.addApplicationFont(path)
    return QFontDatabase.applicationFontFamilies(fid)[0] if fid >= 0 else None


def test_render_g49(fix, qtbot):
    _define_all_fp1_keys(fix)
    _define(fix, "FPLSUSPMAP", "int", 0)
    family = _register_font()
    w = flight_plan.FlightPlan(None)
    if family:
        w.font_family = family
    qtbot.addWidget(w)
    w.resize(800, 480)
    w._plan = _approach_plan()
    w._commit()
    fix.db.set_value("FPLINTEG", True)   # the test defaults leave LOI showing
    fix.db.set_value("FPLAPR", 2)        # LNAV
    for name, state, susp_map, act_leg, tf, menu in SHOTS:
        fix.db.set_value("FPLSTATE", state)
        fix.db.set_value("FPLSUSPMAP", susp_map)
        fix.db.set_value("FPLACTLEG", act_leg)
        fix.db.set_value("FPLTF", tf)
        w._sync_engine_from_bridge()
        w._menu_open = menu
        w._menu_scroll["menu"] = (6, 2)      # scroll the suspend item into view
        assert w.grab().save(os.path.join(HERE, name + ".png"))
