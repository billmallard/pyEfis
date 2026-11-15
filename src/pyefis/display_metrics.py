#  Copyright (c) 2026 MakerPlane
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.

"""Physical display metrics: turn pixels into millimetres.

pyEfis instruments have historically sized both text and geometry as a fraction
of their own widget height. That is scale-free in the wrong way. A fraction of
a pane says nothing about how large a glyph is *to the pilot*, so the same
config renders a 14 mm row on a 21.5" bench monitor and a 4 mm row on a 7"
panel -- and a taller pane spends its extra space making each row bigger rather
than showing more of them.

Legibility in a cockpit is a physical question: how large the glyph subtends at
roughly arm's length. So the primitive here is the millimetre. Callers ask for
a size in mm and get pixels for *this* display.

Where the physical size comes from, in order of preference:

1. **The configured diagonal** (``main.screenDiagonalInches``, which the
   configurator already writes) combined with the actual pixel resolution. This
   is a human assertion about the hardware and is the only source that is right
   by construction -- when it is right.
2. **Qt's reported physical DPI**, when it is plausible. Embedded panels
   routinely lie here (many report a nominal 96 regardless of the real panel),
   which is why this is the fallback rather than the primary.
3. **A nominal 96 DPI**, which reproduces roughly the historical behaviour on a
   desktop-class screen rather than collapsing to something unreadable.

Every source is range-checked. A configured diagonal is user metadata and can be
stale or copied between devices -- observed in the field: two devices of very
different physical size both carrying ``screenDiagonalInches: 21.5``. A bad
value must degrade to the next source, not silently produce 2 mm text.
"""

MM_PER_INCH = 25.4

# What a display with no usable physical information is assumed to be. Not a
# guess at any particular panel -- just the conventional desktop nominal, chosen
# so the no-information path lands near the historical pixel sizes instead of
# somewhere absurd.
NOMINAL_DPI = 96.0

# Anything outside this is taken as a broken measurement rather than an exotic
# display. The low end sits under a projector; the high end is above current
# phone panels, which is far beyond anything pyEfis targets.
MIN_PLAUSIBLE_DPI = 40.0
MAX_PLAUSIBLE_DPI = 500.0


def _plausible(dpi):
    """True when *dpi* is a number that could describe a real display."""
    try:
        dpi = float(dpi)
    except (TypeError, ValueError):
        return False
    if dpi != dpi:                      # NaN
        return False
    return MIN_PLAUSIBLE_DPI <= dpi <= MAX_PLAUSIBLE_DPI


def dpi_from_diagonal(width_px, height_px, diagonal_inches):
    """Pixels per inch implied by a pixel resolution and a physical diagonal.

    Returns ``None`` if the inputs cannot describe a real display, so the caller
    can fall through to the next source rather than dividing by zero or trusting
    a typo.
    """
    try:
        w = float(width_px)
        h = float(height_px)
        diag_in = float(diagonal_inches)
    except (TypeError, ValueError):
        return None
    if w <= 0 or h <= 0 or diag_in <= 0:
        return None
    diag_px = (w * w + h * h) ** 0.5
    dpi = diag_px / diag_in
    return dpi if _plausible(dpi) else None


def dpi_from_qscreen(qscreen):
    """Qt's own idea of the physical DPI, or ``None`` if it is not usable.

    Averages the two axes: Qt exposes them separately and they disagree on
    non-square pixels, which no display pyEfis targets actually has -- a
    disagreement here means the numbers are synthesised, not that the pixels are
    anisotropic.
    """
    if qscreen is None:
        return None
    try:
        x = float(qscreen.physicalDotsPerInchX())
        y = float(qscreen.physicalDotsPerInchY())
    except Exception:
        # A QScreen that cannot answer is exactly the case this guards.
        return None
    dpi = (x + y) / 2.0
    return dpi if _plausible(dpi) else None


def display_dpi(width_px=None, height_px=None, diagonal_inches=None,
                qscreen=None):
    """Best available pixels-per-inch for a display, with the source.

    Returns ``(dpi, source)`` where *source* is one of ``"configured"``,
    ``"qt"`` or ``"nominal"``. The source is returned rather than logged here so
    the caller can report it once at startup instead of on every paint.
    """
    dpi = dpi_from_diagonal(width_px, height_px, diagonal_inches)
    if dpi is not None:
        return dpi, "configured"
    dpi = dpi_from_qscreen(qscreen)
    if dpi is not None:
        return dpi, "qt"
    return NOMINAL_DPI, "nominal"


def pixels_per_mm(width_px=None, height_px=None, diagonal_inches=None,
                  qscreen=None):
    """Pixels per millimetre for this display. Always returns a usable float."""
    dpi, _source = display_dpi(width_px, height_px, diagonal_inches, qscreen)
    return dpi / MM_PER_INCH


def mm_to_px(mm, width_px=None, height_px=None, diagonal_inches=None,
             qscreen=None):
    """Convert *mm* to pixels on this display."""
    return float(mm) * pixels_per_mm(width_px, height_px, diagonal_inches,
                                     qscreen)
