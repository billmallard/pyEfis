#  SPDX-License-Identifier: GPL-2.0-or-later
"""Renders docs/images/holdfix1/*.png (HOLDFIX1, AER-6210) at the Beelink's
Flight Plan pane size, 649 x 993. Not collected by pytest (no test_ prefix);
run it explicitly:

    QT_QPA_PLATFORM=offscreen PYTHONPATH=src python -m pytest \\
        tests/instruments/flight_plan/render_holdfix1_evidence.py --no-cov -q
"""

import os

from tests.instruments.flight_plan.test_hold_editor import (  # noqa: F401
    _flying, page)

OUT = os.path.join(os.path.dirname(__file__), "..", "..", "..", "docs", "images", "holdfix1")


def _save(page, name):
    page.grab().save(os.path.join(OUT, name))


def test_render(page):
    os.makedirs(OUT, exist_ok=True)
    page._open_row_menu(1)
    _save(page, "1_row_menu.png")
    page._row_menu_hold()
    _save(page, "2_editor_default.png")
    # "Hold southeast of BBB on the 130 radial, left turns, 10-mile legs."
    page._hold_set_direction("SE")
    page._hold_toggle_ref()
    page._hold_edit_course()
    page._modal["value"] = "130"
    _save(page, "3_radial_keypad.png")
    page._modal_enter()
    page._hold_set_turn("L")
    page._hold_toggle_unit()
    page._hold_edit_leg()
    page._modal["value"] = "10"
    page._modal_enter()
    _save(page, "4_editor_clearance.png")
    page._hold_insert()
    page._message = ""
    _save(page, "5_plan_with_hold.png")
    _flying(page, "HOLD", 3)
    page._menu_open = True
    _save(page, "6_menu_exit_hold.png")
