"""
Unit tests for the SVS terrain renderer (pyefis.instruments.ai.svs).

Tests the HGT tile reader, tile cache, elevation sampling, clearance colour
logic, and SVSRenderer integration with the AI widget — all without a
physical display or real terrain tiles.
"""
import math
import struct
import tempfile
from pathlib import Path

import numpy as np
import pytest
from PyQt6.QtGui import QPaintEvent, QPainter

from pyefis.instruments.ai.svs import (
    SVSRenderer, TileCache,
    tile_name, load_tile, elevation_at,
    COLOR_SAFE, COLOR_CAUTION, COLOR_WARNING, COLOR_CONFLICT,
    SRTM3_SAMPLES, SRTM3_VOID,
    POLAR_DEFAULTS,
    _QualityController,
)
from pyefis.instruments.ai import AI


# ---------------------------------------------------------------------------
# Helpers — synthetic HGT tile
# ---------------------------------------------------------------------------

def _write_hgt(path: Path, elevation: int = 500):
    """Write a flat-elevation synthetic HGT tile (all samples = elevation)."""
    data = np.full((SRTM3_SAMPLES, SRTM3_SAMPLES), elevation, dtype=">i2")
    data.tofile(path)


def _make_tile_dir(tmp_path: Path, lat: int, lon: int, elevation: int = 500) -> Path:
    """Create a synthetic tile in the standard directory structure."""
    name = tile_name(lat, lon)
    ns_dir = f"{'N' if lat >= 0 else 'S'}{abs(lat):02d}"
    tile_dir = tmp_path / "srtm3" / ns_dir
    tile_dir.mkdir(parents=True, exist_ok=True)
    _write_hgt(tile_dir / f"{name}.hgt", elevation)
    return tmp_path / "srtm3"


# ---------------------------------------------------------------------------
# Tile naming
# ---------------------------------------------------------------------------

class TestTileNaming:
    def test_positive_lat_lon(self):
        assert tile_name(32, -97) == "N32W097"

    def test_negative_lat(self):
        assert tile_name(-33, 18) == "S33E018"

    def test_equator_prime_meridian(self):
        assert tile_name(0, 0) == "N00E000"

    def test_high_latitude(self):
        assert tile_name(59, 10) == "N59E010"


# ---------------------------------------------------------------------------
# HGT tile loading
# ---------------------------------------------------------------------------

class TestTileLoading:
    def test_load_flat_tile(self, tmp_path):
        root = _make_tile_dir(tmp_path, 32, -97, elevation=1500)
        tile = load_tile(root, 32, -97)
        assert tile is not None
        assert tile.shape == (SRTM3_SAMPLES, SRTM3_SAMPLES)
        assert tile[0, 0] == 1500

    def test_missing_tile_returns_none(self, tmp_path):
        root = tmp_path / "srtm3"
        root.mkdir()
        tile = load_tile(root, 99, 99)
        assert tile is None

    def test_void_values_replaced_with_zero(self, tmp_path):
        name = tile_name(10, 10)
        ns_dir = "N10"
        tile_dir = tmp_path / "srtm3" / ns_dir
        tile_dir.mkdir(parents=True)
        data = np.full((SRTM3_SAMPLES, SRTM3_SAMPLES), SRTM3_VOID, dtype=">i2")
        data.tofile(tile_dir / f"{name}.hgt")
        tile = load_tile(tmp_path / "srtm3", 10, 10)
        assert tile is not None
        assert (tile == 0).all()


# ---------------------------------------------------------------------------
# Elevation interpolation
# ---------------------------------------------------------------------------

class TestElevationAt:
    def test_centre_of_flat_tile(self, tmp_path):
        root = _make_tile_dir(tmp_path, 32, -97, elevation=1000)
        tile = load_tile(root, 32, -97)
        # Centre of the tile
        elev = elevation_at(tile, 32, -97, 32.5, -96.5)
        assert abs(elev - 1000) < 1.0

    def test_sw_corner_of_tile(self, tmp_path):
        root = _make_tile_dir(tmp_path, 32, -97, elevation=800)
        tile = load_tile(root, 32, -97)
        elev = elevation_at(tile, 32, -97, 32.0, -97.0)
        assert abs(elev - 800) < 1.0


# ---------------------------------------------------------------------------
# Tile cache
# ---------------------------------------------------------------------------

class TestTileCache:
    def test_cache_hit_returns_same_array(self, tmp_path):
        root = _make_tile_dir(tmp_path, 32, -97)
        cache = TileCache(root)
        a = cache.get(32, -97)
        b = cache.get(32, -97)
        assert a is b  # same object from cache

    def test_missing_tile_returns_none(self, tmp_path):
        root = tmp_path / "srtm3"
        root.mkdir()
        cache = TileCache(root)
        assert cache.get(0, 0) is None

    def test_elevation_method(self, tmp_path):
        root = _make_tile_dir(tmp_path, 32, -97, elevation=600)
        cache = TileCache(root)
        elev = cache.elevation(32.5, -96.5)
        assert abs(elev - 600) < 1.0

    def test_elevation_missing_tile_returns_zero(self, tmp_path):
        root = tmp_path / "srtm3"
        root.mkdir()
        cache = TileCache(root)
        assert cache.elevation(32.5, -96.5) == 0.0

    def test_lru_eviction(self, tmp_path):
        for lat in range(5):
            _make_tile_dir(tmp_path, lat, 0, elevation=100 * lat)
        root = tmp_path / "srtm3"
        cache = TileCache(root, max_tiles=3)
        for lat in range(5):
            cache.get(lat, 0)
        assert len(cache._cache) <= 3


# ---------------------------------------------------------------------------
# SVSRenderer configuration
# ---------------------------------------------------------------------------

class TestSVSRendererConfig:
    def test_disabled_by_default(self):
        r = SVSRenderer({})
        assert r.enabled is False
        assert r.ready is False

    def test_enabled_but_no_tile_path(self):
        r = SVSRenderer({"enabled": True})
        assert r.enabled is True
        assert r.ready is False   # no tile_path configured

    def test_enabled_with_valid_tile_path(self, tmp_path):
        root = _make_tile_dir(tmp_path, 32, -97)
        r = SVSRenderer({"enabled": True, "tile_path": str(root)})
        assert r.ready is True

    def test_renderer_tier_grid_size(self):
        assert SVSRenderer({"renderer": "cpu_sparse"})._grid_n == 48
        assert SVSRenderer({"renderer": "cpu_dense"})._grid_n == 128

    def test_range_nm_default(self):
        assert SVSRenderer({}).range_nm == 30.0

    def test_clearance_colors(self, tmp_path):
        root = _make_tile_dir(tmp_path, 32, -97)
        r = SVSRenderer({
            "enabled": True, "tile_path": str(root),
            "clearance_green_ft": 1000, "clearance_yellow_ft": 500,
        })
        assert r._clearance_color(1500) == COLOR_SAFE
        assert r._clearance_color(750)  == COLOR_CAUTION
        assert r._clearance_color(200)  == COLOR_WARNING
        assert r._clearance_color(-50)  == COLOR_CONFLICT


# ---------------------------------------------------------------------------
# AI widget integration
# ---------------------------------------------------------------------------

class TestAISVSIntegration:
    def test_ai_svs_none_by_default(self, fix, qtbot):
        widget = AI()
        qtbot.addWidget(widget)
        assert widget.svs is None

    def test_set_svs_config_creates_renderer(self, fix, qtbot, tmp_path):
        root = _make_tile_dir(tmp_path, 32, -97)
        widget = AI()
        qtbot.addWidget(widget)
        widget.set_svs_config({"enabled": True, "tile_path": str(root)})
        assert widget.svs is not None
        assert widget.svs.ready is True

    def test_paint_with_svs_disabled(self, fix, qtbot):
        """paintEvent does not raise when SVS is configured but disabled."""
        widget = AI()
        qtbot.addWidget(widget)
        widget.set_svs_config({"enabled": False})
        widget.resize(400, 300)
        widget.show()
        qtbot.waitExposed(widget)
        widget.paintEvent(QPaintEvent(widget.rect()))

    def test_paint_with_svs_enabled_no_tiles(self, fix, qtbot, tmp_path):
        """paintEvent does not raise when SVS enabled but tile dir is empty."""
        empty_dir = tmp_path / "srtm3"
        empty_dir.mkdir()
        widget = AI()
        qtbot.addWidget(widget)
        widget.set_svs_config({"enabled": True, "tile_path": str(empty_dir)})
        widget.resize(400, 300)
        widget.show()
        qtbot.waitExposed(widget)
        widget.paintEvent(QPaintEvent(widget.rect()))

    def test_paint_with_svs_and_synthetic_tile(self, fix, qtbot, tmp_path):
        """Full paintEvent with a synthetic tile loaded — no crash."""
        fix.db.set_value("LAT", 32.5)
        fix.db.set_value("LONG", -96.5)
        fix.db.set_value("ALT", 3000.0)
        root = _make_tile_dir(tmp_path, 32, -97, elevation=500)
        widget = AI()
        qtbot.addWidget(widget)
        widget.set_svs_config({
            "enabled": True,
            "tile_path": str(root),
            "renderer": "cpu_sparse",
            "range_nm": 10,
        })
        widget.resize(400, 300)
        widget.show()
        qtbot.waitExposed(widget)
        widget.paintEvent(QPaintEvent(widget.rect()))

    def test_ai_construction_tolerates_missing_fpm_key(self, fix, qtbot,
                                                      monkeypatch, caplog):
        """If a Flight Path Marker FIX key is undefined (e.g. gateway doesn't
        publish TRACK), the AI widget must still construct — FPM rendering
        is silently disabled, not a hard crash."""
        import pyavtools.fix as _fix
        real_get_item = _fix.db.get_item

        def get_item_no_track(key):
            if key == "TRACK":
                raise KeyError(key)
            return real_get_item(key)

        monkeypatch.setattr(_fix.db, "get_item", get_item_no_track)

        with caplog.at_level("WARNING"):
            widget = AI()
        qtbot.addWidget(widget)
        # FPM key map still includes TRACK and that entry stays in fail-state,
        # so _drawFPM's `any(self._fpm_fail.values())` gate skips rendering.
        assert widget._fpm_fail["TRACK"] is True
        # Paint cycle should still complete without raising.
        widget.resize(400, 300)
        widget.show()
        qtbot.waitExposed(widget)
        widget.paintEvent(QPaintEvent(widget.rect()))
        assert any("TRACK" in r.getMessage() for r in caplog.records)


# ---------------------------------------------------------------------------
# Polar (range, azimuth) tier
# ---------------------------------------------------------------------------

class TestPolarTier:
    """Polar tier samples terrain on a forward fan with radial LOD warp."""

    def test_polar_defaults_loaded(self):
        r = SVSRenderer({"renderer": "polar"})
        assert r._is_polar is True
        assert r._n_range     == POLAR_DEFAULTS["n_range"]
        assert r._n_az        == POLAR_DEFAULTS["n_az"]
        assert r._fov_deg     == POLAR_DEFAULTS["fov_deg"]
        assert r._radial_warp == POLAR_DEFAULTS["radial_warp"]
        assert r._r_min_nm    == POLAR_DEFAULTS["r_min_nm"]

    def test_polar_config_overrides(self):
        r = SVSRenderer({
            "renderer": "polar",
            "n_range": 32, "n_az": 48,
            "fov_deg": 120.0, "radial_warp": 1.5, "r_min_nm": 0.1,
        })
        assert r._n_range     == 32
        assert r._n_az        == 48
        assert r._fov_deg     == 120.0
        assert r._radial_warp == 1.5
        assert r._r_min_nm    == 0.1

    def test_non_polar_tier_flagged_false(self):
        for tier in ("cpu_sparse", "cpu_dense", "cpu_ultra"):
            r = SVSRenderer({"renderer": tier})
            assert r._is_polar is False

    def test_radial_warp_concentrates_samples_near_aircraft(self):
        """Quadratic warp: cell at r=0 must be smaller than cell at r=range."""
        n_r = 16
        warp = 2.0
        range_nm = 30.0
        r_min = 0.01
        t = np.linspace(0.0, 1.0, n_r)
        r_max_eff = range_nm * (1.0 - 1e-6)
        r_nm = r_min + (r_max_eff - r_min) * (t ** warp)
        # Cell size = consecutive differences
        cell_size = np.diff(r_nm)
        # The first (inner) cell must be strictly smaller than the last (outer).
        assert cell_size[0] < cell_size[-1]
        # Outer cell should be at least 3x the inner cell at warp=2.
        assert cell_size[-1] / cell_size[0] >= 3.0

    def _draw_polar(self, renderer, lat=32.5, lon=-96.5, alt_ft=5000.0,
                    heading_deg=0.0):
        """Helper: run SVSRenderer.draw() against an offscreen QImage.
        Avoids constructing the AI widget (which depends on additional FIX
        keys outside SVS's concern)."""
        from PyQt6.QtGui import QImage
        img = QImage(400, 300, QImage.Format.Format_RGB32)
        img.fill(0)
        painter = QPainter(img)
        try:
            renderer.draw(painter, 400, 300, lat, lon, alt_ft,
                          0.0, 0.0, heading_deg, 12.0)
        finally:
            painter.end()
        return img

    def test_polar_draw_on_synthetic_tile(self, tmp_path):
        """Polar draw() completes without raising on a flat synthetic tile."""
        root = _make_tile_dir(tmp_path, 32, -97, elevation=500)
        r = SVSRenderer({
            "enabled": True, "tile_path": str(root),
            "renderer": "polar", "range_nm": 15,
            # Trimmed sample budget to keep the test fast.
            "n_range": 16, "n_az": 24,
        })
        assert r.ready is True
        self._draw_polar(r)

    def test_polar_draw_at_varied_headings(self, tmp_path):
        """Polar grid must work at any heading — covers the heading
        rotation that gets absorbed into the azimuth axis."""
        root = _make_tile_dir(tmp_path, 32, -97, elevation=500)
        r = SVSRenderer({
            "enabled": True, "tile_path": str(root),
            "renderer": "polar", "range_nm": 10,
            "n_range": 8, "n_az": 12,
        })
        for heading in (0.0, 90.0, 180.0, 270.0, 45.0, 359.0):
            self._draw_polar(r, heading_deg=heading)


# ---------------------------------------------------------------------------
# OpenGL tier — scaffolding + fallback machinery
# Step 1 of docs/svs_opengl_plan.md. The GL renderer's draw() stub raises
# NotImplementedError on purpose; these tests verify the fallback path
# transparently downgrades to polar and never crashes.
# ---------------------------------------------------------------------------

class TestWaterDB:
    """``WaterDB`` is a sqlite-backed range-queryable water polygon
    loader, following the ObstacleDB construct-never-raises pattern."""

    def _build_db(self, tmp_path, rows):
        """Build a minimal water.sqlite with the given polygons.
        ``rows`` is a list of (kind, elev_ft, [(lat, lon), ...])."""
        import sqlite3
        from pyefis.instruments.ai.water_db import encode_vertices
        path = tmp_path / "water.sqlite"
        con = sqlite3.connect(str(path))
        con.execute("""
            CREATE TABLE water_polygons (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                min_lat   REAL NOT NULL,
                max_lat   REAL NOT NULL,
                min_lon   REAL NOT NULL,
                max_lon   REAL NOT NULL,
                kind      TEXT NOT NULL,
                elev_ft   REAL,
                vertices  BLOB NOT NULL
            )
        """)
        for kind, elev_ft, verts in rows:
            lats = [v[0] for v in verts]
            lons = [v[1] for v in verts]
            con.execute(
                "INSERT INTO water_polygons "
                "(min_lat, max_lat, min_lon, max_lon, kind, elev_ft, vertices) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (min(lats), max(lats), min(lons), max(lons),
                 kind, elev_ft, encode_vertices(verts)))
        con.commit()
        con.close()
        return path

    def test_missing_file_stays_not_ready(self, tmp_path):
        from pyefis.instruments.ai.water_db import WaterDB
        db = WaterDB(tmp_path / "does_not_exist.sqlite")
        assert db.ready is False
        # Query yields nothing
        assert list(db.polygons_in_range(0.0, 0.0, 30.0)) == []

    def test_none_path_disables_db(self):
        from pyefis.instruments.ai.water_db import WaterDB
        db = WaterDB(None)
        assert db.ready is False

    def test_bad_schema_caught(self, tmp_path):
        """A sqlite file without the expected schema should leave the
        DB in not-ready state, not crash."""
        import sqlite3
        from pyefis.instruments.ai.water_db import WaterDB
        path = tmp_path / "broken.sqlite"
        con = sqlite3.connect(str(path))
        con.execute("CREATE TABLE some_unrelated_table (x INT)")
        con.commit()
        con.close()
        db = WaterDB(path)
        assert db.ready is False

    def test_polygons_in_range_bbox_filter(self, tmp_path):
        from pyefis.instruments.ai.water_db import WaterDB
        # Three polygons:
        #   - Pacific around KSBA (lat 34, lon -120)
        #   - Atlantic near Cape Hatteras NC (lat 35, lon -75)
        #   - Lake Hickory NC near KHKY (lat 35.78, lon -81.3)
        path = self._build_db(tmp_path, [
            ("ocean", None, [(34.0, -120.5), (34.0, -119.5),
                             (34.5, -119.5), (34.5, -120.5)]),
            ("ocean", None, [(35.0, -75.5), (35.0, -74.5),
                             (35.5, -74.5), (35.5, -75.5)]),
            ("lake", 656.0, [(35.78, -81.32), (35.78, -81.28),
                             (35.80, -81.28), (35.80, -81.32)]),
        ])
        db = WaterDB(path)
        assert db.ready is True

        # Aircraft at KSBA — only Pacific should come back.
        polys = list(db.polygons_in_range(34.4, -119.8, 30.0))
        assert len(polys) == 1
        assert polys[0].kind == "ocean"
        assert polys[0].is_ocean is True
        assert len(polys[0].vertices) == 4

        # Aircraft at KHKY — only the lake should come back.
        polys = list(db.polygons_in_range(35.74, -81.39, 10.0))
        assert len(polys) == 1
        assert polys[0].kind == "lake"
        assert polys[0].elev_ft == 656.0
        assert polys[0].is_ocean is False

        # Aircraft mid-Atlantic far from anywhere mapped.
        polys = list(db.polygons_in_range(0.0, 0.0, 30.0))
        assert polys == []

    def test_vertices_roundtrip(self):
        """``encode_vertices`` / ``_decode_vertices`` should be inverses."""
        from pyefis.instruments.ai.water_db import (
            encode_vertices, _decode_vertices)
        verts = [(34.4275, -119.8546),
                 (34.0, -120.0),
                 (-35.123456789, 174.987654321)]   # exercise negatives + precision
        decoded = _decode_vertices(encode_vertices(verts))
        assert len(decoded) == len(verts)
        for (la, lo), (la2, lo2) in zip(verts, decoded):
            assert abs(la - la2) < 1e-12
            assert abs(lo - lo2) < 1e-12


class TestSVSWaterRendering:
    """``_draw_water`` overlays water polygons on top of the terrain
    layer. Sanity-check that it runs without raising at known poses
    and that the DB is wired into the renderer when configured."""

    def _build_db(self, tmp_path, rows):
        # Same minimal builder as TestWaterDB above.
        import sqlite3
        from pyefis.instruments.ai.water_db import encode_vertices
        path = tmp_path / "water.sqlite"
        con = sqlite3.connect(str(path))
        con.execute("""
            CREATE TABLE water_polygons (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                min_lat   REAL NOT NULL, max_lat   REAL NOT NULL,
                min_lon   REAL NOT NULL, max_lon   REAL NOT NULL,
                kind      TEXT NOT NULL, elev_ft   REAL, vertices  BLOB NOT NULL)
        """)
        for kind, elev_ft, verts in rows:
            lats = [v[0] for v in verts]; lons = [v[1] for v in verts]
            con.execute(
                "INSERT INTO water_polygons "
                "(min_lat, max_lat, min_lon, max_lon, kind, elev_ft, vertices) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (min(lats), max(lats), min(lons), max(lons),
                 kind, elev_ft, encode_vertices(verts)))
        con.commit(); con.close()
        return path

    def test_water_db_attached_when_path_configured(self, tmp_path):
        root = _make_tile_dir(tmp_path, 34, -120, elevation=0)
        water = self._build_db(tmp_path, [
            ("ocean", None, [(34.0, -120.5), (34.0, -119.5),
                             (34.5, -119.5), (34.5, -120.5)]),
        ])
        r = SVSRenderer({
            "enabled": True, "tile_path": str(root),
            "water_db_path": str(water),
        })
        assert r.water_db is not None
        assert r.water_db.ready is True

    def test_water_db_disabled_when_path_missing(self, tmp_path):
        root = _make_tile_dir(tmp_path, 34, -120, elevation=0)
        r = SVSRenderer({"enabled": True, "tile_path": str(root)})
        assert r.water_db is not None
        assert r.water_db.ready is False

    def test_draw_water_runs_without_raising_at_ksba(self, tmp_path):
        from PyQt6.QtGui import QImage, QPainter
        # Make a synthetic sea-level tile for the KSBA region so
        # _sample_elevations works.
        root = _make_tile_dir(tmp_path, 34, -120, elevation=0)
        water = self._build_db(tmp_path, [
            ("ocean", None, [
                (34.0, -120.5), (34.0, -119.5),
                (34.5, -119.5), (34.5, -120.5)]),
        ])
        r = SVSRenderer({
            "enabled": True, "tile_path": str(root),
            "water_db_path": str(water), "renderer": "polar",
        })
        img = QImage(400, 300, QImage.Format.Format_RGB32)
        img.fill(0)
        p = QPainter(img)
        try:
            # KSBA short-final pose, looking at the Pacific.
            r.draw(p, 400, 300,
                   34.4275, -119.8546, 500.0,
                   0.0, 0.0, 270.0, 12.0)
        finally:
            p.end()
        # If nothing raised we're good; the polygon should also have
        # produced at least one blue-ish pixel near the bottom-center
        # of the screen at this pose.

    def test_draw_water_skips_when_db_not_ready(self, tmp_path):
        from PyQt6.QtGui import QImage, QPainter
        root = _make_tile_dir(tmp_path, 34, -120, elevation=0)
        r = SVSRenderer({
            "enabled": True, "tile_path": str(root),
            # No water_db_path on purpose.
        })
        img = QImage(400, 300, QImage.Format.Format_RGB32)
        img.fill(0)
        p = QPainter(img)
        try:
            r.draw(p, 400, 300,
                   34.4275, -119.8546, 500.0,
                   0.0, 0.0, 270.0, 12.0)
        finally:
            p.end()


class TestProjectPolygonClipped:
    """``_project_polygon_clipped`` clips polygons against the camera near
    plane so polygons that straddle the aircraft (e.g. a runway being
    crossed) draw their visible portion rather than vanishing the moment
    one corner falls behind. Regression for the runway-disappears-on-
    threshold-crossing bug reported during X-Plane testing."""

    def _renderer(self):
        # No tile_path needed — clipper only uses _project math.
        return SVSRenderer({"renderer": "polar"})

    def test_all_in_front_returns_four_points(self):
        r = self._renderer()
        # KSBA-ish pose, aircraft 1 NM south of the runway looking north.
        # Runway endpoints are at lat 34.43, ±0.001 lon, all forward.
        corners = [
            (34.430, -119.851, 12.0),
            (34.430, -119.853, 12.0),
            (34.432, -119.853, 12.0),
            (34.432, -119.851, 12.0),
        ]
        pts = r._project_polygon_clipped(
            corners,
            ac_lat=34.420, ac_lon=-119.852, ac_alt_ft=500.0,
            pitch_deg=0.0, roll_deg=0.0, heading_deg=0.0,
            ppd=12.0, w=800, h=600, eps=1e-6)
        assert len(pts) == 4

    def test_all_behind_returns_empty(self):
        r = self._renderer()
        # Aircraft north of all corners looking north — all behind.
        corners = [
            (34.420, -119.851, 12.0),
            (34.420, -119.853, 12.0),
            (34.422, -119.853, 12.0),
            (34.422, -119.851, 12.0),
        ]
        pts = r._project_polygon_clipped(
            corners,
            ac_lat=34.440, ac_lon=-119.852, ac_alt_ft=500.0,
            pitch_deg=0.0, roll_deg=0.0, heading_deg=0.0,
            ppd=12.0, w=800, h=600, eps=1e-6)
        assert pts == []

    def test_aircraft_straddling_runway_keeps_visible_half(self):
        """Aircraft is sitting between the two thresholds along the
        runway centerline, heading 90 deg (east) down the runway.
        The two corners behind should be replaced by intersections with
        the camera near plane — total 4 output points (2 originals + 2
        intersections), and all should have positive forward range from
        the camera."""
        r = self._renderer()
        # Runway runs east-west; aircraft at the midpoint, heading east.
        # West threshold corners are behind, east threshold corners are
        # ahead.
        corners = [
            (34.430, -119.860, 12.0),  # west, north — BEHIND
            (34.428, -119.860, 12.0),  # west, south — BEHIND
            (34.428, -119.840, 12.0),  # east, south — AHEAD
            (34.430, -119.840, 12.0),  # east, north — AHEAD
        ]
        pts = r._project_polygon_clipped(
            corners,
            ac_lat=34.429, ac_lon=-119.850, ac_alt_ft=200.0,
            pitch_deg=0.0, roll_deg=0.0, heading_deg=90.0,
            ppd=12.0, w=800, h=600, eps=1e-6)
        # Clipping a 4-vertex polygon against a single plane with two
        # vertices behind produces a 4-vertex output (the two AHEAD
        # corners plus two clipped intersections).
        assert len(pts) == 4

    def test_one_behind_three_ahead_returns_five(self):
        """Sutherland-Hodgman on a quad with one vertex behind the
        plane produces a pentagon (3 originals + 2 intersections)."""
        r = self._renderer()
        # Aircraft at (34.429, -119.851), heading 90 (east). x_fwd
        # tracks d_lon_scaled with this heading.
        corners = [
            (34.430, -119.852, 12.0),  # west of aircraft — BEHIND
            (34.430, -119.850, 12.0),  # east — ahead
            (34.428, -119.850, 12.0),  # east — ahead
            (34.428, -119.840, 12.0),  # well east — ahead
        ]
        pts = r._project_polygon_clipped(
            corners,
            ac_lat=34.429, ac_lon=-119.851, ac_alt_ft=200.0,
            pitch_deg=0.0, roll_deg=0.0, heading_deg=90.0,
            ppd=12.0, w=800, h=600, eps=1e-6)
        assert len(pts) == 5

    def test_runway_polygon_corners_subdivides_long_edges(self):
        """`_runway_polygon_corners` subdivides the two long edges of
        the runway into ``n_subdiv`` segments each so the projected
        polygon traces the screen-curve from the angular projection
        rather than cutting a straight chord through it. With
        ``n_subdiv=8`` the polygon has 4 + 2*7 = 18 vertices."""
        r = self._renderer()
        n = 8
        corners = r._runway_polygon_corners(
            t1_lat=35.735, t1_lon=-81.397, t1_elev=1136.0,
            t2_lat=35.745, t2_lon=-81.380, t2_elev=1190.0,
            perp_lat=-0.0001, perp_lon=0.0001, hw=2.058e-4,
            n_subdiv=n)
        assert len(corners) == 4 + 2 * (n - 1)
        # Subdivision points along the left edge should interpolate
        # between t1 and t2 monotonically.
        # corners[2..n] are the inserts on the left long edge
        left_lats = [c[0] for c in corners[2:2 + n - 1]]
        assert all(35.735 < lat < 35.745 for lat in left_lats)
        # And elevations interpolate too.
        left_elevs = [c[2] for c in corners[2:2 + n - 1]]
        assert all(1136.0 < e < 1190.0 for e in left_elevs)
        assert left_elevs == sorted(left_elevs), \
            "elevations along the left edge should monotonically increase"

    def test_runway_polygon_clips_correctly_with_subdivision(self):
        """A subdivided runway polygon still clips cleanly with the
        camera-near-plane Sutherland-Hodgman implementation. Same
        KHKY-like pose that uncovered the projection-curve issue."""
        r = self._renderer()
        # KHKY 06 thr → 24 thr, aircraft mid-runway-but-off-centerline.
        corners = r._runway_polygon_corners(
            t1_lat=35.73499, t1_lon=-81.39730, t1_elev=1136.3,
            t2_lat=35.74498, t2_lon=-81.37956, t2_elev=1189.6,
            perp_lat=-0.0001405, perp_lon=0.00009895, hw=2.058e-4,
            n_subdiv=16)
        pts = r._project_polygon_clipped(
            corners,
            ac_lat=35.74263, ac_lon=-81.38575, ac_alt_ft=1386.0,
            pitch_deg=10.0, roll_deg=3.0, heading_deg=51.18,
            ppd=12.0, w=800, h=600)
        # Polygon should be visible with some clipped vertices.
        assert len(pts) >= 3
        # No vertex should be wildly out of plausible viewport range —
        # the polygon doesn't bulge to +/-1000+ px the way an
        # un-subdivided chord would have at this pose.
        for pt in pts:
            assert -1500 <= pt.x() <= 2300, (
                f"vertex x={pt.x()} unreasonably far from viewport — "
                f"subdivision should keep the polygon within sane "
                f"projection bounds")

    def test_default_near_plane_visibly_inside_viewport(self):
        """Production default ``eps`` (~0.05 NM) puts clipped vertices
        at moderate screen azimuths instead of ~+/-90 deg the way a
        ``eps=1e-6`` value would. Regression for the "markings appear
        beside the polygon" report — without a sensible near plane the
        polygon visually bulges way past the actual runway edges."""
        r = self._renderer()
        # Aircraft heading east at 230 ft AGL, sitting between the two
        # thresholds of a 150-ft-wide east-west runway 6400 ft long.
        # Same KHKY-like pose that produced the visual bug.
        half_lat = (150.0 / 2.0) / 364491.0   # ~half-width in deg lat
        corners = [
            (34.430 + half_lat, -119.860, 1200.0),  # t1 (west) +perp — BEHIND
            (34.430 - half_lat, -119.860, 1200.0),  # t1 -perp        — BEHIND
            (34.430 - half_lat, -119.830, 1200.0),  # t2 (east) -perp — AHEAD
            (34.430 + half_lat, -119.830, 1200.0),  # t2 +perp        — AHEAD
        ]
        pts = r._project_polygon_clipped(
            corners,
            ac_lat=34.430, ac_lon=-119.850, ac_alt_ft=1400.0,
            pitch_deg=0.0, roll_deg=0.0, heading_deg=90.0,
            ppd=12.0, w=800, h=600)
        assert len(pts) == 4
        # Every projected vertex must land within +/- a viewport width
        # of the centre. With the old eps=1e-6 the clipped vertices
        # projected to roughly +/-1080 px on an 800 px viewport because
        # x_ang -> +/-90 deg as x_fwd -> 0.
        for pt in pts:
            assert -400 <= pt.x() - 400 <= 400, (
                f"vertex x={pt.x():.1f} is far outside the viewport — "
                f"default near-plane is too close, clipped vertices "
                f"are projecting to extreme azimuths")


class TestSVSGLFallback:
    def _draw(self, r, lat=32.5, lon=-96.5, alt_ft=3000.0, heading_deg=0.0):
        from PyQt6.QtGui import QImage
        img = QImage(400, 300, QImage.Format.Format_RGB32)
        img.fill(0)
        painter = QPainter(img)
        try:
            r.draw(painter, 400, 300, lat, lon, alt_ft,
                   0.0, 0.0, heading_deg, 12.0)
        finally:
            painter.end()

    def test_renderer_initially_opengl(self, tmp_path):
        """Construction with renderer='opengl' stores the choice — the
        downgrade happens on first draw, not at config-time."""
        root = _make_tile_dir(tmp_path, 32, -97)
        r = SVSRenderer({
            "enabled": True, "tile_path": str(root),
            "renderer": "opengl",
        })
        assert r.renderer == "opengl"
        assert r._gl_renderer is None
        assert r._gl_init_attempted is False

    def test_first_draw_falls_back_to_polar(self, tmp_path, caplog):
        """SVSGLRenderer.draw raises NotImplementedError today, so the first
        draw call must downgrade the renderer to polar and complete cleanly."""
        root = _make_tile_dir(tmp_path, 32, -97, elevation=500)
        r = SVSRenderer({
            "enabled": True, "tile_path": str(root),
            "renderer": "opengl",
            "n_range": 8, "n_az": 12,        # keep the polar fallback cheap
        })
        with caplog.at_level("WARNING"):
            self._draw(r)
        assert r.renderer == "polar"
        assert r._gl_renderer is None
        assert any("falling back to polar" in rec.getMessage().lower()
                   for rec in caplog.records)

    def test_subsequent_draws_use_polar_without_retrying_gl(self, tmp_path):
        """Once GL has failed and been downgraded, repeated draws stay on
        polar and never re-attempt GL construction."""
        root = _make_tile_dir(tmp_path, 32, -97, elevation=500)
        r = SVSRenderer({
            "enabled": True, "tile_path": str(root),
            "renderer": "opengl",
            "n_range": 8, "n_az": 12,
        })
        self._draw(r)
        assert r.renderer == "polar"
        before = r._gl_init_attempted
        # Drawing again must not change anything.
        for _ in range(3):
            self._draw(r)
        assert r.renderer == "polar"
        assert r._gl_init_attempted == before  # still True; not re-tried

    def test_init_failure_also_falls_back(self, tmp_path, monkeypatch, caplog):
        """If SVSGLRenderer construction itself raises (e.g. a Qt build
        without OpenGL bindings), we still downgrade to polar instead of
        crashing."""
        import pyefis.instruments.ai.svs_gl as svs_gl

        class BrokenGL:
            def __init__(self, *a, **kw):
                raise RuntimeError("simulated missing GL bindings")
        monkeypatch.setattr(svs_gl, "SVSGLRenderer", BrokenGL)

        root = _make_tile_dir(tmp_path, 32, -97, elevation=500)
        r = SVSRenderer({
            "enabled": True, "tile_path": str(root),
            "renderer": "opengl",
            "n_range": 8, "n_az": 12,
        })
        with caplog.at_level("WARNING"):
            self._draw(r)
        assert r.renderer == "polar"
        assert any("opengl renderer unavailable" in rec.getMessage().lower()
                   for rec in caplog.records)

    def test_step6_near_airport_helper(self, tmp_path):
        """Step 6: ``_near_airport`` returns True only when the
        configured airport_db reports an airport within
        ``airport_proximity_nm``. Tested against the helper in
        isolation so it doesn't depend on a live GL context."""
        from pyefis.instruments.ai.svs_gl import SVSGLRenderer

        class _StubDB:
            def __init__(self, hit):
                self.ready = True
                self._hit = hit
            def airports_in_range(self, lat, lon, rng):
                if self._hit:
                    yield ("KXYZ", lat, lon)

        class _StubParent:
            def __init__(self, db, prox=5.0):
                self.airport_db = db
                self.airport_proximity_nm = prox

        # Construct a renderer instance but skip __init__ so no Qt GL
        # context is created — we're only exercising the helper.
        gl_r = SVSGLRenderer.__new__(SVSGLRenderer)

        gl_r._parent = _StubParent(_StubDB(hit=True))
        assert gl_r._near_airport(32.5, -96.5) is True

        gl_r._parent = _StubParent(_StubDB(hit=False))
        assert gl_r._near_airport(32.5, -96.5) is False

        gl_r._parent = _StubParent(_StubDB(hit=True), prox=0.0)
        assert gl_r._near_airport(32.5, -96.5) is False, (
            "airport_proximity_nm=0 must disable the 2-colour mode")

        gl_r._parent = _StubParent(db=None)
        assert gl_r._near_airport(32.5, -96.5) is False

    def test_step7_patch_centring_keeps_aircraft_inside(self):
        """Step 7: the 2x2 patch origin chosen by ``_patch_origin_for``
        keeps the aircraft at least 0.5 deg from every patch edge so
        the GL sampler's CLAMP_TO_EDGE never lies about terrain ahead
        of the nose. Sweeping a representative grid of (lat, lon)
        positions, the worst-case edge distance must stay >= 0.5 deg."""
        from pyefis.instruments.ai.svs_gl import SVSGLRenderer
        worst = 99.0
        for ac_lat in np.arange(-2.0, 35.5, 0.1):
            for ac_lon in np.arange(-122.0, 5.5, 0.5):
                slat, slon = SVSGLRenderer._patch_origin_for(ac_lat, ac_lon)
                # Patch covers [slat, slat+2] x [slon, slon+2].
                dist = min(ac_lat - slat, slat + 2 - ac_lat,
                           ac_lon - slon, slon + 2 - ac_lon)
                worst = min(worst, dist)
                assert dist > 0.0, (
                    f"aircraft ({ac_lat}, {ac_lon}) fell outside patch "
                    f"({slat}..{slat+2}, {slon}..{slon+2})")
        assert worst >= 0.5 - 1e-6, (
            f"worst-case edge distance {worst:.4f} deg < 0.5 deg buffer; "
            f"patch centring regressed")

    def test_step7_patch_rebuilds_at_half_integer_crossings(self):
        """Step 7: as the aircraft flies steadily north across a
        half-integer-degree boundary, ``_patch_origin_for`` must change
        at exactly N + 0.5, not at integer N. This is the rebuild
        trigger."""
        from pyefis.instruments.ai.svs_gl import SVSGLRenderer
        prev = SVSGLRenderer._patch_origin_for(32.0, -97.5)
        crossings = []
        # Step in tenths from 32.0 northward across 33.0; the rebuild
        # should fire when crossing 32.5 (32 -> 33 patch start).
        for tenth in range(1, 11):
            ac_lat = 32.0 + tenth * 0.1
            origin = SVSGLRenderer._patch_origin_for(ac_lat, -97.5)
            if origin != prev:
                crossings.append((round(ac_lat, 2), prev, origin))
                prev = origin
        assert len(crossings) == 1, (
            f"expected exactly one boundary crossing between 32.0 and "
            f"33.0; got {crossings}")
        crossed_at, before, after = crossings[0]
        # We step in 0.1 increments, so the crossing is detected at the
        # first tested lat >= 32.5.
        assert 32.5 <= crossed_at <= 32.6, (
            f"rebuild should fire as ac_lat crosses 32.5; got {crossed_at}")
        assert after[0] == before[0] + 1, (
            f"patch start_lat should advance by 1 deg at the crossing; "
            f"got {before} -> {after}")

    def test_step7_negative_longitude_handled(self):
        """Step 7: negative longitudes (the western hemisphere) must
        still produce a patch that contains the aircraft. ``floor`` is
        the right choice — ``int(x)`` would round toward zero and skew
        the patch east at every western position."""
        from pyefis.instruments.ai.svs_gl import SVSGLRenderer
        # KASE (Aspen) is at lat 39.22, lon -106.87.
        slat, slon = SVSGLRenderer._patch_origin_for(39.22, -106.87)
        assert slat <= 39.22 < slat + 2
        assert slon <= -106.87 < slon + 2

    def test_step3_polar_mesh_renders(self, tmp_path):
        """Step 3 verification: with a real GL context the renderer
        draws the polar (t, az) mesh with debug colour bands. We can't
        easily pixel-match without ground-truth, so we just verify:
        (a) renderer stays in opengl mode (no fallback fired); (b) some
        non-background pixels appear in the lower half of the screen
        (where the z=0 mesh projects when looking forward at altitude).
        Skips cleanly on headless / offscreen test environments."""
        import pytest
        from PyQt6.QtGui import QImage
        root = _make_tile_dir(tmp_path, 32, -97, elevation=500)
        r = SVSRenderer({
            "enabled": True, "tile_path": str(root),
            "renderer": "opengl",
            "range_nm": 30, "auto_range": False,
        })
        img = QImage(400, 300, QImage.Format.Format_RGB32)
        img.fill(0x000000)
        painter = QPainter(img)
        try:
            r.draw(painter, 400, 300, 32.5, -96.5, 3000.0, 0.0, 0.0, 0.0, 12.0)
        finally:
            painter.end()
        if r.renderer != "opengl":
            pytest.skip(f"no GL context in this environment (fell back to "
                        f"{r.renderer})")
        # At altitude with z=0 mesh, the fan should project into the
        # lower portion of the screen (just below the horizon line).
        # Walk a row of pixels there and count anything that isn't the
        # dark grey background (0x0d 0x0d 0x0d ≈ rgb 13,13,13).
        non_bg = 0
        for x in range(50, 350, 5):
            c = img.pixelColor(x, 180)   # below horizon
            if c.red() > 30 or c.green() > 30 or c.blue() > 30:
                non_bg += 1
        assert non_bg > 5, (
            f"expected polar mesh pixels below horizon; only {non_bg} "
            f"non-background samples in scan row")


class TestQualityController:
    def test_default_state_is_level_0(self):
        q = _QualityController(base_detail_distance_nm=3.0)
        assert q.level == 0
        assert q.pressure == 0.0
        assert q.marking_k_strips() == 6
        assert q.detail_distance_nm() == pytest.approx(3.0)
        assert q.max_close_markings() == float("inf")

    def test_pressure_rises_under_slow_frames(self):
        # floor_fps=30 -> dt > 33.3 ms drives pressure up.
        q = _QualityController(target_fps=35, floor_fps=30, ceiling_fps=45)
        # Seed the EMA at slow to reach steady-state quickly.
        for _ in range(60):
            q.update(1.0 / 15.0)   # 15 FPS — well under floor
        assert q.pressure == pytest.approx(1.0)
        # At full pressure we should be at the worst level.
        assert q.level == len(_QualityController.LEVELS) - 1
        assert q.marking_k_strips() == 2
        assert q.max_close_markings() == 2

    def test_recovery_is_slower_than_drop(self):
        # Asymmetric step rates: a controller pinned at L3 must take
        # *more* frames to recover to L0 than it took to drop.
        q = _QualityController(target_fps=35, floor_fps=30, ceiling_fps=45)
        drops = 0
        while q.level < len(_QualityController.LEVELS) - 1:
            q.update(1.0 / 15.0)
            drops += 1
            assert drops < 200, "drop should converge well under 200 frames"
        recoveries = 0
        while q.level > 0:
            q.update(1.0 / 60.0)   # 60 FPS — over ceiling
            recoveries += 1
            assert recoveries < 2000, (
                "recovery should converge, but slow")
        assert recoveries > drops * 5, (
            f"recovery ({recoveries} frames) should be substantially "
            f"slower than drop ({drops} frames)")

    def test_dead_band_holds_pressure_steady(self):
        # At steady FPS inside the dead band (here 35 FPS, between
        # floor=30 and ceiling=45), pressure must not change. The EMA
        # converges to dt = 1/35 = 28.5 ms which sits between the
        # floor's 33.3 ms and the ceiling's 22.2 ms.
        q = _QualityController(target_fps=35, floor_fps=30, ceiling_fps=45)
        for _ in range(1000):
            q.update(1.0 / 35.0)
        assert q.pressure == 0.0

    def test_disabled_controller_stays_at_l0(self):
        q = _QualityController(enabled=False, base_detail_distance_nm=3.0)
        for _ in range(100):
            q.update(1.0 / 5.0)
        assert q.level == 0
        assert q.pressure == 0.0
        assert q.detail_distance_nm() == pytest.approx(3.0)

    def test_hysteresis_prevents_flapping_near_threshold(self):
        # Test the level-selection rule directly, bypassing EMA
        # dynamics so we exercise just the hysteresis logic. Pressure
        # in [exit, enter) should hold the current level, not flap.
        q = _QualityController(target_fps=35, floor_fps=30, ceiling_fps=45)
        q._pressure = 0.20
        q._level = 1
        q._ema_dt = 1.0 / 35.0   # dead band -> pressure won't move
        q.update(1.0 / 35.0)
        assert q.level == 1, (
            "pressure 0.20 sits between L1 exit (0.15) and L1 entry "
            "(0.30) — hysteresis must keep the level at L1")
        # Drop pressure just under the exit threshold and the level
        # should step back to L0 on the next update.
        q._pressure = 0.10
        q.update(1.0 / 35.0)
        assert q.level == 0

    def test_pathological_dt_is_ignored(self):
        # A multi-second pause (window minimised, debugger break, etc.)
        # would otherwise pin the controller at L3 for many seconds.
        q = _QualityController(target_fps=35, floor_fps=30, ceiling_fps=45)
        q.update(5.0)                 # 5-second gap, should clamp
        assert q.pressure == 0.0
        q.update(-0.5)                # negative dt, ignored
        assert q.pressure == 0.0
