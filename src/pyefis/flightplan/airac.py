#  SPDX-License-Identifier: GPL-2.0-or-later
"""AIRAC cycle currency for the loaded procedure (PA9, billmallard/pyEfis#240,
AER-1608).

``FPLDBCYC`` carries the AIRAC cycle the loaded procedures came from
(``"2611"``); fix-gateway's ``flightplan.yaml`` describes it as the key PA9
annunciates when it has expired. A cycle's ident fixes its dates: AIRAC
effective dates fall on one worldwide 28-day grid, and a cycle is current
from its own effective date until the next one. This module turns the ident
into that window.

The grid is the one the procedures pack is built on (makerplane-data
``packtools/cycles.py``): 2024-04-18 is AIRAC 2404, and ``YYNN`` is the
NN-th effective date that falls in year 20YY. Expiry is by UTC date, the
same rule the pack's ``pack_meta.expires`` follows (an exclusive ISO date)
and the data-status screen applies, so the approach and that screen never
disagree about a day.

Expired data is annunciated, never refused (brief guardrail 3, Bill
2026-09-18): nothing here is consulted by a load path. A cycle that is not
a four-digit AIRAC ident reads as unknown, and unknown is not expired.

Qt-free: nothing here may import PyQt6.
"""

from __future__ import annotations

import datetime as _dt
import math

#: An AIRAC effective date known to be cycle 2404 (packtools/cycles.py).
ANCHOR = _dt.date(2024, 4, 18)
CYCLE_DAYS = 28


def _first_of_year(year: int) -> _dt.date:
    jan1 = _dt.date(year, 1, 1)
    k = math.ceil((jan1 - ANCHOR).days / CYCLE_DAYS)
    return ANCHOR + _dt.timedelta(days=k * CYCLE_DAYS)


def effective(cycle) -> _dt.date | None:
    """The effective date of AIRAC *cycle* (``"2611"``), or None when it is
    not a four-digit ident naming a real cycle of its year."""
    text = (cycle or "").strip() if isinstance(cycle, str) else ""
    if len(text) != 4 or not text.isdigit():
        return None
    year, seq = 2000 + int(text[:2]), int(text[2:])
    if seq < 1:
        return None
    day = _first_of_year(year) + _dt.timedelta(days=(seq - 1) * CYCLE_DAYS)
    return day if day.year == year else None


def expires(cycle) -> _dt.date | None:
    """The first UTC date *cycle* is no longer current (the next cycle's
    effective date), or None when the cycle is unknown."""
    start = effective(cycle)
    return start + _dt.timedelta(days=CYCLE_DAYS) if start else None


def utc_today() -> _dt.date:
    return _dt.datetime.now(_dt.timezone.utc).date()


def is_expired(cycle, today: _dt.date | None = None) -> bool:
    """True when *cycle* has expired on *today* (UTC; now by default). An
    unknown cycle is not expired."""
    end = expires(cycle)
    return end is not None and (today or utc_today()) >= end
