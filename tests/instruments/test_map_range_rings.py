"""Moving map range rings (G13, billmallard/pyEfis#136): configurable ring
fractions, labels on/off + clock position, colour/opacity/width/label size.

Geometry is pinned closed-form: ring radii and label anchors are computed from
the MapTransform (cy = h * (1 - anchor), px per NM = cy / range_nm) and asserted
against the layer's own accessors and the calls ``paint()`` actually makes."""
import math

import pytest
from PyQt6.QtCore import QRectF
from PyQt6.QtGui import QPaintEvent, QPainter

from pyefis.instruments import map as moving_map
from pyefis.instruments.map.layers import RangeRingsLayer, parse_ring_fractions
from pyefis.screens import screenbuilder_factory as factory


def _xform(w=400, h=400, range_nm=10.0, anchor=0.5):
    return moving_map.MapTransform(39.0, -106.0, range_nm, 0.0, w, h, anchor)


class _Owner:
    """Stand-in for the MovingMap widget: just the option attributes."""

    def __init__(self, **opts):
        for k, v in opts.items():
            setattr(self, k, v)


def _layer(**opts):
    lay = RangeRingsLayer()
    lay.configure(_Owner(**opts))
    return lay


class _RecordingPainter:
    """Records the drawing calls RangeRingsLayer.paint makes."""

    def __init__(self):
        self.ellipses, self.texts, self.pen, self.font = [], [], None, None

    def setPen(self, pen):
        self.pen = pen

    def setBrush(self, _b):
        pass

    def setFont(self, f):
        self.font = f

    def drawEllipse(self, c, rx, ry):
        self.ellipses.append((c.x(), c.y(), rx, ry))

    def drawText(self, rect, _align, text):
        self.texts.append((QRectF(rect), text))


# --- the default: an unconfigured map renders exactly as before -----------

@pytest.mark.parametrize("lay", [RangeRingsLayer(), _layer()],
                         ids=["never-configured", "configured-empty"])
def test_default_is_half_and_full_range(lay):
    x = _xform()                     # 400x400, anchor 50% -> cy = 200 px = 10 NM
    assert lay.fractions == (0.5, 1.0)
    assert lay.ring_radii_px(x) == pytest.approx([100.0, 200.0])
    p = _RecordingPainter()
    lay.paint(p, x)
    assert p.ellipses == [(200.0, 200.0, pytest.approx(100.0), pytest.approx(100.0)),
                          (200.0, 200.0, pytest.approx(200.0), pytest.approx(200.0))]
    assert [t for _r, t in p.texts] == ["5", "10"]


def test_default_style_matches_original_constants():
    """White alpha 140, width max(1, 0.2% of w), label px max(8, 2.5% of w),
    label rect (cx + 4, cy - r, 80, px + 6) -- the pre-G13 hardcoded paint."""
    lay = RangeRingsLayer()
    c = lay.pen_color()
    assert (c.red(), c.green(), c.blue(), c.alpha()) == (255, 255, 255, 140)
    assert lay.pen_width(_xform(w=400)) == 1.0
    assert lay.pen_width(_xform(w=1000)) == pytest.approx(2.0)
    assert lay.label_pixel_size(_xform(w=200)) == 8
    assert lay.label_pixel_size(_xform(w=800)) == 20
    x = _xform(w=800, h=480)          # cx 400, cy 240
    for r in (120.0, 240.0):
        assert lay.label_rect(x, r) == QRectF(404.0, 240.0 - r, 80.0, 26.0)


def test_default_widget_options_match_layer_defaults(fix, qtbot):
    w = moving_map.MovingMap()
    qtbot.addWidget(w)
    lay = RangeRingsLayer()
    lay.configure(w)
    fresh = RangeRingsLayer()
    for attr in ("fractions", "labels", "label_angle", "color", "opacity",
                 "width_px", "label_size"):
        assert getattr(lay, attr) == getattr(fresh, attr), attr


# --- ring set ----------------------------------------------------------------

def test_four_even_rings_radii():
    lay = _layer(range_ring_fractions="0.25,0.5,0.75,1")
    assert lay.ring_radii_px(_xform()) == pytest.approx([50.0, 100.0, 150.0, 200.0])
    p = _RecordingPainter()
    lay.paint(p, _xform())
    assert [t for _r, t in p.texts] == ["2.5", "5", "7.5", "10"]


def test_radii_follow_anchor_and_range():
    """Ownship at 30% up a 480 px map: cy = 336 px spans range_nm."""
    lay = _layer(range_ring_fractions="0.5,1,1.5")
    x = _xform(w=800, h=480, range_nm=20.0, anchor=0.3)
    assert x.cy == pytest.approx(336.0)
    assert lay.ring_radii_px(x) == pytest.approx([168.0, 336.0, 504.0])


@pytest.mark.parametrize("text,want", [
    ("0.5,1", (0.5, 1.0)),
    (" 1 , 0.5 ,0.5", (0.5, 1.0)),       # sorted, de-duplicated, spaces ok
    ("1", (1.0,)),
    ("0.33,0.66,1", (0.33, 0.66, 1.0)),
    ("0,-1,0.5,2,3", (0.5, 2.0)),         # outside (0, 2] dropped
    ("0,3", (0.5, 1.0)),                  # nothing left -> default
    ("", (0.5, 1.0)),
    (None, (0.5, 1.0)),
    ("half,1", (0.5, 1.0)),               # garbage -> default, never no rings
])
def test_parse_ring_fractions(text, want):
    assert parse_ring_fractions(text) == want


# --- labels ------------------------------------------------------------------

def test_labels_off_draws_rings_but_no_text():
    lay = _layer(range_ring_labels=False)
    p = _RecordingPainter()
    lay.paint(p, _xform())
    assert len(p.ellipses) == 2 and p.texts == []


@pytest.mark.parametrize("angle,dx,dy", [
    (0, 0.0, -1.0),       # top
    (90, 1.0, 0.0),       # right
    (180, 0.0, 1.0),      # bottom
    (270, -1.0, 0.0),     # left
    (45, math.sqrt(0.5), -math.sqrt(0.5)),
    (450, 1.0, 0.0),      # wraps to 90
])
def test_label_anchor_per_clock_angle(angle, dx, dy):
    lay = _layer(range_ring_label_angle=angle)
    x = _xform(w=800, h=480, anchor=0.5)  # cx 400, cy 240
    r = 120.0
    a = lay.label_anchor(x, r)
    assert (a.x(), a.y()) == (pytest.approx(400.0 + r * dx),
                              pytest.approx(240.0 + r * dy))
    rect = lay.label_rect(x, r)
    assert (rect.x(), rect.y()) == (pytest.approx(a.x() + 4.0), pytest.approx(a.y()))


def test_paint_places_labels_at_configured_angle():
    lay = _layer(range_ring_label_angle=90, range_ring_label_size=12)
    p = _RecordingPainter()
    lay.paint(p, _xform())               # cx = cy = 200, radii 100 / 200
    rects = [r for r, _t in p.texts]
    assert rects == [QRectF(304.0, 200.0, 80.0, 18.0),
                     QRectF(404.0, 200.0, 80.0, 18.0)]


# --- style -------------------------------------------------------------------

def test_style_options():
    lay = _layer(range_ring_color="#00ff00", range_ring_opacity=100,
                 range_ring_width=3, range_ring_label_size=14)
    c = lay.pen_color()
    assert (c.red(), c.green(), c.blue(), c.alpha()) == (0, 255, 0, 255)
    assert lay.pen_width(_xform(w=2000)) == 3.0       # fixed, not auto
    assert lay.label_pixel_size(_xform(w=2000)) == 14
    p = _RecordingPainter()
    lay.paint(p, _xform())
    assert p.pen.widthF() == 3.0
    assert p.pen.color().alpha() == 255
    assert p.font.pixelSize() == 14


@pytest.mark.parametrize("opts,alpha,rgb", [
    ({"range_ring_opacity": 0}, 0, (255, 255, 255)),
    ({"range_ring_opacity": 250}, 255, (255, 255, 255)),     # clamped
    ({"range_ring_opacity": "x"}, 140, (255, 255, 255)),     # bad -> default
    ({"range_ring_color": "notacolour"}, 140, (255, 255, 255)),
    ({"range_ring_color": ""}, 140, (255, 255, 255)),
])
def test_style_bad_values_fall_back(opts, alpha, rgb):
    c = _layer(**opts).pen_color()
    assert (c.red(), c.green(), c.blue()) == rgb and c.alpha() == alpha


# --- the range readout never depends on the ring labels ------------------------

def test_range_chip_shown_with_ring_labels_off(fix, qtbot, monkeypatch):
    seen = []

    class _P(QPainter):
        def drawText(self, *a):
            seen.append(a[-1])
            return super().drawText(*a)

    monkeypatch.setattr(moving_map, "QPainter", _P)
    w = moving_map.MovingMap()
    qtbot.addWidget(w)
    w.range_ring_labels = False
    w.resize(300, 300)
    w.show()
    qtbot.waitExposed(w)
    w.paintEvent(QPaintEvent(w.rect()))
    assert any(s.startswith("10 NM") for s in seen)


# --- declared for the editor / configurator ------------------------------------

def test_every_ring_option_is_a_declared_prop(fix, qtbot):
    props = {p.name: p for p in factory.REGISTRY["moving_map"].properties}
    w = moving_map.MovingMap()
    qtbot.addWidget(w)
    names = [n for n in vars(w) if n.startswith("range_ring_")]
    assert sorted(names) == sorted([
        "range_ring_fractions", "range_ring_labels", "range_ring_label_angle",
        "range_ring_color", "range_ring_opacity", "range_ring_width",
        "range_ring_label_size"])
    for n in names:
        assert n in props, n
        assert props[n].default == getattr(w, n), n
