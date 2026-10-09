"""Pure-geometry pin for the pitch ladder's visible extent (AER-1806).

No rendering, no image thresholds, no pixel scanning -- this exists
specifically to catch the AER-1799 v1 eval build's class of bug (a
hardcoded ``visiblePitchAngle`` silently truncating a raised
``pitchDegreesShown``) in under a second, which
docs/aer-1799-evidence/measure_ladder_extent.py cannot: that scanner
over-reports the down extent in exactly the case this pins (it read -19
for the shipped ``(30, 15, 68)`` config where the geometry below says
-15).

Also pins the ladder's NUMERAL-to-RUNG derivation (AER-2652) -- same
house style, no rasterisation: the degree each numeral claims is read
from its own text, the degree its rung implies is recovered from the
scene-graph y, and the two must agree.
"""

import pytest
from PyQt6.QtCore import QSize
from PyQt6.QtGui import QResizeEvent
from PyQt6.QtWidgets import QGraphicsLineItem, QGraphicsTextItem

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


def _built_ladder(qtbot, width=300, height=300):
    """An AI whose resizeEvent has run, so self.scene / pitchItems exist.

    No show(), no exposure, no paint: Qt does not deliver a resize event
    to a hidden widget, so resizeEvent is driven directly -- the same
    ``resize()`` + ``resizeEvent(QResizeEvent(...))`` idiom
    test_ai.py's bankAngleRadius pin uses. Keeps these checks runnable
    on any host, GL or not, and under a second.
    """
    widget = ai.AI()
    qtbot.addWidget(widget)
    widget.resize(width, height)
    widget.resizeEvent(QResizeEvent(QSize(width, height), QSize(0, 0)))
    assert widget.pitchItems, "resizeEvent did not build the ladder"
    return widget


def _degree_from_scene_y(widget, center_y):
    """Scene y of a ladder item -> the pitch degree that y encodes.

    The inverse of resizeEvent's ``y = h / 2 - pixelsPerDeg * i``, read
    back off the scene graph. Deriving the degree this way (rather than
    trusting the ``i`` stored alongside the item in ``pitchItems``) is
    what makes the numeral pin below non-circular.
    """
    return (widget.scene.height() / 2.0 - center_y) / widget.pixelsPerDeg


def _numerals(widget):
    """[(scene_center_y, text)] for every numeral item the ladder built."""
    return [(item.sceneBoundingRect().center().y(), item.toPlainText())
            for _i, item in widget.pitchItems
            if isinstance(item, QGraphicsTextItem)]


def test_every_ladder_numeral_matches_its_rung_geometry(fix, qtbot):
    """Every pitch numeral must read as the degree its own y position means.

    The refactor this exists to catch: splitting the numeral's text away
    from the rung's placement -- a label table, a formatter dict, a
    cached list of strings, anything that makes
    ``scene.addText(str(i))`` (ai_widget.py resizeEvent) no longer the
    same ``i`` that sets ``y = h / 2 - pixelsPerDeg * i`` one line
    above. On dev those two are the same loop variable, so a numeral
    reading 10 beside the 20 rung is structurally inexpressible; the
    moment a second label source exists it becomes expressible and
    silent, because nothing rasterised ever asserts the glyph.

    Deliberately NOT a render-and-read check (AER-2652): QA's
    pitch-ladder judge already measured its own OCR to be
    host-dependent -- on one build/pose/viewport, three numerals read on
    one host and nine on another -- so rebuilding that instrument here
    would import the blind spot instead of covering it. This is pure
    arithmetic over the scene graph: the label's own text on one side,
    the y it was placed at on the other.
    """
    widget = _built_ladder(qtbot)
    numerals = _numerals(widget)
    assert numerals, "the ladder built no numerals at all"
    for center_y, text in numerals:
        geometric = _degree_from_scene_y(widget, center_y)
        assert float(text) == pytest.approx(geometric, abs=1e-6), (
            f"numeral {text!r} sits at scene y {center_y}, which under "
            f"pixelsPerDeg={widget.pixelsPerDeg} is the "
            f"{geometric:+.3f} deg rung")


def test_ladder_numeral_census_is_complete_and_paired(fix, qtbot):
    """Every numbered rung carries exactly two numerals, and no others exist.

    The sibling half of the pin above: that one proves no numeral LIES
    about its rung, this one proves none is MISSING or EXTRA. Both
    degrees here come from the scene geometry, not from the stored
    ``i``, so dropping a rung, double-labelling one, or labelling an
    unnumbered (majorDiv/minorDiv) rung all move it.

    Expected set is every multiple of ``numberedDiv`` in [-90, 90]
    except 0 (resizeEvent skips zero -- the horizon line is drawn
    separately), twice each for the left and right of the ladder.
    """
    widget = _built_ladder(qtbot)
    seen = {}
    for center_y, _text in _numerals(widget):
        degree = round(_degree_from_scene_y(widget, center_y))
        seen[degree] = seen.get(degree, 0) + 1
    expected = {d: 2 for d in range(-90, 91)
                if d != 0 and d % widget.numberedDiv == 0}
    assert seen == expected


def test_each_numeral_sits_on_a_drawn_numbered_rung(fix, qtbot):
    """A numeral's vertical centre must coincide with a real rung line.

    Catches the complement of the two pins above: a refactor that moves
    the rung LINES but leaves the numerals on the old y (or vice versa)
    keeps every label self-consistent with the ``h / 2 - ppd * i``
    formula while the ladder visibly comes apart. Numbered-rung lines
    are identified by their drawn length (``numberedDivWidth``, distinct
    from majorDivWidth and minorDivWidth), so this never consults the
    stored ``i`` either.
    """
    widget = _built_ladder(qtbot)
    rung_ys = [
        item.sceneBoundingRect().center().y()
        for _i, item in widget.pitchItems
        if isinstance(item, QGraphicsLineItem)
        and item.line().length() == pytest.approx(widget.numberedDivWidth)
    ]
    assert len(_numerals(widget)) == 2 * len(rung_ys)
    for center_y, text in _numerals(widget):
        assert any(center_y == pytest.approx(y, abs=1e-6) for y in rung_ys), (
            f"numeral {text!r} at scene y {center_y} is not on any "
            f"numbered rung line {sorted(rung_ys)}")
