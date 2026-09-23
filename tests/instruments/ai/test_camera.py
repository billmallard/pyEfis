"""Unit tests for the unified SVS camera (camera.py, plan P3)."""

import math
import pytest

from pyefis.instruments.ai.camera import (
    view_projection, project, M_PER_DEG_LAT, DEG_PER_RAD, EARTH_CURVATURE,
)

PPD = 12.0
W, H = 800, 600


def _vp(heading=0.0, pitch=0.0, roll=0.0, ac=(0.0, 0.0, 300.0)):
    return view_projection(ac[0], ac[1], ac[2], heading, pitch, roll,
                           PPD, W, H)


class TestViewProjection:
    def test_point_dead_ahead_at_eye_level_is_screen_centre(self):
        vp = _vp()
        x, y, w = project(vp, 0.0, 5000.0, 300.0)
        assert w == pytest.approx(5000.0)
        assert x == pytest.approx(0.0, abs=1e-9)
        assert y == pytest.approx(0.0, abs=1e-9)

    def test_point_behind_has_negative_w(self):
        vp = _vp()
        _, _, w = project(vp, 0.0, -5000.0, 300.0)
        assert w < 0

    def test_small_angle_matches_pixels_per_deg(self):
        # A point 1 degree right of the nose must land ppd pixels right
        # of centre (the AI's screen-scale contract).
        vp = _vp()
        d = 5000.0
        r = d * math.tan(math.radians(1.0))
        x, _, w = project(vp, r, d, 300.0)
        px = (x / w) * (W / 2.0)
        assert px == pytest.approx(PPD * 1.0, rel=1e-3)

    def test_heading_rotates_world(self):
        # Heading 090: a point due east is dead ahead.
        vp = _vp(heading=90.0)
        x, y, w = project(vp, 5000.0, 0.0, 300.0)
        assert w == pytest.approx(5000.0)
        assert x == pytest.approx(0.0, abs=1e-9)

    def test_pitch_up_moves_ground_point_down_screen(self):
        x0, y0, w0 = project(_vp(), 0.0, 5000.0, 0.0)      # ground ahead
        x1, y1, w1 = project(_vp(pitch=10.0), 0.0, 5000.0, 0.0)
        assert y1 / w1 < y0 / w0   # NDC y is positive-up

    def test_roll_rotates_screen(self):
        # Right-of-nose point, 30 deg right roll: screen x shrinks by
        # cos(30), picks up a y component.
        vp = _vp(roll=30.0)
        d, r = 5000.0, 500.0
        x, y, w = project(vp, r, d, 300.0)
        x_flat, _, _ = project(_vp(), r, d, 300.0)
        assert x == pytest.approx(x_flat * math.cos(math.radians(30.0)),
                                  rel=1e-6)
        assert y != pytest.approx(0.0)

    def test_translation_is_aircraft_relative(self):
        vp = view_projection(1000.0, 2000.0, 300.0, 0.0, 0.0, 0.0,
                             PPD, W, H)
        x, y, w = project(vp, 1000.0, 7000.0, 300.0)
        assert w == pytest.approx(5000.0)
        assert x == pytest.approx(0.0, abs=1e-9)

    def test_curvature_constant_drops_about_right(self):
        # ~50 NM: the geometric drop is ~676 m (2,200 ft).
        d = 50.0 * 1852.0
        assert d * d * EARTH_CURVATURE == pytest.approx(672.7, rel=0.01)


class TestAzimuthalExtentFollowsViewportAspect:
    """AER-1478: there is no configured forward-fan angle -- the SVS
    azimuthal extent is whatever the AI viewport's aspect ratio implies
    via pixelsPerDeg (ai_widget.py:488 sets
    ``pixelsPerDeg = height / pitchDegreesShown``; camera.py applies that
    same scale to x). Pin the relation directly against view_projection
    so a later edit to the screen-scale factors fails this test loudly
    instead of silently drifting, across more than one viewport aspect.

    This class exercises view_projection's DEFAULT coupling, i.e. what
    happens when a caller leaves ``pixels_per_deg_h`` unset (as every call
    site did before AER-1973). svs_gl.py's actual call site no longer does
    that -- see TestTerrainHFOVPinnedAcrossPitchDegreesShown below for the
    live, pinned behaviour.
    """

    PITCH_DEGREES_SHOWN = 30.0

    @pytest.mark.parametrize("w, h", [(800, 480), (1024, 600)])
    def test_column_matches_w2_plus_theta_times_ppd(self, w, h):
        ppd = h / self.PITCH_DEGREES_SHOWN
        vp = view_projection(0.0, 0.0, 300.0, 0.0, 0.0, 0.0, ppd, w, h)
        theta_deg = 2.0
        d = 5000.0
        e = d * math.tan(math.radians(theta_deg))
        x, _, wgt = project(vp, e, d, 300.0)
        col = w / 2.0 + (x / wgt) * (w / 2.0)
        assert col == pytest.approx(w / 2.0 + theta_deg * ppd, rel=1e-3)

    @pytest.mark.parametrize("w, h, expect_hfov_deg", [
        (800, 480, 50.0),
        (1024, 600, 51.2),
    ])
    def test_half_fan_equals_w2_over_ppd(self, w, h, expect_hfov_deg):
        # Half-fan (deg from the nose to the screen edge) = (W/2) / ppd,
        # i.e. HFOV_deg = viewport_width * pitchDegreesShown / viewport_height.
        # No fixed fan angle exists anywhere in the renderer (fov_deg was
        # dead config, deleted in AER-1478) -- this is the only azimuth cull.
        ppd = h / self.PITCH_DEGREES_SHOWN
        half_fan_deg = (w / 2.0) / ppd
        assert half_fan_deg * 2.0 == pytest.approx(expect_hfov_deg, rel=1e-6)

    def test_half_fan_differs_across_aspect(self):
        # Same pitchDegreesShown, different aspect ratios -> different
        # azimuthal extent. If this ever came out equal, HFOV would once
        # again be a fixed constant instead of aspect-driven.
        ppd_a = 480 / self.PITCH_DEGREES_SHOWN
        ppd_b = 600 / self.PITCH_DEGREES_SHOWN
        half_fan_a = (800 / 2.0) / ppd_a
        half_fan_b = (1024 / 2.0) / ppd_b
        assert half_fan_a != pytest.approx(half_fan_b)


class TestTerrainHFOVPinnedAcrossPitchDegreesShown:
    """AER-1973 raises the AI widget's default pitchDegreesShown 30 -> 50
    (more ladder gain, taller terrain view vertically) without widening the
    terrain horizontally -- svs_gl.py's ``_update_camera`` now always
    passes an explicit ``pixels_per_deg_h`` pinned to
    ``h / _TERRAIN_HFOV_PITCH_DEG`` (AER-1806's decouple hook, wired here
    for the first time). This is a pure-arithmetic pin on
    view_projection's sx term (terrain horizontal clip-space scale) so a
    future pitchDegreesShown edit that forgets to keep passing
    pixels_per_deg_h fails HERE, immediately, instead of silently
    widening the terrain picture the way AER-1799's evaluated and
    rejected Option 1 coupling did. No rendered frame involved.
    """

    def test_sx_unchanged_as_live_pitch_degrees_shown_varies(self):
        from pyefis.instruments.ai.svs_gl import _TERRAIN_HFOV_PITCH_DEG

        w, h = 800, 480
        pixels_per_deg_h = h / _TERRAIN_HFOV_PITCH_DEG

        sx_values = [
            view_projection(0.0, 0.0, 300.0, 0.0, 0.0, 0.0,
                            h / pitch_degrees_shown, w, h,
                            pixels_per_deg_h=pixels_per_deg_h)[0, 0]
            for pitch_degrees_shown in (30.0, 50.0, 60.0)
        ]
        assert sx_values[0] == pytest.approx(sx_values[1])
        assert sx_values[1] == pytest.approx(sx_values[2])

    def test_sx_matches_pinned_hfov_not_live_ppd(self):
        from pyefis.instruments.ai.svs_gl import _TERRAIN_HFOV_PITCH_DEG

        w, h = 800, 480
        live_ppd = h / 50.0  # today's live pitchDegreesShown
        pinned_ppd_h = h / _TERRAIN_HFOV_PITCH_DEG

        vp = view_projection(0.0, 0.0, 300.0, 0.0, 0.0, 0.0,
                             live_ppd, w, h, pixels_per_deg_h=pinned_ppd_h)
        expected_sx = DEG_PER_RAD * pinned_ppd_h * 2.0 / w
        unpinned_sx = DEG_PER_RAD * live_ppd * 2.0 / w
        assert vp[0, 0] == pytest.approx(expected_sx)
        assert vp[0, 0] != pytest.approx(unpinned_sx)
