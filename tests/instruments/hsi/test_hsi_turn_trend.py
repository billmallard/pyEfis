"""ATT1b (AER-6076): the HSI turn-rate trend.

A Garmin-style arc from the lubber line to the heading the aircraft will reach
in 6 s at the present rate of turn (ROT, deg/s, + = right), with fixed marks at
half (9 deg) and standard (18 deg) rate. Above 4 deg/s it stops at 24 deg and
gains an arrowhead. It is hidden, marks and all, when ROT is old, bad or
failed, on the full rose and on the arc presentation alike.
"""
import math
from types import SimpleNamespace

import pytest
from PyQt6.QtGui import QColor, QPainter

import pyavtools.fix as fixmod
from pyefis.instruments import hsi
from pyefis.screens.screenbuilder_options import apply_options

MAGENTA = QColor("#ff00ff")


def _mk(qtbot, rot, orientation="heading_up", layout="corners"):
    w = hsi.HSI(cdi_enabled=False, gsi_enabled=False)
    qtbot.addWidget(w)
    w.orientation = orientation
    w.readout_layout = layout
    w.track_indicator_enabled = False
    w.resize(320, 320)
    w.show()
    qtbot.waitExposed(w)
    w._HeadOld = w._HeadBad = w._HeadFail = False
    w._CourseOld = w._CourseBad = w._CourseFail = False
    w.setHeading(120.0)
    # Drive the real ROT item, so the widget's own subscription is exercised.
    it = fixmod.db.get_item("ROT")
    it.old = it.bad = it.fail = False
    fixmod.db.set_value("ROT", rot)
    assert w._rot == rot and w._turn_trend_shown()
    return w


class _Spy:
    """Record the trend's drawArc / drawPolyline / drawPolygon calls during one
    grab. Only the trend draws arcs or polylines on these widgets."""

    def __init__(self, monkeypatch):
        self.arcs, self.polylines, self.polygons = [], [], []
        real_arc, real_pl = QPainter.drawArc, QPainter.drawPolyline
        real_pg = QPainter.drawPolygon

        def arc(p, *a):
            self.arcs.append(a)
            return real_arc(p, *a)

        def pl(p, *a):
            self.polylines.append([(q.x(), q.y()) for q in a[0]])
            return real_pl(p, *a)

        def pg(p, *a):
            self.polygons.append((QColor(p.brush().color()), a))
            return real_pg(p, *a)
        monkeypatch.setattr(QPainter, "drawArc", arc)
        monkeypatch.setattr(QPainter, "drawPolyline", pl)
        monkeypatch.setattr(QPainter, "drawPolygon", pg)


@pytest.mark.parametrize("rot,span_deg", [(3.0, 18.0), (-3.0, -18.0),
                                          (1.5, 9.0), (-1.0, -6.0)])
def test_rose_arc_length_is_six_seconds_of_turn(fix, qtbot, monkeypatch, rot, span_deg):
    w = _mk(qtbot, rot)
    spy = _Spy(monkeypatch)
    w.grab()
    assert len(spy.arcs) == 1
    rect, start, span = spy.arcs[0]
    assert start == 90 * 16                       # rooted at the lubber
    assert span == int(round(-span_deg * 16))     # Qt CCW+: right turn sweeps CW
    rt = w._turn_trend_rose_radius()
    assert rect.center().x() == pytest.approx(w.cx)
    assert rect.center().y() == pytest.approx(w.cy)
    assert rect.width() == pytest.approx(2 * rt)
    assert rt > w.r                               # outside the ring


def test_standard_rate_reaches_the_standard_rate_mark(fix, qtbot):
    w = _mk(qtbot, w_rot := 3.0)
    d, capped = w._turn_trend_deg()
    assert d == pytest.approx(w._turn_trend_marks()[-1]) == pytest.approx(18.0)
    assert not capped
    assert w._turn_trend_marks() == (-18.0, -9.0, 9.0, 18.0)
    assert w_rot * w.TURN_TREND_SECONDS == 18.0


@pytest.mark.parametrize("rot", [5.0, -5.0, 12.0])
def test_fast_turn_caps_at_24_deg_with_an_arrowhead(fix, qtbot, monkeypatch, rot):
    w = _mk(qtbot, rot)
    spy = _Spy(monkeypatch)
    w.grab()
    _rect, _start, span = spy.arcs[0]
    assert span == int(round(-math.copysign(24.0, rot) * 16))
    heads = [a for col, a in spy.polygons if col == MAGENTA]
    assert len(heads) == 1


def test_no_arrowhead_at_or_below_the_cap(fix, qtbot, monkeypatch):
    w = _mk(qtbot, 4.0)
    spy = _Spy(monkeypatch)
    w.grab()
    assert [a for col, a in spy.polygons if col == MAGENTA] == []


def test_rose_pixels_end_at_the_18_deg_mark(fix, qtbot):
    """Closed-form geometry above; this checks the paint lands there too:
    trend colour inside the 18-deg sweep, none past it or on the other side."""
    for rot, sgn in ((3.0, 1.0), (-3.0, -1.0)):
        w = _mk(qtbot, rot)
        img = w.grab().toImage()
        rt = w._turn_trend_rose_radius()

        def px(deg):
            a = math.radians(deg)
            return QColor(img.pixel(round(w.cx + rt * math.sin(a)),
                                    round(w.cy - rt * math.cos(a))))
        assert px(sgn * 12.0) == MAGENTA
        assert px(sgn * 16.0) == MAGENTA
        assert px(sgn * 21.0) != MAGENTA
        assert px(-sgn * 12.0) != MAGENTA


@pytest.mark.parametrize("flag", ["old", "bad", "fail"])
@pytest.mark.parametrize("orientation", ["heading_up", "arc"])
def test_hidden_when_rot_invalid(fix, qtbot, monkeypatch, flag, orientation):
    w = _mk(qtbot, 3.0, orientation=orientation)
    calls = []
    monkeypatch.setattr(w, "_draw_turn_trend_rose", lambda c: calls.append("rose"))
    monkeypatch.setattr(w, "_draw_turn_trend_arc", lambda c: calls.append("arc"))
    w.grab()
    assert calls == ["rose" if orientation == "heading_up" else "arc"]
    calls.clear()
    setattr(fixmod.db.get_item("ROT"), flag, True)
    assert not w._turn_trend_shown()
    w.grab()
    assert calls == []                      # neither the arc nor its marks


def test_hidden_without_a_rot_key(fix, qtbot, monkeypatch):
    w = _mk(qtbot, 3.0)
    w.rotdb = None
    spy = _Spy(monkeypatch)
    w.grab()
    assert spy.arcs == []


def test_hidden_when_disabled(fix, qtbot, monkeypatch):
    w = _mk(qtbot, 3.0)
    w.turn_rate_enabled = False
    spy = _Spy(monkeypatch)
    w.grab()
    assert spy.arcs == []


def test_quality_recovery_repaints(fix, qtbot, monkeypatch):
    """A flag change repaints at once even with the value holding steady."""
    w = _mk(qtbot, 3.0)
    it = fixmod.db.get_item("ROT")
    it.fail = True
    assert not w._turn_trend_shown()
    n = []
    monkeypatch.setattr(w, "update", lambda *a: n.append(1))
    it.fail = False
    assert w._turn_trend_shown()
    assert n                                # repainted with no value change


def test_does_not_depend_on_heading_validity(fix, qtbot, monkeypatch):
    """The arc hangs off the fixed lubber, not the card: a failed HEAD (card
    frozen, HDG flag) does not make the turn rate wrong."""
    w = _mk(qtbot, 3.0)
    w.setHeadFail(True)
    spy = _Spy(monkeypatch)
    w.grab()
    assert len(spy.arcs) == 1


@pytest.mark.parametrize("rot", [3.0, -3.0])
def test_arc_presentation_ends_on_the_band_at_18_deg(fix, qtbot, monkeypatch, rot):
    w = _mk(qtbot, rot, orientation="arc")
    spy = _Spy(monkeypatch)
    w.grab()
    assert len(spy.polylines) == 1
    pts = spy.polylines[0]
    assert pts[0] == pytest.approx(w._turn_trend_arc_point(0.0))
    assert pts[-1] == pytest.approx(w._turn_trend_arc_point(rot * 6.0))
    # And that end is the band point 18 deg off the heading, lifted clear.
    bx, by = w._arc_band_point(120.0 + rot * 6.0)
    assert pts[-1][0] == pytest.approx(bx)
    assert pts[-1][1] < by


def test_options_reach_the_widget_through_apply_options(fix, qtbot):
    """The YAML shape, through the real option path (AER-5807 lesson)."""
    w = hsi.HSI(cdi_enabled=False, gsi_enabled=False)
    qtbot.addWidget(w)
    screen = SimpleNamespace(instruments=[w], encoder_list=[])
    apply_options(screen, 0, {"type": "horizontal_situation_indicator",
                              "options": {"turn_rate_enabled": "false",
                                          "turn_rate_color": "#ffffff"}})
    assert w.turn_rate_enabled is False
    assert w.turn_rate_color == "#ffffff"
