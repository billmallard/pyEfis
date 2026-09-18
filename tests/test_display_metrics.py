#  SPDX-License-Identifier: GPL-2.0-or-later
"""Tests for `pyefis.display_metrics`.

The module exists so instruments can size text and touch targets in
millimetres rather than as a fraction of their own pane. Its whole value is the
fallback order, so that is what these pin: a configured diagonal wins, an
implausible one falls through rather than being trusted, and the no-information
path still returns something usable instead of raising.

No Qt import here -- the module is deliberately Qt-free at import time so it can
be used from anywhere, and a fake stands in for QScreen.
"""

import math

import pytest

from pyefis import display_metrics as dm


class _FakeScreen:
    """Stands in for QScreen. `None` values raise, like a screen that cannot answer."""

    def __init__(self, x, y=None):
        self._x, self._y = x, (x if y is None else y)

    def physicalDotsPerInchX(self):
        if self._x is None:
            raise RuntimeError("no physical size")
        return self._x

    def physicalDotsPerInchY(self):
        if self._y is None:
            raise RuntimeError("no physical size")
        return self._y


# --------------------------------------------------------------------------
# dpi_from_diagonal
# --------------------------------------------------------------------------

def test_configured_diagonal_gives_the_real_dpi():
    # The Beelink bench panel: 1920x1080 on a 21.5" diagonal.
    dpi = dm.dpi_from_diagonal(1920, 1080, 21.5)
    assert dpi == pytest.approx(102.46, abs=0.05)


def test_a_seven_inch_panel_is_denser_than_a_desktop_one():
    """The point of the module: same pixels, different physical size."""
    desktop = dm.dpi_from_diagonal(1920, 1080, 21.5)
    panel = dm.dpi_from_diagonal(1024, 600, 7.0)
    assert panel > desktop * 1.5


@pytest.mark.parametrize("w,h,diag", [
    (0, 1080, 21.5),            # no width
    (1920, 0, 21.5),            # no height
    (1920, 1080, 0),            # no diagonal
    (1920, 1080, -21.5),        # negative diagonal
    (1920, 1080, None),         # absent
    (1920, 1080, "big"),        # unparseable
    (None, None, 21.5),         # no resolution
])
def test_unusable_inputs_return_none_rather_than_a_number(w, h, diag):
    assert dm.dpi_from_diagonal(w, h, diag) is None


def test_an_absurd_diagonal_is_refused_not_trusted():
    """A typo must fall through to the next source.

    Field case this guards: two devices of very different physical size were
    both configured with `screenDiagonalInches: 21.5`, so this value is user
    metadata and can be simply wrong. A 1 mm or 1000 inch 'display' is a broken
    measurement, not an exotic one.
    """
    assert dm.dpi_from_diagonal(1920, 1080, 0.05) is None      # ~44000 dpi
    assert dm.dpi_from_diagonal(1920, 1080, 1000.0) is None    # ~2 dpi


# --------------------------------------------------------------------------
# fallback order
# --------------------------------------------------------------------------

def test_configured_diagonal_beats_qt():
    dpi, source = dm.display_dpi(1920, 1080, 21.5, _FakeScreen(96.0))
    assert source == "configured"
    assert dpi == pytest.approx(102.46, abs=0.05)


def test_qt_is_used_when_no_diagonal_is_configured():
    dpi, source = dm.display_dpi(1920, 1080, None, _FakeScreen(141.0))
    assert source == "qt"
    assert dpi == pytest.approx(141.0)


def test_qt_is_skipped_when_it_reports_nonsense():
    dpi, source = dm.display_dpi(1920, 1080, None, _FakeScreen(2.0))
    assert source == "nominal"
    assert dpi == dm.NOMINAL_DPI


def test_a_screen_that_cannot_answer_falls_through():
    dpi, source = dm.display_dpi(1920, 1080, None, _FakeScreen(None))
    assert source == "nominal"
    assert dpi == dm.NOMINAL_DPI


def test_no_information_at_all_still_returns_something_usable():
    dpi, source = dm.display_dpi()
    assert source == "nominal"
    assert dm.MIN_PLAUSIBLE_DPI < dpi < dm.MAX_PLAUSIBLE_DPI


def test_disagreeing_axes_are_averaged():
    dpi, source = dm.display_dpi(None, None, None, _FakeScreen(100.0, 140.0))
    assert source == "qt"
    assert dpi == pytest.approx(120.0)


# --------------------------------------------------------------------------
# conversions
# --------------------------------------------------------------------------

def test_mm_to_px_round_trips_through_the_configured_dpi():
    # 14 mm at 102.46 dpi -> ~56 px, which is the row height this was built for.
    px = dm.mm_to_px(14.0, 1920, 1080, 21.5)
    assert px == pytest.approx(56.5, abs=0.5)


def test_the_same_mm_is_more_pixels_on_a_denser_panel():
    desktop = dm.mm_to_px(14.0, 1920, 1080, 21.5)
    panel = dm.mm_to_px(14.0, 1024, 600, 7.0)
    assert panel > desktop


def test_pixels_per_mm_is_always_finite_and_positive():
    for args in [(), (1920, 1080, 21.5), (0, 0, 0), (None, None, None)]:
        ppm = dm.pixels_per_mm(*args)
        assert math.isfinite(ppm) and ppm > 0
