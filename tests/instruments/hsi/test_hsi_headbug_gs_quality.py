"""INS5 (AER-6588): the HSI's heading bug and track diamond honour the quality
of HEADBUG and GS, as HSI-FAIL-001 rules (hsi_widget_spec.md section 7.2).

On dev both keys were read for their value alone, so a stale or failed
selected heading kept drawing a cyan bug and HDG readout, and a stale or failed
ground speed kept the track diamond up. The rules under test:

- `HEADBUG` old or bad: grey bug and grey HDG readout; fail: no bug, HDG `---°`.
- `GS` old, bad or fail: no track diamond (the `TRACKM`/`GS` row).

Each flag is driven through the FIX item, so the subscription is under test
too, and every case runs on both paint paths (rose and arc).
"""
import pytest
from PyQt6.QtGui import QColor, QPaintEvent

import pyavtools.fix as fixmod
from pyefis.instruments import hsi

CYAN = QColor("#00ffff")
GREY = QColor("#808080")
HEAD = 120.0
BUG = 130.0                     # inside the arc sector, off the lubber line
TRACK = 110.0


def _define(key, value):
    fixmod.db.define_item(key, key, "float", 0.0, 360.0, "deg", 0, "")
    fixmod.db.set_value(key, value)
    item = fixmod.db.get_item(key)
    item.old = item.bad = item.fail = False
    return item


def _mk(qtbot, orientation):
    _define("HEADBUG", BUG)
    _define("TRACKM", TRACK)
    for key, value in (("HEAD", HEAD), ("GS", 100.0)):
        fixmod.db.set_value(key, value)
        item = fixmod.db.get_item(key)
        item.old = item.bad = item.fail = False
    w = hsi.HSI(cdi_enabled=False, gsi_enabled=False)
    qtbot.addWidget(w)
    w.heading_bug_enabled = True
    w.track_indicator_enabled = True
    w.orientation = orientation
    w.readout_layout = "top_panel"
    w.resize(300, 300)
    w.show()
    qtbot.waitExposed(w)
    w._CourseOld = w._CourseBad = w._CourseFail = False
    w._HeadOld = w._HeadBad = w._HeadFail = False
    w.setHeading(HEAD)
    w._update_track()
    return w


class _Paint:
    """One paintEvent: the colour each heading bug was drawn in (both paths),
    whether the track diamond was drawn, and the HDG readout cell."""

    def __init__(self, w, monkeypatch):
        self.bugs = []
        self.diamond = False
        self.hdg = None

        real_bug = w._hdg_bug_polygon
        real_dia = w._track_diamond_polygon
        real_band = w._draw_arc_band_marker
        real_panel = w._draw_readout_panel

        def spy_bug():
            # The rose path sets the pen just before it asks for the polygon.
            self.bugs.append(self._pen_color)
            return real_bug()

        def spy_dia():
            self.diamond = True
            return real_dia()

        def spy_band(c, value, color, kind):
            if kind == "bug":
                self.bugs.append(QColor(color).name())
            else:
                self.diamond = True
            return real_band(c, value, color, kind)

        def spy_panel(c, x, y, pw, ph, orientation, segments):
            for seg in segments:
                if seg[0] == "HDG":
                    self.hdg = (seg[1], QColor(seg[2]).name())
            return real_panel(c, x, y, pw, ph, orientation, segments)

        self._pen_color = None
        from PyQt6.QtGui import QPainter
        real_set_pen = QPainter.setPen

        def spy_set_pen(painter, pen):
            try:
                self._pen_color = pen.color().name()
            except AttributeError:
                self._pen_color = None
            return real_set_pen(painter, pen)

        monkeypatch.setattr(QPainter, "setPen", spy_set_pen)
        monkeypatch.setattr(w, "_hdg_bug_polygon", spy_bug)
        monkeypatch.setattr(w, "_track_diamond_polygon", spy_dia)
        monkeypatch.setattr(w, "_draw_arc_band_marker", spy_band)
        monkeypatch.setattr(w, "_draw_readout_panel", spy_panel)
        w.paintEvent(QPaintEvent(w.rect()))
        monkeypatch.undo()


@pytest.mark.parametrize("orientation", ["heading_up", "arc"])
def test_valid_headbug_and_gs_control(fix, qtbot, monkeypatch, orientation):
    """Control: all valid, so the bug is cyan, the readout reads the bug and
    the diamond is drawn. The absences below are the flag's doing."""
    w = _mk(qtbot, orientation)
    p = _Paint(w, monkeypatch)
    assert p.bugs == [CYAN.name()]
    assert p.hdg == ("130°", CYAN.name())
    assert p.diamond is True


@pytest.mark.parametrize("orientation", ["heading_up", "arc"])
@pytest.mark.parametrize("flag", ["old", "bad"])
def test_old_or_bad_headbug_greys_bug_and_readout(fix, qtbot, monkeypatch,
                                                  orientation, flag):
    w = _mk(qtbot, orientation)
    setattr(fixmod.db.get_item("HEADBUG"), flag, True)
    p = _Paint(w, monkeypatch)
    assert p.bugs == [GREY.name()]
    assert p.hdg == ("130°", GREY.name())
    assert p.diamond is True                      # TRACKM/GS untouched

    setattr(fixmod.db.get_item("HEADBUG"), flag, False)
    p = _Paint(w, monkeypatch)
    assert p.bugs == [CYAN.name()]
    assert p.hdg == ("130°", CYAN.name())


@pytest.mark.parametrize("orientation", ["heading_up", "arc"])
def test_failed_headbug_removes_bug_and_dashes_readout(fix, qtbot, monkeypatch,
                                                      orientation):
    w = _mk(qtbot, orientation)
    fixmod.db.get_item("HEADBUG").fail = True
    p = _Paint(w, monkeypatch)
    assert p.bugs == []
    assert p.hdg[0] == "---°"
    assert p.diamond is True


@pytest.mark.parametrize("orientation", ["heading_up", "arc"])
@pytest.mark.parametrize("flag", ["old", "bad", "fail"])
def test_degraded_gs_hides_track_diamond(fix, qtbot, monkeypatch, orientation,
                                         flag):
    w = _mk(qtbot, orientation)
    setattr(fixmod.db.get_item("GS"), flag, True)
    p = _Paint(w, monkeypatch)
    assert p.diamond is False
    assert p.bugs == [CYAN.name()]                # HEADBUG untouched

    setattr(fixmod.db.get_item("GS"), flag, False)
    assert _Paint(w, monkeypatch).diamond is True


def test_initial_headbug_and_gs_quality_is_read(fix, qtbot):
    """A source already degraded when the screen is built draws that way from
    the first frame."""
    _define("HEADBUG", BUG).bad = True
    _define("TRACKM", TRACK)
    fixmod.db.get_item("GS").old = True
    w = hsi.HSI(cdi_enabled=False, gsi_enabled=False)
    qtbot.addWidget(w)
    assert w._HdgBugBad is True
    assert w._GsOld is True
