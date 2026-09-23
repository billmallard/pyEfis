"""Pure-geometry pin for the pitch ladder's visible extent (AER-1806).

No rendering, no image thresholds, no pixel scanning -- this exists
specifically to catch the AER-1799 v1 eval build's class of bug (a
hardcoded ``visiblePitchAngle`` silently truncating a raised
``pitchDegreesShown``) in under a second, which
docs/aer-1799-evidence/measure_ladder_extent.py cannot: that scanner
over-reports the down extent in exactly the case this pins (it read -19
for the shipped ``(30, 15, 68)`` config where the geometry below says
-15).
"""

import pytest

from pyefis.instruments import ai


def _visible_extent(pitch_degrees_shown, visible_pitch_angle, horizon_position):
    """(pitchDegreesShown, visiblePitchAngle, horizon_position) ->
    (visible_up, visible_down), in degrees from the current pitch.

    ``horizon_position`` (percent up the screen, 50 = centred) splits the
    viewport's pitchDegreesShown span into a screen-space extent above the
    horizon (``f * D``) and below it (``(1 - f) * D``); visiblePitchAngle
    then truncates whichever of those is larger -- the same two
    constraints setPitchItems (ai_widget.py) and _horizon_offset_px/_deg
    apply, expressed here without Qt or a painted frame.
    """
    f = 1.0 - horizon_position / 100.0
    d = float(pitch_degrees_shown)
    visible_up = min(f * d, visible_pitch_angle)
    visible_down = min((1.0 - f) * d, visible_pitch_angle)
    return visible_up, visible_down


@pytest.mark.parametrize("d, vpa, horizon, expected", [
    # dev's shipped values: symmetric horizon, ladder unclipped either way.
    (30, 15, 50, (15.0, 15.0)),
    # dev's shipped live config (horizon_position: 68): more screen below
    # the horizon than above it, so "up" is screen-clipped to 9.6 while
    # "down" hits the 15 deg visiblePitchAngle ceiling first.
    (30, 15, 68, (9.6, 15.0)),
    # AER-1799's raised pitchDegreesShown=50 with visiblePitchAngle owned
    # (25 = 50 / 2, this issue's fix) -- symmetric horizon, unclipped.
    (50, 25, 50, (25.0, 25.0)),
    # Same raised pitchDegreesShown, at the live horizon_position=68.
    (50, 25, 68, (16.0, 25.0)),
])
def test_visible_extent_matches_geometry(d, vpa, horizon, expected):
    up, down = _visible_extent(d, vpa, horizon)
    assert up == pytest.approx(expected[0])
    assert down == pytest.approx(expected[1])


def test_visible_pitch_angle_is_owned_by_pitch_degrees_shown(fix, qtbot):
    """The constant-ownership fix this issue lands: visiblePitchAngle must
    be DERIVED from pitchDegreesShown (D / 2), not an independent literal.

    Run unmodified against the AER-1799 v1 eval build
    (aer-1799/pitch-range-svs-fov-eval, commit 7e42491), which raises
    pitchDegreesShown to 50 (+-25 intended, per AC 23.1311-1C Sec 8.5(c))
    but leaves visiblePitchAngle hardcoded at 15, this assertion is
    ``15 == 25.0`` -- False, red -- even though that build's full test
    suite stayed green, because nothing else pinned the relationship
    between the two constants.
    """
    widget = ai.AI()
    qtbot.addWidget(widget)
    assert widget.visiblePitchAngle == widget.pitchDegreesShown / 2


def test_shipped_config_visible_extent_matches_pitch_degrees_shown_50(fix, qtbot):
    """AER-1973 deliberately moves this pin from (9.6, 15.0) to (16.0, 25.0).

    This test previously asserted the live ladder geometry at dev's shipped
    (pitchDegreesShown=30, horizon_position=68) was unchanged by the
    AER-1806 refactor. AER-1973 raises the widget default pitchDegreesShown
    30 -> 50 (Bill's AER-1802 ruling: horizon_position stays 68, but the
    pitch-up ceiling goes from +9.6 to +16.0 deg without touching the
    ground area) -- visiblePitchAngle follows for free via the AER-1806
    ownership fix. So this pin MUST move too; re-pinning it here is that
    deliberate edit, not a silent re-baseline against a red test. See the
    parametrized case (50, 25, 68, (16.0, 25.0)) above for the same
    arithmetic in isolation.
    """
    widget = ai.AI()
    qtbot.addWidget(widget)
    widget.horizon_position = 68
    up, down = _visible_extent(
        widget.pitchDegreesShown, widget.visiblePitchAngle,
        widget.horizon_position)
    assert (up, down) == pytest.approx((16.0, 25.0))
