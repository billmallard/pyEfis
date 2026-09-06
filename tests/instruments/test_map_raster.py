"""MP5: pure-numpy even-odd scanline fill (briefs/map_gesture_perf_plan.md
section 4; pyEfis #98). No Qt import here on purpose -- fill_even_odd is a
standalone geometry primitive, so these pin the algorithm itself, ahead of
and independent from its wiring into TerrainLayer (test_moving_map.py)."""
import numpy as np

from pyefis.instruments.map.raster import fill_even_odd


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
    """The brief's guardrail: ALL rings of ALL polygons in range go
    into one fill_even_odd() call for throughput. Two unrelated,
    non-overlapping polygons in the same call must not interfere with
    each other's parity."""
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
