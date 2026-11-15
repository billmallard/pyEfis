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

import math

import pytest
from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QBrush, QColor
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
# Shared static-element drop-shadow tokens (AER-392 / pyEfis#142)
# --------------------------------------------------------------------------

def test_bake_blurred_silhouette_pads_the_canvas(qtbot):
    """The bake canvas must be bigger than the widget-sized target -- see
    SHADOW_CANVAS_PAD_RATIO -- or the Gaussian falloff clips into a hard
    edge before it can fully resolve (gotcha #2)."""
    def paint_dot(p):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(0, 0, 0)))
        p.drawEllipse(QRectF(40, 40, 20, 20))

    blur = 10.0
    img, pad = helpers.bake_blurred_silhouette(100, 100, paint_dot, blur)
    assert pad == int(math.ceil(blur * helpers.SHADOW_CANVAS_PAD_RATIO))
    assert img.width() == 100 + 2 * pad
    assert img.height() == 100 + 2 * pad
    # The shape's own centre is punched back out (AER-415) -- zero, not
    # opaque; the falloff just past the shape's edge is where the halo
    # actually lives, and a corner far from either is still empty -- proof
    # the bake drew a halo (not a blank canvas) without filling the shape.
    assert img.pixelColor(pad + 50, pad + 50).alpha() == 0
    assert img.pixelColor(pad + 60, pad + 50).alpha() > 0
    assert img.pixelColor(0, 0).alpha() == 0


def test_bake_blurred_silhouette_uses_the_requested_colour(qtbot):
    def paint_square(p):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(0, 0, 0)))
        p.drawRect(QRectF(10, 10, 30, 30))

    img, pad = helpers.bake_blurred_silhouette(
        60, 60, paint_square, 2.0, color=QColor(255, 0, 0), alpha=1.0)
    # The shape's own interior is punched out (AER-415), so sample the
    # falloff right at the square's edge rather than its centre.
    edge = img.pixelColor(pad + 40, pad + 25)
    assert edge.alpha() > 0
    assert edge.red() > edge.green()
    assert edge.red() > edge.blue()


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
# Corner radius: ONE height-based token (AER-413)
#
# The corner radius is READOUT_RADIUS_RATIO of the container's OWN panel
# height, for every readout box -- so the HSI HDG|MAG|CRS panel and the tape
# box share one corner from one number. These pin that invariant on both, so a
# change to _READOUT_PANEL_H or to the token fails loudly instead of letting
# the two silently drift apart (which is exactly what the earlier
# font_height-based TAPE_READOUT_RADIUS_RATIO allowed).
# --------------------------------------------------------------------------

def test_token_is_the_measured_invariant():
    """The one token is 0.145 -- 16.8px on the HSI's 115.52px panel, the
    proportion the AER-386 derivation actually measured -- not the 0.17 it
    first encoded (which had the 1.20 panel-height multiplier baked in)."""
    assert helpers.READOUT_RADIUS_RATIO == pytest.approx(0.145)
    assert not hasattr(helpers, "TAPE_READOUT_RADIUS_RATIO")


def test_tape_readout_radius_is_a_fraction_of_panel_height(readout):
    """The tape box corner is READOUT_RADIUS_RATIO of the panel's own height.
    Keyed to panel height, not font_height: changing _READOUT_PANEL_H moves the
    panel and its corner together, so the corner stays this fraction and keeps
    matching the HSI panel."""
    panel_h = readout.readout_rect.height()
    assert panel_h > 0
    assert readout.readout_radius == pytest.approx(
        panel_h * helpers.READOUT_RADIUS_RATIO)
    assert readout.readout_radius / panel_h == pytest.approx(
        helpers.READOUT_RADIUS_RATIO)


def test_hsi_panel_radius_is_the_same_fraction_of_panel_height(fix, qtbot, monkeypatch):
    """The HSI HDG|MAG|CRS panel corner is the SAME fraction of its OWN height
    as the tape box -- one token, one corner. Capture the radius the panel
    hands QPainter and check it is READOUT_RADIUS_RATIO of the panel height it
    was drawn at, independent of fontSize (the base it used to key to)."""
    from PyQt6.QtGui import QImage, QPainter
    from pyefis.instruments import hsi

    widget = hsi.HSI()
    qtbot.addWidget(widget)
    widget.resize(400, 400)
    widget.show()
    qtbot.waitExposed(widget)

    captured = {}
    real = helpers.draw_readout_panel

    def spy(painter, rect, radius, *a, **k):
        captured["radius"] = radius
        captured["h"] = QRectF(rect).height()
        return real(painter, rect, radius, *a, **k)

    monkeypatch.setattr(helpers, "draw_readout_panel", spy)

    img = QImage(400, 400, QImage.Format.Format_ARGB32)
    painter = QPainter(img)
    panel_h = 120.0
    widget._draw_readout_panel(
        painter, 40.0, 40.0, 200.0, panel_h, "h",
        [("HDG", "270", QColor("cyan")),
         ("MAG", "268", QColor("white")),
         ("CRS", "265", QColor("magenta"))])
    painter.end()

    assert captured["h"] == pytest.approx(panel_h)
    assert captured["radius"] == pytest.approx(
        panel_h * helpers.READOUT_RADIUS_RATIO)
    assert captured["radius"] / captured["h"] == pytest.approx(
        helpers.READOUT_RADIUS_RATIO)


# --------------------------------------------------------------------------
# The tapes: the read arrow is gone (Bill, 2026-08-27) -- not shrunk, not
# replaced by a tick/caret/hairline. Deleted for good.
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


def test_readout_notch_helper_is_gone():
    """draw_readout_notch() and its sizing helpers must not exist -- if this
    fails, the arrow (or something with the same job) has crept back."""
    assert not hasattr(helpers, "draw_readout_notch")
    assert not hasattr(airspeed.Airspeed_Tape, "_readout_notch_size")
    assert not hasattr(altimeter.Altimeter_Tape, "_readout_notch_size")


@pytest.fixture
def polygon_calls(monkeypatch):
    """Spy on every QPainter.drawPolygon call app-wide. The read-notch
    triangle was the only drawPolygon() call the tapes made outside the
    (disabled-here) trend indicator, so any call caught here means something
    is drawing a triangle marker again -- pixel-colour sampling can't
    distinguish that from ordinary antialiasing bleed off the box border, so
    this spies on the draw call itself instead."""
    from PyQt6.QtGui import QPainter
    calls = []
    real = QPainter.drawPolygon

    def spy(self, *args, **kwargs):
        calls.append(args)
        return real(self, *args, **kwargs)

    monkeypatch.setattr(QPainter, "drawPolygon", spy)
    return calls


def test_airspeed_tape_draws_no_arrow(fix, qtbot, polygon_calls):
    widget = airspeed.Airspeed_Tape(show_trend=False)
    _paint_over(qtbot, widget, (160, 480))
    assert not polygon_calls, "airspeed tape drew a polygon -- the arrow is back"


def test_altimeter_tape_draws_no_arrow(fix, qtbot, polygon_calls):
    widget = altimeter.Altimeter_Tape(show_trend=False)
    _paint_over(qtbot, widget, (200, 480))
    assert not polygon_calls, "altimeter tape drew a polygon -- the arrow is back"


def test_altimeter_tape_draws_no_arrow_with_numeric_box_off(fix, qtbot, polygon_calls):
    """numeric_box=False used to fall back to a width-derived notch. It must
    now draw nothing at that site either -- no replacement mark in this PR."""
    widget = altimeter.Altimeter_Tape(numeric_box=False, show_trend=False)
    _paint_over(qtbot, widget, (200, 480))
    assert widget.numerical_display is None
    assert not polygon_calls, "altimeter tape drew a polygon -- the arrow is back"


def test_airspeed_tas_panel_is_translucent(fix, qtbot):
    """The TAS box was a solid white slab -- the brightest thing on the PFD for
    the least time-critical number on it. It is now the shared panel."""
    widget = airspeed.Airspeed_Tape(show_tas=True)
    img = _paint_over(qtbot, widget, (160, 480))
    # A point inside the TAS panel, clear of its label and value glyphs.
    pixel = img.pixelColor(int(160 * 0.10), 480 - 8)
    assert pixel.red() < 200, "TAS panel is still an opaque light slab"
