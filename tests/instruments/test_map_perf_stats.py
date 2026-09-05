"""MP6: MapPerfStats counters + GUI-thread responsiveness probe
(briefs/map_gesture_perf_plan.md section 4, pyEfis #98).

Correctness/instrumentation only -- these tests assert the counters and
the probe work, not that rendering changed (it hasn't: MP6 adds no
raster change). ``_process_job`` is exercised directly (no background
thread) so publish-vs-superseded is deterministic: the DoD only needs
the accounting to be right, not a race against a real worker."""
import sys
import threading
import time

import numpy as np
import pytest
from PyQt6.QtGui import QPaintEvent

from pyefis.instruments import map as moving_map
from pyefis.instruments.map.layers import RangeRingsLayer
from pyefis.instruments.map.layers.airports import AirportsLayer
from pyefis.instruments.map.layers.navaids import NavaidsLayer
from pyefis.instruments.map.layers.roads import RoadsLayer
from pyefis.instruments.map.layers.terrain import TerrainLayer
from pyefis.instruments.map.perf import (GuiProbe, MapPerfStats,
                                         PROBE_GAP_WARN_MS)


class _FakeCache:
    """Uniform 500 m land tile cache; no mosaic/mip support, so
    TerrainLayer._sample falls back to the per-tile path (same shape as
    test_moving_map.py's _LandCache)."""

    def get(self, la, lo):
        return np.full((1201, 1201), 500.0, dtype=np.float32)


class _FakeWaterDB:
    """One square 4-vertex lake, east of centre -- enough to exercise
    the water-path counters without a real WaterDB."""

    ready = True

    def __init__(self, lat0, lon0):
        d = 0.01
        clat, clon = lat0, lon0 + 0.05
        self._poly = type("P", (), {})()
        self._poly.vertices = [
            (clat - d, clon - d), (clat - d, clon + d),
            (clat + d, clon + d), (clat + d, clon - d)]

    def polygons_in_range(self, lat, lon, range_nm,
                          min_bbox_diag_deg=None, drop_ocean=False):
        yield self._poly


def _xform():
    return moving_map.MapTransform(34.5, -120.5, 10.0, 0.0, 200, 200, 0.5)


# --- LayerStats / WaterStats / _Ring -----------------------------------

def test_layer_stats_records_render_ms_and_max():
    from pyefis.instruments.map.perf import LayerStats
    ls = LayerStats()
    ls.record_render_ms(5.0)
    ls.record_render_ms(2.0)
    ls.record_render_ms(9.0)
    assert ls.last_render_ms == 9.0
    assert ls.max_render_ms == 9.0


def test_map_perf_stats_layer_get_or_create_is_stable():
    stats = MapPerfStats()
    a = stats.layer("terrain")
    b = stats.layer("terrain")
    assert a is b
    a.jobs_requested = 3
    assert stats.layer("terrain").jobs_requested == 3


def test_water_stats_record_round_trips():
    from pyefis.instruments.map.perf import WaterStats
    w = WaterStats()
    w.record(5, 200, 5, 200, 200)
    d = w.as_dict()
    assert d["polygons_before"] == 5 and d["vertices_before"] == 200
    assert d["qpointf_count"] == 200


def test_map_perf_stats_summary_text_contains_key_fields():
    stats = MapPerfStats()
    stats.record_paint_ms(5.0)
    stats.layer("terrain").jobs_requested += 1
    text = stats.summary_text()
    assert "frames" in text
    assert "terrain" in text


# --- is_settled ----------------------------------------------------------

def test_range_rings_default_is_settled_true():
    """Layers with no async render (brief: base contract) never block the
    settle measurement."""
    lay = RangeRingsLayer()
    assert lay.is_settled(_xform()) is True


def test_terrain_is_settled_true_when_layer_inactive():
    lay = TerrainLayer()   # no tile_path configured -> self._cache is None
    assert lay.is_settled(_xform()) is True


def test_terrain_is_settled_false_until_cache_matches_key(qapp):
    lay = TerrainLayer()
    lay._cache = _FakeCache()

    class Owner:
        _alt_ft = 0.0
    lay._owner = Owner
    x = _xform()
    assert lay.is_settled(x) is False    # nothing rendered yet
    key = lay._key(x)
    img, meta = lay._render((key, x.lat0, x.lon0, x.range_nm, x.w, x.h, x.cy))
    lay._img = (img, key, meta)
    assert lay.is_settled(x) is True


# --- per-layer job lifecycle counters (terrain: image worker) -----------

def test_terrain_process_job_publishes_and_counts(qapp):
    lay = TerrainLayer()
    lay._cache = _FakeCache()

    class Owner:
        _alt_ft = 0.0
        perf = MapPerfStats()
    lay._owner = Owner
    x = _xform()
    key = lay._key(x)
    job = (key, x.lat0, x.lon0, x.range_nm, x.w, x.h, x.cy)
    lay._job = job
    lay._process_job(job)

    ls = Owner.perf.layer("terrain")
    assert ls.jobs_started == 1
    assert ls.jobs_published == 1
    assert ls.jobs_superseded == 0
    assert ls.last_render_ms >= 0.0
    assert lay._img is not None and lay._img[1] == key


def test_terrain_process_job_supersede_when_job_moves_on(qapp, monkeypatch):
    """AER-588: a render that finishes after a newer job replaced
    ``_job`` is still published (newest-wins) -- MP6 counts it as both
    published and superseded, since it was already stale on arrival."""
    lay = TerrainLayer()
    lay._cache = _FakeCache()

    class Owner:
        _alt_ft = 0.0
        perf = MapPerfStats()
    lay._owner = Owner
    x = _xform()
    key = lay._key(x)
    job = (key, x.lat0, x.lon0, x.range_nm, x.w, x.h, x.cy)
    lay._job = job

    real_render = lay._render

    def fake_render(j):
        # Simulate a newer request arriving while this one "renders":
        # any value that doesn't equal ``job`` triggers the supersede path.
        lay._job = "a-newer-job-replaced-this-one"
        return real_render(j)

    monkeypatch.setattr(lay, "_render", fake_render)
    lay._process_job(job)

    ls = Owner.perf.layer("terrain")
    assert ls.jobs_started == 1
    assert ls.jobs_published == 1
    assert ls.jobs_superseded == 1
    assert lay._img is not None and lay._img[1] == key


def test_terrain_request_counts_once_for_same_key_repost(qapp, qtbot):
    """The #89 same-key dedup in ``_request`` must not double-count a
    repost as a second ``jobs_requested``. Uses a real background worker
    (unlike the ``_process_job`` tests above), so the owner needs a real
    ``update()`` -- a bare stub makes the worker thread's completion
    callback raise on a delayed background thread."""
    lay = TerrainLayer()
    lay._cache = _FakeCache()

    class Owner:
        _alt_ft = 0.0
        perf = MapPerfStats()

        def update(self):
            pass
    owner = Owner()
    lay._owner = owner
    x = _xform()
    key = lay._key(x)
    lay._request(key, x)
    lay._request(key, x)
    assert owner.perf.layer("terrain").jobs_requested == 1
    qtbot.waitUntil(lambda: lay._img is not None, timeout=1000)


# --- water-path counters (brief: polys/verts before+after, QPointF) -----

def test_terrain_water_counters_recorded(qapp):
    lat0, lon0 = 34.5, -120.5
    lay = TerrainLayer()
    lay._cache = _FakeCache()
    lay._water = _FakeWaterDB(lat0, lon0)

    class Owner:
        _alt_ft = 3000.0
        perf = MapPerfStats()
    lay._owner = Owner
    x = moving_map.MapTransform(lat0, lon0, 10.0, 0.0, 200, 200, 0.5)
    key = lay._key(x)
    lay._render((key, x.lat0, x.lon0, x.range_nm, x.w, x.h, x.cy))

    w = Owner.perf.water
    assert w.polygons_before == 1
    assert w.vertices_before == 4
    # No decimation until MP4: after == before.
    assert w.polygons_after == w.polygons_before
    assert w.vertices_after == w.vertices_before
    # No numpy fill until MP5: one QPointF per vertex, same as today.
    assert w.qpointf_count == 4


# --- roads / navaids / airports reuse the same accounting ---------------

class _FakeHighwayDB:
    ready = True

    def polylines_in_range(self, lat, lon, range_nm, classes=None):
        return iter(())


def test_roads_process_job_publishes_and_counts(qapp):
    lay = RoadsLayer()
    lay._db = _FakeHighwayDB()

    class Owner:
        perf = MapPerfStats()
    lay._owner = Owner
    x = _xform()
    key = lay._key(x)
    job = (key, x.lat0, x.lon0, x.range_nm, x.w, x.h, x.cy)
    lay._job = job
    lay._process_job(job)

    ls = Owner.perf.layer("roads")
    assert ls.jobs_started == 1 and ls.jobs_published == 1
    assert lay._img is not None


def test_navaids_process_job_publish_and_supersede(qapp, monkeypatch):
    lay = NavaidsLayer()

    class Owner:
        perf = MapPerfStats()
    lay._owner = Owner
    lay._path = "dummy"
    x = _xform()
    key = lay._key(x)
    job = (key, x.lat0, x.lon0, x.range_nm)
    monkeypatch.setattr(lay, "_query", lambda con, *a: [("V1", "VOR",
                                                          "115.0", 34.5,
                                                          -120.5)])

    lay._job = job
    con = lay._process_job(job, object())   # non-None con skips sqlite3.connect
    ls = Owner.perf.layer("navaids")
    assert ls.jobs_started == 1 and ls.jobs_published == 1
    assert lay._snap[0] == key

    # A second job that "moves on" during the query is still published
    # (newest-wins, AER-588), but counted as superseded too.
    key2 = (key[0] + 1, key[1], key[2])
    job2 = (key2, x.lat0, x.lon0, x.range_nm)
    lay._job = job2

    def fake_query(c, *a):
        lay._job = job    # a newer request replaced ours mid-collect
        return [("V2", "VOR", "116.0", 34.6, -120.6)]

    monkeypatch.setattr(lay, "_query", fake_query)
    lay._process_job(job2, con)
    assert ls.jobs_started == 2
    assert ls.jobs_published == 2
    assert ls.jobs_superseded == 1
    assert lay._snap[0] == key2


def test_airports_process_job_publish_and_supersede(qapp, monkeypatch):
    lay = AirportsLayer()

    class Owner:
        perf = MapPerfStats()
    lay._owner = Owner
    x = _xform()
    key = lay._key(x)
    job = (key, x.lat0, x.lon0, x.range_nm)
    lay._job = job
    monkeypatch.setattr(lay, "_collect", lambda j: [{"icao": "KXXX"}])
    lay._process_job(job)

    ls = Owner.perf.layer("airports")
    assert ls.jobs_started == 1 and ls.jobs_published == 1
    assert lay._snap == (key, [{"icao": "KXXX"}])


# --- MovingMap wiring: perf options default off, paint ms, settle -------

def test_perf_options_default_off_and_probe_stopped(fix, qtbot):
    w = moving_map.MovingMap()
    qtbot.addWidget(w)
    assert w.map_perf_log is False
    assert w.map_perf_overlay is False
    assert w.perf.probe.running is False


def test_map_perf_log_starts_and_stops_probe(fix, qtbot):
    w = moving_map.MovingMap()
    qtbot.addWidget(w)
    w.map_perf_log = True
    assert w.perf.probe.running is True
    w.map_perf_log = False
    assert w.perf.probe.running is False


def test_map_perf_overlay_also_starts_probe(fix, qtbot):
    w = moving_map.MovingMap()
    qtbot.addWidget(w)
    w.map_perf_overlay = True
    assert w.perf.probe.running is True


def test_paint_records_paint_ms_and_frame_count(fix, qtbot):
    w = moving_map.MovingMap()
    qtbot.addWidget(w)
    w.resize(200, 200)
    w.show()
    qtbot.waitExposed(w)
    assert w.perf.frames_painted == 0
    w.paintEvent(QPaintEvent(w.rect()))
    assert w.perf.frames_painted == 1
    p50, p95, mx, n = w.perf.paint_ms.stats()
    assert n == 1 and mx >= 0.0


def test_settle_latency_recorded_after_gesture_and_paint(fix, qtbot):
    """DoD-adjacent: with no data paths configured every layer is
    trivially settled (is_settled() short-circuits True), so one
    gesture call + one paint is enough to measure a real, deterministic
    settle latency end to end."""
    w = moving_map.MovingMap()
    qtbot.addWidget(w)
    w.resize(300, 300)
    w.show()
    qtbot.waitExposed(w)
    w.paintEvent(QPaintEvent(w.rect()))     # builds layers
    w.perf.settle_latency_ms = None

    w.rotate_by(5.0)
    assert w._perf_settle_pending is True
    w.paintEvent(QPaintEvent(w.rect()))
    assert w._perf_settle_pending is False
    assert w.perf.settle_latency_ms is not None
    assert w.perf.settle_latency_ms >= 0.0


# --- schema (mirrors gesture_frame_rate_in_schema) -----------------------

def test_perf_options_in_schema():
    from pyefis.editor import schema as sch
    opts = sch.build_schema()["instruments"]["moving_map"]["options"]
    assert "map_perf_log" in opts and opts["map_perf_log"]["default"] is False
    assert ("map_perf_overlay" in opts
            and opts["map_perf_overlay"]["default"] is False)


# --- GuiProbe: the DoD's GIL-starvation detector -------------------------

def test_gui_probe_reports_gap_when_gil_held(qtbot):
    """DoD: probe reports > 50 ms gaps when a test thread holds the GIL
    on purpose. ``sys.setswitchinterval`` is raised so a pure-Python
    busy loop on another thread genuinely starves the GUI thread for the
    duration -- the same failure class the brief measured from PyQt6's
    QPointF/QPainter construction not releasing the GIL (section 1.3),
    reproduced deterministically instead of via a slow real render."""
    probe = GuiProbe(interval_ms=5)
    probe.start(None)
    qtbot.wait(50)

    old_interval = sys.getswitchinterval()
    sys.setswitchinterval(1.0)
    try:
        def hog():
            t0 = time.perf_counter()
            x = 0
            while time.perf_counter() - t0 < 0.25:
                x += 1
        th = threading.Thread(target=hog, daemon=True)
        th.start()
        qtbot.wait(400)
        th.join()
    finally:
        sys.setswitchinterval(old_interval)
    probe.stop()

    stats = probe.stats()
    assert stats["max_ms"] > PROBE_GAP_WARN_MS
    assert stats["over_count"] >= 1
