"""Track 1b: per-level heightmap textures -- CPU-side builder tests.

No GL context needed: these exercise _level_height_array (the ENU->lat/lon
inverse mapping, world-anchoring across level snaps, and the water
sentinel). See docs/track1b_notes.md.
"""
import math

import numpy as np
import pytest

from pyefis.instruments.ai.svs import SVSRenderer
from pyefis.instruments.ai.camera import M_PER_DEG_LAT
from pyefis.instruments.ai.svs_gl import SVSGLRenderer


def _write_hgt(tmp_path, lat, lon, n, value, gradient=0.0):
    """Write a synthetic .hgt tile: constant ``value`` plus an optional
    south->north gradient (metres per row)."""
    ns = "N%02d" % lat if lat >= 0 else "S%02d" % -lat
    ew = "W%03d" % -lon if lon < 0 else "E%03d" % lon
    d = tmp_path / ns
    d.mkdir(exist_ok=True)
    rows = np.arange(n, dtype=np.float64)[::-1]  # hgt row 0 = north
    data = (np.full((n, n), float(value)) + rows[:, None] * gradient)
    (d / f"{ns}{ew}.hgt").write_bytes(
        data.astype(">i2").tobytes())


@pytest.fixture
def glr(tmp_path):
    for la in (32, 33):
        for lo in (-98, -97):
            _write_hgt(tmp_path, la, lo, 1201, 100 + 10 * (la - 32),
                       gradient=0.1)
    r = SVSRenderer({"enabled": True, "tile_path": str(tmp_path)})
    g = SVSGLRenderer(r)
    g._patch_origin = (32, -98)
    g._frame_lat_cos = math.cos(math.radians(32.5))
    return g


def test_level_array_matches_direct_sampling(glr):
    """Texel (i, j) must hold the elevation at exactly the ENU point
    origin + (j, i)*spacing, i.e. the same value the CPU sampler returns
    for the equivalent lat/lon."""
    spacing = 92.0
    size = 9
    o_e, o_n = 40000.0, 50000.0
    arr = glr._level_height_array(o_e, o_n, spacing, size)
    o_lat, o_lon = glr._patch_origin
    for (i, j) in ((0, 0), (3, 5), (8, 8)):
        lon = o_lon + (o_e + j * spacing) / (M_PER_DEG_LAT
                                             * glr._frame_lat_cos)
        lat = o_lat + (o_n + i * spacing) / M_PER_DEG_LAT
        elev, water = glr._parent._sample_elevations(
            np.array([[lat]]), np.array([[lon]]))
        assert not water[0, 0]
        assert arr[i, j] == pytest.approx(elev[0, 0], abs=1e-3)


def test_level_array_world_anchored_across_snap(glr):
    """A level snap moves the texture window by whole cells: texels that
    describe the same ground must be BIT-IDENTICAL before and after (this
    is what makes rebuilds invisible -- the Track 1b analogue of the
    phase-anchor fix)."""
    spacing = 185.0
    size = 12
    a = glr._level_height_array(30000.0, 60000.0, spacing, size)
    # snap 3 cells east, 2 north
    b = glr._level_height_array(30000.0 + 3 * spacing,
                                60000.0 + 2 * spacing, spacing, size)
    # overlap: a[2:, 3:] describes the same ground as b[:-2, :-3]
    assert np.array_equal(a[2:, 3:], b[:-2, :-3])


def test_level_array_water_sentinel(glr):
    """Ground outside any tile carries the -9999 sentinel."""
    # Far north of the written tiles (lat 35+): no tile -> sentinel.
    o_n = 3.2 * M_PER_DEG_LAT
    arr = glr._level_height_array(10000.0, o_n, 500.0, 8)
    assert (arr <= -1000.0).all()


def test_native_base_m(glr):
    """Innermost spacing derives from the finest tile present (1201 ->
    ~92.7 m)."""
    assert glr._native_base_m() == pytest.approx(
        M_PER_DEG_LAT / 1200.0, rel=1e-6)
