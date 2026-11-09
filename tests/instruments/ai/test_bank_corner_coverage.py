"""pyEfis #319: no view background past the sky/ground rectangles at bank
when horizon_position raises the horizon (AER-5251).

``resizeEvent`` sizes the scene so its sky/ground rectangles cover the
viewport rotated about the viewport centre. ``redraw()`` instead pivots the
view about the raised horizon point (``_horizon_offset_px()`` above
centre), and the viewport corners on the far side of that pivot then reach
past the scene edge -- a background-coloured triangle in a top corner at
moderate bank.

The test paints the real widget with SVS off, the view background set to a
colour nothing in the attitude display uses, and asserts no viewport pixel
is that colour.
"""
import pytest
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import QApplication

from pyefis.instruments import ai

# A colour the sky/ground gradients, horizon line, ladder and bank
# symbology never paint.
_SENTINEL = QColor(255, 0, 255)


@pytest.fixture
def app(qtbot):
    test_app = QApplication.instance()
    if test_app is None:
        test_app = QApplication([])
    return test_app


def _reset_items(fix):
    for key in ("PITCH", "ROLL", "ALAT", "TAS"):
        item = fix.db.get_item(key)
        item.old = item.bad = item.fail = False


def _exposed_pixels(fix, qtbot, horizon_position, bank, width, height):
    _reset_items(fix)
    widget = ai.AI()
    qtbot.addWidget(widget)
    widget.horizon_position = horizon_position
    widget.resize(width, height)
    widget.show()
    qtbot.waitExposed(widget)
    widget.setBackgroundBrush(QBrush(_SENTINEL))
    widget._pitchAngle = 0.0
    widget._rollAngle = bank
    widget.redraw()
    img = widget.viewport().grab().toImage()
    target = _SENTINEL.rgb()
    return sum(1 for y in range(0, img.height(), 2)
               for x in range(0, img.width(), 2)
               if img.pixel(x, y) & 0xFFFFFF == target & 0xFFFFFF)


@pytest.mark.parametrize("size", [(1248, 1200), (1024, 600), (480, 800)])
@pytest.mark.parametrize("bank", [30, -30, 60, -60, 90, -90, 180])
def test_no_background_at_bank_with_raised_horizon(fix, qtbot, app, bank,
                                                   size):
    w, h = size
    n = _exposed_pixels(fix, qtbot, 68, bank, w, h)
    assert n == 0, (f"{n} sampled viewport pixels show the view background "
                    f"at bank {bank}, horizon_position 68, {w}x{h}")


@pytest.mark.parametrize("bank", [30, -30, 90, 180])
def test_no_background_at_bank_with_lowered_horizon(fix, qtbot, app, bank):
    # The pivot can sit below centre too; the offset's sign must not matter.
    n = _exposed_pixels(fix, qtbot, 30, bank, 1024, 600)
    assert n == 0
