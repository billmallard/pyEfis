#  SPDX-License-Identifier: GPL-2.0-or-later
"""Renders docs/images/holdfix2/*.png (HOLDFIX2, AER-6322) at the Beelink's
Flight Plan pane size, 649 x 993. Not collected by pytest (no test_ prefix);
run it explicitly:

    QT_QPA_PLATFORM=offscreen PYTHONPATH=src python -m pytest \\
        tests/instruments/flight_plan/render_holdfix2_evidence.py --no-cov -q
"""

import os

from tests.instruments.flight_plan.test_hold_editor import _flying
from tests.instruments.flight_plan.test_hold_ppos import page  # noqa: F401

OUT = os.path.join(os.path.dirname(__file__), "..", "..", "..", "docs", "images", "holdfix2")


def _save(page, name):
    page.grab().save(os.path.join(OUT, name))


def test_render(page):
    os.makedirs(OUT, exist_ok=True)
    _flying(page, "ENR", 2)                  # AAA -> BBB
    page._menu_open = True
    _save(page, "1_menu.png")
    page._menu_hold_ppos()
    _save(page, "2_editor_default.png")
    page._hold_insert()
    assert page.sent == [("ACT", 3)]
    _flying(page, "HOLD", 3)                 # the engine, after that ACT
    _save(page, "3_plan_with_ppos_hold.png")
    page._message = ""
    page.fixdb.db.get_item("LAT").old = True
    page._menu_open = True
    page._menu_hold_ppos()
    _save(page, "4_no_gps_position.png")
