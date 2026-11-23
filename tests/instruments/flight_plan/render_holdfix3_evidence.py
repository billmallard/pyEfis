#  SPDX-License-Identifier: GPL-2.0-or-later
"""Renders docs/images/holdfix3/*.png (HOLDFIX3 "as published", AER-6328)
at the Beelink's Flight Plan pane size, 649 x 993. The holds are the five
AIRAC 2611 publishes at BTG, moved onto the test route's BBB. Not collected
by pytest (no test_ prefix); run it explicitly:

    QT_QPA_PLATFORM=offscreen PYTHONPATH=src python -m pytest \\
        tests/instruments/flight_plan/render_holdfix3_evidence.py --no-cov -q
"""

import os

from tests.instruments.flight_plan.test_hold_editor import (  # noqa: F401
    _published, page)

OUT = os.path.join(os.path.dirname(__file__), "..", "..", "..", "docs", "images", "holdfix3")

# BTG in 2611 (name, no, ident, lat, lon, side, inbound, turn, leg_nm, charts).
BTG = [
    ("BBB VORTAC*WA", 1, "BBB", 34.0, -119.0, "S", 343, "R", None, "ENROUTE HIGH|ENROUTE LOW"),
    ("BBB VORTAC*WA", 2, "BBB", 34.0, -119.0, "S", 343, "R", 10, "STAR"),
    ("BBB VORTAC*WA", 3, "BBB", 34.0, -119.0, "NW", 149, "R", None, "IAP|SID"),
    ("BBB VORTAC*WA", 4, "BBB", 34.0, -119.0, "N", 164, "R", None, "IAP"),
    ("BBB VORTAC*WA", 5, "BBB", 34.0, -119.0, "N", 165, "R", 5, "IAP"),
]


def _save(page, name):
    page.grab().save(os.path.join(OUT, name))


def test_render(page, tmp_path):
    os.makedirs(OUT, exist_ok=True)
    _published(page, tmp_path, BTG)
    page._open_hold_editor(1)
    _save(page, "1_editor_published_row.png")
    page._hold_published()
    _save(page, "2_chooser.png")
    page._hold_apply_published(page._hold_edit["published"][0])
    _save(page, "3_enroute_timed_std_time.png")
    page._hold_published()
    page._hold_apply_published(page._hold_edit["published"][1])
    _save(page, "4_star_10nm.png")
