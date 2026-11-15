#  SPDX-License-Identifier: GPL-2.0-or-later
"""A short list draws its rows at the physical row height (pyEfis #400).

The Catalog list, the Direct-To page's FPL and NRST tabs and the waypoint
picker do not scroll. Each sized its rows as ``pane height / row count``, so a
Catalog holding one stored route drew that row the height of the whole list
area, with a font sized off it that clipped at the pane edge (seen on the
Beelink bench, 672x1080: ``KGPM-KGPM  1182N7WF`` with the distance and
waypoint count cut off). Two rows were half that, still oversized.

Each list now draws ``row_height_mm`` rows, the same as the FPL page's own
list, and shrinks them only when too many rows would not otherwise fit.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from pyefis.flightplan import model as fp_model
from pyefis.instruments import flight_plan

BEELINK = SimpleNamespace(screenWidth=1920, screenHeight=1080, screenDiagonalInches=21.5)
PANE_H = 900


def _wp(ident):
    return fp_model.Waypoint(id=ident, type="airport", lat=34.4, lon=-119.8)


def _page(qtbot, monkeypatch, n):
    w = flight_plan.FlightPlan(None)
    qtbot.addWidget(w)
    w.parent = SimpleNamespace(parent=BEELINK)
    w.resize(672, 1080)
    wps = [_wp(f"K{i:03d}") for i in range(n)]
    w._plan = fp_model.FlightPlan(name="TEST", waypoints=wps)
    entries = [SimpleNamespace(slug=f"r{i}", name=f"ROUTE{i}", count=2, comment="",
                               mtime=float(i)) for i in range(n)]
    monkeypatch.setattr(w, "_catalog_entries", lambda: entries)
    monkeypatch.setattr(w, "_catalog_entry_distance_nm", lambda *a: None)
    idx = SimpleNamespace(
        nearest=lambda lat, lon, types=None: [(wp, 10.0, 90.0, 5000) for wp in wps],
        recent=SimpleNamespace(list=lambda: []))
    monkeypatch.setattr(w, "_ensure_waypoint_index", lambda: idx)
    monkeypatch.setattr(w, "_entry_tab_rows", lambda: wps)
    w._entry_tab = "Nearest"
    return w


def _catalog(w):
    w._paint_catalog_list(MagicMock(), w.width(), 0, PANE_H)


def _dto_fpl(w):
    w._paint_dto_fpl_tab(MagicMock(), w.width(), 0, PANE_H)


def _dto_nrst(w):
    w._paint_dto_nrst_tab(MagicMock(), w.width(), 0, PANE_H)


def _picker(w):
    w._paint_entry_list(MagicMock(), w.width(), 0, PANE_H)


LISTS = [_catalog, _dto_fpl, _dto_nrst, _picker]


def _row_heights(w, paint):
    w._tap_targets, w._tap_kinds = [], []
    paint(w)
    return [t[3] for t, k in zip(w._tap_targets, w._tap_kinds) if k == "row"]


@pytest.mark.parametrize("paint", LISTS, ids=lambda f: f.__name__)
def test_one_row_list_draws_the_physical_row(fix, qtbot, monkeypatch, paint):
    w = _page(qtbot, monkeypatch, 1)
    heights = _row_heights(w, paint)
    assert len(heights) == 1
    # The physical row is ~56 px on the Beelink; the old code drew 900.
    assert heights[0] == pytest.approx(w._row_h_cap())
    assert heights[0] < PANE_H * 0.1


@pytest.mark.parametrize("paint", LISTS, ids=lambda f: f.__name__)
def test_short_list_rows_match_a_multi_row_list(fix, qtbot, monkeypatch, paint):
    one = _row_heights(_page(qtbot, monkeypatch, 1), paint)
    three = _row_heights(_page(qtbot, monkeypatch, 3), paint)
    assert three == pytest.approx([one[0]] * 3)


@pytest.mark.parametrize("paint", LISTS, ids=lambda f: f.__name__)
def test_a_list_too_long_to_fit_still_shrinks_to_fit(fix, qtbot, monkeypatch, paint):
    """No scrolling on these lists, so a long one keeps the old fit."""
    w = _page(qtbot, monkeypatch, 30)
    heights = _row_heights(w, paint)
    assert heights[0] < w._row_h_cap()
    assert sum(heights) <= PANE_H + 1e-6
