"""MP5: pure-numpy even-odd scanline fill (briefs/map_gesture_perf_plan.md
section 4; pyEfis #98). No Qt import here on purpose -- fill_even_odd is a
standalone geometry primitive, so these pin the algorithm itself, ahead of
and independent from its wiring into TerrainLayer (test_moving_map.py)."""
import numpy as np

from pyefis.instruments.map.raster import fill_even_odd, fill_union


def _square(cx, cy, half):
    return np.array([[cx - half, cy - half], [cx + half, cy - half],
                     [cx + half, cy + half], [cx - half, cy + half]],
                    dtype=np.float64)


def test_fill_even_odd_single_square_exact():
    """A square with integer corners fills exactly its interior pixels
    (pixel (i, j) covers [i, i+1) x [j, j+1); the shared-edge half-open
    scanline test must not bleed one row/column past the boundary)."""
    n = 10
    mask = fill_even_odd([_square(5, 5, 3)], n)   # corners (2,2)-(8,8)
    expected = np.zeros((n, n), dtype=bool)
    expected[2:8, 2:8] = True
    assert np.array_equal(mask, expected)


def test_fill_even_odd_island_hole():
    """#44: a ring nested inside another, both passed to ONE
    fill_even_odd() call, must resolve via the even-odd rule -- the
    inner ring is unpainted, matching QPainterPath's OddEvenFill."""
    n = 10
    outer = _square(5, 5, 4)     # corners (1,1)-(9,9)
    hole = _square(5, 5, 2)      # corners (3,3)-(7,7)
    mask = fill_even_odd([outer, hole], n)
    expected = np.zeros((n, n), dtype=bool)
    expected[1:9, 1:9] = True
    expected[3:7, 3:7] = False
    assert np.array_equal(mask, expected)


def test_fill_even_odd_disjoint_polygons_share_one_accumulator():
    """The brief's guardrail: disjoint polygons can share one
    fill_even_odd() accumulator for throughput -- two unrelated,
    non-overlapping polygons in the same call must not interfere with
    each other's parity. (Overlapping ones can: see fill_union below.)"""
    n = 14
    a = _square(3, 3, 2)     # corners (1,1)-(5,5)
    b = _square(10, 10, 2)   # corners (8,8)-(12,12)
    mask = fill_even_odd([a, b], n)
    expected = np.zeros((n, n), dtype=bool)
    expected[1:5, 1:5] = True
    expected[8:12, 8:12] = True
    assert np.array_equal(mask, expected)


def test_fill_even_odd_nested_lake_on_island():
    """A pond (outer ring) sitting inside an island (hole) inside a
    lake (outer ring): three nested rings in one call must alternate
    water/land/water/land as the even-odd count increments per ring
    crossed, the same nesting #44's build-side fix exercises."""
    n = 20
    lake = _square(10, 10, 8)    # corners (2,2)-(18,18):  water
    island = _square(10, 10, 5)  # corners (5,5)-(15,15):  land
    pond = _square(10, 10, 2)    # corners (8,8)-(12,12):  water
    mask = fill_even_odd([lake, island, pond], n)
    assert mask[10, 10]              # pond centre: water (3 rings deep, odd)
    assert not mask[6, 10]           # island band: land (2 rings deep, even)
    assert mask[3, 10]               # lake band: water (1 ring deep, odd)
    assert not mask[0, 10]           # outside everything: land


def test_fill_even_odd_empty_input():
    n = 8
    assert fill_even_odd([], n).sum() == 0
    assert fill_even_odd([np.zeros((2, 2))], n).sum() == 0   # < 3 verts


def test_fill_even_odd_vertex_on_scanline_not_double_counted():
    """A vertex landing exactly on a pixel-centre scanline (yc = j + 0.5)
    is shared by two edges; the half-open crossing test (min <= yc <
    max) must count it once, not zero or twice, or the shared row would
    mis-parity every pixel to its right."""
    n = 10
    # Triangle with an apex exactly on y = 4.5 (a scanline centre).
    tri = np.array([[2.0, 1.0], [8.0, 4.5], [2.0, 8.0]], dtype=np.float64)
    mask = fill_even_odd([tri], n)
    # Row 4 (yc=4.5) must show a single filled span from the two edges
    # meeting at the apex, not a gap (double count -> even parity) or a
    # spurious extra crossing.
    row = mask[4]
    assert row.any()
    filled_cols = np.nonzero(row)[0]
    assert list(filled_cols) == list(
        range(filled_cols[0], filled_cols[-1] + 1))   # contiguous


# ---------------------------------------------------------------------------
# AER-4596: fill_union -- even-odd within a polygon, union across polygons
# ---------------------------------------------------------------------------

def test_fill_union_overlap_is_covered():
    """Two polygons sharing pixels -- an OSM split-ocean seam sliver, or
    an NE lake over its OSM twin -- cover the overlap. One shared
    even-odd accumulator cancels it to land; fill_even_odd still does,
    which is why the map no longer feeds it separate polygons."""
    n = 12
    a = _square(4, 6, 3)     # corners (1,3)-(7,9)
    b = _square(7, 6, 3)     # corners (4,3)-(10,9): cols 4-6 overlap
    expected = np.zeros((n, n), dtype=bool)
    expected[3:9, 1:10] = True
    assert np.array_equal(fill_union([[a], [b]], n), expected)
    assert not fill_even_odd([a, b], n)[5, 5]   # the defect, pinned


def test_fill_union_island_hole_cut_beside_overlap():
    """Even-odd still applies WITHIN a polygon: a lake's island hole stays
    land while a second polygon overlaps the lake's water elsewhere."""
    n = 20
    outer = _square(8, 10, 6)     # corners (2,4)-(14,16)
    hole = _square(6, 10, 2)      # corners (4,8)-(8,12)
    other = _square(14, 10, 3)    # corners (11,7)-(17,13): overlaps outer
    mask = fill_union([[outer, hole], [other]], n)
    expected = np.zeros((n, n), dtype=bool)
    expected[4:16, 2:14] = True
    expected[8:12, 4:8] = False
    expected[7:13, 11:17] = True
    assert np.array_equal(mask, expected)


def test_fill_union_equals_or_of_whole_image_fills():
    """The per-polygon bbox window (and the shared call for isolated
    windows) is exact: fill_union equals the OR of one whole-image
    fill_even_odd per polygon, for random overlapping, disjoint and
    off-image polygons with generic (non-integer) vertices."""
    rng = np.random.default_rng(4596)
    n = 64
    for _ in range(40):
        polys = []
        for _ in range(rng.integers(1, 9)):
            cx, cy = rng.uniform(-10, n + 10, 2)
            r = rng.uniform(1, 25)
            k = int(rng.integers(3, 12))
            ang = np.sort(rng.uniform(0, 2 * np.pi, k))
            rad = r * rng.uniform(0.4, 1.0, k)
            outer = np.stack((cx + rad * np.cos(ang),
                              cy + rad * np.sin(ang)), axis=1)
            rings = [outer]
            if rng.random() < 0.4:
                rings.append(_square(cx, cy, r * 0.2))
            polys.append(rings)
        expected = np.zeros((n, n), dtype=bool)
        for rings in polys:
            expected |= fill_even_odd(rings, n)
        assert np.array_equal(fill_union(polys, n), expected)


def test_fill_union_empty_input():
    n = 8
    assert fill_union([], n).sum() == 0
    assert fill_union([[np.zeros((2, 2))]], n).sum() == 0
    assert fill_union([[_square(-20, -20, 3)]], n).sum() == 0   # off image
