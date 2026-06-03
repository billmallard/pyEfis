"""
Synthetic Vision System (SVS) terrain renderer for the pyEfis AI widget.

Reads SRTM3 HGT tiles and projects a terrain grid into the AI viewport
using the same pixelsPerDeg coordinate frame as the Flight Path Marker.

Rendering tiers (selected by config):
  cpu_sparse  — 48×48 NumPy grid, ~15 Hz on Raspberry Pi 4
  cpu_dense   — 128×128 NumPy grid, ~20 Hz on Raspberry Pi 5 / x86
  opengl      — GPU-backed mesh via PyQt6 OpenGL (work in progress —
                see docs/svs_opengl_plan.md; current stub falls back
                to polar on first draw)

Tile format: NASA SRTMGL3 V003, 1°×1° HGT tiles, big-endian int16,
1201×1201 samples. Void values (-32768) are treated as sea level.

SVS is disabled by default. Enable in screen YAML:
    svs:
        enabled: true
        renderer: cpu_sparse
        range_nm: 30
        tile_path: /media/terrain/srtm3
"""

import math
import os
import sqlite3
import struct
import logging
import time
from pathlib import Path


# ---------------------------------------------------------------------------
# Lightweight per-frame profiler. Each named segment accumulates wall-clock
# time and a call count; once the report interval elapses we log a single
# summary line and reset. Enabled via ``svs_perf_log: true`` in the SVS
# config block; zero overhead when disabled (the methods check a flag
# before doing any timing math).
# ---------------------------------------------------------------------------
class _SVSPerfLog:
    REPORT_INTERVAL_S = 2.0

    def __init__(self, enabled: bool = False):
        self.enabled = enabled
        self._accum: dict[str, int] = {}    # ns total since last report
        self._count: dict[str, int] = {}
        self._last_report = time.perf_counter() if enabled else 0.0

    def time(self, name: str):
        """Context manager that times the with-block and adds it to
        the accumulator under *name*. No-ops cleanly when disabled."""
        if not self.enabled:
            return _NoopTimer()
        return _PerfTimer(self, name)

    def add_ns(self, name: str, ns: int):
        if not self.enabled:
            return
        self._accum[name] = self._accum.get(name, 0) + ns
        self._count[name] = self._count.get(name, 0) + 1

    def maybe_report(self):
        if not self.enabled:
            return
        now = time.perf_counter()
        if now - self._last_report < self.REPORT_INTERVAL_S:
            return
        elapsed = now - self._last_report
        lines = [f"SVS perf (last {elapsed:.1f}s):"]
        for name in sorted(self._accum, key=lambda k: -self._accum[k]):
            n = self._count[name]
            total_ms = self._accum[name] / 1e6
            per_call_ms = total_ms / n if n else 0
            pct = 100.0 * (self._accum[name] / 1e9) / elapsed
            lines.append(
                f"  {name:<30} {n:>5} calls  "
                f"{total_ms:>8.1f}ms total  "
                f"{per_call_ms:>7.2f}ms/call  "
                f"{pct:>5.1f}%")
        log.info("\n".join(lines))
        self._accum.clear()
        self._count.clear()
        self._last_report = now


class _PerfTimer:
    """Tiny context manager that records the with-block duration."""
    __slots__ = ("_p", "_name", "_t0")

    def __init__(self, p, name):
        self._p = p
        self._name = name

    def __enter__(self):
        self._t0 = time.perf_counter_ns()
        return self

    def __exit__(self, *exc):
        self._p.add_ns(self._name, time.perf_counter_ns() - self._t0)
        return False


class _NoopTimer:
    """Returned when profiling is off — zero allocation, zero work."""
    __slots__ = ()
    def __enter__(self): return self
    def __exit__(self, *exc): return False

import numpy as np
from PyQt6.QtCore import QLineF, QPointF, QRectF
from PyQt6.QtGui import (QBrush, QColor, QFont, QFontMetricsF, QPainter, QPen,
                         QPolygonF, QTransform)

log = logging.getLogger(__name__)

# SRTM3 tile constants
SRTM3_SAMPLES = 1201          # samples per side (includes 1-sample overlap)
SRTM3_VOID    = -32768        # void / no-data marker

# Clearance colour thresholds (ft above terrain)
COLOR_SAFE      = QColor(0,   100,  0)    # dark green  — ≥ green threshold
COLOR_CAUTION   = QColor(180, 130,  0)    # amber       — yellow threshold to green
COLOR_WARNING   = QColor(200,  40,  0)    # dark red    — 0 to yellow threshold
COLOR_CONFLICT  = QColor(180,   0, 180)   # magenta     — aircraft at or below terrain
COLOR_WATER     = QColor( 20,  80, 150)   # ocean blue  — SRTM void / open water

# Sentinel written into elevation arrays where the source tile was void (ocean).
# Must be far enough negative that real below-sea-level terrain (≥ −430 m) is
# never mistaken for water.
_WATER_SENTINEL = -9999.0

# Rendering grid sizes per tier (used by the legacy rectangular tiers).
# The polar tier reads its parameters from POLAR_DEFAULTS instead.
GRID_SIZES = {
    "cpu_sparse": 48,
    "cpu_dense":  128,
    "cpu_ultra":  192,  # ~2.3× more quads than dense; SRTM3 data supports it
    "polar":      0,    # polar tier uses (n_range, n_az) — see POLAR_DEFAULTS
    "opengl":     0,    # GPU mesh — dispatched via SVSGLRenderer in svs_gl.py
                         # (work in progress; current stub falls back to polar)
}

# Polar (range, azimuth) tier defaults. The polar tier samples terrain on a
# forward-facing fan centred on the aircraft, with a radial warp that
# concentrates samples near the aircraft (finer near, coarser far). See
# docs/svs_rendering.md for the rationale.
#
# Cells = n_range × n_az. At the defaults below: 80 × 120 = 9,600 cells —
# 42% fewer quads than cpu_dense (16k) but ~25% faster per frame and
# noticeably crisper in the near-field thanks to the radial LOD. Tuned
# from an A/B sweep at 39.20 N / 106.85 W, 12,000 ft, head 150°.
POLAR_DEFAULTS = {
    "n_range":     80,    # radial samples
    "n_az":        120,   # azimuthal samples
    "fov_deg":     140.0, # total forward field-of-view (±70°)
    "radial_warp": 1.5,   # outer cell ~10× inner cell at default n_range
    "r_min_nm":    0.05,  # epsilon at r=0 to avoid the singularity
}


# ---------------------------------------------------------------------------
# HGT tile reader
# ---------------------------------------------------------------------------

def tile_name(lat: int, lon: int) -> str:
    ns = "N" if lat >= 0 else "S"
    ew = "E" if lon >= 0 else "W"
    return f"{ns}{abs(lat):02d}{ew}{abs(lon):03d}"


def _hgt_path(tile_root: Path, lat: int, lon: int) -> Path | None:
    """Find the HGT file for the 1°×1° tile whose SW corner is (lat, lon)."""
    name = tile_name(lat, lon)
    ns_dir = f"{'N' if lat >= 0 else 'S'}{abs(lat):02d}"
    candidates = [
        tile_root / ns_dir / f"{name}.hgt",
        tile_root / f"{name}.hgt",
        tile_root / f"{name}.HGT",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def load_tile(tile_root: Path, lat: int, lon: int) -> np.ndarray | None:
    """
    Load an SRTM3 HGT tile and return a (1201, 1201) int16 NumPy array.
    Row 0 = northernmost row; column 0 = westernmost column.
    Returns None if the tile file is not found.
    """
    path = _hgt_path(tile_root, lat, lon)
    if path is None:
        return None
    try:
        data = np.fromfile(path, dtype=">i2").reshape(SRTM3_SAMPLES, SRTM3_SAMPLES)
        data = data.astype(np.float32)
        data[data == SRTM3_VOID] = _WATER_SENTINEL
        return data
    except Exception as e:
        log.warning(f"SVS: failed to load tile {path}: {e}")
        return None


def elevation_at(tile: np.ndarray, tile_lat: int, tile_lon: int,
                 lat: float, lon: float) -> float:
    """Bilinear interpolation of elevation at (lat, lon) from a loaded tile."""
    row_f = (tile_lat + 1.0 - lat) * (SRTM3_SAMPLES - 1)
    col_f = (lon - tile_lon)       * (SRTM3_SAMPLES - 1)
    row = int(row_f); col = int(col_f)
    row = max(0, min(row, SRTM3_SAMPLES - 2))
    col = max(0, min(col, SRTM3_SAMPLES - 2))
    dr = row_f - row; dc = col_f - col
    return (tile[row,   col  ] * (1 - dr) * (1 - dc) +
            tile[row,   col+1] * (1 - dr) *      dc  +
            tile[row+1, col  ] *      dr  * (1 - dc) +
            tile[row+1, col+1] *      dr  *      dc)


# ---------------------------------------------------------------------------
# Terrain cache — keeps recently used tiles in memory
# ---------------------------------------------------------------------------

class TileCache:
    def __init__(self, tile_root: Path, max_tiles: int = 9):
        self.tile_root = tile_root
        self.max_tiles = max_tiles
        self._cache: dict[tuple, np.ndarray] = {}
        self._order: list[tuple] = []

    def get(self, lat: int, lon: int) -> np.ndarray | None:
        key = (lat, lon)
        if key in self._cache:
            self._order.remove(key)
            self._order.append(key)
            return self._cache[key]
        tile = load_tile(self.tile_root, lat, lon)
        if tile is not None:
            self._cache[key] = tile
            self._order.append(key)
            if len(self._order) > self.max_tiles:
                evict = self._order.pop(0)
                del self._cache[evict]
        return tile

    def elevation(self, lat: float, lon: float) -> float:
        """Return MSL elevation in metres at (lat, lon), or 0.0 if no tile."""
        tile_lat = int(math.floor(lat))
        tile_lon = int(math.floor(lon))
        tile = self.get(tile_lat, tile_lon)
        if tile is None:
            return 0.0
        return elevation_at(tile, tile_lat, tile_lon, lat, lon)


# ---------------------------------------------------------------------------
# Embedded airport / runway database
# Populated with hand-checked FAA data; replaced later by NASR CSV download.
# Each runway entry: thr1 = first threshold, thr2 = opposite threshold.
# Coordinates from FAA NASR; elevations in ft MSL; width in ft.
# ---------------------------------------------------------------------------
_AIRPORT_DB = {
    "KASE": {
        "label": "ASE",
        "ref_lat": 39.2232, "ref_lon": -106.8688, "elev_ft": 7820,
        "runways": [
            {   # Runway 15/33 — Aspen/Pitkin County Airport
                "thr1_lat": 39.2282, "thr1_lon": -106.8723, "thr1_elev_ft": 7828,
                "thr2_lat": 39.2075, "thr2_lon": -106.8644, "thr2_elev_ft": 7938,
                "width_ft": 100,
            },
        ],
    },
}

# ---------------------------------------------------------------------------
# SVS renderer
# ---------------------------------------------------------------------------

NM_TO_DEG = 1.0 / 60.0   # 1 NM ≈ 1/60 degree latitude

class SVSRenderer:
    """
    Projects a terrain grid into the AI viewport.

    Coordinate convention matches the AI + FPM: the viewport centre is the
    aircraft reference (pitch=0, roll=0). pixelsPerDeg converts angular
    offsets to pixels. The terrain is projected point-by-point: for each
    grid sample we compute its bearing and elevation angle relative to the
    aircraft, then map those to (x, y) in the AI viewport using the same
    roll/pitch transform as the FPM.
    """

    def __init__(self, config: dict):
        self.enabled      = config.get("enabled", False)
        self.renderer     = config.get("renderer", "cpu_sparse")
        self.range_nm     = float(config.get("range_nm", 30))
        tile_path         = config.get("tile_path", "")
        self.cache        = TileCache(Path(tile_path)) if tile_path else None

        # Optional airport / runway database. When configured the
        # hand-coded _AIRPORT_DB fallback is bypassed; NASR gives full
        # CONUS coverage with widths/markings/displaced thresholds for
        # Tier C rendering, CIFP gives coarser nationwide coverage.
        from pyefis.instruments.ai.airport_db import make_airport_db
        self.airport_db = make_airport_db(config)
        # Within this distance, runways render with painted surface markings
        # (FAA AC 150/5340-1L). Beyond it, the symbol-style grey rectangle.
        self.detail_distance_nm = float(config.get("detail_distance_nm", 3.0))
        # When the aircraft is within this distance of ANY airport in the
        # database, terrain colouring collapses to a 2-colour scheme:
        # SAFE (green) for terrain below the aircraft, CONFLICT (magenta)
        # for terrain above. The 500/1000 ft warning/caution bands are
        # suppressed — they would otherwise paint the whole pattern area
        # red on a normal landing approach. Set to 0 to disable.
        self.airport_proximity_nm = float(config.get("airport_proximity_nm", 5.0))

        # Optional FAA DOF obstacle database. Renders towers, antennas,
        # tall buildings as vertical poles. ``obstacle_min_agl_ft`` filters
        # the ~636k nationwide records down to charted obstacles worth
        # showing (default 200 ft, matching the FAA charting threshold).
        from pyefis.instruments.ai.obstacle_db import ObstacleDB
        self.obstacle_db = ObstacleDB(config.get("dof_db_path", "") or None)
        self.obstacle_min_agl_ft = float(config.get("obstacle_min_agl_ft", 200.0))

        # Optional water-polygon database (oceans + lakes + rivers as
        # OSM / Natural Earth vector polygons). When configured, water
        # bodies are painted on top of the terrain layer with the
        # standard COLOR_WATER blue, fixing the "sea-level cells look
        # like SAFE-green terrain" problem the SRTM-only path leaves
        # at coastlines and over lakes.
        from pyefis.instruments.ai.water_db import WaterDB
        # water_max_vertices caps the per-polygon vertex count at load
        # time. OSM coastline polygons can carry thousands of vertices
        # at 30 m spacing — finer detail than the cockpit display can
        # resolve at typical SVS ranges, and a real CPU bottleneck on
        # the Python projection loop. None = use WaterDB's default.
        self.water_db = WaterDB(
            config.get("water_db_path", "") or None,
            max_vertices=config.get("water_max_vertices"))
        self.green_ft     = float(config.get("clearance_green_ft",  1000))
        self.yellow_ft    = float(config.get("clearance_yellow_ft",  500))
        self.terrain_fill  = config.get("terrain_fill", True)
        self.grid_lines    = config.get("grid_lines", True)
        self.auto_range    = config.get("auto_range", True)
        self.min_range_nm  = float(config.get("min_range_nm", 8.0))
        self._grid_n       = GRID_SIZES.get(self.renderer, 48)

        # OpenGL tier state — see docs/svs_opengl_plan.md. The renderer
        # is lazy-constructed inside draw(), so we can probe Qt's OpenGL
        # context capability at a point where a QPainter is available
        # rather than at SVSRenderer init time.
        self._gl_renderer        = None
        self._gl_init_attempted  = False

        # Per-frame profiler. ``svs_perf_log: true`` in the SVS config
        # turns on a lightweight per-segment timing pass that prints a
        # summary line every couple of seconds. Off by default; zero
        # overhead when disabled.
        self._perf = _SVSPerfLog(
            enabled=bool(config.get("svs_perf_log", False)))
        if self._perf.enabled:
            log.info("SVS perf logging enabled")

        # Polar tier parameters — only consulted when renderer == "polar"
        self._is_polar     = (self.renderer == "polar")
        self._n_range      = int(config.get("n_range",
                                            POLAR_DEFAULTS["n_range"]))
        self._n_az         = int(config.get("n_az",
                                            POLAR_DEFAULTS["n_az"]))
        self._fov_deg      = float(config.get("fov_deg",
                                              POLAR_DEFAULTS["fov_deg"]))
        self._radial_warp  = float(config.get("radial_warp",
                                              POLAR_DEFAULTS["radial_warp"]))
        self._r_min_nm     = float(config.get("r_min_nm",
                                              POLAR_DEFAULTS["r_min_nm"]))

    @property
    def ready(self) -> bool:
        return self.enabled and self.cache is not None and self.cache.tile_root.is_dir()

    def _auto_range_nm(self, ac_lat: float, ac_lon: float,
                       ac_alt_ft: float) -> float:
        """Compute the effective rendered range in NM, scaling down from
        ``range_nm`` based on AGL and MSL when ``auto_range`` is on.
        Shared by the polar/CPU rasterisation path and the GL overlay
        path so both honour the same auto-scale rule."""
        _agl_elev, _ = self._sample_elevations(
            np.array([[ac_lat]]), np.array([[ac_lon]]))
        ac_ground_m = float(_agl_elev[0, 0])
        agl_ft = ac_alt_ft - ac_ground_m * 3.28084
        if self.auto_range:
            agl_range = 0.1 * math.sqrt(max(0.0, agl_ft))
            msl_range = ac_alt_ft * 0.001
            return min(self.range_nm,
                       max(self.min_range_nm, agl_range, msl_range))
        return self.range_nm

    def _clearance_color(self, clearance_ft: float) -> QColor:
        if clearance_ft < 0:
            return COLOR_CONFLICT
        elif clearance_ft < self.yellow_ft:
            return COLOR_WARNING
        elif clearance_ft < self.green_ft:
            return COLOR_CAUTION
        return COLOR_SAFE

    def draw(self, p: QPainter, w: int, h: int,
             ac_lat: float, ac_lon: float, ac_alt_ft: float,
             pitch_deg: float, roll_deg: float, heading_deg: float,
             pixels_per_deg: float):
        """
        Draw the SVS terrain overlay onto the AI viewport.

        Called from AI.paintEvent() when SVS is enabled and data is ready.
        The painter p has NO active transform — SVS builds its own.
        """
        if not self.ready:
            return

        # ------------------------------------------------------------------
        # OpenGL tier dispatch (work-in-progress per docs/svs_opengl_plan.md).
        # Lazy-init the GL renderer on first draw — that's the earliest point
        # at which a Qt OpenGL context can be created. Any exception during
        # construction OR during the first draw downgrades self.renderer to
        # "polar" permanently; we never re-attempt GL in this process.
        # ------------------------------------------------------------------
        if self.renderer == "opengl":
            if (self._gl_renderer is None
                    and not self._gl_init_attempted):
                self._gl_init_attempted = True
                try:
                    from pyefis.instruments.ai.svs_gl import SVSGLRenderer
                    self._gl_renderer = SVSGLRenderer(self)
                except Exception as e:
                    log.warning(
                        "SVS OpenGL renderer unavailable (%s); "
                        "falling back to polar tier", e)
            if self._gl_renderer is not None:
                try:
                    with self._perf.time("gl_terrain"):
                        self._gl_renderer.draw(
                            p, w, h, ac_lat, ac_lon, ac_alt_ft,
                            pitch_deg, roll_deg, heading_deg, pixels_per_deg)
                    # GL drew the terrain; paint the CPU overlays on top.
                    # _draw_obstacles needs the auto-ranged range_nm.
                    with self._perf.time("auto_range"):
                        range_nm = self._auto_range_nm(
                            ac_lat, ac_lon, ac_alt_ft)
                    p.save()
                    p.resetTransform()
                    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                    try:
                        # Water FIRST so runway/obstacle overlays render
                        # cleanly above it (a runway on a bridge, a
                        # navaid in a bay, an OSM-mapped pier, etc).
                        with self._perf.time("water"):
                            self._draw_water(
                                p, w, h, ac_lat, ac_lon, ac_alt_ft,
                                pitch_deg, roll_deg, heading_deg,
                                pixels_per_deg, range_nm)
                        with self._perf.time("runways"):
                            self._draw_runways(
                                p, w, h, ac_lat, ac_lon, ac_alt_ft,
                                pitch_deg, roll_deg, heading_deg,
                                pixels_per_deg)
                        with self._perf.time("obstacles"):
                            self._draw_obstacles(
                                p, w, h, ac_lat, ac_lon, ac_alt_ft,
                                pitch_deg, roll_deg, heading_deg,
                                pixels_per_deg, range_nm)
                    finally:
                        p.restore()
                    self._perf.maybe_report()
                    return
                except Exception as e:
                    log.warning(
                        "SVS OpenGL draw failed (%s); falling back to polar "
                        "permanently", e)
                    self._gl_renderer = None
            # Either init failed or first draw failed — switch the renderer
            # type and continue into the polar path below.
            self.renderer = "polar"
            self._is_polar = True

        range_nm = self._auto_range_nm(ac_lat, ac_lon, ac_alt_ft)
        range_deg = range_nm * NM_TO_DEG
        lat_cos = math.cos(math.radians(ac_lat))

        # Are we close enough to a known airport to switch to the 2-colour
        # "airport pattern" terrain scheme? We only need to know whether the
        # database yields ANY airport within proximity range — the same
        # query the runway renderer will run again below, but cached.
        near_airport = False
        if (self.airport_proximity_nm > 0.0
                and getattr(self, "airport_db", None) is not None
                and self.airport_db.ready):
            for _ in self.airport_db.airports_in_range(
                    ac_lat, ac_lon, self.airport_proximity_nm):
                near_airport = True
                break

        # ------------------------------------------------------------------
        # Build the sample grid in geographic coordinates.
        #
        # Two paths:
        #   - polar:     (range, azimuth) fan, finer near the aircraft.
        #                Saves the ~50% of samples wasted behind the aircraft
        #                on the rectangular path, and concentrates resolution
        #                where collision geometry matters most.
        #   - rectangular (legacy cpu_sparse/dense/ultra): uniform lat/lon grid.
        # ------------------------------------------------------------------
        head_rad = math.radians(heading_deg)
        cos_h, sin_h = math.cos(head_rad), math.sin(head_rad)
        if self._is_polar:
            n_r  = self._n_range
            n_az = self._n_az
            fov  = self._fov_deg
            warp = self._radial_warp
            r_min_nm_eff = min(self._r_min_nm, range_nm * 0.01)

            # Radial samples (NM), warped so cells are finer near the aircraft.
            # The outer endpoint is nudged slightly under range_nm so the
            # shared visibility test (range_deg_grid < range_deg) keeps the
            # outermost ring of quads.
            r_max_eff = range_nm * (1.0 - 1e-6)
            t = np.linspace(0.0, 1.0, n_r, dtype=np.float64)
            r_nm  = r_min_nm_eff + (r_max_eff - r_min_nm_eff) * (t ** warp)
            r_deg = r_nm * NM_TO_DEG                                   # (n_r,)

            # Azimuth samples relative to the nose, in degrees.
            az_deg = np.linspace(-fov / 2.0, fov / 2.0, n_az, dtype=np.float64)
            az_rad = np.radians(az_deg)
            cos_a  = np.cos(az_rad)                                    # (n_az,)
            sin_a  = np.sin(az_rad)

            # Geographic bearing of each (i, j): heading + azimuth.
            brg_rad = head_rad + az_rad                                # (n_az,)
            sin_b   = np.sin(brg_rad)
            cos_b   = np.cos(brg_rad)

            r_deg_col = r_deg[:, None]                                 # (n_r, 1)
            # lat/lon grids (n_r, n_az)
            lat_grid = ac_lat + r_deg_col * cos_b[None, :]
            lon_grid = ac_lon + r_deg_col * sin_b[None, :] / lat_cos

            # Aircraft-frame coordinates fall straight out of (r, az):
            #   x_fwd   = r · cos(az),  x_right = r · sin(az).
            # Heading rotation is already absorbed into the azimuth axis.
            x_fwd   = r_deg_col * cos_a[None, :]
            x_right = r_deg_col * sin_a[None, :]

            # Range in degrees — broadcast r_deg across azimuth columns.
            range_deg_grid = np.broadcast_to(r_deg_col,
                                             (n_r, n_az)).astype(np.float64).copy()
            range_deg_grid = np.where(range_deg_grid < 1e-6,
                                      1e-6, range_deg_grid)
        else:
            n = self._grid_n
            # Build a grid of (lat, lon) points centred on the aircraft.
            # Grid runs from -range_deg to +range_deg in both lat and lon.
            lats = np.linspace(ac_lat - range_deg, ac_lat + range_deg, n)
            lons = np.linspace(ac_lon - range_deg, ac_lon + range_deg, n)
            lat_grid, lon_grid = np.meshgrid(lats, lons, indexing='ij')  # (n, n)

            # Convert terrain positions to aircraft frame (heading-relative).
            d_lat = (lat_grid - ac_lat)                  # degrees N/S
            d_lon = (lon_grid - ac_lon) * lat_cos        # degrees E/W (scaled)
            # d_lon = east, d_lat = north → aircraft frame
            x_fwd   =  d_lat * cos_h + d_lon * sin_h    # forward (positive = ahead)
            x_right = -d_lat * sin_h + d_lon * cos_h    # right of nose

            range_deg_grid = np.sqrt(d_lat ** 2 + d_lon ** 2)
            range_deg_grid = np.where(range_deg_grid < 1e-6, 1e-6, range_deg_grid)

        # Vectorised terrain elevation lookup (one tile at a time)
        elev_m, is_water = self._sample_elevations(lat_grid, lon_grid)
        elev_ft = elev_m * 3.28084

        rows, cols = elev_m.shape

        # Elevation angle of terrain above/below horizon (degrees)
        ac_alt_m = ac_alt_ft * 0.3048
        terrain_alt_m = elev_m * 1.0           # already metres
        alt_diff_m = terrain_alt_m - ac_alt_m  # positive = terrain above aircraft
        range_m = range_deg_grid * 111139.0    # 1 degree ≈ 111,139 m
        elev_angle_deg = np.degrees(np.arctan2(alt_diff_m, range_m))

        # Only draw terrain in front of the aircraft (x_fwd > 0) and within
        # the configured range. The polar grid is forward-only by
        # construction (|az| ≤ fov/2 < 90°), so x_fwd > 0 is always true and
        # range_deg_grid ≤ range_deg by construction — but evaluating the
        # mask uniformly keeps the rest of the drawing code symmetric.
        visible = (x_fwd > 0) & (range_deg_grid < range_deg)

        # Map to AI viewport pixels using the same coordinate system as FPM
        # Lateral: x_right degrees → pixels (using pixelsPerDeg)
        # Vertical: (pitch - elev_angle) → pixels, then apply roll
        x_ang = np.degrees(np.arctan2(x_right, x_fwd))   # azimuth offset
        y_ang = elev_angle_deg - pitch_deg                 # elevation relative to pitch

        x_px = x_ang * pixels_per_deg
        y_px = -y_ang * pixels_per_deg     # negative = up on screen

        # Apply roll rotation to (x_px, y_px)
        roll_rad = math.radians(roll_deg)
        cos_r, sin_r = math.cos(-roll_rad), math.sin(-roll_rad)
        x_rot = x_px * cos_r - y_px * sin_r + w / 2
        y_rot = x_px * sin_r + y_px * cos_r + h / 2

        # Clearance colours — water points use a sentinel so _cidx routes them
        # to COLOR_WATER regardless of numeric clearance.
        clearance_ft = ac_alt_ft - elev_ft
        clearance_ft = np.where(is_water, _WATER_SENTINEL, clearance_ft)

        # ------------------------------------------------------------------
        # Slope shading — Lambertian lighting from a fixed sun direction.
        # Surface normal expressed in geographic (E, N, Up); sun direction
        # below is also in (E, N, Up), so the dot product is frame-correct.
        # Sun from upper-NW in geographic frame: (-1, 1, 2) normalised.
        # ------------------------------------------------------------------
        # Amplify slopes so lighting is dramatic at SVS grid scales —
        # without it, horizontal cell size (~hundreds of metres) dwarfs
        # typical relief (~tens of metres) and normals collapse to "up".
        SLOPE_EXAG = 4.0
        dz_di = np.gradient(elev_m.astype(float), axis=0)  # per row-step
        dz_dj = np.gradient(elev_m.astype(float), axis=1)  # per col-step
        if self._is_polar:
            # Polar grid: axis 0 is radial (bearing brg = heading + az),
            # axis 1 is azimuthal. Convert per-index gradients into per-metre
            # slopes in geographic (E, N) using:
            #   dz/dr   = dz_di / dr_step(i)
            #   dz/darc = dz_dj / arc_step(i)        # arc_step = r · Δaz
            # then rotate (dz/dr, dz/darc) → (dz/dE, dz/dN) via bearing.
            r_m_arr        = r_nm * 1852.0                     # (n_r,)
            dr_m_step      = np.gradient(r_m_arr)              # (n_r,)
            dr_m_step      = np.where(dr_m_step  < 1e-6, 1e-6, dr_m_step)
            daz_rad        = (az_rad[-1] - az_rad[0]) / max(n_az - 1, 1)
            arc_m_step     = r_m_arr * daz_rad                 # (n_r,)
            arc_m_step     = np.where(arc_m_step < 1e-6, 1e-6, arc_m_step)
            dz_dr   = dz_di / dr_m_step[:, None]               # (n_r, n_az)
            dz_darc = dz_dj / arc_m_step[:, None]
            sin_b_g = sin_b[None, :]
            cos_b_g = cos_b[None, :]
            dz_dE = dz_dr * sin_b_g + dz_darc * cos_b_g
            dz_dN = dz_dr * cos_b_g - dz_darc * sin_b_g
            # Unnormalised surface normal: (-dz/dE, -dz/dN, 1) in (E, N, Up).
            mag = np.sqrt((dz_dE * SLOPE_EXAG) ** 2
                          + (dz_dN * SLOPE_EXAG) ** 2 + 1.0)
            mag = np.where(mag < 1e-6, 1e-6, mag)
            nx = -dz_dE * SLOPE_EXAG / mag
            ny = -dz_dN * SLOPE_EXAG / mag
            nz =          1.0          / mag
        else:
            # Rectangular grid: axis 0 ↔ lat (north), axis 1 ↔ lon (east).
            # dz_di and dz_dj are per index step of size step_m metres.
            step_m = (range_deg * 2 / max(rows - 1, 1)) * 111139.0
            mag = np.sqrt((dz_dj * SLOPE_EXAG) ** 2
                          + (dz_di * SLOPE_EXAG) ** 2 + step_m ** 2)
            mag = np.where(mag < 1e-6, 1e-6, mag)
            nx = -dz_dj * SLOPE_EXAG / mag   # east  component of normal
            ny = -dz_di * SLOPE_EXAG / mag   # north component of normal
            nz =  step_m / mag               # up    component of normal
        # Sun direction (pointing from surface toward sun), geographic (E, N, Up)
        _lx, _ly, _lz = -1.0, 1.0, 2.0
        _lm = math.sqrt(_lx*_lx + _ly*_ly + _lz*_lz)
        _lx, _ly, _lz = _lx/_lm, _ly/_lm, _lz/_lm
        AMBIENT = 0.10
        DIFFUSE = 0.90
        diffuse   = np.clip(nx * _lx + ny * _ly + nz * _lz, 0.0, 1.0)
        intensity = AMBIENT + DIFFUSE * diffuse   # (n,n) ∈ [AMBIENT, 1.0]

        # Smooth intensity with a 3×3 Gaussian to soften hard colour steps at
        # quad boundaries where a ridge bisects a grid cell.
        _g = np.array([[1,2,1],[2,4,2],[1,2,1]], dtype=np.float32) / 16.0
        _ip = np.pad(intensity, 1, mode='edge')
        intensity = sum(_g[_di, _dj] * _ip[_di:_di+rows, _dj:_dj+cols]
                        for _di in range(3) for _dj in range(3))

        # Build shade table: 5 clearance categories × N_SHADE intensity levels
        # Categories: 0=safe, 1=caution, 2=warning, 3=conflict, 4=water
        N_SHADE = 32
        _BASE_COLS = (COLOR_SAFE, COLOR_CAUTION, COLOR_WARNING, COLOR_CONFLICT, COLOR_WATER)
        shade_table = []
        for _bc in _BASE_COLS:
            for _si in range(N_SHADE):
                _f = AMBIENT + DIFFUSE * (_si / (N_SHADE - 1))
                shade_table.append(QColor(
                    min(255, int(_bc.red()   * _f)),
                    min(255, int(_bc.green() * _f)),
                    min(255, int(_bc.blue()  * _f)),
                ))

        p.save()
        p.resetTransform()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # ------------------------------------------------------------------
        # Vectorised per-cell / per-edge aggregates.
        #
        # The Python for-loops we used to walk every (i, j) cell were
        # dominated by NumPy scalar-indexing overhead, not by the math
        # itself. Compute everything once as whole-array operations,
        # then iterate only over the cells/edges we actually draw —
        # grouped by shade key so each bucket fills one QPainterPath.
        # ------------------------------------------------------------------
        # Per-cell aggregates over the 4 corners (rows-1, cols-1)
        c00 = clearance_ft[:-1, :-1]; c01 = clearance_ft[:-1, 1:]
        c10 = clearance_ft[ 1:, :-1]; c11 = clearance_ft[ 1:, 1:]
        cell_cmin  = np.minimum(np.minimum(c00, c01), np.minimum(c10, c11))
        cell_inten = (intensity[:-1, :-1] + intensity[:-1, 1:]
                      + intensity[1:, :-1] + intensity[1:, 1:]) * 0.25
        cell_visible = (visible[:-1, :-1] & visible[:-1, 1:]
                        & visible[1:, :-1] & visible[1:, 1:])

        # Per-edge aggregates over the 2 endpoints (only computed if needed)
        if self.grid_lines:
            e1_cmin  = np.minimum(clearance_ft[:, :-1], clearance_ft[:, 1:])
            e1_inten = (intensity[:, :-1]   + intensity[:, 1:])   * 0.5
            e1_vis   = visible[:, :-1] & visible[:, 1:]
            e0_cmin  = np.minimum(clearance_ft[:-1, :], clearance_ft[1:, :])
            e0_inten = (intensity[:-1, :]   + intensity[1:, :])   * 0.5
            e0_vis   = visible[:-1, :] & visible[1:, :]

        def _keys_from(cmin, inten):
            """Vectorised shade-key calculation: clearance bucket × 32-step
            intensity quantisation. When the aircraft is near a known
            airport, collapse the warning/caution bands so a normal landing
            approach doesn't paint half the screen red."""
            if near_airport:
                # 3 categories only: water / conflict (above ac) / safe (below).
                cidx = np.where(cmin <= _WATER_SENTINEL / 2.0, 4,
                       np.where(cmin < 0, 3, 0))
            else:
                cidx = np.where(cmin <= _WATER_SENTINEL / 2.0, 4,
                       np.where(cmin < 0,              3,
                       np.where(cmin < self.yellow_ft, 2,
                       np.where(cmin < self.green_ft,  1, 0))))
            si = ((inten - AMBIENT) / DIFFUSE * (N_SHADE - 1) + 0.5).astype(np.int32)
            np.clip(si, 0, N_SHADE - 1, out=si)
            return (cidx * N_SHADE + si).astype(np.int32)

        # Vertex coordinates as Python lists — list indexing is ~3× faster
        # than NumPy scalar indexing for the per-cell QPointF construction.
        x_list = x_rot.tolist()
        y_list = y_rot.tolist()

        from PyQt6.QtGui import QPainterPath as _QPP, QPen as _QPen

        # ------------------------------------------------------------------
        # Filled terrain quads
        # ------------------------------------------------------------------
        if self.terrain_fill:
            cell_keys = _keys_from(cell_cmin, cell_inten)
            flat_keys = cell_keys.ravel()
            flat_vis  = cell_visible.ravel()
            vis_idx   = np.flatnonzero(flat_vis)
            if vis_idx.size:
                vis_keys  = flat_keys[vis_idx]
                # Stable sort so contiguous runs share the same key.
                order = np.argsort(vis_keys, kind='stable')
                vis_idx_sorted  = vis_idx[order]
                vis_keys_sorted = vis_keys[order]
                # Run boundaries via diff — cheap on int32.
                boundaries = np.flatnonzero(np.diff(vis_keys_sorted)) + 1
                starts = np.concatenate(([0], boundaries))
                ends   = np.concatenate((boundaries, [vis_idx_sorted.size]))

                cell_cols = cols - 1
                p.setPen(Qt_NoPen())
                for s, e in zip(starts.tolist(), ends.tolist()):
                    key = int(vis_keys_sorted[s])
                    path = _QPP()
                    for flat_i in vis_idx_sorted[s:e].tolist():
                        i, j = divmod(flat_i, cell_cols)
                        path.addPolygon(QPolygonF([
                            QPointF(x_list[i    ][j    ], y_list[i    ][j    ]),
                            QPointF(x_list[i    ][j + 1], y_list[i    ][j + 1]),
                            QPointF(x_list[i + 1][j + 1], y_list[i + 1][j + 1]),
                            QPointF(x_list[i + 1][j    ], y_list[i + 1][j    ]),
                        ]))
                    p.setBrush(QBrush(shade_table[key]))
                    p.drawPath(path)

        # ------------------------------------------------------------------
        # Grid-line overlay
        # ------------------------------------------------------------------
        if self.grid_lines:
            # Both edge axes contribute to the same shade-key buckets.
            # Build (key, x1, y1, x2, y2) tuples then sort+group as above.
            e1_keys = _keys_from(e1_cmin, e1_inten)
            e0_keys = _keys_from(e0_cmin, e0_inten)

            # Edge1: (i, j) — (i, j+1) — shape (rows, cols-1)
            e1_idx = np.flatnonzero(e1_vis.ravel())
            # Edge0: (i, j) — (i+1, j) — shape (rows-1, cols)
            e0_idx = np.flatnonzero(e0_vis.ravel())

            if e1_idx.size + e0_idx.size:
                # Encode axis in the high bit so a single concat+sort works.
                e1_pack = e1_idx.astype(np.int64)               # axis 1: low bits
                e0_pack = e0_idx.astype(np.int64) | (1 << 40)   # axis 0: tagged

                all_keys = np.concatenate((
                    e1_keys.ravel()[e1_idx],
                    e0_keys.ravel()[e0_idx]))
                all_pack = np.concatenate((e1_pack, e0_pack))

                order = np.argsort(all_keys, kind='stable')
                keys_sorted = all_keys[order]
                pack_sorted = all_pack[order]
                boundaries = np.flatnonzero(np.diff(keys_sorted)) + 1
                starts = np.concatenate(([0], boundaries))
                ends   = np.concatenate((boundaries, [keys_sorted.size]))

                e1_cols = cols - 1   # column count of e1 array
                e0_cols = cols       # column count of e0 array
                AXIS_TAG = 1 << 40

                pen = _QPen()
                pen.setWidth(1)
                for s, e in zip(starts.tolist(), ends.tolist()):
                    key = int(keys_sorted[s])
                    lines = []
                    for packed in pack_sorted[s:e].tolist():
                        if packed & AXIS_TAG:
                            flat_i = packed ^ AXIS_TAG
                            i, j = divmod(flat_i, e0_cols)
                            lines.append(QLineF(
                                x_list[i    ][j], y_list[i    ][j],
                                x_list[i + 1][j], y_list[i + 1][j]))
                        else:
                            flat_i = packed
                            i, j = divmod(flat_i, e1_cols)
                            lines.append(QLineF(
                                x_list[i][j    ], y_list[i][j    ],
                                x_list[i][j + 1], y_list[i][j + 1]))
                    pen.setColor(shade_table[key])
                    p.setPen(pen)
                    p.drawLines(lines)

        self._draw_water(p, w, h, ac_lat, ac_lon, ac_alt_ft,
                         pitch_deg, roll_deg, heading_deg, pixels_per_deg,
                         range_nm)

        self._draw_runways(p, w, h, ac_lat, ac_lon, ac_alt_ft,
                           pitch_deg, roll_deg, heading_deg, pixels_per_deg)

        self._draw_obstacles(p, w, h, ac_lat, ac_lon, ac_alt_ft,
                             pitch_deg, roll_deg, heading_deg, pixels_per_deg,
                             range_nm)

        p.restore()

    def _project_point(self, lat, lon, alt_ft,
                       ac_lat, ac_lon, ac_alt_ft,
                       pitch_deg, roll_deg, heading_deg,
                       ppd, w, h):
        """Project a geographic point to AI-viewport screen (x, y).
        Returns (sx, sy, in_front); in_front=False when point is behind aircraft."""
        lat_cos = math.cos(math.radians(ac_lat))
        d_lat = lat - ac_lat
        d_lon = (lon - ac_lon) * lat_cos          # scaled so 1 unit ≈ 111 km

        head_rad = math.radians(heading_deg)
        cos_h, sin_h = math.cos(head_rad), math.sin(head_rad)
        x_fwd   =  d_lat * cos_h + d_lon * sin_h
        x_right = -d_lat * sin_h + d_lon * cos_h

        if x_fwd <= 1e-6:
            return 0.0, 0.0, False

        range_m = math.sqrt(d_lat ** 2 + d_lon ** 2) * 111139.0
        range_m = max(range_m, 1.0)

        alt_diff_m    = (alt_ft - ac_alt_ft) * 0.3048
        elev_angle_deg = math.degrees(math.atan2(alt_diff_m, range_m))

        x_ang = math.degrees(math.atan2(x_right, x_fwd))
        y_ang = elev_angle_deg - pitch_deg

        x_px = x_ang * ppd
        y_px = -y_ang * ppd

        roll_rad = math.radians(roll_deg)
        cos_r, sin_r = math.cos(-roll_rad), math.sin(-roll_rad)
        sx = x_px * cos_r - y_px * sin_r + w / 2
        sy = x_px * sin_r + y_px * cos_r + h / 2
        return sx, sy, True

    # Default near-plane distance for polygon clipping, in degrees of
    # latitude. 0.05 NM (the polar terrain mesh's inner ring) is small
    # enough that the visible polygon still reaches the foreground, but
    # large enough that clipped vertices project to reasonable
    # azimuths instead of ~+/-90 deg the way x_fwd=epsilon would.
    _NEAR_PLANE_DEG = 0.05 / 60.0   # 0.05 NM in degrees of lat

    # Number of segments along each long runway edge. The angular
    # projection in _project_point produces a CURVE on screen from a
    # straight 3D line — a runway edge offset perpendicular from the
    # centerline traces a hyperbolic-ish arc, mild in the far field
    # and sharper near the camera. The runway polygon was drawn from
    # just four corners (a chord through that curve), which read
    # visibly different from the markings (each independently
    # projected and naturally following the curve). Subdividing every
    # 1/_RUNWAY_LONG_EDGE_SEGMENTS of the runway length gives the
    # polygon roughly the same shape as the markings cluster.
    _RUNWAY_LONG_EDGE_SEGMENTS = 16

    def _runway_polygon_corners(self, t1_lat, t1_lon, t1_elev,
                                t2_lat, t2_lon, t2_elev,
                                perp_lat, perp_lon, hw,
                                n_subdiv=None):
        """Build the runway polygon as a CCW vertex ring with both
        long edges subdivided into ``n_subdiv`` segments. Each
        intermediate vertex carries a lat/lon/elev interpolated
        linearly between the thresholds so the rendered polygon
        traces the screen-curve of an angular projection rather than
        cutting a straight chord through it."""
        if n_subdiv is None:
            n_subdiv = self._RUNWAY_LONG_EDGE_SEGMENTS
        corners = []
        # Short edge at thr1 (06-end): right corner first, then left
        # corner — keeps the polygon CCW when followed by the long
        # edge that walks down the "left" side toward thr2.
        corners.append((t1_lat + perp_lat * hw,
                        t1_lon + perp_lon * hw, t1_elev))
        corners.append((t1_lat - perp_lat * hw,
                        t1_lon - perp_lon * hw, t1_elev))
        # Long "left" edge thr1-perp -> thr2-perp (n_subdiv-1 inserts).
        for k in range(1, n_subdiv):
            f = k / n_subdiv
            corners.append((
                t1_lat + f * (t2_lat - t1_lat) - perp_lat * hw,
                t1_lon + f * (t2_lon - t1_lon) - perp_lon * hw,
                t1_elev + f * (t2_elev - t1_elev)))
        # Short edge at thr2 (24-end)
        corners.append((t2_lat - perp_lat * hw,
                        t2_lon - perp_lon * hw, t2_elev))
        corners.append((t2_lat + perp_lat * hw,
                        t2_lon + perp_lon * hw, t2_elev))
        # Long "right" edge thr2+perp -> thr1+perp.
        for k in range(1, n_subdiv):
            f = k / n_subdiv
            corners.append((
                t2_lat + f * (t1_lat - t2_lat) + perp_lat * hw,
                t2_lon + f * (t1_lon - t2_lon) + perp_lon * hw,
                t2_elev + f * (t1_elev - t2_elev)))
        return corners

    def _project_polygon_clipped(self, corners, ac_lat, ac_lon, ac_alt_ft,
                                 pitch_deg, roll_deg, heading_deg, ppd, w, h,
                                 eps=None):
        """Project a polygon (list of ``(lat, lon, elev_ft)`` corners) to
        screen with a Sutherland-Hodgman clip against the camera near
        plane (``x_fwd > eps``). Polygons that straddle the aircraft —
        a runway being crossed on short final, for example — get their
        edges intersected with the near plane so the visible portion
        still draws instead of vanishing.

        ``eps`` is the near-plane distance in degrees of latitude. The
        default (~0.05 NM, matching the polar mesh's inner ring) puts
        clipped vertices at reasonable screen azimuths; an arbitrarily
        small value (e.g. 1e-6) pushes them out to ~+/-90 deg and the
        polygon visibly bulges to the screen edges even when the
        runway is straight ahead.

        Returns a list of QPointF for the clipped polygon; empty when
        the polygon is fully behind the near plane."""
        if eps is None:
            eps = self._NEAR_PLANE_DEG
        lat_cos = math.cos(math.radians(ac_lat))
        head_rad = math.radians(heading_deg)
        cos_h, sin_h = math.cos(head_rad), math.sin(head_rad)

        cam = []
        for lat, lon, elev_ft in corners:
            d_lat = lat - ac_lat
            d_lon = (lon - ac_lon) * lat_cos
            x_fwd   =  d_lat * cos_h + d_lon * sin_h
            x_right = -d_lat * sin_h + d_lon * cos_h
            alt_diff_m = (elev_ft - ac_alt_ft) * 0.3048
            cam.append((x_fwd, x_right, alt_diff_m))

        clipped = []
        n = len(cam)
        for i in range(n):
            a = cam[i]
            b = cam[(i + 1) % n]
            a_in = a[0] > eps
            b_in = b[0] > eps
            if a_in:
                clipped.append(a)
            if a_in != b_in and abs(b[0] - a[0]) > 1e-12:
                t = (eps - a[0]) / (b[0] - a[0])
                clipped.append((
                    eps,
                    a[1] + t * (b[1] - a[1]),
                    a[2] + t * (b[2] - a[2]),
                ))

        if not clipped:
            return []

        roll_rad = math.radians(-roll_deg)
        cos_r, sin_r = math.cos(roll_rad), math.sin(roll_rad)
        pts = []
        for x_fwd, x_right, alt_diff_m in clipped:
            range_m = math.sqrt(x_fwd ** 2 + x_right ** 2) * 111139.0
            range_m = max(range_m, 1.0)
            elev_angle_deg = math.degrees(math.atan2(alt_diff_m, range_m))
            x_ang = math.degrees(math.atan2(x_right, x_fwd))
            y_ang = elev_angle_deg - pitch_deg
            x_px = x_ang * ppd
            y_px = -y_ang * ppd
            sx = x_px * cos_r - y_px * sin_r + w / 2
            sy = x_px * sin_r + y_px * cos_r + h / 2
            pts.append(QPointF(sx, sy))
        return pts

    def _airports_in_range(self, ac_lat, ac_lon):
        """Yield ``(label, ref_lat, ref_lon, elev_ft, runways)`` records from
        whichever data source is configured. Each runway dict carries the
        threshold positions, width, and (for NASR) the Tier C fields:
        marking type, displaced threshold offset, designators, TDZ elev."""
        if getattr(self, "airport_db", None) is not None and self.airport_db.ready:
            for ap in self.airport_db.airports_in_range(ac_lat, ac_lon, self.range_nm):
                # ICAO codes are 4 letters incl. leading K for CONUS. Strip
                # it so the cockpit label reads "SBA" rather than "KSBA".
                label = ap.icao[1:] if (len(ap.icao) == 4 and ap.icao[0] == 'K') else ap.icao
                runways = [{
                    "thr1_lat": r.thr1_lat, "thr1_lon": r.thr1_lon, "thr1_elev_ft": r.thr1_elev_ft,
                    "thr2_lat": r.thr2_lat, "thr2_lon": r.thr2_lon, "thr2_elev_ft": r.thr2_elev_ft,
                    "width_ft": r.width_ft,
                    "length_ft": r.length_ft,
                    "thr1_designator": r.thr1_designator,
                    "thr2_designator": r.thr2_designator,
                    "thr1_marking": r.thr1_marking,
                    "thr2_marking": r.thr2_marking,
                    "thr1_displaced_ft": r.thr1_displaced_ft,
                    "thr2_displaced_ft": r.thr2_displaced_ft,
                } for r in ap.runways]
                yield label, ap.ref_lat, ap.ref_lon, ap.elev_ft, runways
            return
        # Built-in fallback
        for icao, apt in _AIRPORT_DB.items():
            yield apt["label"], apt["ref_lat"], apt["ref_lon"], apt["elev_ft"], apt["runways"]

    def _draw_water(self, p, w, h, ac_lat, ac_lon, ac_alt_ft,
                    pitch_deg, roll_deg, heading_deg, ppd, range_nm):
        """Paint OSM / Natural Earth water polygons in COLOR_WATER on
        top of the terrain layer. Each polygon is projected via
        ``_project_polygon_clipped`` exactly like a runway — the same
        camera-near-plane Sutherland-Hodgman clip and width-adaptive
        eps that the runway code uses.

        Polygon surface elevation:
          * ``poly.elev_ft`` if the build tool recorded one (e.g.
            crater-lake-style lakes with a known surface elev).
          * Otherwise sampled from the SRTM heightmap at the polygon's
            first vertex. For ocean polygons SRTM returns either 0
            (open water cells) or the void sentinel (which we treat
            as 0); for lakes SRTM reports the water surface elevation.

        Drawn BEFORE runways/obstacles in the overlay stack so a
        runway crossing a lake (or a tower in a lake) renders on top.
        """
        if getattr(self, "water_db", None) is None or not self.water_db.ready:
            return

        from PyQt6.QtGui import QPolygonF as _QPolygonF

        # Same width-adaptive near plane the runway clipper uses; we
        # don't have a perp half-width here so pick a small constant
        # that keeps clipped vertices at sensible azimuths for typical
        # water shapes. ~50 m forward sits comfortably outside the
        # polar fan's FOV when the polygon edge straddles the camera.
        eps_default = 50.0 / 111139.0

        # Sentinel value used by the SRTM loader for ocean / void cells.
        WATER_SENTINEL_M = _WATER_SENTINEL / 3.28084

        p.setPen(Qt_NoPen())
        p.setBrush(QBrush(COLOR_WATER))

        with self._perf.time("water.query"):
            polys = list(self.water_db.polygons_in_range(
                ac_lat, ac_lon, range_nm))

        for poly in polys:
            if len(poly.vertices) < 3:
                continue

            # Pick a surface elevation for the polygon.
            # Ocean is sea level by definition — skip the SRTM lookup
            # entirely. With ~100 ocean polygons in range near any
            # coast, _sample_elevations was the dominant per-frame
            # cost in the water overlay (each call constructs numpy
            # arrays and hits the tile cache); short-circuiting here
            # is the difference between 2 FPS and a usable frame
            # rate.
            if poly.is_ocean:
                surface_ft = 0.0
            elif poly.elev_ft is not None:
                surface_ft = float(poly.elev_ft)
            else:
                with self._perf.time("water.srtm_sample"):
                    vlat, vlon = poly.vertices[0]
                    elev_m, _ = self._sample_elevations(
                        np.array([[vlat]]), np.array([[vlon]]))
                    e = float(elev_m[0, 0])
                if e <= WATER_SENTINEL_M / 2.0:
                    surface_ft = 0.0
                else:
                    surface_ft = e * 3.28084

            corners = [(lat, lon, surface_ft)
                       for (lat, lon) in poly.vertices]
            with self._perf.time("water.project"):
                pts = self._project_polygon_clipped(
                    corners, ac_lat, ac_lon, ac_alt_ft,
                    pitch_deg, roll_deg, heading_deg, ppd, w, h,
                    eps=eps_default)
            if len(pts) >= 3:
                with self._perf.time("water.drawPolygon"):
                    p.drawPolygon(_QPolygonF(pts))

    def _draw_obstacles(self, p, w, h, ac_lat, ac_lon, ac_alt_ft,
                        pitch_deg, roll_deg, heading_deg, ppd, range_nm):
        """Render FAA DOF obstacles (towers, antennas, tall buildings) as
        vertical poles with a tip marker. Poles taller than the aircraft
        get a CONFLICT-magenta tint; poles below the aircraft are tinted
        by their lighting code (red/white) or grey if unlit."""
        if getattr(self, "obstacle_db", None) is None or not self.obstacle_db.ready:
            return

        # Reuse the airport range (after auto-range scaling) for obstacles —
        # they should appear at the same horizon distance the terrain does.
        POLE_PEN_LIT_RED   = QPen(QColor(220,  60,  60), 2)
        POLE_PEN_LIT_WHITE = QPen(QColor(230, 230, 230), 2)
        POLE_PEN_UNLIT     = QPen(QColor(160, 160, 160), 2)
        POLE_PEN_CONFLICT  = QPen(QColor(200,   0, 200), 2)
        TIP_RADIUS         = 4

        for obs in self.obstacle_db.obstacles_in_range(
                ac_lat, ac_lon, range_nm, min_agl_ft=self.obstacle_min_agl_ft):
            sx_base, sy_base, vis_base = self._project_point(
                obs.lat, obs.lon, obs.base_amsl_ft,
                ac_lat, ac_lon, ac_alt_ft,
                pitch_deg, roll_deg, heading_deg, ppd, w, h)
            sx_top, sy_top, vis_top = self._project_point(
                obs.lat, obs.lon, obs.amsl_ft,
                ac_lat, ac_lon, ac_alt_ft,
                pitch_deg, roll_deg, heading_deg, ppd, w, h)
            if not (vis_base and vis_top):
                continue

            # Conflict colouring overrides lighting when the obstacle tip
            # is above the aircraft — same convention as terrain.
            if obs.amsl_ft >= ac_alt_ft:
                pen = POLE_PEN_CONFLICT
            else:
                cat = obs.lighting_category()
                if cat == "red":
                    pen = POLE_PEN_LIT_RED
                elif cat in ("white", "dual"):
                    pen = POLE_PEN_LIT_WHITE
                else:
                    pen = POLE_PEN_UNLIT
            p.setPen(pen)
            p.setBrush(QBrush(pen.color()))
            p.drawLine(QPointF(sx_base, sy_base), QPointF(sx_top, sy_top))
            p.drawEllipse(QPointF(sx_top, sy_top), TIP_RADIUS, TIP_RADIUS)

    def _draw_runways(self, p, w, h, ac_lat, ac_lon, ac_alt_ft,
                      pitch_deg, roll_deg, heading_deg, ppd):
        """Draw runways and airport markers for everything in range."""
        lat_cos   = math.cos(math.radians(ac_lat))
        range_m   = self.range_nm * 1852.0

        RWY_FILL    = QColor( 55,  55,  55)  # asphalt grey — markings on top read crisply
        RWY_OUTLINE = QColor(180, 180, 180)  # slightly brighter edge so the quad reads at distance
        FLAG_FILL   = QColor(255, 220,   0)
        FLAG_TEXT   = QColor(255, 255,   0)

        rwy_pen  = QPen(RWY_OUTLINE, 1)
        flag_pen = QPen(QColor(0, 0, 0), 1)
        font     = QFont("sans-serif", 9, QFont.Weight.Bold)

        for label, ref_lat, ref_lon, ref_elev_ft, runways in \
                self._airports_in_range(ac_lat, ac_lon):
            # Range-check on airport reference point
            d_lat_ref = (ref_lat - ac_lat)
            d_lon_ref = (ref_lon - ac_lon) * lat_cos
            if math.sqrt(d_lat_ref ** 2 + d_lon_ref ** 2) * 111139.0 > range_m:
                continue

            # --- Runway rectangles ---
            for rwy in runways:
                t1_lat, t1_lon = rwy["thr1_lat"], rwy["thr1_lon"]
                t2_lat, t2_lon = rwy["thr2_lat"], rwy["thr2_lon"]
                t1_elev = rwy["thr1_elev_ft"]
                t2_elev = rwy["thr2_elev_ft"]

                # Perpendicular offset for runway width
                dl = t2_lat - t1_lat
                dm = (t2_lon - t1_lon) * lat_cos
                rwy_len = math.sqrt(dl ** 2 + dm ** 2)
                if rwy_len < 1e-9:
                    continue
                # Unit perpendicular in lat / scaled-lon space, then unscale lon
                perp_lat =  -dm / rwy_len
                perp_lon =  dl  / rwy_len / lat_cos
                hw = (rwy["width_ft"] / 2.0) / 364491.0   # half-width in degrees lat

                corners = self._runway_polygon_corners(
                    t1_lat, t1_lon, t1_elev,
                    t2_lat, t2_lon, t2_elev,
                    perp_lat, perp_lon, hw)

                # Near-plane distance: width-adaptive. The Sutherland-
                # Hodgman intersection along a long runway edge has
                # x_right ~ hw (the perpendicular half-width), so the
                # clipped vertex projects to x_ang = atan2(hw, eps).
                # Keeping that angle at the polar fan's edge (~70 deg)
                # makes the polygon visually extend right up to the
                # aircraft instead of leaving a fixed-distance "no
                # asphalt" gap directly under the nose — which was
                # what caused the runway to look like it was
                # truncating away as the aircraft flew over it.
                near_plane_deg = hw / math.tan(math.radians(70.0))
                pts = self._project_polygon_clipped(
                    corners, ac_lat, ac_lon, ac_alt_ft,
                    pitch_deg, roll_deg, heading_deg, ppd, w, h,
                    eps=near_plane_deg)

                if len(pts) >= 3:
                    p.setPen(rwy_pen)
                    p.setBrush(QBrush(RWY_FILL))
                    p.drawPolygon(QPolygonF(pts))

                    # Tier C surface markings — only painted when close enough
                    # that they'd actually be legible on screen.
                    rwy_center_lat = 0.5 * (rwy["thr1_lat"] + rwy["thr2_lat"])
                    rwy_center_lon = 0.5 * (rwy["thr1_lon"] + rwy["thr2_lon"])
                    d_lat_c = (rwy_center_lat - ac_lat) * 60.0
                    d_lon_c = (rwy_center_lon - ac_lon) * 60.0 * lat_cos
                    if d_lat_c * d_lat_c + d_lon_c * d_lon_c \
                            <= self.detail_distance_nm * self.detail_distance_nm:
                        self._draw_runway_markings(
                            p, w, h, ac_lat, ac_lon, ac_alt_ft,
                            pitch_deg, roll_deg, heading_deg, ppd, rwy)

            # --- Airport flag marker — pole rising from ground to POLE_HT ---
            POLE_HT_FT = 2000
            sx_base, sy_base, vis_base = self._project_point(
                ref_lat, ref_lon, ref_elev_ft,
                ac_lat, ac_lon, ac_alt_ft,
                pitch_deg, roll_deg, heading_deg, ppd, w, h)
            sx_top, sy_top, vis_top = self._project_point(
                ref_lat, ref_lon, ref_elev_ft + POLE_HT_FT,
                ac_lat, ac_lon, ac_alt_ft,
                pitch_deg, roll_deg, heading_deg, ppd, w, h)
            if vis_base and vis_top:
                pole_pen = QPen(FLAG_FILL, 2)
                p.setPen(pole_pen)
                p.drawLine(QPointF(sx_base, sy_base), QPointF(sx_top, sy_top))
                # Flag rectangle to the right of the pole tip
                fw, fh = 18, 10
                flag_rect = QPolygonF([
                    QPointF(sx_top,      sy_top),
                    QPointF(sx_top + fw, sy_top),
                    QPointF(sx_top + fw, sy_top + fh),
                    QPointF(sx_top,      sy_top + fh),
                ])
                p.setBrush(QBrush(FLAG_FILL))
                p.setPen(flag_pen)
                p.drawPolygon(flag_rect)
                # Identifier above/right of flag
                p.setPen(QPen(FLAG_TEXT))
                p.setFont(font)
                p.drawText(QPointF(sx_top + fw + 3, sy_top + fh), label)

    # -----------------------------------------------------------------
    # Tier C surface markings (FAA AC 150/5340-1L)
    # -----------------------------------------------------------------
    def _draw_runway_markings(self, p, w, h, ac_lat, ac_lon, ac_alt_ft,
                              pitch_deg, roll_deg, heading_deg, ppd, rwy):
        """Paint AC 150/5340-1L surface markings on top of the runway quad.

        Designators, threshold bars, centerline stripes, aiming point, touchdown
        zone markers (PIR only), side stripes (PIR only), and displaced-threshold
        chevrons. The runway base grey rectangle has already been drawn by the
        caller; we just layer markings on top in viewport pixel coordinates,
        each polygon projected through ``_project_point``.
        """
        t1_lat, t1_lon = rwy["thr1_lat"], rwy["thr1_lon"]
        t2_lat, t2_lon = rwy["thr2_lat"], rwy["thr2_lon"]
        t1_elev = rwy["thr1_elev_ft"]
        t2_elev = rwy["thr2_elev_ft"]
        length_ft = float(rwy.get("length_ft") or 0.0)
        width_ft  = float(rwy.get("width_ft")  or 100.0)
        d1 = float(rwy.get("thr1_displaced_ft") or 0.0)
        d2 = float(rwy.get("thr2_displaced_ft") or 0.0)
        m1 = (rwy.get("thr1_marking") or "").upper()
        m2 = (rwy.get("thr2_marking") or "").upper()
        des1 = (rwy.get("thr1_designator") or "").strip()
        des2 = (rwy.get("thr2_designator") or "").strip()

        # If length wasn't supplied, derive it from the threshold delta.
        lat_cos = math.cos(math.radians(ac_lat))
        d_lat = (t2_lat - t1_lat)
        d_lon = (t2_lon - t1_lon) * lat_cos
        rwy_deg_len = math.sqrt(d_lat * d_lat + d_lon * d_lon)
        if rwy_deg_len < 1e-9:
            return
        if length_ft <= 0:
            length_ft = rwy_deg_len * 364491.0   # 1 deg lat ≈ 364491 ft

        # Unit perpendicular in (deg-lat, deg-lon-lat-corrected) space.
        # Same right-hand convention as the runway-quad code in the caller.
        perp_lat = -d_lon / rwy_deg_len
        perp_lon =  d_lat / rwy_deg_len / lat_cos

        ft_per_deg_lat = 364491.0

        def rwy_point(along_ft, across_ft, height_ft=0.0):
            """Return (lat, lon, elev_ft) for a runway-local point.
            along=0 is thr1, along=length_ft is thr2; across=0 is centerline,
            across=+width/2 is right of the thr1→thr2 direction."""
            f = max(0.0, min(1.0, along_ft / length_ft))
            clat = t1_lat + f * (t2_lat - t1_lat)
            clon = t1_lon + f * (t2_lon - t1_lon)
            celev = t1_elev + f * (t2_elev - t1_elev)
            across_deg = across_ft / ft_per_deg_lat
            return (clat + perp_lat * across_deg,
                    clon + perp_lon * across_deg,
                    celev + height_ft)

        def project(along_ft, across_ft, height_ft=0.0):
            lat, lon, elev = rwy_point(along_ft, across_ft, height_ft)
            sx, sy, vis = self._project_point(
                lat, lon, elev, ac_lat, ac_lon, ac_alt_ft,
                pitch_deg, roll_deg, heading_deg, ppd, w, h)
            return sx, sy, vis

        def quad(a0, c0, a1, c1, a2, c2, a3, c3, height_ft=0.0):
            """Project a 4-corner polygon in runway-local coords. Returns
            QPolygonF or None if any corner is behind the aircraft."""
            pts = []
            for a, c in ((a0, c0), (a1, c1), (a2, c2), (a3, c3)):
                sx, sy, vis = project(a, c, height_ft)
                if not vis:
                    return None
                pts.append(QPointF(sx, sy))
            return QPolygonF(pts)

        from PyQt6.QtCore import Qt as _Qt
        WHITE  = QColor(245, 245, 245)
        YELLOW = QColor(220, 200, 60)

        p.setPen(Qt_NoPen())
        p.setBrush(QBrush(WHITE))

        # ---------------------------------------------------------------
        # Per-end markings
        # Each end gets: threshold bars, designator, aiming point, TDZ (PIR),
        # side stripes (PIR), displaced-threshold chevrons (if displaced).
        # ---------------------------------------------------------------
        # End-1 (thr1) markings — usable threshold at along = d1.
        # End-2 (thr2) markings — usable threshold at along = length_ft - d2.
        # Designators, aiming points, TDZ are all measured FROM the usable
        # threshold, INWARD along the runway (toward the opposite end).
        for thr_along, sign, designator, marking, displaced in (
                (d1,                  +1, des1, m1, d1),
                (length_ft - d2,      -1, des2, m2, d2)):
            # Skip if there's no room at this end (very short runway).
            usable_remaining = (length_ft - d1 - d2)
            if usable_remaining < 100.0:
                continue

            # ----- Threshold bars (PIR and NPI) --------------------------
            if marking in ("PIR", "NPI"):
                # 8 stripes total, each 5.75 ft wide × 150 ft long, evenly
                # spaced across the runway width, leaving small gaps. We use
                # a half-width of 70% width to avoid the very edge.
                n_stripes = max(4, min(16, int(round(width_ft / 12.5))))
                stripe_w_ft = 5.75
                bar_len_ft  = 150.0
                # Stripes span ±0.45*W around centerline.
                span = 0.45 * width_ft * 2.0          # total span
                step = span / max(n_stripes, 1)
                first = -span / 2.0 + step / 2.0
                # Bars sit INSIDE the runway, starting at usable threshold.
                bar_a0 = thr_along
                bar_a1 = thr_along + sign * bar_len_ft
                for k in range(n_stripes):
                    c = first + k * step
                    poly = quad(bar_a0, c - stripe_w_ft / 2,
                                bar_a0, c + stripe_w_ft / 2,
                                bar_a1, c + stripe_w_ft / 2,
                                bar_a1, c - stripe_w_ft / 2)
                    if poly is not None:
                        p.drawPolygon(poly)

            # ----- Designator (always, if we have one) -------------------
            if designator:
                # FAA AC 150/5340-1L runway designator markings:
                #   Height: 60 ft for every character
                #   Width:  "1" = 5.33 ft stroke (no flag/foot), L/C/R = 24 ft,
                #           all other digits = 20 ft
                #   Spacing between characters: 5 ft
                #   Layout: if the designator carries a parallel-runway letter
                #           (L/C/R), the letter goes on its own row BELOW the
                #           numbers (closer to the threshold), separated by
                #           a ~20 ft gap. So pilot reads numbers first, then
                #           letter.
                # Each character is rendered in its own FAA-spec slot via
                # quadToQuad; "1" is hand-drawn (no font) to match the FAA
                # plain-stroke style.
                CHAR_H_FT     = 60.0
                CHAR_GAP_FT   = 5.0
                ROW_GAP_FT    = 20.0       # gap between numbers and letter row
                STROKE_FT     = 5.33
                def _char_w(c):
                    if c == '1':              return STROKE_FT
                    if c in ('L', 'C', 'R'):  return 24.0
                    return 20.0

                # Split designator into "numbers" row and an optional letter row.
                if designator[-1] in ('L', 'C', 'R'):
                    number_part = designator[:-1]
                    letter_part = designator[-1]
                else:
                    number_part = designator
                    letter_part = ""

                center_along = thr_along + sign * 380.0
                font = QFont("DejaVu Sans", 10)
                font.setPixelSize(200)
                font.setBold(True)
                from PyQt6.QtGui import QPainterPath as _QPP
                from PyQt6.QtCore import QRectF as _QRectF

                # Number of horizontal strips per designator character. A
                # single quadToQuad across a 60-ft tall character is a
                # linear chord through the curve produced by the angular
                # projection; at low AGL that chord visibly diverges from
                # where the character's outline actually should go. K
                # strips per character give K independent quadToQuad
                # transforms, each spanning a much smaller along-distance,
                # so the assembled glyph follows the same curve the
                # threshold bars and centerline stripes already trace.
                # K=6 is enough to make the seam invisible at typical
                # short-final altitudes; larger K costs ~K paint ops per
                # character.
                K_STRIPS = 6

                def _render_row(chars, row_center_along):
                    """Paint one designator row centered on
                    ``row_center_along``, with each character's outline
                    perspective-mapped through K horizontal strips so
                    the glyph traces the same curve as the rest of the
                    runway markings rather than fitting one linear
                    chord across the full character height."""
                    if not chars:
                        return
                    widths = [_char_w(c) for c in chars]
                    total_w = sum(widths) + CHAR_GAP_FT * max(0, len(chars) - 1)
                    top_a = row_center_along + sign * (CHAR_H_FT / 2.0)
                    bot_a = row_center_along - sign * (CHAR_H_FT / 2.0)
                    # Start at pilot's LEFT edge of the row (stepping by +sign
                    # per char handles both thr1 and thr2 orientations).
                    cur_across = -sign * (total_w / 2.0)
                    for idx, ch in enumerate(chars):
                        cw = widths[idx]
                        sL = cur_across
                        sR = cur_across + sign * cw

                        # Build the character outline. FAA "1" is a plain
                        # vertical bar (no font flag/foot) — render it as
                        # a filled rectangle in source space so it gets
                        # the same per-strip perspective treatment as the
                        # other glyphs.
                        char_path = _QPP()
                        if ch == '1':
                            char_path.addRect(0.0, 0.0, STROKE_FT, CHAR_H_FT)
                        else:
                            char_path.addText(0, 0, font, ch)
                        gb = char_path.boundingRect()
                        if gb.width() <= 0.5 or gb.height() <= 0.5:
                            cur_across += sign * (cw + CHAR_GAP_FT)
                            continue

                        # Project K+1 horizontal slices spanning the
                        # character along the runway. Each adjacent pair
                        # of slices defines one perspective strip.
                        slices = []
                        for k in range(K_STRIPS + 1):
                            f = k / K_STRIPS
                            a = top_a + f * (bot_a - top_a)
                            Lx, Ly, vL = project(a, sL)
                            Rx, Ry, vR = project(a, sR)
                            slices.append((QPointF(Lx, Ly),
                                           QPointF(Rx, Ry), vL and vR))

                        for k in range(K_STRIPS):
                            L0, R0, ok0 = slices[k]
                            L1, R1, ok1 = slices[k + 1]
                            if not (ok0 and ok1):
                                continue
                            y_top = gb.top() + (k / K_STRIPS) * gb.height()
                            y_bot = gb.top() + ((k + 1) / K_STRIPS) * gb.height()
                            src = QPolygonF([
                                QPointF(gb.left(),  y_top),
                                QPointF(gb.right(), y_top),
                                QPointF(gb.right(), y_bot),
                                QPointF(gb.left(),  y_bot),
                            ])
                            dst = QPolygonF([L0, R0, R1, L1])
                            xfm = QTransform()
                            if not QTransform.quadToQuad(src, dst, xfm):
                                continue
                            strip_clip = _QPP()
                            strip_clip.addRect(_QRectF(
                                gb.left(), y_top,
                                gb.width(), y_bot - y_top))
                            strip_path = char_path.intersected(strip_clip)
                            p.save()
                            p.setTransform(xfm)
                            p.setBrush(QBrush(WHITE))
                            p.setPen(Qt_NoPen())
                            p.drawPath(strip_path)
                            p.restore()

                        cur_across += sign * (cw + CHAR_GAP_FT)

                if letter_part:
                    # Two-row layout. Numbers go on the "far" row (farther
                    # from threshold = +sign direction), letter on the "near"
                    # row (closer to threshold). The 380 ft anchor stays the
                    # centroid of the whole group.
                    row_offset = (CHAR_H_FT + ROW_GAP_FT) / 2.0
                    _render_row(number_part, center_along + sign * row_offset)
                    _render_row(letter_part, center_along - sign * row_offset)
                else:
                    _render_row(number_part, center_along)

            # ----- Aiming point (PIR and NPI) ----------------------------
            if marking in ("PIR", "NPI") and usable_remaining > 2400.0:
                # Two bars 150 ft × 30 ft, 72 ft apart centerline-to-centerline,
                # starting at 1000 ft from threshold.
                aim_a0 = thr_along + sign * 1000.0
                aim_a1 = aim_a0 + sign * 150.0
                for c_center in (-36.0, +36.0):
                    poly = quad(aim_a0, c_center - 15.0,
                                aim_a0, c_center + 15.0,
                                aim_a1, c_center + 15.0,
                                aim_a1, c_center - 15.0)
                    if poly is not None:
                        p.drawPolygon(poly)

            # ----- Touchdown zone markers (PIR only) ----------------------
            # Standard 3/2/1 pattern (per side), at 500/1500/2500 ft from
            # threshold. We skip the 1000 ft set because the aiming point
            # sits there. Each TDZ stripe is 75 ft long × 6 ft wide.
            if marking == "PIR" and usable_remaining > 3000.0:
                STRIPE_LEN = 75.0
                STRIPE_W   = 6.0
                STRIPE_GAP = 5.0
                # Centerline offsets for the stripes (right of centerline;
                # mirrored to the left automatically).
                centerline_offset = 36.0
                for dist_ft, n_stripes in (
                        (500.0, 3), (1500.0, 2), (2500.0, 1)):
                    if dist_ft + STRIPE_LEN > usable_remaining:
                        continue
                    a0 = thr_along + sign * dist_ft
                    a1 = a0 + sign * STRIPE_LEN
                    for side in (-1.0, +1.0):
                        for k in range(n_stripes):
                            c_inner = side * (centerline_offset
                                              + k * (STRIPE_W + STRIPE_GAP))
                            c_outer = c_inner + side * STRIPE_W
                            c_lo, c_hi = min(c_inner, c_outer), max(c_inner, c_outer)
                            poly = quad(a0, c_lo, a0, c_hi,
                                        a1, c_hi, a1, c_lo)
                            if poly is not None:
                                p.drawPolygon(poly)

            # ----- Displaced-threshold chevrons --------------------------
            if displaced > 50.0:
                # White arrows in displaced area, pointing toward the usable
                # threshold. We draw them as elongated triangles down the
                # centerline, spaced every 200 ft.
                p.setBrush(QBrush(WHITE))
                # Displaced area runs from thr1/thr2 OUTWARD from runway
                # interior. For end-1, displaced area is along=0..d1.
                # For end-2, it's along=length_ft-d2..length_ft.
                if sign > 0:                       # end-1
                    chev_start, chev_end = 0.0, displaced
                else:                              # end-2
                    chev_start, chev_end = length_ft - displaced, length_ft
                # Each chevron is 90 ft long, pointing toward usable threshold.
                CHEV_LEN = 90.0
                CHEV_HW  = 20.0
                pos = chev_start + 50.0 if sign > 0 else chev_end - 50.0
                while (sign > 0 and pos + CHEV_LEN < chev_end - 30.0) or \
                      (sign < 0 and pos - CHEV_LEN > chev_start + 30.0):
                    # Tip points toward usable threshold (direction = +sign).
                    tip_a  = pos + sign * CHEV_LEN
                    base_a = pos
                    # Two filled triangles forming a chevron outline. Drawing
                    # one elongated triangle is simpler and reads as an arrow.
                    pts = []
                    for a, c in ((base_a, -CHEV_HW),
                                 (tip_a,   0.0),
                                 (base_a, +CHEV_HW)):
                        sx, sy, vis = project(a, c)
                        if not vis:
                            pts = None
                            break
                        pts.append(QPointF(sx, sy))
                    if pts:
                        p.drawPolygon(QPolygonF(pts))
                    pos += sign * 200.0

        # ---------------------------------------------------------------
        # Whole-runway markings: side stripes (PIR) + centerline (all).
        # ---------------------------------------------------------------
        usable_a0 = d1
        usable_a1 = length_ft - d2
        # ----- Side stripes (PIR only) -------------------------------------
        # Each side stripe runs the FULL usable length of the runway. A
        # 4-corner chord across that length would cut visibly straight
        # across the curve traced by the (now subdivided) runway polygon
        # edges — the user-reported "two tight strings connecting the
        # 06 and 24 ends while the asphalt fill bows underneath" came
        # from exactly this mismatch. Subdivide the long edges so each
        # stripe traces the same curve the runway polygon does.
        if "PIR" in (m1, m2) and usable_a1 - usable_a0 > 200.0:
            STRIPE_W = 3.0
            for side in (-1.0, +1.0):
                c_in  = side * (width_ft * 0.5 - STRIPE_W)
                c_out = side * (width_ft * 0.5)
                c_lo, c_hi = min(c_in, c_out), max(c_in, c_out)
                n_sub = self._RUNWAY_LONG_EDGE_SEGMENTS
                strip_corners = []
                # Short edge at usable_a0 (CCW order: c_lo then c_hi).
                strip_corners.append(rwy_point(usable_a0, c_lo))
                strip_corners.append(rwy_point(usable_a0, c_hi))
                # Long edge at across=c_hi, from usable_a0 -> usable_a1.
                for k in range(1, n_sub):
                    f = k / n_sub
                    strip_corners.append(rwy_point(
                        usable_a0 + f * (usable_a1 - usable_a0), c_hi))
                # Short edge at usable_a1.
                strip_corners.append(rwy_point(usable_a1, c_hi))
                strip_corners.append(rwy_point(usable_a1, c_lo))
                # Long edge at across=c_lo, from usable_a1 -> usable_a0.
                for k in range(1, n_sub):
                    f = k / n_sub
                    strip_corners.append(rwy_point(
                        usable_a1 + f * (usable_a0 - usable_a1), c_lo))
                # Width-adaptive near plane based on the full runway
                # half-width — same trade-off as the main polygon.
                hw_deg = (width_ft / 2.0) / 364491.0
                eps = hw_deg / math.tan(math.radians(70.0))
                stripe_pts = self._project_polygon_clipped(
                    strip_corners, ac_lat, ac_lon, ac_alt_ft,
                    pitch_deg, roll_deg, heading_deg, ppd, w, h,
                    eps=eps)
                if len(stripe_pts) >= 3:
                    p.drawPolygon(QPolygonF(stripe_pts))

        # ----- Centerline stripes (always; cosmetic for BSC) ---------------
        # 120 ft stripe + 80 ft gap, starting 50 ft inboard of threshold bars
        # (so 200 ft from threshold on PIR/NPI; 50 ft on BSC).
        STRIPE_LEN = 120.0
        STRIPE_GAP = 80.0
        CL_WIDTH   = 3.0
        cl_a0 = usable_a0 + (200.0 if m1 in ("PIR", "NPI") else 50.0)
        cl_a1 = usable_a1 - (200.0 if m2 in ("PIR", "NPI") else 50.0)
        a = cl_a0
        while a + STRIPE_LEN < cl_a1:
            poly = quad(a,                -CL_WIDTH / 2.0,
                        a,                +CL_WIDTH / 2.0,
                        a + STRIPE_LEN,   +CL_WIDTH / 2.0,
                        a + STRIPE_LEN,   -CL_WIDTH / 2.0)
            if poly is not None:
                p.drawPolygon(poly)
            a += STRIPE_LEN + STRIPE_GAP

    def _sample_elevations(self, lat_grid: np.ndarray,
                           lon_grid: np.ndarray) -> tuple:
        """
        Sample elevation for the entire grid in one vectorised pass.
        Returns (elev_m, is_water) — same shape as the input grids —
        with is_water marking ocean (SRTM void tiles or missing tiles).

        Points over ocean are initialised to _WATER_SENTINEL; bilinear
        interpolation near coastlines may produce large-negative values that are
        also caught by the water mask.  Elevation is clamped to 0 m after masking
        so clearance arithmetic is not affected by the sentinel.
        """
        elev = np.full(lat_grid.shape, _WATER_SENTINEL, dtype=np.float32)

        tile_lat_grid = np.floor(lat_grid).astype(np.int32)
        tile_lon_grid = np.floor(lon_grid).astype(np.int32)

        keys = np.unique(
            np.stack([tile_lat_grid.ravel(), tile_lon_grid.ravel()], axis=1),
            axis=0
        )

        for tile_lat, tile_lon in keys:
            tile = self.cache.get(int(tile_lat), int(tile_lon))
            if tile is None:
                continue  # missing tile file — stays as water sentinel

            mask = (tile_lat_grid == tile_lat) & (tile_lon_grid == tile_lon)
            lats = lat_grid[mask]
            lons = lon_grid[mask]

            row_f = (tile_lat + 1.0 - lats) * (SRTM3_SAMPLES - 1)
            col_f = (lons - tile_lon)        * (SRTM3_SAMPLES - 1)

            row = np.clip(np.floor(row_f).astype(np.int32), 0, SRTM3_SAMPLES - 2)
            col = np.clip(np.floor(col_f).astype(np.int32), 0, SRTM3_SAMPLES - 2)
            dr  = (row_f - row).astype(np.float32)
            dc  = (col_f - col).astype(np.float32)

            elev[mask] = (tile[row,     col    ] * (1 - dr) * (1 - dc) +
                          tile[row,     col + 1] * (1 - dr) *      dc  +
                          tile[row + 1, col    ] *      dr  * (1 - dc) +
                          tile[row + 1, col + 1] *      dr  *      dc)

        # Two water cases:
        #   1. Missing tile (open ocean, no HGT file) — stays at _WATER_SENTINEL
        #   2. Void-filled SRTM product — ocean pixels are exactly 0.0
        # Both are detected here; elev is clamped to 0 so clearance maths is clean.
        is_water = (elev < (_WATER_SENTINEL / 2.0)) | (elev == 0.0)
        elev = np.where(is_water, 0.0, elev)
        return elev, is_water


# ---------------------------------------------------------------------------
# Tiny helper — avoids importing Qt.NoPen at module level before QApp exists
# ---------------------------------------------------------------------------
def Qt_NoPen():
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QPen
    return QPen(Qt.PenStyle.NoPen)


# ---------------------------------------------------------------------------
# Scene-graph wrapper — lets SVS participate in the same z-order system
# as the pitch ladder, runways, and other items in the AI scene.
# ---------------------------------------------------------------------------
class SVSGraphicsItem:
    """QGraphicsItem that delegates painting to an SVSRenderer.

    Construction is deferred to a factory function so importing this module
    doesn't require a QApplication. Call ``make_svs_item(renderer, ai_widget)``
    to instantiate.
    """
    pass  # placeholder for documentation; real class created by the factory


def make_svs_item(renderer: "SVSRenderer", ai_widget):
    """Build a QGraphicsItem subclass instance that delegates to *renderer*.

    The item reads pose state (lat/lon/alt/pitch/roll/heading/ppd) from the
    parent ``ai_widget`` at paint time. Z-value defaults to one below the
    pitch ladder (ladder is z=1); override with ``setZValue`` after creation
    or via the ``z_value`` SVS config key picked up by the AI widget.
    """
    from PyQt6.QtCore    import QRectF
    from PyQt6.QtWidgets import QGraphicsItem

    class _SVSGraphicsItem(QGraphicsItem):
        def __init__(self, _renderer, _ai):
            super().__init__()
            self._renderer = _renderer
            self._ai       = _ai

        def boundingRect(self):
            # Generous rect so Qt never culls the item — SVS uses
            # resetTransform() internally and draws in pure viewport pixels,
            # so the scene-coordinate bounds don't actually constrain output.
            return QRectF(-1e6, -1e6, 2e6, 2e6)

        def paint(self, painter, option, widget=None):
            if self._renderer is None or not self._renderer.ready:
                return
            ai = self._ai
            vp = ai.viewport()
            ppd = getattr(ai, 'pixelsPerDeg',
                          vp.height() / ai.pitchDegreesShown)
            # SVS does its geographic projection in true-north
            # coordinates, so subtract local magnetic variation from
            # the magnetic HEAD before projecting. _magvar defaults to
            # 0 when the FIX MAGVAR key isn't published — in that case
            # the SVS picture sits with a constant rotation equal to
            # local variation, which is small enough not to break the
            # picture but worth correcting where the data is available.
            head_true = ai._fpm_head - getattr(ai, "_magvar", 0.0)
            # SVSRenderer.draw does its own save/resetTransform/restore so the
            # outer scene transform is preserved for the next item in z order.
            self._renderer.draw(
                painter, vp.width(), vp.height(),
                ai._svs_lat, ai._svs_lon, ai._svs_alt,
                ai._pitchAngle, ai._rollAngle, head_true,
                ppd)

    return _SVSGraphicsItem(renderer, ai_widget)
