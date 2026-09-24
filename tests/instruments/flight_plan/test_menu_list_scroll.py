#  SPDX-License-Identifier: GPL-2.0-or-later
"""``_paint_menu_list`` popup sizing and scrolling (AER-1605 follow-up).

Bill, testing "Load Airway" live: picking V27 out of GVO pops a long exit-fix
list where "the fonts appear to be relative to the pop-up window height" --
tiny and unselectable -- and asked for scrolling. The old code sized every
row as ``(h * 0.76) / (len(items) + 1)``, so the font shrank without bound as
the list grew; a 30-fix airway crushed it to a sliver.

The fix makes row height physical (``_row_h_cap()``, the same millimetre cap
``_paint_list`` already uses for the main FPL rows) and, when the item count
no longer fits, scrolls a fixed-height window instead of shrinking further.
These tests pin both halves: the row stays the same physical size no matter
how long the list gets, and a list too long to fit exposes tappable
up/down rows that page through it correctly.
"""

from types import SimpleNamespace

import pytest
from PyQt6.QtGui import QPainter, QPixmap

from pyefis.instruments import flight_plan


BEELINK = SimpleNamespace(screenWidth=1920, screenHeight=1080,
                          screenDiagonalInches=21.5)


def _widget(qtbot, size=(649, 993), display=BEELINK):
    w = flight_plan.FlightPlan(None)
    qtbot.addWidget(w)
    w.parent = SimpleNamespace(parent=display)
    w.resize(*size)
    return w


def _items(n):
    return [(f"ITEM{i:02d}", (lambda i=i: i)) for i in range(n)]


def _render(w, items, key="k"):
    pixmap = QPixmap(w.width(), w.height())
    painter = QPainter(pixmap)
    w._tap_targets = []
    w._paint_menu_list(painter, w.width(), w.height(), items, (lambda: None),
                        scroll_key=key)
    painter.end()
    return w._tap_targets


def test_short_list_shows_every_item_with_no_scroll_arrows(fix, qtbot):
    w = _widget(qtbot)
    taps = _render(w, _items(5))
    # 5 items + Cancel, no up/down arrow taps.
    assert len(taps) == 6
    assert taps[0][3] == pytest.approx(w._row_h_cap())


def test_long_list_keeps_the_physical_row_height(fix, qtbot):
    """The bug: row/font height used to shrink as 1/n. It must not."""
    w = _widget(qtbot)
    short_taps = _render(w, _items(5), key="short")
    long_taps = _render(w, _items(30), key="long")
    assert short_taps[0][3] == pytest.approx(long_taps[0][3])
    assert long_taps[0][3] == pytest.approx(w._row_h_cap())


def test_long_list_scrolls_instead_of_shrinking(fix, qtbot):
    w = _widget(qtbot)
    items = _items(30)
    taps = _render(w, items, key="v27")
    n_items, offset = w._menu_scroll["v27"]
    assert (n_items, offset) == (30, 0)
    # Fewer item rows than the full list, plus a live down-arrow (no live
    # up-arrow yet -- already at the top) and Cancel.
    item_row_count = len(taps) - 2  # down arrow + cancel
    assert 0 < item_row_count < 30


def test_scrolling_down_then_past_the_end_clamps(fix, qtbot):
    w = _widget(qtbot)
    items = _items(30)
    _render(w, items, key="v27")
    _, offset0 = w._menu_scroll["v27"]

    taps = _render(w, items, key="v27")
    item_row_count = len(taps) - 2  # down-only at the top
    w._menu_scroll_by("v27", item_row_count)
    taps = _render(w, items, key="v27")
    _, offset1 = w._menu_scroll["v27"]
    assert offset1 == item_row_count > offset0

    # Scrolling far past the end clamps to the last full page, not an
    # index that would run off the end of `items`.
    w._menu_scroll_by("v27", 10_000)
    taps = _render(w, items, key="v27")
    _, offset2 = w._menu_scroll["v27"]
    assert offset2 <= 30 - 1
    visible_rows = len(taps) - 2  # up-only at the bottom, no down arrow
    assert offset2 + visible_rows == 30


def test_reopening_a_shorter_list_under_the_same_key_resets_scroll(fix, qtbot):
    """A stale offset from a longer list must not survive onto a shorter
    one opened under the same scroll_key (e.g. a different, shorter
    airway picked after scrolling partway down a long one)."""
    w = _widget(qtbot)
    long_items = _items(30)
    _render(w, long_items, key="airway_picker_exit")
    w._menu_scroll_by("airway_picker_exit", 15)
    _render(w, long_items, key="airway_picker_exit")
    assert w._menu_scroll["airway_picker_exit"][1] == 15

    short_items = _items(3)
    taps = _render(w, short_items, key="airway_picker_exit")
    assert w._menu_scroll["airway_picker_exit"] == (3, 0)
    assert len(taps) == 4  # 3 items + Cancel, no arrows
