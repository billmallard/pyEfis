"""
Unit tests for the RD1 road-ribbon extrusion (pyefis.instruments.ai.road_ribbon,
issue #161, brief svs_roads_visual_plan.md section 3.1 / section 4 DoD).

Pure-numpy module — no GL, no SVSRenderer, no terrain tiles needed. Widths
are checked with ``out_dtype=np.float64`` so the assertions measure the
mitre/offset MATH to 1e-3 m, not the (much coarser, ~1 m) resolution a
float32 lat/lon round-trip gives — see the module docstring on
``extrude_ribbons``'s ``out_dtype`` for why production still uses float32.
"""
import math

import numpy as np
import pytest

from pyefis.instruments.ai import road_ribbon as rr

AC_LAT, AC_LON = 39.0, -107.0


def _width_between(a, b):
    """Great-circle-ish (flat-earth, fine at these scales) metre distance
    between two (lat, lon, elev_ft) rows, via the same ENU frame the
    module itself uses."""
    d_e = (a[1] - b[1]) * rr.M_PER_DEG_LAT * math.cos(math.radians(AC_LAT))
    d_n = (a[0] - b[0]) * rr.M_PER_DEG_LAT
    return float(math.hypot(d_e, d_n))


def _straight_ribbon(fclass="motorway", ppd=1_000_000.0, **kw):
    line = np.array([[39.00, -107.00], [39.01, -107.00]], dtype=np.float64)
    pts, offsets = rr.subdivide_polylines(
        [line], AC_LAT, AC_LON, subdivide_m=1e9, subdivide_nm=0.0)
    elev = np.zeros(pts.shape[0], dtype=np.float32)
    vis = np.ones(pts.shape[0], dtype=bool)
    return rr.extrude_ribbons(pts, offsets, [fclass], elev, vis,
                              AC_LAT, AC_LON, ppd, out_dtype=np.float64,
                              **kw)


class TestSubdivision:
    def test_short_segment_untouched(self):
        line = np.array([[39.00, -107.00], [39.0005, -107.00]],
                        dtype=np.float64)  # ~55 m < default 150 m
        pts, offsets = rr.subdivide_polylines([line], 39.00, -107.00)
        assert pts.shape[0] == 2
        assert list(offsets) == [0, 2]

    def test_long_segment_subdivided_to_expected_count(self):
        # ~2222.78 m at 0.02 deg lat -> ceil(2222.78 / 150) = 15 segments
        # -> 16 points.
        line = np.array([[39.00, -107.00], [39.02, -107.00]],
                        dtype=np.float64)
        pts, offsets = rr.subdivide_polylines(
            [line], 39.00, -107.00, subdivide_m=150.0, subdivide_nm=4.0)
        seg_len_m = 0.02 * rr.M_PER_DEG_LAT
        expected_segments = math.ceil(seg_len_m / 150.0)
        assert pts.shape[0] == expected_segments + 1
        assert offsets.tolist() == [0, expected_segments + 1]
        # Endpoints preserved exactly.
        assert pts[0].tolist() == line[0].tolist()
        np.testing.assert_allclose(pts[-1], line[-1])

    def test_far_polyline_not_subdivided(self):
        # ~2.2 km long, but centred ~3 deg (~180 NM) from the aircraft --
        # well outside subdivide_nm.
        far_line = np.array([[39.00, -110.00], [39.02, -110.00]],
                            dtype=np.float64)
        pts, offsets = rr.subdivide_polylines(
            [far_line], AC_LAT, AC_LON, subdivide_m=150.0,
            subdivide_nm=4.0)
        assert pts.shape[0] == 2

    def test_multiple_polylines_offsets_independent(self):
        near = np.array([[39.00, -107.00], [39.02, -107.00]])
        short = np.array([[39.00, -107.00], [39.001, -107.00]])
        pts, offsets = rr.subdivide_polylines(
            [near, short], AC_LAT, AC_LON, subdivide_m=150.0,
            subdivide_nm=4.0)
        n_near = offsets[1] - offsets[0]
        n_short = offsets[2] - offsets[1]
        assert n_near > 2          # subdivided
        assert n_short == 2        # short segment, untouched
        assert pts.shape[0] == offsets[-1]


class TestStraightSegmentWidth:
    def test_fill_width_exact_to_1e3_m(self):
        casing, fill = _straight_ribbon("motorway")
        w0 = _width_between(fill[0], fill[1])   # left_i0, right_i0
        w1 = _width_between(fill[2], fill[4])   # left_i1, right_i1
        assert abs(w0 - 16.0) < 1e-3
        assert abs(w1 - 16.0) < 1e-3

    def test_casing_width_is_class_width_plus_2x_casing_m(self):
        casing, fill = _straight_ribbon("motorway", casing_m=2.5)
        cw0 = _width_between(casing[0], casing[1])
        assert abs(cw0 - (16.0 + 2 * 2.5)) < 1e-3

    def test_unknown_class_uses_default_width(self):
        casing, fill = _straight_ribbon("cycleway")
        w0 = _width_between(fill[0], fill[1])
        assert abs(w0 - rr.DEFAULT_UNKNOWN_WIDTH_M) < 1e-3

    @pytest.mark.parametrize("fclass,expected", [
        ("motorway", 16.0), ("trunk", 13.0), ("primary", 11.0),
        ("secondary", 8.0), ("motorway_link", 7.0), ("trunk_link", 7.0),
        ("primary_link", 6.0), ("secondary_link", 6.0),
    ])
    def test_class_width_table(self, fclass, expected):
        casing, fill = _straight_ribbon(fclass)
        assert abs(_width_between(fill[0], fill[1]) - expected) < 1e-3


class TestMitreJoin:
    def test_90_degree_corner_offset_and_continuity(self):
        line = np.array([[39.00, -107.00], [39.01, -107.00],
                         [39.01, -106.99]], dtype=np.float64)
        pts, offsets = rr.subdivide_polylines(
            [line], AC_LAT, AC_LON, subdivide_m=1e9, subdivide_nm=0.0)
        elev = np.zeros(pts.shape[0], dtype=np.float32)
        vis = np.ones(pts.shape[0], dtype=bool)
        casing, fill = rr.extrude_ribbons(
            pts, offsets, ["motorway"], elev, vis, AC_LAT, AC_LON,
            1_000_000.0, out_dtype=np.float64)
        # Segment 0 is fill[0:6], segment 1 is fill[6:12]. The corner
        # vertex (index 1) is left_i1 of segment 0 and left_i0 of
        # segment 1 -- a mitred join means both segments compute the
        # SAME offset point there (no gap/overlap at the corner).
        corner_seg0 = fill[2]
        corner_seg1 = fill[6]
        assert _width_between(corner_seg0, corner_seg1) < 1e-6
        # A 90-degree mitre scales the half-width by 1/cos(45) = sqrt(2).
        true_corner = pts[1]
        gap = _width_between(corner_seg0, true_corner)
        assert abs(gap - 8.0 * math.sqrt(2)) < 1e-3

    def test_straight_line_no_mitre_scaling(self):
        # A dead-straight interior vertex (theta = 0) must NOT widen.
        line = np.array([[39.00, -107.00], [39.01, -107.00],
                         [39.02, -107.00]], dtype=np.float64)
        pts, offsets = rr.subdivide_polylines(
            [line], AC_LAT, AC_LON, subdivide_m=1e9, subdivide_nm=0.0)
        elev = np.zeros(pts.shape[0], dtype=np.float32)
        vis = np.ones(pts.shape[0], dtype=bool)
        casing, fill = rr.extrude_ribbons(
            pts, offsets, ["motorway"], elev, vis, AC_LAT, AC_LON,
            1_000_000.0, out_dtype=np.float64)
        interior_left = fill[6]     # left_i0 of segment 1 == vertex 1
        assert abs(_width_between(interior_left, pts[1]) - 8.0) < 1e-3


class TestHairpinClamp:
    def test_near_180_degree_reversal_clamps_to_2x_width(self):
        # A switchback: the path nearly doubles back on itself at
        # vertex 1 (interior angle close to 180 degrees).
        line = np.array([[39.00, -107.00], [39.01, -107.00],
                         [39.0001, -107.00]], dtype=np.float64)
        pts, offsets = rr.subdivide_polylines(
            [line], AC_LAT, AC_LON, subdivide_m=1e9, subdivide_nm=0.0)
        elev = np.zeros(pts.shape[0], dtype=np.float32)
        vis = np.ones(pts.shape[0], dtype=bool)
        casing, fill = rr.extrude_ribbons(
            pts, offsets, ["motorway"], elev, vis, AC_LAT, AC_LON,
            1_000_000.0, out_dtype=np.float64)
        assert np.all(np.isfinite(fill))
        assert np.all(np.isfinite(casing))
        corner = fill[2]
        gap = _width_between(corner, pts[1])
        # Half-width is 8 m; the clamp caps the mitre scale at 2x.
        assert gap <= 16.0 + 1e-6

    def test_exact_180_degree_reversal_does_not_divide_by_zero(self):
        # The two adjacent segment normals cancel exactly -- the
        # degenerate case the clamp exists for.
        line = np.array([[39.00, -107.00], [39.01, -107.00],
                         [39.00, -107.00]], dtype=np.float64)
        pts, offsets = rr.subdivide_polylines(
            [line], AC_LAT, AC_LON, subdivide_m=1e9, subdivide_nm=0.0)
        elev = np.zeros(pts.shape[0], dtype=np.float32)
        vis = np.ones(pts.shape[0], dtype=bool)
        casing, fill = rr.extrude_ribbons(
            pts, offsets, ["motorway"], elev, vis, AC_LAT, AC_LON,
            1_000_000.0, out_dtype=np.float64)
        assert np.all(np.isfinite(fill))
        assert np.all(np.isfinite(casing))


class TestScreenSpaceFloor:
    def test_far_vertex_widens_past_class_width(self):
        far_line = np.array([[39.00, -107.00], [39.00, -106.5]],
                            dtype=np.float64)
        pts, offsets = rr.subdivide_polylines(
            [far_line], AC_LAT, AC_LON, subdivide_m=1e9, subdivide_nm=0.0)
        elev = np.zeros(pts.shape[0], dtype=np.float32)
        vis = np.ones(pts.shape[0], dtype=bool)
        casing, fill = rr.extrude_ribbons(
            pts, offsets, ["secondary"], elev, vis, AC_LAT, AC_LON,
            pixels_per_deg=24.0, min_px=1.5, out_dtype=np.float64)
        w_near = _width_between(fill[0], fill[1])     # vertex at the a/c
        w_far = _width_between(fill[2], fill[4])      # ~23 NM away
        assert abs(w_near - 8.0) < 1e-3               # class width, no floor
        assert w_far > 8.0                            # floor overrides

    def test_floor_matches_closed_form(self):
        far_line = np.array([[39.00, -107.00], [39.00, -106.5]],
                            dtype=np.float64)
        pts, offsets = rr.subdivide_polylines(
            [far_line], AC_LAT, AC_LON, subdivide_m=1e9, subdivide_nm=0.0)
        elev = np.zeros(pts.shape[0], dtype=np.float32)
        vis = np.ones(pts.shape[0], dtype=bool)
        ppd = 24.0
        min_px = 1.5
        casing, fill = rr.extrude_ribbons(
            pts, offsets, ["secondary"], elev, vis, AC_LAT, AC_LON,
            pixels_per_deg=ppd, min_px=min_px, out_dtype=np.float64)
        w_far = _width_between(fill[2], fill[4])
        lat_cos = math.cos(math.radians(AC_LAT))
        e = (pts[1, 1] - AC_LON) * rr.M_PER_DEG_LAT * lat_cos
        n = (pts[1, 0] - AC_LAT) * rr.M_PER_DEG_LAT
        dist_m = math.hypot(e, n)
        expected = dist_m * math.tan(math.radians(min_px / ppd))
        assert abs(w_far - expected) < 1e-2


class TestLOSGaps:
    def test_masked_endpoint_drops_its_segments_only(self):
        # 4 collinear vertices -> 3 segments; mask vertex 2 (index 2).
        line = np.array([[39.00, -107.00], [39.01, -107.00],
                         [39.02, -107.00], [39.03, -107.00]],
                        dtype=np.float64)
        pts, offsets = rr.subdivide_polylines(
            [line], AC_LAT, AC_LON, subdivide_m=1e9, subdivide_nm=0.0)
        elev = np.zeros(pts.shape[0], dtype=np.float32)
        vis = np.array([True, True, False, True])
        casing, fill = rr.extrude_ribbons(
            pts, offsets, ["motorway"], elev, vis, AC_LAT, AC_LON,
            1_000_000.0, out_dtype=np.float64)
        # Only segment (0, 1) has both endpoints visible.
        assert fill.shape[0] == 6
        assert casing.shape[0] == 6

    def test_all_masked_returns_none(self):
        line = np.array([[39.00, -107.00], [39.01, -107.00]],
                        dtype=np.float64)
        pts, offsets = rr.subdivide_polylines(
            [line], AC_LAT, AC_LON, subdivide_m=1e9, subdivide_nm=0.0)
        elev = np.zeros(pts.shape[0], dtype=np.float32)
        vis = np.zeros(pts.shape[0], dtype=bool)
        casing, fill = rr.extrude_ribbons(
            pts, offsets, ["motorway"], elev, vis, AC_LAT, AC_LON,
            1_000_000.0, out_dtype=np.float64)
        assert casing is None
        assert fill is None


class TestBudgetTrim:
    def test_under_budget_keeps_everything(self):
        lengths = np.array([10, 10, 10])
        keep = rr.trim_to_vertex_budget(
            lengths, ["motorway", "trunk", "motorway_link"],
            np.array([False, True, True]), max_output_vertices=1_000_000)
        assert keep.all()

    def test_drops_far_links_before_far_trunks(self):
        lengths = np.array([1000, 500, 200, 800, 400, 50], dtype=np.int64)
        fclasses = ["motorway_link", "trunk_link", "primary_link",
                   "trunk", "trunk", "motorway"]
        is_far = np.array([True, True, True, True, True, False])
        out_each = 6 * (lengths - 1)
        budget = int(out_each.sum() * 0.5)
        keep = rr.trim_to_vertex_budget(lengths, fclasses, is_far, budget)
        assert int(out_each[keep].sum()) <= budget
        assert keep[5]                       # near motorway never dropped
        dropped_links = int((~keep[:3]).sum())
        dropped_trunks = int((~keep[3:5]).sum())
        assert dropped_links >= 1
        if dropped_trunks > 0:
            assert dropped_links == 3        # every link gone first

    def test_near_tier_never_dropped_even_when_over_budget(self):
        lengths = np.array([100_000, 100_000])
        fclasses = ["motorway_link", "motorway_link"]
        is_far = np.array([False, False])    # both near-tier
        keep = rr.trim_to_vertex_budget(lengths, fclasses, is_far,
                                        max_output_vertices=1)
        assert keep.all()

    def test_apply_keep_mask_rebuilds_concatenated_array(self):
        lengths = np.array([2, 3, 2])
        offsets = rr._polyline_offsets(lengths)
        pts = np.arange(offsets[-1] * 2, dtype=np.float64).reshape(-1, 2)
        fclasses = ["a", "b", "c"]
        keep = np.array([True, False, True])
        new_pts, new_offsets, new_fclasses = rr.apply_keep_mask(
            pts, offsets, fclasses, keep)
        assert new_fclasses == ["a", "c"]
        assert new_offsets.tolist() == [0, 2, 4]
        np.testing.assert_array_equal(new_pts[:2], pts[0:2])
        np.testing.assert_array_equal(new_pts[2:4], pts[5:7])


class TestHexColor:
    def test_parses_hash_prefixed(self):
        assert rr.hex_to_rgba01("#b8b4ad") == pytest.approx(
            (0xb8 / 255, 0xb4 / 255, 0xad / 255, 1.0))

    def test_parses_without_hash(self):
        assert rr.hex_to_rgba01("4a4a4a") == pytest.approx(
            (0x4a / 255, 0x4a / 255, 0x4a / 255, 1.0))

    def test_malformed_falls_back_to_default(self):
        assert rr.hex_to_rgba01("not-a-color",
                                default=(1, 0, 0, 1)) == (1, 0, 0, 1)
