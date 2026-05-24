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
