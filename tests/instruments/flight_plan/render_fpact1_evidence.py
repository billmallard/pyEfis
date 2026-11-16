#  SPDX-License-Identifier: GPL-2.0-or-later
"""Renders docs/images/fpact1/*.png (FPACT1, AER-5801). Not collected by
pytest (no test_ prefix); run it explicitly:

    QT_QPA_PLATFORM=offscreen PYTHONPATH=src python -m pytest \\
        tests/instruments/flight_plan/render_fpact1_evidence.py --no-cov -q
"""

import os

from tests.instruments.flight_plan.test_activate_leg_far_fix import (  # noqa: F401
    _activate_sanfi_from_row, page)

OUT = os.path.join(os.path.dirname(__file__), "..", "..", "..", "docs", "images", "fpact1")


def test_render(page):
    os.makedirs(OUT, exist_ok=True)
    page.grab().save(os.path.join(OUT, "fpl_before_activate.png"))
    _activate_sanfi_from_row(page)
    page.grab().save(os.path.join(OUT, "fpl_far_fix_question.png"))
    assert page.sent == []
