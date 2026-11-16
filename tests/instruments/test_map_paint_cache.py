"""MAPPAINT1 (AER-5668): the map's repaint got cheaper without drawing
anything different. Each test here renders the same view two ways -- the
new path and the old one -- and compares the pixels exactly.

- A repaint that only the ND overlay needs blits the cached layer image
  and must match a repaint that redraws every layer.
- The range rings are rasterized once and blitted; the blit must match
  drawing them, over any background colour.
- Airways and fixes project with numpy and skip what cannot reach the
  screen; they must match the per-row loop they replace, including a later
  airway line crossing an earlier airway label."""

import random

import numpy as np
import pytest
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPolygonF

from pyefis.instruments import map as moving_map
from pyefis.instruments.map import nd
from pyefis.instruments.map.layers import (STANDARD_PALETTE, ScreenImage,
                                           mark_drawn, qcolor)
from pyefis.instruments.map.layers.navaids import AirwaysLayer, FixesLayer

W, H = 650, 1000
LAT, LON = 35.7, -83.4


def _image(fill=None):
    img = QImage(W, H, QImage.Format.Format_RGB32)
    img.fill(fill if fill is not None else QColor(16, 24, 32))
    return img


def _noise(seed=7):
    """A background with every channel varied, so a blend that rounds
    differently from direct drawing shows up somewhere."""
    rng = np.random.default_rng(seed)
    img = _image()
    ptr = img.bits()
    ptr.setsize(img.sizeInBytes())
    buf = np.frombuffer(ptr, np.uint8).reshape(H, W, 4)
    buf[:, :, :3] = rng.integers(0, 256, (H, W, 3), dtype=np.uint8)
    buf[:, :, 3] = 255
    return img


def _painted(img, draw):
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    draw(p)
    p.end()
    return img


def _transform(rot_deg=0.0, range_nm=10.0):
    return moving_map.MapTransform(LAT, LON, range_nm, rot_deg, W, H, 0.5,
                                   palette=STANDARD_PALETTE)


# --- projection ---------------------------------------------------------

@pytest.mark.parametrize("rot", [0.0, 37.3, 307.0])
def test_to_screen_xy_lands_on_the_same_floats(rot):
    x = _transform(rot)
    rng = random.Random(3)
    lats = np.array([LAT + rng.uniform(-0.5, 0.5) for _ in range(200)])
    lons = np.array([LON + rng.uniform(-0.5, 0.5) for _ in range(200)])
    xs, ys = x.to_screen_xy(lats, lons)
    for la, lo, sx, sy in zip(lats.tolist(), lons.tolist(), xs.tolist(),
                              ys.tolist()):
        q = x.to_screen(la, lo)
        assert (sx, sy) == (q.x(), q.y())


# --- airways and fixes against the loops they replace --------------------

def _airway_rows(n=400, seed=11):
    """Segments scattered over the query window (2.2x range, as _bbox
    asks), so most are off screen; idents repeat, so each airway's label
    goes on its first row; a few lines cross the screen centre, over
    earlier labels."""
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        la1 = LAT + rng.uniform(-0.37, 0.37)
        lo1 = LON + rng.uniform(-0.45, 0.45)
        if i % 9 == 0:
            la2, lo2 = 2 * LAT - la1, 2 * LON - lo1
        else:
            la2 = la1 + rng.uniform(-0.08, 0.08)
            lo2 = lo1 + rng.uniform(-0.08, 0.08)
        rows.append(("V%d" % (i % 37), la1, lo1, la2, lo2))
    return rows


def _old_airways(p, x, rows):
    """AirwaysLayer.paint before MAPPAINT1, verbatim but for the
    snapshot."""
    pen = QPen(qcolor(getattr(x, "palette", STANDARD_PALETTE)["airway"]))
    pen.setWidthF(max(1.0, x.w * 0.003))
    f = QFont(x.font_family)
    f.setPixelSize(max(7, int(x.w * 0.018)))
    p.setFont(f)
    labelled = set()
    for awy, la1, lo1, la2, lo2 in rows:
        p.setPen(pen)
        e1 = x.to_screen(la1, lo1)
        e2 = x.to_screen(la2, lo2)
        p.drawLine(e1, e2)
        if awy not in labelled and x.range_nm <= 80:
            labelled.add(awy)
            mx, my = (e1.x() + e2.x()) / 2, (e1.y() + e2.y()) / 2
            if 0 < mx < x.w and 0 < my < x.h:
                p.setPen(QPen(QColor(150, 180, 240)))
                p.drawText(QRectF(mx - 30, my - f.pixelSize() - 2,
                                  60, f.pixelSize() + 4),
                           Qt.AlignmentFlag.AlignHCenter, awy)


def _old_fixes(p, x, rows):
    """FixesLayer.paint before MAPPAINT1, verbatim but for the snapshot."""
    s = max(3.0, x.w * 0.008)
    f = QFont(x.font_family)
    f.setPixelSize(max(7, int(x.w * 0.018)))
    p.setFont(f)
    p.setBrush(Qt.BrushStyle.NoBrush)
    pal = getattr(x, "palette", STANDARD_PALETTE)
    fix_pen = QPen(qcolor(pal["fix"]), pal["fix_width"])
    for fid, lat, lon in rows:
        c = x.to_screen(lat, lon)
        if not (0 < c.x() < x.w and 0 < c.y() < x.h):
            continue
        p.setPen(fix_pen)
        p.drawPolygon(QPolygonF([
            QPointF(c.x(), c.y() - s),
            QPointF(c.x() + s * 0.87, c.y() + s * 0.5),
            QPointF(c.x() - s * 0.87, c.y() + s * 0.5)]))
        p.setPen(QPen(QColor(200, 210, 235, 220)))
        p.drawText(QRectF(c.x() - 50, c.y() + s + 1, 100,
                          f.pixelSize() + 4),
                   Qt.AlignmentFlag.AlignHCenter, fid)
        mark_drawn(x, fid, c, c.y() + s + 1 + f.pixelSize() + 4, True)


def _layer_with(cls, rows):
    layer = cls()
    layer._snapshot = lambda x, max_range: rows
    return layer


@pytest.mark.parametrize("rot", [0.0, 307.0])
def test_airways_draw_what_the_row_loop_drew(qapp, rot):
    rows = _airway_rows()
    x = _transform(rot)
    old = _painted(_noise(), lambda p: _old_airways(p, x, rows))
    layer = _layer_with(AirwaysLayer, rows)
    new = _painted(_noise(), lambda p: layer.paint(p, _transform(rot)))
    assert new == old
    # Companion: the scene is not trivially empty or all on screen.
    xs, ys = x.to_screen_xy(np.array([r[1] for r in rows]),
                            np.array([r[2] for r in rows]))
    on = ((xs > 0) & (xs < W) & (ys > 0) & (ys < H)).sum()
    assert 0 < on < len(rows) // 2
    assert old != _noise()


def test_airway_culling_keeps_a_line_whose_ends_straddle_the_screen(qapp):
    """Both ends off screen, on opposite sides: the line crosses it and
    must draw."""
    x = _transform()
    rows = [("J1", LAT, LON - 0.6, LAT, LON + 0.6)]
    layer = _layer_with(AirwaysLayer, rows)
    new = _painted(_image(), lambda p: layer.paint(p, x))
    assert new == _painted(_image(), lambda p: _old_airways(p, x, rows))
    assert new != _image()


@pytest.mark.parametrize("rot", [0.0, 307.0])
def test_fixes_draw_what_the_row_loop_drew(qapp, rot):
    rng = random.Random(5)
    rows = [("FX%03d" % i, LAT + rng.uniform(-0.37, 0.37),
             LON + rng.uniform(-0.45, 0.45)) for i in range(400)]
    x_old, x_new = _transform(rot), _transform(rot)
    old = _painted(_noise(), lambda p: _old_fixes(p, x_old, rows))
    layer = _layer_with(FixesLayer, rows)
    new = _painted(_noise(), lambda p: layer.paint(p, x_new))
    assert new == old
    # The flight-plan layer reads what was drawn (G59): same records.
    assert x_new.drawn_points.keys() == x_old.drawn_points.keys()
    for k in x_old.drawn_points:
        assert ([(q.x(), q.y(), b, lab) for q, b, lab in x_new.drawn_points[k]]
                == [(q.x(), q.y(), b, lab)
                    for q, b, lab in x_old.drawn_points[k]])
    assert 0 < len(x_old.drawn_points) < len(rows) // 2


# --- screen-space images -------------------------------------------------

def _rings(range_nm=10.0, **opts):
    from pyefis.instruments.map.layers import RangeRingsLayer
    layer = RangeRingsLayer()
    for k, v in opts.items():
        setattr(layer, k, v)
    return layer, _transform(range_nm=range_nm)


def _old_rings(layer, p, x):
    """RangeRingsLayer.paint before MAPPAINT1, verbatim."""
    from pyefis.instruments.map.layers import format_range_nm
    ring_c, label_c = layer.colors(x)
    pen = QPen(ring_c)
    pen.setWidthF(layer.pen_width(x))
    label_pen = QPen(pen)
    label_pen.setColor(label_c)
    p.setBrush(Qt.BrushStyle.NoBrush)
    f = QFont(x.font_family)
    f.setPixelSize(layer.label_pixel_size(x))
    p.setFont(f)
    for frac, r_px in zip(layer.fractions, layer.ring_radii_px(x)):
        p.setPen(pen)
        p.drawEllipse(QPointF(x.cx, x.cy), r_px, r_px)
        if layer.labels:
            rect = layer.label_rect(x, r_px)
            if layer.label_kept_out(x, rect):
                continue
            p.setPen(label_pen)
            p.drawText(rect, Qt.AlignmentFlag.AlignLeft,
                       format_range_nm(x.range_nm * frac))


@pytest.mark.parametrize("opts", [
    {},
    # Rings close together, labels around the clock and fat strokes: a
    # later ring crosses an earlier ring's label.
    {"fractions": (0.5, 0.55, 0.6, 1.0, 1.5), "label_angle": 135.0,
     "width_px": 6.0, "label_size": 30},
])
def test_range_rings_blit_matches_drawing_them(qapp, opts):
    layer, x = _rings(**opts)
    ref, _x = _rings(**opts)
    direct = _painted(_noise(), lambda p: _old_rings(ref, p, x))
    _painted(_image(), lambda p: layer.paint(p, x))      # build the images
    builds = layer.image_builds
    blit = _painted(_noise(), lambda p: layer.paint(p, x))
    assert layer.image_builds == builds == len(layer.fractions)
    assert blit == direct
    assert direct != _noise()


def test_range_rings_image_follows_the_rings(qapp):
    """A new range alone leaves the rings where they were on screen (they
    are fractions of it): only the labels, drawn directly, change. A new
    ring width is a new image."""
    layer, x = _rings()
    ref, _x = _rings()
    _painted(_image(), lambda p: layer.paint(p, x))
    x20 = _rings(20.0)[1]
    got = _painted(_noise(), lambda p: layer.paint(p, x20))
    assert layer.image_builds == 2
    assert got == _painted(_noise(), lambda p: _old_rings(ref, p, x20))
    layer.width_px = ref.width_px = 4.0
    got = _painted(_noise(), lambda p: layer.paint(p, x20))
    assert layer.image_builds == 4
    assert got == _painted(_noise(), lambda p: _old_rings(ref, p, x20))


def _box():
    return QRectF(0.0, 0.0, W, H)


def test_screen_image_draws_directly_under_a_transformed_painter(qapp):
    calls = []
    img = ScreenImage()
    _painted(_image(), lambda p: (p.translate(3, 4),
                                  img.paint(p, W, H, _box(), "k",
                                            calls.append)))
    assert len(calls) == 1 and img.builds == 0


def test_screen_image_off_screen_bounds_draw_nothing(qapp):
    calls = []
    img = ScreenImage()
    got = _painted(_image(), lambda p: img.paint(
        p, W, H, QRectF(W + 10.0, 0.0, 50.0, 50.0), "k", calls.append))
    assert calls == [] and got == _image()


@pytest.fixture
def nd_map(fix, qtbot):
    for key, value in (("GS", 136.0), ("TAS", 128.0), ("WINDDIR", 250.0),
                       ("WINDSPD", 18.0)):
        fix.db.define_item(key, key, "float", -1e6, 1e6, "", 0, "")
        fix.db.set_value(key, value)
        item = fix.db.get_item(key)
        item.old = item.bad = item.fail = False
    m = moving_map.MovingMap(None)
    qtbot.addWidget(m)
    m.resize(W, H)
    m.nd_mode = "ctr"
    m.layer_airways = True
    m.layer_fixes = True
    m._build_layers()
    rng = random.Random(9)
    for layer in m._layers:
        if layer.id == "airways":
            layer._path = "x"
            rows = _airway_rows()
            layer._snapshot = lambda x, r, rows=rows: rows
        elif layer.id == "fixes":
            layer._path = "x"
            rows = [("FX%03d" % i, LAT + rng.uniform(-0.3, 0.3),
                     LON + rng.uniform(-0.3, 0.3)) for i in range(200)]
            layer._snapshot = lambda x, r, rows=rows: rows
    m._lat, m._lon, m._track, m._track_true = LAT, LON, 307.0, 301.0
    m._old = {"LAT": False, "LONG": False, "TRACKM": False}
    return m, fix


def _grab(m):
    return m.grab().toImage()


def test_overlay_only_repaint_matches_a_full_repaint(nd_map, qapp):
    """An ND readout change repaints over the cached layer image; the frame
    must be exactly what redrawing every layer gives."""
    m, fix = nd_map
    m.update()
    _grab(m)                                  # layers drawn, image cached
    renders, reuses = m.perf.layer_renders, m.perf.layer_reuses
    fix.db.set_value("GS", 141.0)             # an ND-only change
    m._track = 309.0                          # and the magnetic TRK box
    reused = _grab(m)
    assert (m.perf.layer_renders, m.perf.layer_reuses) == (renders,
                                                           reuses + 1)
    m.update()                                # what a layer publish does
    full = _grab(m)
    assert m.perf.layer_renders == renders + 1
    assert reused == full
    # Companion: the change did reach the screen.
    fix.db.set_value("GS", 136.0)
    m.update()
    assert _grab(m) != full


def test_a_moved_view_redraws_the_layers(nd_map, qapp):
    m, _fix = nd_map
    m.update()
    _grab(m)
    renders = m.perf.layer_renders
    m._lat += 0.01
    _grab(m)
    assert m.perf.layer_renders == renders + 1


def test_frame_clock_overlay_change_does_not_invalidate_the_layers(
        nd_map, qapp):
    """The clock's overlay-only path must not go through update(), which
    is what marks the layer image stale."""
    m, fix = nd_map
    m.isVisible = lambda: True
    m._frame_tick()
    gen = m._layer_gen
    fix.db.set_value("GS", 150.0)
    m._frame_tick()
    assert m._layer_gen == gen
    m._lat += 0.05                            # the view moves: layers redraw
    m._frame_tick()
    assert m._layer_gen == gen + 1


def test_a_moved_keep_out_redraws_the_layers(nd_map, qapp, monkeypatch):
    """The TRK box hides the range-ring label under it (G11c), and its
    width follows the track's digits in a proportional font. An overlay-only
    track change that moves the keep-out must redraw the layers, or a ring
    label would stay hidden, or drawn under the box."""
    m, _fix = nd_map
    m.nd_mode = "expanded"

    def keep_out(widget, x, own=None):
        return (QRectF(100.0 + widget._track, 50.0, 120.0, 400.0),)

    monkeypatch.setattr(nd, "keep_out", keep_out)
    m.update()
    _grab(m)
    renders = m.perf.layer_renders
    m._track = 330.0                          # overlay-only, keep-out moves
    moved = _grab(m)
    assert m.perf.layer_renders == renders + 1
    m.update()
    assert _grab(m) == moved


def _half_px_deg(m):
    """Half a screen px of latitude at the map's drawn scale: one step of
    the frame clock's position quantum."""
    from pyefis.instruments.ai.camera import M_PER_DEG_LAT
    return 0.5 / m._transform()._px_per_m / M_PER_DEG_LAT


@pytest.mark.parametrize("mode", ["ctr", "expanded"])
def test_sub_pixel_motion_keeps_the_layer_image(nd_map, qapp, mode):
    """The aircraft always moves a little between two ND readout changes.
    Under half a px (the frame clock's own threshold) the layers stay as
    drawn and the overlay is drawn in their transform; at half a px they
    redraw. In EXPANDED the TRK box keep-out is checked at the ownship
    position the image was drawn at, or it would never match in flight."""
    m, fix = nd_map
    m.nd_mode = mode
    step = _half_px_deg(m)
    m._lat = round(m._lat / step) * step      # the middle of a clock step
    m.update()
    _grab(m)
    drawn = m._layer_x
    renders, reuses = m.perf.layer_renders, m.perf.layer_reuses
    m._lat += 0.3 * step
    fix.db.set_value("GS", 142.0)
    _grab(m)
    assert (m.perf.layer_renders, m.perf.layer_reuses) == (renders,
                                                           reuses + 1)
    assert m._layer_x is drawn
    m._lat += 0.4 * step                      # into the next clock step
    _grab(m)
    assert m.perf.layer_renders == renders + 1
    assert m._layer_x is not drawn


def test_overlay_frames_draw_ownship_where_the_map_was_drawn(nd_map, qapp):
    """On an overlay-only frame ownship and the ND sit where they were on
    the frame that drew the layers, so the frame is that one with new
    readouts, not one with ownship nudged across a map that stayed put."""
    m, fix = nd_map
    step = _half_px_deg(m)
    m._lat = round(m._lat / step) * step
    m.update()
    drawn = _grab(m)
    m._lat += 0.2 * step
    m._lon += 0.2 * step
    fix.db.set_value("GS", 136.0)             # unchanged readout
    again = _grab(m)                          # a repaint without update()
    assert m.perf.layer_reuses >= 1
    assert again == drawn
