"""Shared readout-panel style (P5c).

The airspeed/altitude tape readout boxes used to be a solid white-on-black
rectangle with bracket "arms" and an opaque black triangle pointer. P5c brings
them onto the same rounded, translucent panel the HSI readout panels use
(pyEfis #122). These tests pin the three things that make that a real change
rather than a cosmetic one:

  * the panel style lives in ONE place (pyefis.instruments.helpers), so the HSI
    and the tapes cannot drift apart;
  * the panel is genuinely translucent -- and still legible over both a fully
    lit sky and dark ground, which is what a translucent fill has to earn;
  * the bracket arms and the opaque triangle are gone, and the scrolling drum
    is clipped to the panel instead of bleeding past it.
"""

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QGraphicsLineItem, QGraphicsPathItem, QGraphicsRectItem, QWidget,
)

from pyefis.instruments import airspeed, altimeter, helpers
from pyefis.instruments.NumericalDisplay import NumericalDisplay


# --------------------------------------------------------------------------
# helpers: the shared style primitives
# --------------------------------------------------------------------------

def _srgb_to_linear(channel):
    c = channel / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _relative_luminance(rgb):
    r, g, b = (_srgb_to_linear(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(fg, bg):
    l1, l2 = _relative_luminance(fg), _relative_luminance(bg)
    if l1 < l2:
        l1, l2 = l2, l1
    return (l1 + 0.05) / (l2 + 0.05)


def _over(fill_rgb, alpha, background_rgb):
    """Source-over composite of a translucent fill onto an opaque background."""
    return tuple(alpha * f + (1.0 - alpha) * b
                 for f, b in zip(fill_rgb, background_rgb))


#: QColor stores alpha as 8-bit, so a round-trip through setAlphaF lands within
#: half a step of the requested float.
_ALPHA_TOL = 1.0 / 255.0


def test_readout_panel_pen_brush_is_translucent_black():
    pen, brush = helpers.readout_panel_pen_brush(QColor(Qt.GlobalColor.white))
    assert brush.color().red() == brush.color().green() == 0
    assert brush.color().alphaF() == pytest.approx(
        helpers.READOUT_FILL_ALPHA, abs=_ALPHA_TOL)
    assert pen.color().alphaF() == pytest.approx(
        helpers.READOUT_BORDER_ALPHA, abs=_ALPHA_TOL)
    # Border takes the caller's colour, not a hardcoded white.
    cyan_pen, _ = helpers.readout_panel_pen_brush(QColor("#00ffff"))
    assert (cyan_pen.color().red(), cyan_pen.color().green(),
            cyan_pen.color().blue()) == (0, 255, 255)


def test_readout_panel_pen_brush_clamps_alpha_and_pen_width():
    pen, brush = helpers.readout_panel_pen_brush(
        QColor(Qt.GlobalColor.white), pen_width=0.0,
        fill_alpha=5.0, border_alpha=-2.0)
    assert brush.color().alphaF() == pytest.approx(1.0, abs=_ALPHA_TOL)
    assert pen.color().alphaF() == pytest.approx(0.0, abs=_ALPHA_TOL)
    assert pen.widthF() >= 1.0


@pytest.mark.parametrize("background", [(255, 255, 255), (0, 0, 0),
                                        (150, 190, 235), (30, 60, 20)])
@pytest.mark.parametrize("alpha", [helpers.READOUT_FILL_ALPHA, 0.85])
def test_readout_value_stays_legible_over_sky_and_ground(background, alpha):
    """A white value on the panel clears the WCAG 4.5:1 floor over anything the
    tape can sit on -- a fully lit sky is the worst case, and that is checked
    WITHOUT counting the tape's own dark backing, so it is a floor, not a
    best case. This is the constraint that bounds READOUT_FILL_ALPHA: drop it
    much below 0.6 and a white value over bright sky fails here.
    """
    composited = _over((0, 0, 0), alpha, background)
    assert _contrast((255, 255, 255), composited) >= 4.5


# --------------------------------------------------------------------------
# NumericalDisplay: the box the tapes actually draw
# --------------------------------------------------------------------------

@pytest.fixture
def readout(qtbot):
    widget = NumericalDisplay(total_decimals=3, scroll_decimal=1)
    qtbot.addWidget(widget)
    widget.resize(90, 60)
    widget.show()
    qtbot.waitExposed(widget)
    return widget


def test_readout_panel_is_a_rounded_translucent_path(readout):
    paths = [i for i in readout.scene.items() if isinstance(i, QGraphicsPathItem)]
    assert len(paths) == 1, "expected exactly one readout container"
    panel = paths[0]
    assert panel.brush().color().alphaF() == pytest.approx(
        helpers.READOUT_FILL_ALPHA, abs=_ALPHA_TOL)
    # A rounded rect is not a rect: its path has curves, which is what
    # distinguishes it from the pre-P5c QGraphicsRectItem.
    assert panel.path().elementCount() > 4
    assert any(e.isCurveTo() for e in
               (panel.path().elementAt(i)
                for i in range(panel.path().elementCount())))


def test_readout_has_no_bracket_arms_or_opaque_plate(readout):
    """The four framing lines and the solid black plate are gone -- they were
    the dated part of the look, and a solid plate defeats the translucency."""
    assert not [i for i in readout.scene.items()
                if isinstance(i, QGraphicsLineItem)]
    for item in readout.scene.items():
        if isinstance(item, QGraphicsRectItem):
            assert item.brush().color().alphaF() < 1.0
    for item in readout.scrolling_area.scene.items():
        if isinstance(item, QGraphicsRectItem):
            assert item.brush().color().alphaF() < 1.0


def test_scrolling_drum_is_clipped_inside_the_panel(readout):
    """The drum used to be the full widget height, so neighbouring digits
    spilled out above and below the box. It is now one digit tall and sits
    inside the panel."""
    drum = readout.scrolling_area
    panel = readout.readout_rect
    assert drum.height() <= panel.height() + 1
    assert drum.y() >= panel.top() - 1
    assert drum.y() + drum.height() <= panel.bottom() + 1
    assert drum.x() + drum.width() <= panel.right() + 1


def test_readout_rect_published_for_the_tapes(readout):
    assert readout.readout_rect is not None
    assert readout.readout_rect.height() > 0
    assert readout.readout_rect.width() <= readout.width()


def test_fail_scene_keeps_the_panel_shape(readout):
    readout.setFail(True)
    paths = [i for i in readout.fail_scene.items()
             if isinstance(i, QGraphicsPathItem)]
    assert len(paths) == 1
    assert paths[0].path().boundingRect().height() == pytest.approx(
        readout.readout_rect.height(), abs=1.0)


# --------------------------------------------------------------------------
# The tapes: read notch replaces the opaque black triangle
# --------------------------------------------------------------------------

def _paint_over(qtbot, widget, size, background=(255, 255, 255)):
    """Show `widget` on an opaque background of `background` and grab the
    result, so a translucent fill composites against a known colour (a bare
    grab has no defined backdrop). Returns the grabbed QImage."""
    host = QWidget()
    host.setAutoFillBackground(True)
    palette = host.palette()
    palette.setColor(host.backgroundRole(), QColor(*background))
    host.setPalette(palette)
    qtbot.addWidget(host)
    widget.setParent(host)
    widget.move(0, 0)
    widget.resize(*size)
    host.resize(*size)
    host.show()
    qtbot.waitExposed(host)
    widget.show()
    return host.grab().toImage()


@pytest.fixture
def notch_calls(monkeypatch):
    calls = []
    real = helpers.draw_readout_notch

    def spy(painter, x, y, size, side, border_color, **kwargs):
        calls.append({"x": x, "y": y, "size": size, "side": side,
                      "kwargs": kwargs})
        return real(painter, x, y, size, side, border_color, **kwargs)

    monkeypatch.setattr(helpers, "draw_readout_notch", spy)
    return calls


def test_airspeed_tape_notch_points_at_the_scale(fix, qtbot, notch_calls):
    widget = airspeed.Airspeed_Tape()
    _paint_over(qtbot, widget, (160, 480))
    assert notch_calls, "airspeed tape drew no read notch"
    call = notch_calls[-1]
    # The IAS box is on the RIGHT of the tape, so its notch points left.
    assert call["side"] == "left"
    # Sized off the readout panel, not off the tape width.
    assert call["size"] == pytest.approx(
        widget.numerical_display.readout_rect.height() * 0.42)


def test_altimeter_tape_notch_points_at_the_scale(fix, qtbot, notch_calls):
    widget = altimeter.Altimeter_Tape()
    _paint_over(qtbot, widget, (200, 480))
    assert notch_calls, "altimeter tape drew no read notch"
    # The altitude box is on the LEFT of the tape, so its notch points right.
    assert notch_calls[-1]["side"] == "right"


def test_altimeter_tape_notch_survives_numeric_box_off(fix, qtbot, notch_calls):
    """numeric_box=False removes the readout panel but must keep the read
    notch -- otherwise nothing marks where on the scale the value is read."""
    widget = altimeter.Altimeter_Tape(numeric_box=False)
    _paint_over(qtbot, widget, (200, 480))
    assert widget.numerical_display is None
    assert notch_calls and notch_calls[-1]["side"] == "right"
    assert notch_calls[-1]["size"] == pytest.approx(200 / 12.0)


@pytest.mark.parametrize(
    "kind,width,pointer_side",
    [("airspeed", 160, "left"), ("altimeter", 200, "right")],
)
def test_tape_read_notch_is_translucent_not_an_opaque_slab(
        fix, qtbot, kind, width, pointer_side):
    """Painted over white, the notch must land between the two extremes: not
    the untouched background (it IS drawn) and not an opaque black triangle
    (the pre-P5c look, which read as a hole punched in the sky)."""
    widget = (airspeed.Airspeed_Tape() if kind == "airspeed"
              else altimeter.Altimeter_Tape())
    img = _paint_over(qtbot, widget, (width, 480))
    step = -1 if pointer_side == "left" else 1
    x = int(widget.numeric_box_pos.x() + step * max(2, width // 40))
    y = int(widget.numeric_box_pos.y())
    pixel = img.pixelColor(x, y)
    assert 15 < pixel.red() < 200, (
        f"notch pixel at ({x}, {y}) is {pixel.red()} -- expected a translucent "
        "fill, not an opaque slab or an unpainted background")


def test_airspeed_tas_panel_is_translucent(fix, qtbot):
    """The TAS box was a solid white slab -- the brightest thing on the PFD for
    the least time-critical number on it. It is now the shared panel."""
    widget = airspeed.Airspeed_Tape(show_tas=True)
    img = _paint_over(qtbot, widget, (160, 480))
    # A point inside the TAS panel, clear of its label and value glyphs.
    pixel = img.pixelColor(int(160 * 0.10), 480 - 8)
    assert pixel.red() < 200, "TAS panel is still an opaque light slab"
