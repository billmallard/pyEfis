#  SPDX-License-Identifier: GPL-2.0-or-later
"""AIRAC cycle currency for the loaded procedure (PA9, AER-1608)."""

from datetime import date

import pytest

from pyefis.flightplan import airac


# Effective dates from makerplane-data packtools/cycles.py (airac_id over the
# 28-day grid anchored at 2024-04-18 = 2404), which builds the pack.
@pytest.mark.parametrize("cycle, day", [
    ("2404", date(2024, 4, 18)),
    ("2501", date(2025, 1, 23)),
    ("2601", date(2026, 1, 22)),
    ("2609", date(2026, 9, 3)),
    ("2611", date(2026, 10, 29)),
    ("2613", date(2026, 12, 24)),
    ("2701", date(2027, 1, 21)),
    ("2014", date(2020, 12, 31)),   # a 14-cycle year
])
def test_effective_dates_follow_the_grid(cycle, day):
    assert airac.effective(cycle) == day


@pytest.mark.parametrize("cycle", ["", None, "26", "2600", "2614", "260500", "AB11", 2611])
def test_a_cycle_that_is_not_an_airac_ident_is_unknown(cycle):
    assert airac.effective(cycle) is None
    assert airac.expires(cycle) is None
    assert airac.is_expired(cycle, date(2099, 1, 1)) is False


def test_a_cycle_expires_on_the_next_effective_date():
    assert airac.expires("2611") == date(2026, 11, 26) == airac.effective("2612")
    assert airac.expires("2613") == airac.effective("2701")


def test_expiry_is_by_utc_date_and_the_expiry_day_is_expired():
    # The pack's pack_meta.expires is exclusive: the first day not covered.
    assert not airac.is_expired("2611", date(2026, 10, 29))
    assert not airac.is_expired("2611", date(2026, 11, 25))
    assert airac.is_expired("2611", date(2026, 11, 26))


def test_today_defaults_to_the_utc_date(monkeypatch):
    monkeypatch.setattr(airac, "utc_today", lambda: date(2026, 11, 26))
    assert airac.is_expired("2611")
    monkeypatch.setattr(airac, "utc_today", lambda: date(2026, 11, 25))
    assert not airac.is_expired("2611")
