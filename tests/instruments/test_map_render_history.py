"""MP13 (pyEfis #203): a pinch-out keeps map content out to the viewport
edges by painting the widest earlier window image behind the current one,
instead of the dark fill (briefs/map_gesture_perf_plan.md MP13)."""
import math

from PyQt6.QtGui import QColor, QImage, QPainter

from pyefis.instruments import map as moving_map
from pyefis.instruments.map import layers as map_layers
from pyefis.instruments.map.layers import RenderHistory
from pyefis.instruments.map.layers.roads import RoadsLayer
from pyefis.instruments.map.layers.terrain import TerrainLayer

LAT, LON = 34.5, -120.5
W = H = 300
DARK = QColor(16, 24, 32)        # MovingMap.paintEvent's background fill
RED = QColor(200, 0, 0)
GREEN = QColor(0, 160, 0)


def _xf(range_nm, lat=LAT, lon=LON, rot=0.0, defer=True):
    x = moving_map.MapTransform(lat, lon, range_nm, rot, W, H, 0.5)
    x.defer_render = defer
    return x


def _entry(layer, range_nm, color, lat=LAT, lon=LON, w=W, h=H):
    """A window image entry with the exact geometry ``_render`` gives one
    rendered at *range_nm* -- same n, same metres per pixel."""
    x = moving_map.MapTransform(lat, lon, range_nm, 0.0, w, h, 0.5)
    px_per_m = max(1.0, x.cy) / (range_nm * 1852.0)
    half_diag_m = 0.5 * math.hypot(w, h) / px_per_m * 1.25
    n = int(min(1024, max(64, 2 * half_diag_m * px_per_m)))
    img = QImage(n, n, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(color)
    return (img, layer._key(x), (lat, lon, 2 * half_diag_m / n))


def _terrain():
    lay = TerrainLayer()
    lay._cache = object()            # non-None: paint() proceeds
    lay._owner = None
    return lay


class _ReadyDB:
    ready = True


def _roads():
    lay = RoadsLayer()
    lay._db = _ReadyDB()
    lay._owner = None
    return lay


def _publish(lay, *entries):
    for e in entries:
        lay._img = e
        lay._history.add(e)


def _paint(lay, x):
    out = QImage(W, H, QImage.Format.Format_ARGB32)
    out.fill(DARK)
    p = QPainter(out)
    lay.paint(p, x)
    p.end()
    return out


def _px(img, x, y):
    return img.pixelColor(x, y).rgb() & 0xFFFFFF


# --- RenderHistory eviction -------------------------------------------------

def test_history_replaces_an_entry_of_the_same_range_bucket():
    lay = _terrain()
    h = RenderHistory()
    old = _entry(lay, 40.0, RED)
    new = _entry(lay, 40.0, GREEN, lat=LAT + 0.2)
    h.add(old)
    h.add(new)
    assert h.entries() == [new]


def test_history_is_three_deep_and_protects_the_widest():
    lay = _terrain()
    h = RenderHistory()
    wide = _entry(lay, 40.0, RED)
    h.add(wide)
    for r in (10.0, 12.0, 14.0, 17.0):
        h.add(_entry(lay, r, GREEN))
    got = h.entries()
    assert len(got) == 3
    assert wide in got                       # never pushed out by close-ins
    assert got[-1][1] == lay._key(_xf(17.0))


def test_history_evicts_a_flown_away_entry_before_the_oldest():
    lay = _terrain()
    h = RenderHistory()
    far = _entry(lay, 20.0, RED, lat=LAT - 3.0)      # 180 NM south
    near = _entry(lay, 40.0, RED)
    h.add(far)
    h.add(near)
    h.add(_entry(lay, 30.0, GREEN))
    h.add(_entry(lay, 10.0, GREEN))
    got = h.entries()
    assert far not in got and near in got
    assert len(got) == 3


def test_history_drops_entries_from_another_widget_size():
    lay = _terrain()
    h = RenderHistory()
    h.add(_entry(lay, 40.0, RED, w=400))
    h.add(_entry(lay, 10.0, GREEN))
    assert len(h) == 1
    assert h.widest(lay._key(_xf(10.0)))[1][3] == W


def test_process_job_records_each_publish():
    lay = _terrain()
    e40, e10 = _entry(lay, 40.0, RED), _entry(lay, 10.0, GREEN)
    by_key = {e40[1]: e40, e10[1]: e10}
    lay._render = lambda job: (by_key[job[0]][0], by_key[job[0]][2])
    lay._process_job((e40[1],))
    lay._process_job((e10[1],))
    assert [e[1] for e in lay._history.entries()] == [e40[1], e10[1]]
    assert lay._img[1] == e10[1]


# --- paint: the dark border a pinch-out used to show ------------------------

def test_terrain_pinch_out_without_history_shows_the_dark_border():
    """Baseline: the defect this item fixes. Current image rendered at
    10 NM, pinched out to 30 NM mid-gesture: corners are the dark fill."""
    lay = _terrain()
    _publish(lay, _entry(lay, 10.0, GREEN))
    out = _paint(lay, _xf(30.0))
    assert _px(out, W // 2, H // 2) == GREEN.rgb() & 0xFFFFFF
    assert _px(out, 1, 1) == DARK.rgb() & 0xFFFFFF


def test_terrain_pinch_out_paints_the_wider_cached_image_to_the_edges():
    lay = _terrain()
    _publish(lay, _entry(lay, 40.0, RED), _entry(lay, 10.0, GREEN))
    out = _paint(lay, _xf(30.0))
    assert _px(out, W // 2, H // 2) == GREEN.rgb() & 0xFFFFFF
    for cx, cy in ((1, 1), (W - 2, 1), (1, H - 2), (W - 2, H - 2)):
        assert _px(out, cx, cy) == RED.rgb() & 0xFFFFFF


def test_terrain_pinch_out_backdrop_registers_under_rotation():
    """Track-up rotation: the backdrop goes through the same R(-rot)
    painter transform as the current image (#90), so it still fills."""
    lay = _terrain()
    _publish(lay, _entry(lay, 40.0, RED), _entry(lay, 10.0, GREEN))
    out = _paint(lay, _xf(30.0, rot=37.0))
    for cx, cy in ((1, 1), (W - 2, 1), (1, H - 2), (W - 2, H - 2)):
        assert _px(out, cx, cy) == RED.rgb() & 0xFFFFFF


def test_no_backdrop_blit_while_the_current_image_still_covers(monkeypatch):
    """A small pinch-out the current image still covers (its 1.25x
    oversize) draws exactly one image, as before MP13."""
    calls = []
    real = map_layers.blit_window_image
    monkeypatch.setattr(map_layers, "blit_window_image",
                        lambda p, x, e, smooth=False: (calls.append(e[1]),
                                                       real(p, x, e, smooth)))
    lay = _terrain()
    e40, e10 = _entry(lay, 40.0, RED), _entry(lay, 10.0, GREEN)
    _publish(lay, e40, e10)
    _paint(lay, _xf(11.5))
    assert lay._key(_xf(11.5)) != e10[1]     # a stale-key blit, not exact
    assert calls == [e10[1]]


def test_roads_backdrop_is_clipped_out_of_the_current_footprint():
    """Roads are a transparent overlay: inside the current image the wider
    one must not show through, or every road there would draw twice."""
    lay = _roads()
    _publish(lay, _entry(lay, 40.0, RED), _entry(lay, 10.0, QColor(0, 0, 0, 0)))
    out = _paint(lay, _xf(30.0))
    assert _px(out, W // 2, H // 2) == DARK.rgb() & 0xFFFFFF
    assert _px(out, 1, 1) == RED.rgb() & 0xFFFFFF
