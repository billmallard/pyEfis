"""Pure-geometry unit tests for the AER-1805 horizon-off-scale trigger.

No QApplication, no widget construction, no rendering, no pixel scanning --
this pins the closed-form contract:

    (pitchDegreesShown, horizon_position, pitch) -> (horizon on/off glass,
                                                       chevrons on/off)

the same standard AER-1802 holds its own implementing PR to.
"""

import pytest

from pyefis.instruments.ai.ai_widget import AI


class _FakeAI:
    """Duck-types only the attributes _horizon_off_glass reads, plus the
    staticmethod it calls on self (Python resolves unbound calls through
    the instance's class, so a plain object needs it too)."""

    unusualPitchHighDeg = 30
    unusualPitchLowDeg = -20
    _horizon_exit_pitch = staticmethod(AI._horizon_exit_pitch)

    def __init__(self, pitch_degrees_shown, horizon_position, pitch_angle):
        self.pitchDegreesShown = pitch_degrees_shown
        self.horizon_position = horizon_position
        self._pitchAngle = pitch_angle


def _chevrons_fire(pitch_degrees_shown, horizon_position, pitch_angle):
    fake = _FakeAI(pitch_degrees_shown, horizon_position, pitch_angle)
    horizon_off = AI._horizon_off_glass(fake)
    fires = (pitch_angle > fake.unusualPitchHighDeg
             or pitch_angle < fake.unusualPitchLowDeg
             or horizon_off)
    return horizon_off, fires


class TestHorizonExitPitch:
    """AC 23.1311-1C 8.5(b): where the pitch=0 horizon line leaves the
    glass, as a function of the live geometry rather than a constant."""

    @pytest.mark.parametrize(
        "pitch_degrees_shown, horizon_position, expected_top, expected_bottom",
        [
            (30, 68, -9.6, 20.4),   # shipped bench config (issue table)
            (50, 68, -16.0, 34.0),  # AER-1799 candidate (issue table)
            (50, 50, -25.0, 25.0),  # centred (issue table)
        ],
    )
    def test_matches_issue_table(self, pitch_degrees_shown, horizon_position,
                                  expected_top, expected_bottom):
        top, bottom = AI._horizon_exit_pitch(horizon_position,
                                              pitch_degrees_shown)
        assert top == pytest.approx(expected_top)
        assert bottom == pytest.approx(expected_bottom)

    def test_centred_horizon_is_symmetric(self):
        top, bottom = AI._horizon_exit_pitch(50, 40)
        assert top == pytest.approx(-20.0)
        assert bottom == pytest.approx(20.0)


class TestChevronTrigger:
    """Chevrons must engage no later than the horizon leaving the glass,
    at whatever horizon_position / pitchDegreesShown the panel runs."""

    def test_shipped_config_window_is_closed(self):
        # AER-1805: at pitchDegreesShown=30, horizon_position=68 the horizon
        # is gone by -9.6 deg but the old fixed -20 deg constant left a
        # 10.4 deg window with the horizon reference lost and no off-scale
        # cue. This is the row that fails on unfixed code (see
        # test_fails_on_constant_only_trigger below).
        horizon_off, fires = _chevrons_fire(
            pitch_degrees_shown=30, horizon_position=68, pitch_angle=-9.6)
        assert horizon_off is True
        assert fires is True

        # Mid-window: horizon already off-glass, well short of -20.
        horizon_off, fires = _chevrons_fire(
            pitch_degrees_shown=30, horizon_position=68, pitch_angle=-15.0)
        assert horizon_off is True
        assert fires is True

    def test_fails_on_constant_only_trigger(self):
        # Reproduces the pre-fix trigger (constants only, no geometry) to
        # prove this row is a real regression test, not a tautology: at the
        # shipped 30/68 config and pitch=-15 the horizon has already left
        # the glass (-9.6), but the old code's constant-only condition
        # stayed silent all the way to -20.
        pitch_angle = -15.0
        old_fires = pitch_angle > 30 or pitch_angle < -20
        assert old_fires is False
        horizon_off, new_fires = _chevrons_fire(
            pitch_degrees_shown=30, horizon_position=68,
            pitch_angle=pitch_angle)
        assert horizon_off is True
        assert new_fires is True

    def test_aer_1799_candidate_window(self):
        # pitchDegreesShown=50, horizon_position=68: horizon gone at -16,
        # constant fires at -20 -- a narrower but still real 4 deg gap.
        horizon_off, fires = _chevrons_fire(
            pitch_degrees_shown=50, horizon_position=68, pitch_angle=-17.0)
        assert horizon_off is True
        assert fires is True

    def test_centred_horizon_constant_still_governs(self):
        # pitchDegreesShown=50, horizon_position=50: horizon does not leave
        # the glass until -25, but the AC 25-11B constant (-20) already
        # covers the unusual-attitude regime first -- no window, and the
        # geometric term must not suppress that earlier, still-valid cue.
        horizon_off, fires = _chevrons_fire(
            pitch_degrees_shown=50, horizon_position=50, pitch_angle=-22.0)
        assert horizon_off is False
        assert fires is True

    def test_normal_attitude_no_chevrons(self):
        horizon_off, fires = _chevrons_fire(
            pitch_degrees_shown=30, horizon_position=68, pitch_angle=5.0)
        assert horizon_off is False
        assert fires is False
