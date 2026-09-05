#  SPDX-License-Identifier: GPL-2.0-or-later
#  Moving map performance instrumentation (MP6, briefs/map_gesture_perf_plan.md
#  section 4; pyEfis #98). Correctness/instrumentation only -- adds no raster
#  change and does not alter what gets painted.
#
#  MapPerfStats holds the per-widget counters the brief calls for: frames
#  painted, a paint-ms ring buffer (p50/p95/max), per-layer worker job
#  lifecycle counts + render ms, the water-path polygon/vertex/QPointF
#  counts, and the last measured gesture settle latency. GuiProbe is the
#  objective GIL-starvation detector from section 1.3 of the brief: a
#  10 ms QTimer measuring its own tick-to-tick wall-clock gap on the GUI
#  thread, so any worker (map or SVS) holding the GIL shows up as a gap
#  far larger than the timer period, independent of what stalled it.
#
#  Both pieces are effectively free when the owning ``map_perf_log`` /
#  ``map_perf_overlay`` options are off: MapPerfStats is a handful of
#  counters nobody reads, and GuiProbe's QTimer is only started while one
#  of those options is on (mirrors ai/svs.py's _SVSPerfLog gating).

import logging
import time
from collections import deque

from PyQt6.QtCore import QTimer

log = logging.getLogger(__name__)

#: how often map_perf_log emits a summary line (mirrors _SVSPerfLog).
REPORT_INTERVAL_S = 2.0
#: paint-ms / probe-gap ring buffer depth (brief section 4: "ring buffer 256").
RING_SIZE = 256
#: GuiProbe tick period (brief section 4: "a 10 ms QTimer").
PROBE_INTERVAL_MS = 10
#: gap threshold the brief counts separately ("count of gaps > 50 ms").
PROBE_GAP_WARN_MS = 50.0


def _percentiles(values):
    """p50/p95/max of an unordered iterable of floats; zeros when empty."""
    v = sorted(values)
    if not v:
        return (0.0, 0.0, 0.0)
    n = len(v)
    return (v[int(0.50 * (n - 1))], v[int(0.95 * (n - 1))], v[-1])


class _Ring:
    """Fixed-capacity ring buffer of floats with p50/p95/max/count."""

    def __init__(self, cap=RING_SIZE):
        self._buf = deque(maxlen=cap)

    def add(self, v):
        self._buf.append(float(v))

    def stats(self):
        p50, p95, mx = _percentiles(self._buf)
        return (p50, p95, mx, len(self._buf))

    def __len__(self):
        return len(self._buf)


class LayerStats:
    """Per-layer worker-job lifecycle counters (brief section 4): a job is
    ``requested`` when a new window/snapshot key is queued, ``started``
    when the worker thread picks it up, ``published`` when the finished
    result lands in the paint-side cache, and ``superseded`` when the
    worker finished the render but a newer job had already replaced
    ``_job`` while it ran -- the render is thrown away (brief section 2,
    root cause R2: "renders started and discarded per pinch"). Cumulative
    for the process lifetime, plus the last and max render wall-time."""

    def __init__(self):
        self.jobs_requested = 0
        self.jobs_started = 0
        self.jobs_published = 0
        self.jobs_superseded = 0
        self.last_render_ms = 0.0
        self.max_render_ms = 0.0

    def record_render_ms(self, ms):
        self.last_render_ms = ms
        if ms > self.max_render_ms:
            self.max_render_ms = ms

    def as_dict(self):
        return dict(jobs_requested=self.jobs_requested,
                    jobs_started=self.jobs_started,
                    jobs_published=self.jobs_published,
                    jobs_superseded=self.jobs_superseded,
                    last_render_ms=self.last_render_ms,
                    max_render_ms=self.max_render_ms)


class WaterStats:
    """Water-rasterization counters (brief section 4: "water polygons and
    vertices before/after decimation"; "QPointF count in the water
    path"). A snapshot of the most recent ``TerrainLayer._draw_water``
    call. Until MP4 (vertex decimation) and MP5 (numpy scanline fill)
    land, ``*_after`` mirrors ``*_before`` and ``qpointf_count`` equals
    ``vertices_after`` -- today's per-vertex QPointF path; MP4 will make
    ``*_after`` smaller and MP5 will drive ``qpointf_count`` to 0."""

    def __init__(self):
        self.polygons_before = 0
        self.vertices_before = 0
        self.polygons_after = 0
        self.vertices_after = 0
        self.qpointf_count = 0

    def record(self, polygons_before, vertices_before,
               polygons_after, vertices_after, qpointf_count):
        self.polygons_before = polygons_before
        self.vertices_before = vertices_before
        self.polygons_after = polygons_after
        self.vertices_after = vertices_after
        self.qpointf_count = qpointf_count

    def as_dict(self):
        return dict(polygons_before=self.polygons_before,
                    vertices_before=self.vertices_before,
                    polygons_after=self.polygons_after,
                    vertices_after=self.vertices_after,
                    qpointf_count=self.qpointf_count)


class GuiProbe:
    """A QTimer on the GUI thread measuring the wall-clock gap between
    consecutive ticks. It has to run ON the thread being probed -- a
    background thread would only measure its own scheduling, not the GUI
    event loop's -- so GIL starvation from ANY worker (map or SVS) shows
    up here as a gap far larger than ``interval_ms``. This is the
    objective "does the screen redraw" number the perf plan asks for in
    place of impressions (brief section 3)."""

    def __init__(self, interval_ms=PROBE_INTERVAL_MS,
                 gap_warn_ms=PROBE_GAP_WARN_MS):
        self.interval_ms = interval_ms
        self.gap_warn_ms = gap_warn_ms
        self.over_count = 0
        self._gaps = _Ring()
        self._last_ns = None
        self._timer = None

    @property
    def running(self):
        return self._timer is not None and self._timer.isActive()

    def start(self, parent):
        """Idempotent: a second start() while already running is a no-op."""
        if self._timer is not None:
            return
        self._timer = QTimer(parent)
        self._timer.timeout.connect(self._tick)
        self._last_ns = None
        self._timer.start(self.interval_ms)

    def stop(self):
        if self._timer is not None:
            self._timer.stop()
            self._timer.deleteLater()
            self._timer = None

    def _tick(self):
        now = time.perf_counter_ns()
        if self._last_ns is not None:
            gap_ms = (now - self._last_ns) / 1e6
            self._gaps.add(gap_ms)
            if gap_ms > self.gap_warn_ms:
                self.over_count += 1
        self._last_ns = now

    def stats(self):
        p50, p95, mx, n = self._gaps.stats()
        return dict(p50_ms=p50, p95_ms=p95, max_ms=mx, count=n,
                    over_count=self.over_count)

    def reset(self):
        self._gaps = _Ring()
        self.over_count = 0


class MapPerfStats:
    """Owns every MP6 counter for one MovingMap widget. Cheap to create
    unconditionally; the GuiProbe timer is the only piece with ongoing
    cost, and MovingMap only starts it while ``map_perf_log`` or
    ``map_perf_overlay`` is on."""

    def __init__(self):
        self.frames_painted = 0
        self.paint_ms = _Ring()
        self.layers = {}          # layer id -> LayerStats
        self.water = WaterStats()
        self.settle_latency_ms = None
        self.probe = GuiProbe()
        self._last_report = None

    def layer(self, layer_id):
        """Get-or-create the LayerStats for *layer_id*."""
        ls = self.layers.get(layer_id)
        if ls is None:
            ls = LayerStats()
            self.layers[layer_id] = ls
        return ls

    def record_paint_ms(self, ms):
        self.frames_painted += 1
        self.paint_ms.add(ms)

    def summary_text(self):
        p50, p95, mx, n = self.paint_ms.stats()
        lines = ["Map perf: %d frames, paint ms p50=%.1f p95=%.1f max=%.1f "
                 "(n=%d)" % (self.frames_painted, p50, p95, mx, n)]
        for lid in sorted(self.layers):
            ls = self.layers[lid]
            lines.append(
                "  %-10s req=%d start=%d pub=%d superseded=%d "
                "render ms last=%.1f max=%.1f" % (
                    lid, ls.jobs_requested, ls.jobs_started,
                    ls.jobs_published, ls.jobs_superseded,
                    ls.last_render_ms, ls.max_render_ms))
        w = self.water
        if w.polygons_before or w.vertices_before:
            lines.append(
                "  water polys %d->%d verts %d->%d qpointf=%d" % (
                    w.polygons_before, w.polygons_after,
                    w.vertices_before, w.vertices_after, w.qpointf_count))
        if self.settle_latency_ms is not None:
            lines.append("  settle latency %.0f ms" % self.settle_latency_ms)
        gp = self.probe.stats()
        lines.append(
            "  gui gap p50=%.1f p95=%.1f max=%.1f n=%d >%dms=%d" % (
                gp["p50_ms"], gp["p95_ms"], gp["max_ms"], gp["count"],
                int(self.probe.gap_warn_ms), gp["over_count"]))
        return "\n".join(lines)

    def maybe_report(self, now=None):
        """Log a summary at most every REPORT_INTERVAL_S (mirrors
        ai/svs.py's _SVSPerfLog.maybe_report). Returns True when it
        logged."""
        now = time.perf_counter() if now is None else now
        if self._last_report is None:
            self._last_report = now
            return False
        if now - self._last_report < REPORT_INTERVAL_S:
            return False
        self._last_report = now
        log.info(self.summary_text())
        return True
