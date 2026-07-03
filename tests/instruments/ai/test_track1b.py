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


def test_level_array_water_sentinel(glr, tmp_path):
    """A missing tile INSIDE the patch carries the -9999 sentinel; ground
    beyond the patch bounds clamps to the edge (old CLAMP_TO_EDGE look)."""
    import shutil
    # Remove the NE tile (33, -97) and rebuild the renderer's cache view.
    (tmp_path / "N33" / "N33W097.hgt").unlink()
    glr._parent.cache._cache.clear()
    glr._parent.cache._order.clear()
    # Sample inside the missing tile's quadrant (lat 33.5, lon -96.5-ish).
    o_e = 1.4 * M_PER_DEG_LAT * glr._frame_lat_cos
    o_n = 1.5 * M_PER_DEG_LAT
    arr = glr._level_height_array(o_e, o_n, 200.0, 8)
    assert (arr <= -1000.0).all()
    # Beyond the patch: clamped, so finite (edge values), never garbage.
    far = glr._level_height_array(o_e, 3.5 * M_PER_DEG_LAT, 500.0, 8)
    assert np.isfinite(far).all()


def test_native_base_m(glr):
    """Innermost spacing derives from the finest tile present (1201 ->
    ~92.7 m)."""
    assert glr._native_base_m() == pytest.approx(
        M_PER_DEG_LAT / 1200.0, rel=1e-6)


# ---------------------------------------------------------------------------
# Clipmap index template: checkerboard diagonals (ridge-crest sawtooth fix).
# _build_clipmap_template only touches self._parent._clip_cells, so a
# SimpleNamespace stands in -- no GL context needed.
# ---------------------------------------------------------------------------

_TN = 8   # template test grid size


def _template(n=_TN):
    import types
    fake = types.SimpleNamespace(
        _parent=types.SimpleNamespace(_clip_cells=n))
    return SVSGLRenderer._build_clipmap_template(fake)


def _quads(idx):
    """Index buffer -> (quads, 2 triangles, 3 vertex ids)."""
    return idx.reshape(-1, 2, 3)


def test_template_checkerboard_diagonals():
    """Each parity variant splits quads with (row+col+parity) even along
    v10-v01 (the historical diagonal) and odd quads along v00-v11."""
    n, m = _TN, _TN + 1
    verts, full, _ = _template()
    assert verts.shape == (m * m, 2)
    for parity in (0, 1):
        quads = _quads(full[parity])
        assert quads.shape[0] == n * n
        for q, (t1, t2) in enumerate(quads):
            a, b = divmod(q, n)
            v00 = a * m + b
            v10 = (a + 1) * m + b
            v01 = a * m + b + 1
            v11 = (a + 1) * m + b + 1
            if (a + b + parity) % 2 == 0:
                assert list(t1) == [v00, v10, v01]
                assert list(t2) == [v10, v11, v01]
            else:
                assert list(t1) == [v00, v10, v11]
                assert list(t2) == [v00, v11, v01]


def test_template_checkerboard_world_anchored():
    """The draw loop selects the variant by origin cell parity, so a
    one-cell snap (which flips origin parity AND shifts the template
    quad covering a given world cell by one) must leave the WORLD
    diagonal unchanged: variant 1 at column b-1 == variant 0 at b."""
    n, m = _TN, _TN + 1
    _, full, _ = _template()
    q0 = _quads(full[0]).reshape(n, n, 2, 3)
    q1 = _quads(full[1]).reshape(n, n, 2, 3)

    def split_is_alt(pair, a, b):
        shared = set(pair[0]) & set(pair[1])
        return shared == {a * m + b, (a + 1) * m + b + 1}

    for a in range(n):
        for b in range(1, n):
            # Same world cell, origins one cell apart in east:
            # template (a, b) under variant 0 vs (a, b-1) under
            # variant 1. The vertex ids differ; the split must not.
            assert (split_is_alt(q0[a, b], a, b)
                    == split_is_alt(q1[a, b - 1], a, b - 1))


def test_template_winding_consistent():
    """Both split directions keep the original template winding."""
    verts, full, annulus = _template()
    for idx in (*full, *annulus):
        tri = verts[idx.reshape(-1, 3)]
        e1 = tri[:, 1] - tri[:, 0]
        e2 = tri[:, 2] - tri[:, 0]
        cross = e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]
        assert (cross < 0).all()


def test_template_annulus_skips_hole():
    """Annulus variants drop exactly the centre-hole quads."""
    n, m = _TN, _TN + 1
    _, _, annulus = _template()
    h = n // 4 - 1
    lo, hi = n // 2 - h, n // 2 + h
    for parity in (0, 1):
        quads = _quads(annulus[parity])
        assert quads.shape[0] == n * n - (2 * h) ** 2
        # Both split patterns start triangle 1 at v00 -> quad identity.
        cells = {divmod(int(t1[0]), m) for t1, _ in quads}
        for a in range(n):
            for b in range(n):
                inside = lo <= a < hi and lo <= b < hi
                assert ((a, b) in cells) == (not inside)
