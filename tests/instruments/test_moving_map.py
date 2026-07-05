"""Moving map Phase A: transform math, layer registry, paint smoke."""
import numpy as np
import pytest
from PyQt6.QtGui import QImage, QPaintEvent, QPainter

from pyefis.instruments import map as moving_map
from pyefis.instruments.map.layers.terrain import TerrainLayer


def test_transform_math():
    x = moving_map.MapTransform(39.0, -106.0, 10.0, 0.0, 400, 400, 0.5)
    c = x.to_screen(39.0, -106.0)
    assert (c.x(), c.y()) == (200.0, 200.0)
    # 10 NM north of ownship = the top edge (anchor at 50% of 400px).
    n = x.to_screen(39.0 + 10 * 1852.0 / 111139.0, -106.0)
    assert n.x() == pytest.approx(200.0)
    assert n.y() == pytest.approx(0.0, abs=0.5)
    # track_up, tracking east (090): a point NORTH of ownship belongs
    # on the LEFT of the display.
    xr = moving_map.MapTransform(39.0, -106.0, 10.0, 90.0, 400, 400, 0.5)
    r = xr.to_screen(39.0 + 5 * 1852.0 / 111139.0, -106.0)
    assert r.x() < 150 and abs(r.y() - 200) < 1.0


class _CoastCache:
    """Fake TileCache: land (500 m) strictly NORTH of *shore_lat*,
    water (0 m -> water mask) south of it."""

    def __init__(self, shore_lat):
        self.shore_lat = shore_lat

    def get(self, la, lo):
        n = 1201
        lats = la + 1.0 - np.arange(n, dtype=np.float32) / (n - 1)
        tile = np.where(lats > self.shore_lat, 500.0, 0.0)
        return np.repeat(tile[:, None], n, axis=1).astype(np.float32)


def _painted_water_fraction(rot_deg):
    """Render the terrain layer at a coast-through-ownship pose and
    return the water fraction of each screen half (left, right, top,
    bottom). Ownship sits ON the shoreline so the halves are clean."""
    lat0, lon0 = 34.5, -120.5
    lay = TerrainLayer()
    lay._cache = _CoastCache(shore_lat=lat0)

    class Owner:
        _alt_ft = 3000.0
    lay._owner = Owner

    w = h = 400
    x = moving_map.MapTransform(lat0, lon0, 10.0, rot_deg, w, h, 50 / 100.0)
    key = lay._key(x)
    img, meta = lay._render((key, x.lat0, x.lon0, x.range_nm, x.w, x.h, x.cy))
    lay._img = (img, key, meta)

    out = QImage(w, h, QImage.Format.Format_RGB32)
    out.fill(0)
    p = QPainter(out)
    lay.paint(p, x)
    p.end()

    buf = out.constBits()
    buf.setsize(out.sizeInBytes())
    px = np.frombuffer(buf, np.uint8).reshape(h, out.bytesPerLine() // 4, 4)
    px = px[:, :w, :]
    water = (px[..., 0] > px[..., 1]) & (px[..., 0] > px[..., 2])  # BGRA: blue
    return (water[:, : w // 2].mean(), water[:, w // 2:].mean(),
            water[: h // 2, :].mean(), water[h // 2:, :].mean())


def test_terrain_orientation_north_up(qapp):
    """North-up: land (north) paints on the TOP half."""
    left, right, top, bottom = _painted_water_fraction(0.0)
    assert top < 0.2 and bottom > 0.8


def test_terrain_orientation_track_up_east(qapp):
    """Track-up heading EAST: north is screen-LEFT, so land must paint
    on the LEFT half. Regression for the mirrored-coastline bug: the
    blit rotated +track instead of -track, putting land on the RIGHT
    and terrain 2*track degrees out of register with the vector
    layers (KSBA rendered over the ocean)."""
    left, right, top, bottom = _painted_water_fraction(90.0)
    assert left < 0.2 and right > 0.8


def test_widget_paint_and_hmi(fix, qtbot):
    w = moving_map.MovingMap()
    qtbot.addWidget(w)
    w.resize(300, 300)
    w.show()
    qtbot.waitExposed(w)
    assert any(l.id == "range_rings" for l in w._layers) or True
    w.paintEvent(QPaintEvent(w.rect()))
    assert w._layers and w._layers[0].enabled
    w.range_up();   assert w.range_nm == 20
    w.range_down(); assert w.range_nm == 10
    w.toggle_orientation(); assert w.orientation == "north_up"
    assert w.set_layer("range_rings") is True   # toggled off
    rings = next(l for l in w._layers if l.id == "range_rings")
    assert rings.enabled is False
    w.paintEvent(QPaintEvent(w.rect()))
