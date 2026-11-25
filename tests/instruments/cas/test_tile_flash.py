#  SPDX-License-Identifier: GPL-2.0-or-later
"""The two paint_tile keywords CAS3 adds to the shared lamp tile (ANN1):
``flash_blank`` and ``align`` (docs/cas_widget_spec.md, CASW-WIN-003)."""

import pytest
from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QImage, QPainter

from pyefis.instruments import tile as tiles

W, H = 200, 40
ON, OFF = 0.1, 0.6      # tiles.BLINK_HALF_S = 0.5


@pytest.fixture(autouse=True)
def _app(qapp):
    """Text needs a QGuiApplication, even on a QImage."""
    return qapp


def _paint(t, now, **kw):
    img = QImage(W, H, QImage.Format.Format_RGB32)
    img.fill(QColor("#000000"))
    p = QPainter(img)
    tiles.paint_tile(p, QRectF(0, 0, W, H), t, px=16, border_px=2, now=now,
                     **kw)
    p.end()
    return img


def _count(img, color, x0=4, x1=W - 4, tol=40):
    n = 0
    for y in range(4, H - 4):
        for x in range(x0, x1):
            c = img.pixelColor(x, y)
            if (abs(c.red() - color.red()) <= tol
                    and abs(c.green() - color.green()) <= tol
                    and abs(c.blue() - color.blue()) <= tol):
                n += 1
    return n


@pytest.mark.parametrize("level", [tiles.WARNING, tiles.CAUTION,
                                   tiles.ADVISORY])
def test_never_blank_flash_keeps_the_caption_in_both_phases(level):
    """CASW-WIN-003: with flash_blank=False a flashing tile swaps fill each
    half-period and its caption is drawn in both: inside the box there is
    level-coloured ink and dark ink in both phases, and the phases differ."""
    t = tiles.Tile("NAV FAIL", level, flash=True)
    color = QColor(tiles.DEFAULT_COLORS[level])
    on, off = _paint(t, ON, flash_blank=False), _paint(t, OFF, flash_blank=False)
    assert on != off
    for img in (on, off):
        inside = _count(img, color)
        dark = _count(img, QColor("#000000"))
        assert inside > 50 and dark > 50, (level, inside, dark)


def test_default_flash_still_blanks_for_the_annunciator():
    """The default is ANN1's blink, unchanged: the off phase draws no caption
    and no fill, only the outline."""
    t = tiles.Tile("TRIM", tiles.CAUTION, flash=True)
    off = _paint(t, OFF)
    amber = QColor(tiles.DEFAULT_COLORS[tiles.CAUTION])
    interior = _count(off, amber, x0=8, x1=W - 8)
    assert interior < 2 * (H - 8) * 2      # the two side borders at most


def test_steady_tile_is_the_same_either_way():
    """flash_blank only matters while flashing."""
    t = tiles.Tile("HDG FAIL", tiles.CAUTION)
    assert _paint(t, OFF) == _paint(t, OFF, flash_blank=False)


def test_left_alignment_puts_the_caption_on_the_left():
    """align: a left-aligned caption's ink is in the left half of the box,
    inset from the border; centred is the default."""
    t = tiles.Tile("AP", tiles.ADVISORY)
    white = QColor("#ffffff")
    left = _paint(t, ON, align=Qt.AlignmentFlag.AlignLeft
                  | Qt.AlignmentFlag.AlignVCenter)
    centre = _paint(t, ON)
    assert _count(left, white, 6, W // 2) > 0
    assert _count(left, white, W // 2, W - 6) == 0
    assert _count(centre, white, 6, W // 3) == 0
