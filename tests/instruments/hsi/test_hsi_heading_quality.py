"""CERT1e: the HSI under a failed, expired or suspect HEAD.

A heading that stops updating leaves the card, the numerals, the heading bug and
the MAG readout at their last values. Under `fail` (CERT1's watchdog on a hung
gateway) and `old` (one heading source stopped while fix-gateway runs, the
likelier field failure) none of them may read as live: the HDG flag shows, the
numerals, bug and track diamond go, and MAG shows a red XXX. `old` gets the
`fail` look, as CERT1b ruled for the tapes. Under `bad` the flag shows and MAG is
blank under an amber label. Every case is tested with CDI and GSI absent, so the
heading alone has to carry it.
"""
from unittest import mock

import pytest
from PyQt6.QtGui import QColor, QPainter, QPaintEvent

from pyefis.instruments import hsi

RED = QColor(255, 0, 0)
AMBER = QColor(255, 150, 0)
FROZEN = 120.0                                  # a 5-deg multiple: the arc draws numerals only then (AER-5894 follow-up)
FROZEN_TEXT = "120°"


def _mk(qtbot, orientation, layout="top_panel", nav=False):
    """A heading-only HSI (no CDI, no GSI; both when `nav`), heading bug and
    track diamond on, COURSE valid, everything valid, holding FROZEN."""
    w = hsi.HSI(cdi_enabled=nav, gsi_enabled=nav)
    qtbot.addWidget(w)
    w.heading_bug_enabled = True
    w.track_indicator_enabled = True
    w.orientation = orientation
    w.readout_layout = layout
    w.resize(300, 300)                         # builds the bug + track items
    w.show()
    qtbot.waitExposed(w)
    w._CourseOld = w._CourseBad = w._CourseFail = False
    w._HeadOld = w._HeadBad = w._HeadFail = False
    w._TrackOld = w._TrackBad = w._TrackFail = False
    w._CdiOld = w._CdiBad = w._CdiFail = False
    w._GsiOld = w._GsiBad = w._GsiFail = False
    w.gsdb = None                               # no speed gate on the diamond
    w.setHeading(FROZEN)
    w._hdgBug = FROZEN + 10.0                  # in the arc sector, not FROZEN
    w.setTrack(FROZEN - 10.0)
    w._update_track()
    return w


def _set(w, flag):
    {"fail": w.setHeadFail, "old": w.setHeadOld, "bad": w.setHeadBad}[flag](True)


class _Paint:
    """One paintEvent, recording what it drew: every drawText string, the MAG
    cell (label, value, label colour, value colour), and whether the heading
    bug and the track diamond were drawn on either paint path."""

    def __init__(self, w, monkeypatch):
        self.texts = []
        self.mag = None
        self.markers = []
        real_text = QPainter.drawText
        texts = self.texts

        def spy_text(painter, *a):
            texts.append(a[-1])
            return real_text(painter, *a)
        monkeypatch.setattr(QPainter, "drawText", spy_text)

        real_panel = w._draw_readout_panel

        def spy_panel(c, x, y, pw, ph, orientation, segments):
            for seg in segments:
                if seg[0] == "MAG":
                    self.mag = (seg[1], QColor(seg[2]),
                                QColor(seg[3]) if len(seg) > 3 and seg[3] else None)
            return real_panel(c, x, y, pw, ph, orientation, segments)
        monkeypatch.setattr(w, "_draw_readout_panel", spy_panel)

        real_box = w._draw_readout_box

        def spy_box(c, ax, ay, anchor, label, value, color, value_color=None):
            if label == "MAG":
                self.mag = (value, QColor(color),
                            QColor(value_color) if value_color else None)
            return real_box(c, ax, ay, anchor, label, value, color, value_color)
        monkeypatch.setattr(w, "_draw_readout_box", spy_box)

        real_bug = w._hdg_bug_polygon
        real_dia = w._track_diamond_polygon
        real_band = w._draw_arc_band_marker
        monkeypatch.setattr(w, "_hdg_bug_polygon",
                            lambda: (self.markers.append("bug"), real_bug())[1])
        monkeypatch.setattr(w, "_track_diamond_polygon",
                            lambda: (self.markers.append("diamond"), real_dia())[1])

        def spy_band(c, value, color, kind):
            self.markers.append(kind)
            return real_band(c, value, color, kind)
        monkeypatch.setattr(w, "_draw_arc_band_marker", spy_band)

        w.paintEvent(QPaintEvent(w.rect()))
        monkeypatch.undo()

    def numerals(self, w):
        rose = {txt for _cnt, txt in getattr(w, "_rose_labels", ())}
        arc = set(w.cardinal) | {str(n) for n in range(1, 36)}
        return [t for t in self.texts if t in (rose | arc)]


@pytest.mark.parametrize("orientation", ["heading_up", "arc"])
def test_valid_heading_control(fix, qtbot, monkeypatch, orientation):
    """Control: with HEAD valid every element under test is drawn, so the
    absences asserted below are caused by the flag, not by the fixture."""
    w = _mk(qtbot, orientation)
    p = _Paint(w, monkeypatch)
    assert w._showHdgFlag is False
    assert p.mag[0] == FROZEN_TEXT
    assert p.numerals(w)
    assert "bug" in p.markers and "diamond" in p.markers


@pytest.mark.parametrize("orientation", ["heading_up", "arc"])
@pytest.mark.parametrize("flag", ["fail", "old"])
def test_failed_or_old_heading_shows_no_frozen_value(fix, qtbot, monkeypatch,
                                                    orientation, flag):
    """CERT1e | fail and old: HDG flag, red XXX in MAG, no numerals, no bug, no
    track diamond -- nothing on the card reads as a live heading."""
    w = _mk(qtbot, orientation)
    _set(w, flag)
    p = _Paint(w, monkeypatch)
    assert w._showHdgFlag is True
    assert p.mag[0] == "XXX"
    assert p.mag[1] == RED and p.mag[2] == RED
    assert FROZEN_TEXT not in p.texts
    assert p.numerals(w) == []
    assert "bug" not in p.markers
    assert "diamond" not in p.markers


@pytest.mark.parametrize("orientation", ["heading_up", "arc"])
def test_bad_heading_blanks_mag_under_an_amber_label(fix, qtbot, monkeypatch,
                                                    orientation):
    """CERT1e | bad: HDG flag, MAG blank under an amber label, no numerals, bug
    or track diamond."""
    w = _mk(qtbot, orientation)
    _set(w, "bad")
    p = _Paint(w, monkeypatch)
    assert w._showHdgFlag is True
    assert p.mag[0] == ""
    assert p.mag[1] == AMBER
    assert FROZEN_TEXT not in p.texts
    assert p.numerals(w) == []
    assert "bug" not in p.markers
    assert "diamond" not in p.markers


@pytest.mark.parametrize("orientation", ["heading_up", "arc"])
@pytest.mark.parametrize("flag", ["fail", "old", "bad"])
def test_split_layout_mag_box_follows_the_flag(fix, qtbot, monkeypatch,
                                               orientation, flag):
    """The split layout draws MAG as its own box: same rule as the panel."""
    w = _mk(qtbot, orientation, layout="split")
    _set(w, flag)
    p = _Paint(w, monkeypatch)
    assert p.mag[0] == ("" if flag == "bad" else "XXX")
    assert FROZEN_TEXT not in p.texts


@pytest.mark.parametrize("flag", ["fail", "old", "bad"])
def test_is_fail_tests_head_alone(fix, qtbot, flag):
    """isFail() tested _HeadBad but not _HeadFail, so on an HSI with no CDI/GSI
    keys a failed HEAD left the numerals up."""
    w = _mk(qtbot, "heading_up")
    assert w.isFail() is False
    _set(w, flag)
    assert w.isFail() is True


@pytest.mark.parametrize("flag", ["fail", "old", "bad"])
def test_heading_quality_change_repaints_without_a_value_change(fix, qtbot, flag):
    """A stale heading sends no value changes, so the flag change itself must
    schedule the repaint; otherwise the frozen card stays drawn as live."""
    w = _mk(qtbot, "heading_up")
    with mock.patch.object(w, "update") as upd:
        _set(w, flag)
    assert upd.called


@pytest.mark.parametrize("flag", ["fail", "old", "bad"])
def test_heading_sync_push_refused_on_an_invalid_heading(fix, qtbot, flag):
    """A push on HDG syncs the bug to the heading; with no valid heading there is
    nothing to sync to, and it must not write the frozen value."""
    w = _mk(qtbot, "heading_up")
    w._edit_field = "hdg"
    w._edit_item = mock.Mock()
    _set(w, flag)
    assert w.enc_clicked() is False
    w._edit_item.output_value.assert_not_called()


def _value_pens(painter, value):
    """The pen colour in force at each drawText of `value` on a mock painter."""
    pen = None
    out = []
    for name, args, _kw in painter.method_calls:
        if name == "setPen":
            pen = QColor(args[0].color())
        elif name == "drawText" and args[-1] == value:
            out.append(pen)
    return out


@pytest.mark.parametrize("layout", ["top_panel", "split"])
def test_mag_xxx_is_painted_red(fix, qtbot, layout):
    """The red XXX is the value's own pen, not just the label's: the readout
    primitives paint each value in fg_color unless told otherwise."""
    w = _mk(qtbot, "heading_up", layout=layout)
    painter = mock.MagicMock()
    painter.fontMetrics.return_value.horizontalAdvance.return_value = 10
    painter.fontMetrics.return_value.height.return_value = 10
    if layout == "top_panel":
        w._draw_readout_panel(painter, 0, 0, 120, 40, "h",
                              [("HDG", "130°", QColor("cyan")),
                               ("MAG", "XXX", RED, RED)])
    else:
        w._draw_readout_box(painter, 60, 0, "ct", "MAG", "XXX", RED, RED)
    assert _value_pens(painter, "XXX") == [RED]
    if layout == "top_panel":                   # a segment with no value colour
        assert _value_pens(painter, "130°") == [QColor(w.fg_color)]


# CERT1f (Bill, 2026-11-20): the numerals follow HEAD alone. A failed CDI or
# GSI, or a bad COURSE, takes away only what it drives (the course pointer and
# the deviation bar), never the compass numerals over a valid heading. Before
# this, isFail() gated the numerals, and a panel with no course source (COURSE
# invalid) showed ticks with no numbers in every frame (pyEfis #508).
_NAV_FAULTS = {
    "cdi_fail": lambda w: w.setCdiFail(True),
    "gsi_fail": lambda w: w.setGsiFail(True),
    "course_bad": lambda w: w.setCourseBad(True),
    "course_fail": lambda w: w.setCourseFail(True),
}


@pytest.mark.parametrize("orientation", ["heading_up", "arc"])
@pytest.mark.parametrize("fault", sorted(_NAV_FAULTS))
def test_nav_fault_alone_keeps_the_numerals(fix, qtbot, monkeypatch,
                                            orientation, fault):
    """CERT1f | HEAD valid, one nav fault: numerals drawn, no HDG flag."""
    w = _mk(qtbot, orientation, nav=True)
    assert w.cdi_enabled and w.gsi_enabled
    _NAV_FAULTS[fault](w)
    p = _Paint(w, monkeypatch)
    assert w._showHdgFlag is False
    assert p.numerals(w)
    assert all(label.opacity() == 1 for label in w.labels)


@pytest.mark.parametrize("fault", ["cdi_fail", "course_bad", "course_fail"])
def test_nav_fault_still_drops_the_deviation_bar(fix, qtbot, fault):
    """The fault keeps its own consequence: no deviation bar (G66)."""
    w = _mk(qtbot, "heading_up", nav=True)
    _NAV_FAULTS[fault](w)
    assert not w._cdi_shown()


@pytest.mark.parametrize("orientation", ["heading_up", "arc"])
@pytest.mark.parametrize("flag", ["fail", "old", "bad"])
def test_invalid_heading_hides_numerals_with_nav_valid(fix, qtbot, monkeypatch,
                                                       orientation, flag):
    """The converse: a valid nav state does not hold the numerals up over an
    invalid heading."""
    w = _mk(qtbot, orientation, nav=True)
    _set(w, flag)
    p = _Paint(w, monkeypatch)
    assert p.numerals(w) == []
    assert all(label.opacity() == 0 for label in w.labels)
