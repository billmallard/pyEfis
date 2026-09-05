import math
from unittest import mock

import pytest
from PyQt6.QtCore import Qt, QRectF, qRound
from PyQt6.QtGui import QColor, QPaintEvent, QPen
from PyQt6.QtWidgets import (
    QApplication, QGraphicsEllipseItem, QGraphicsPixmapItem,
)

from pyefis.instruments import hsi
from tests.utils import track_calls


@pytest.fixture
def app(qtbot):
    test_app = QApplication.instance()
    if test_app is None:
        test_app = QApplication([])
    return test_app


def _set_quality(item, *, old=False, bad=False, fail=False):
    item.old = old
    item.bad = bad
    item.fail = fail


def test_hsi_default_flags_heading_and_bug(fix, qtbot):
    widget = hsi.HSI(font_percent=0.1)
    qtbot.addWidget(widget)
    widget.resize(300, 200)
    widget.show()
    qtbot.waitExposed(widget)

    assert widget.getRatio() == 1
    assert widget.cdi_enabled is False
    assert widget.gsi_enabled is False
    assert widget._CdiOld is False
    assert widget._GsiFail is False
    assert widget.fontSize == 30
    assert widget.getHeading() == 0
    assert widget.getCoursePointer() == 0
    assert len(widget.labels) > 0

    widget.rotate = mock.Mock()
    widget.heading = 350
    widget.heading = 10
    widget.heading = 200
    widget.heading = 350
    widget.heading = 100
    widget.heading = 200
    widget.heading = 200

    assert widget.heading == 200
    assert widget.rotate.call_args_list[0].args == (10,)
    assert widget.rotate.call_args_list[1].args == (-20,)
    assert widget.rotate.call_args_list[2].args == (170,)
    assert widget.rotate.call_args_list[3].args == (-150,)
    assert widget.rotate.call_args_list[4].args == (-110,)

    widget.coursePointer = 370
    assert widget.coursePointer == 360
    assert widget.course_pointer is not None
    assert widget.course_pointer.polygon().count() == 3
    widget.coursePointer = 360

    widget.keyPressEvent(None)
    widget.wheelEvent(None)
    widget.showEvent(None)


def test_hsi_resize_does_not_accumulate_rotation(fix, qtbot):
    """resizeEvent must re-apply the absolute -heading rotation from a clean
    transform. It fires repeatedly (layout settling / geometry changes); without
    resetting first, each call stacked another -heading rotation and the card
    showed heading+offset (e.g. 290 when actually 052)."""
    import math
    widget = hsi.HSI()
    qtbot.addWidget(widget)
    widget.resize(200, 200)
    widget.show()
    qtbot.waitExposed(widget)
    widget.setHeading(52)

    widget.resizeEvent(None)
    t1 = widget.transform()
    widget.resizeEvent(None)
    widget.resizeEvent(None)
    t2 = widget.transform()

    assert t1 == t2                                      # idempotent, no stacking
    # transform is exactly a -52 rotation, not a multiple of it
    assert abs(t2.m11() - math.cos(math.radians(52))) < 1e-6


def test_hsi_course_pointer_before_resize_and_no_deviation_paint(fix, qtbot):
    widget = hsi.HSI()
    qtbot.addWidget(widget)
    widget.setCoursePointer(45)
    widget.resize(200, 200)
    widget.show()
    qtbot.waitExposed(widget)

    assert widget.coursePointer == 45
    widget.paintEvent(QPaintEvent(widget.rect()))


def test_hsi_source_auto_color(fix, qtbot):
    """source_auto_color tints the course pointer + CDI by NAVSRC: magenta
    (course_color) for a GPS source (2), green (vloc_color) for a NAV source
    (0/1). Off, or with no NAVSRC, falls back to the static colours."""
    widget = hsi.HSI(cdi_enabled=True)
    qtbot.addWidget(widget)
    widget.resize(200, 200)
    widget.show()
    qtbot.waitExposed(widget)

    widget.setNavsrc(2)                                   # GPS
    assert widget._source_color() == QColor(widget.course_color)
    assert widget.course_pointer.brush().color() == QColor(widget.course_color)

    widget.setNavsrc(0)                                   # NAV1
    assert widget._source_color() == QColor(widget.vloc_color)
    assert widget.course_pointer.brush().color() == QColor(widget.vloc_color)

    widget.source_auto_color = False                      # static fallback
    assert widget._source_color() is None


def test_hsi_source_label(fix, qtbot):
    """The source annunciation reads GPS for a GPS source, VLOCn from NAVSRC
    alone, and refines to VOR/LOC when NAVTYPE is set."""
    widget = hsi.HSI()
    qtbot.addWidget(widget)
    widget.resize(200, 200)
    widget.show()
    qtbot.waitExposed(widget)

    widget.setNavsrc(2)
    assert widget._source_label() == "GPS"
    widget.setNavsrc(0)
    assert widget._source_label() == "VLOC1"     # no NAVTYPE -> VLOC fallback
    widget.setNavtype(1)                         # VOR
    assert widget._source_label() == "VOR1"
    widget.setNavtype(2)                         # LOC
    assert widget._source_label() == "LOC1"
    widget.setNavsrc(1)                          # NAV2
    widget.setNavtype(0)                         # type unknown -> VLOC fallback
    assert widget._source_label() == "VLOC2"


def test_hsi_cdi_gsi_old_tracks_oldchanged_not_failchanged(fix, qtbot):
    """Regression: CDI/GSI 'old' and 'bad' must follow the oldChanged/badChanged
    signals. They were wired to failChanged, so once the items were old at
    construction (no data yet) the flags latched True and the deviation needles
    never reappeared even with valid data."""
    widget = hsi.HSI(cdi_enabled=True, gsi_enabled=True)
    qtbot.addWidget(widget)
    widget._CdiOld = widget._GsiOld = True
    widget._CdiBad = widget._GsiBad = True

    widget.cdidb.oldChanged.emit(False)
    widget.cdidb.badChanged.emit(False)
    widget.gsidb.oldChanged.emit(False)
    widget.gsidb.badChanged.emit(False)
    widget._GsiFail = False

    assert widget._CdiOld is False and widget._CdiBad is False
    assert widget._GsiOld is False and widget._GsiBad is False

    # with the flags clear, the needles are shown independently per channel
    widget.resize(200, 200)
    widget.show()
    qtbot.waitExposed(widget)
    widget.paintEvent(QPaintEvent(widget.rect()))
    assert widget._showCDI is True
    assert widget._showGSI is True


def test_hsi_gsi_hidden_when_no_glideslope(fix, qtbot):
    """GSV=0 (a VOR has no glideslope) hides the GS needle while the lateral CDI
    stays. GSV absent or >=0.5 -> GS shown on its own quality."""
    widget = hsi.HSI(cdi_enabled=True, gsi_enabled=True)
    qtbot.addWidget(widget)
    widget.resize(200, 200)
    widget.show()
    qtbot.waitExposed(widget)
    widget._CdiOld = widget._CdiBad = widget._GsiOld = widget._GsiBad = widget._GsiFail = False

    widget.setGsv(1)
    widget.paintEvent(QPaintEvent(widget.rect()))
    assert widget._showGSI is True

    widget.setGsv(0)                       # no glideslope (VOR)
    widget.paintEvent(QPaintEvent(widget.rect()))
    assert widget._showGSI is False        # GS needle hidden
    assert widget._showCDI is True         # lateral guidance unaffected

    widget.setTofrom(1)                    # TO -> triangle renders without error
    widget.paintEvent(QPaintEvent(widget.rect()))


def test_hsi_source_label_tap_cycles_navsrc(fix, qtbot, monkeypatch):
    """Tapping the nav-source annunciation writes the next NAVSRC (GPS 2 -> NAV1
    0); taps outside the label do nothing."""
    widget = hsi.HSI(cdi_enabled=True)
    qtbot.addWidget(widget)
    widget.resize(200, 200)
    widget.show()
    qtbot.waitExposed(widget)
    widget.navsrcdb = object()             # simulate a panel with a nav source
    widget._navsrc = 2                      # GPS
    widget.paintEvent(QPaintEvent(widget.rect()))   # sets the tap rect
    assert widget._source_label_rect is not None

    written = []
    monkeypatch.setattr(hsi.fix.db, "set_value", lambda k, v: written.append((k, v)))

    class _P:
        def __init__(s, x, y): s._x, s._y = x, y
        def x(s): return s._x
        def y(s): return s._y

    class _Ev:
        def __init__(s, x, y): s._p = _P(x, y)
        def pos(s): return s._p
        def accept(s): pass

    r = widget._source_label_rect
    widget.mousePressEvent(_Ev(r[0] + r[2] // 2, r[1] + r[3] // 2))   # inside label
    assert written == [("NAVSRC", 0.0)]    # GPS(2) -> NAV1(0)


def test_hsi_enabled_cdi_gsi_state_and_paint_paths(fix, qtbot):
    _set_quality(fix.db.get_item("HEAD"))
    _set_quality(fix.db.get_item("COURSE"))
    _set_quality(fix.db.get_item("CDI"))
    _set_quality(fix.db.get_item("GSI"))
    fix.db.set_value("CDI", 0.5)
    fix.db.set_value("GSI", -0.5)

    widget = hsi.HSI(cdi_enabled=True, gsi_enabled=True)
    qtbot.addWidget(widget)
    widget.visiblePointers = [False, False, False, False]
    widget.resize(300, 300)
    widget.show()
    qtbot.waitExposed(widget)
    event = QPaintEvent(widget.rect())

    with track_calls(QPen, "setWidth") as tracker:
        widget.paintEvent(event)

    assert tracker.was_called_with("setWidth", 3)
    assert widget.cdi == 0.5
    assert widget.gsi == -0.5
    assert widget.isOld() is False
    assert widget.isFail() is False

    widget.update = mock.Mock()
    widget.cdi = -0.25
    widget.gsi = 0.25
    widget.setCdiOld(True)
    widget.setCdiBad(True)
    widget.setGsiOld(True)
    widget.setGsiBad(True)

    assert widget.cdi == -0.25
    assert widget.gsi == 0.25
    assert widget._CdiOld is True
    assert widget._CdiBad is True
    assert widget._GsiOld is True
    assert widget._GsiBad is True
    assert widget.update.call_count >= 4

    widget.paintEvent(event)
    assert widget._showCDI is False
    assert widget._showGSI is False


def test_hsi_quality_flags_hide_and_restore_labels(fix, qtbot):
    _set_quality(fix.db.get_item("HEAD"))
    _set_quality(fix.db.get_item("COURSE"))
    _set_quality(fix.db.get_item("CDI"))
    _set_quality(fix.db.get_item("GSI"))
    widget = hsi.HSI(cdi_enabled=True, gsi_enabled=True)
    qtbot.addWidget(widget)
    widget.resize(300, 300)
    widget.show()
    qtbot.waitExposed(widget)

    widget.setHeadOld(True)
    widget.setHeadBad(True)
    widget.setCourseOld(True)
    widget.setCourseBad(True)
    assert widget.isOld() is True

    widget.setHeadFail(True)
    assert widget._HeadFail is True
    assert widget.isFail() is True
    assert all(label.opacity() == 0 for label in widget.labels)
    widget.setHeadFail(True)

    widget.setHeadBad(False)
    widget.setHeadFail(False)
    widget.setCourseBad(False)
    widget.setCourseFail(True)
    assert widget._CourseFail is True
    widget.setCourseFail(False)
    widget.setCourseFail(False)

    widget.setCdiFail(True)
    assert widget._CdiFail is True
    widget.setCdiFail(True)
    widget.setCdiFail(False)
    widget.setGsiFail(True)
    assert widget._GsiFail is True
    widget.setGsiFail(True)
    widget.setGsiFail(False)

    widget.setHeadOld(False)
    widget.setCourseOld(False)
    widget.setCdiOld(False)
    widget.setCdiBad(False)
    widget.setGsiOld(False)
    widget.setGsiBad(False)

    assert widget.isFail() is False
    assert widget.isOld() is False
    assert all(label.opacity() == 1 for label in widget.labels)


def test_hsi_setters_skip_noop_and_hidden_updates(fix, qtbot):
    _set_quality(fix.db.get_item("HEAD"))
    _set_quality(fix.db.get_item("COURSE"))
    _set_quality(fix.db.get_item("CDI"))
    _set_quality(fix.db.get_item("GSI"))
    widget = hsi.HSI(cdi_enabled=True, gsi_enabled=True)
    qtbot.addWidget(widget)

    widget.update = mock.Mock()
    widget.setCdi(0.25)
    widget.setCdi(0.25)
    widget.setGsi(0)
    widget.setCdiOld(False)
    widget.setCdiBad(False)
    widget.setGsiOld(False)
    widget.setGsiBad(False)

    widget.update.assert_not_called()


def test_hsi_disabled_cdi_gsi_setters_do_not_update(fix, qtbot):
    widget = hsi.HSI(cdi_enabled=False, gsi_enabled=False)
    qtbot.addWidget(widget)
    widget.resize(200, 200)
    widget.show()
    qtbot.waitExposed(widget)
    widget.update = mock.Mock()

    widget.setCdiOld(True)
    widget.setCdiBad(True)
    widget.setCdiFail(True)
    widget.setGsiOld(True)
    widget.setGsiBad(True)
    widget.setGsiFail(True)

    assert widget._CdiOld is False
    assert widget._CdiBad is False
    assert widget._CdiFail is False
    assert widget._GsiOld is False
    assert widget._GsiBad is False
    assert widget._GsiFail is False
    widget.update.assert_not_called()


def test_heading_display_format():
    """The boxed heading readout is always three zero-padded digits with a
    trailing degree sign; 360 and 0 both read 000."""
    f = hsi.HeadingDisplay._fmt_heading
    assert f(3) == "003°"
    assert f(30) == "030°"
    assert f(0) == "000°"
    assert f(360) == "000°"
    assert f(90) == "090°"
    assert f(359.7) == "359°"      # truncates, like the old display


def test_heading_display_quality_and_heading_paths(fix, qtbot):
    _set_quality(fix.db.get_item("HEAD"))
    widget = hsi.HeadingDisplay(fg_color=Qt.GlobalColor.white)
    qtbot.addWidget(widget)
    widget.resize(300, 100)
    widget.show()
    qtbot.waitExposed(widget)
    widget.resizeEvent(None)
    event = QPaintEvent(widget.rect())

    assert widget.getHeading() == 0
    widget.update = mock.Mock()
    widget.heading = 361
    widget.heading = 360

    assert widget.heading == 360
    widget.update.assert_called_once_with()

    with track_calls(QPen, "__init__") as tracker:
        widget.setFail(True)
        widget.paintEvent(event)
    assert tracker.was_called_with("__init__", QColor(Qt.GlobalColor.red))

    widget.setFail(False)
    with track_calls(QPen, "__init__") as tracker:
        widget.setBad(True)
        widget.paintEvent(event)
    assert tracker.was_called_with("__init__", QColor(255, 150, 0))

    with track_calls(QPen, "__init__") as tracker:
        widget.setBad(False)
        widget.setOld(True)
        widget.paintEvent(event)
    assert tracker.was_called_with("__init__", QColor(255, 150, 0))

    widget.setOld(False)
    widget.paintEvent(event)
    widget.showEvent(None)


def test_dg_tape_heading_and_events(fix, qtbot):
    widget = hsi.DG_Tape()
    qtbot.addWidget(widget)
    widget.resize(300, 100)
    widget.show()
    qtbot.waitExposed(widget)

    assert widget.getHeading() == 0
    assert widget.scene is not None
    widget.centerOn = mock.Mock()

    widget.heading = 45
    widget.heading = 45
    widget.showEvent(None)
    widget.keyPressEvent(None)
    widget.wheelEvent(None)

    assert widget.heading == 45
    assert widget.centerOn.call_count == 2


# =============================================================================
# HSI requirements test catalog -- keyed to hsi_widget_spec.md sec 7 (Flags,
# Alerts & Failure Annunciation) and avionics_reference.md.
#
# Each docstring: HSI-TC-NNN | requirement ID | intent.
# Passing tests verify shipped behaviour. The xfail(strict) tests are the
# executable gap tracker for the not-yet-implemented warning flags: they fail
# today (the flag state does not exist) and will xpass -- which, under strict,
# fails the run -- the moment the flag is implemented, prompting removal of the
# marker. Spec sec 10 carries the full case<->requirement map.
# =============================================================================


def _mk_hsi(qtbot, **kw):
    w = hsi.HSI(**kw)
    qtbot.addWidget(w)
    w.resize(300, 300)
    w.show()
    qtbot.waitExposed(w)
    return w


def test_hsi_cat_all_valid_shows_both_needles(fix, qtbot):
    """HSI-TC-001 | HSI-FAIL-001 (happy path) | Every deviation signal valid and a
    glideslope present -> both the CDI and GS needles are shown."""
    w = _mk_hsi(qtbot, cdi_enabled=True, gsi_enabled=True)
    w._CdiOld = w._CdiBad = w._GsiOld = w._GsiBad = w._GsiFail = False
    w.setGsv(1)
    w.paintEvent(QPaintEvent(w.rect()))
    assert w._showCDI is True
    assert w._showGSI is True


def test_hsi_cat_cdi_hidden_when_old_or_bad(fix, qtbot):
    """HSI-TC-021 | HSI-FAIL-001 (CDI) | Stale (old) or invalid (bad) lateral deviation
    removes the CDI bar."""
    w = _mk_hsi(qtbot, cdi_enabled=True)
    w._CdiOld, w._CdiBad = True, False
    w.paintEvent(QPaintEvent(w.rect()))
    assert w._showCDI is False
    w._CdiOld, w._CdiBad = False, True
    w.paintEvent(QPaintEvent(w.rect()))
    assert w._showCDI is False


def test_hsi_cat_gsi_hidden_when_old_or_bad(fix, qtbot):
    """HSI-TC-031 | HSI-FAIL-001 (GSI) | Stale/invalid GS deviation removes the GS
    diamond even with a glideslope present."""
    w = _mk_hsi(qtbot, cdi_enabled=True, gsi_enabled=True)
    w.setGsv(1)
    w._GsiOld, w._GsiBad = True, False
    w.paintEvent(QPaintEvent(w.rect()))
    assert w._showGSI is False


def test_hsi_cat_gs_absent_when_gsv_zero(fix, qtbot):
    """HSI-TC-032 | HSI-ANN-003 (no-GS case) | GSV=0 (a VOR / no glideslope) -> GS scale
    absent, lateral CDI unaffected. The 'no GS present' branch, distinct from GS-lost
    (HSI-TC-103)."""
    w = _mk_hsi(qtbot, cdi_enabled=True, gsi_enabled=True)
    w._CdiOld = w._CdiBad = w._GsiOld = w._GsiBad = w._GsiFail = False
    w.setGsv(0)
    w.paintEvent(QPaintEvent(w.rect()))
    assert w._showGSI is False
    assert w._showCDI is True


def test_hsi_cat_cdi_full_scale_boundary(fix, qtbot):
    """HSI-TC-060 | HSI-DEV-001 (edge) | The normalized CDI at +/-1.0 full-scale (and 0)
    paints without error and stays shown; the source owns full-scale (spec sec 4.2)."""
    w = _mk_hsi(qtbot, cdi_enabled=True)
    w._CdiOld = w._CdiBad = False
    for dev in (1.0, -1.0, 0.0):
        w.setCdi(dev)
        w.paintEvent(QPaintEvent(w.rect()))
        assert w._showCDI is True


def test_hsi_cat_gsi_full_scale_boundary(fix, qtbot):
    """HSI-TC-062 | HSI-DEV-001 (edge) | The normalized GS at +/-1.0 full-scale (and 0)
    paints without error and stays shown."""
    w = _mk_hsi(qtbot, cdi_enabled=True, gsi_enabled=True)
    w.setGsv(1)
    w._GsiOld = w._GsiBad = w._GsiFail = False
    for dev in (1.0, -1.0, 0.0):
        w.setGsi(dev)
        w.paintEvent(QPaintEvent(w.rect()))
        assert w._showGSI is True


def test_hsi_cat_source_switch_tracks_colour_and_label(fix, qtbot):
    """HSI-TC-041 | HSI-COLOR-001 + HSI-SRC-001 (edge) | Switching NAVSRC GPS->NAV1->NAV2
    moves the source colour (magenta<->green) and the annunciation together."""
    w = _mk_hsi(qtbot, cdi_enabled=True)
    w.setNavsrc(2)
    assert w._source_color() == QColor(w.course_color) and w._source_label() == "GPS"
    w.setNavsrc(0)
    assert w._source_color() == QColor(w.vloc_color) and w._source_label() == "VLOC1"
    w.setNavsrc(1)
    assert w._source_color() == QColor(w.vloc_color) and w._source_label() == "VLOC2"


def test_hsi_cat_hdg_flag_on_head_fail(fix, qtbot):
    """HSI-TC-101 | HSI-ANN-001 | On HEAD fail the HSI annunciates a heading (compass)
    warning flag (IFH p.118; AC 25-11B 4.2): paintEvent sets w._showHdgFlag and draws a
    red HDG flag."""
    w = _mk_hsi(qtbot, cdi_enabled=True)
    w.setHeadFail(True)
    w.paintEvent(QPaintEvent(w.rect()))
    assert w._showHdgFlag is True


def test_hsi_cat_nav_flag_on_cdi_invalid(fix, qtbot):
    """HSI-TC-102 | HSI-ANN-002 | On selected-lateral-source fail/invalid the HSI shows a
    NAV warning flag and removes the CDI (IFH p.118/p.283): paintEvent sets w._showNavFlag
    and _showCDI is False."""
    w = _mk_hsi(qtbot, cdi_enabled=True)
    w.setCdiBad(True)
    w.setCdiFail(True)
    w.paintEvent(QPaintEvent(w.rect()))
    assert w._showNavFlag is True
    assert w._showCDI is False        # flag + remove the deviation bar


def test_hsi_cat_gs_flag_on_gs_lost(fix, qtbot):
    """HSI-TC-103 | HSI-ANN-003 | When a glideslope is expected (present) but its signal
    is lost/failed, the HSI shows a GS warning flag and no diamond -- distinct from 'no GS
    present' (GSV=0, HSI-TC-032) where the scale is simply absent (IFH p.283): paintEvent
    sets w._showGsFlag and _showGSI stays False (mutually exclusive)."""
    w = _mk_hsi(qtbot, cdi_enabled=True, gsi_enabled=True)
    w.setGsv(1)            # glideslope present / expected
    w.setGsiFail(True)     # ...but the GS signal has failed
    w.paintEvent(QPaintEvent(w.rect()))
    assert w._showGsFlag is True
    assert w._showGSI is False       # flag replaces the diamond


# =============================================================================
# Heading / compass requirements test catalog -- keyed to heading_widget_spec.md
# sec 4 (Heading Presentation & Annunciation) and avionics_reference.md sec 4.4.
#
# Docstrings: HDG-TC-NNN | requirement ID | intent.
# Passing tests verify shipped behaviour. The xfail(strict) test is the gap
# tracker for DG_Tape heading-invalid annunciation (AC 23.1311-1C sec 8.6.a):
# today the heading tape ignores HEAD fail/old/bad (an in-code TODO). Spec sec 5
# carries the case<->requirement map.
# =============================================================================


def test_hdg_cat_heading_presentation(fix, qtbot):
    """HDG-TC-001 | HDG-DISP-001 | Clear heading presentation: a boxed numeric readout plus
    a heading scale/tape with cardinal points. AC 23.1311-1C sec 8.6.b (p.23)."""
    _set_quality(fix.db.get_item("HEAD"))
    disp = hsi.HeadingDisplay(fg_color=Qt.GlobalColor.white)
    qtbot.addWidget(disp)
    disp.resize(200, 80)
    disp.show()
    qtbot.waitExposed(disp)
    disp.setHeading(90)
    assert disp.getHeading() == 90

    tape = hsi.DG_Tape()
    qtbot.addWidget(tape)
    tape.resize(300, 100)
    tape.show()
    qtbot.waitExposed(tape)
    assert tape.scene is not None
    assert tape.cardinal[:4] == ["N", "E", "S", "W"]      # cardinal points
    tape.setHeading(180)
    assert tape.getHeading() == 180


def test_hdg_cat_heading_format_wraps(fix, qtbot):
    """HDG-TC-002 | HDG-FMT-001 | Magnetic heading is three zero-padded digits, wrapping at
    360 (000-359). AC 23.1311-1C sec 8.6.b (p.23)."""
    f = hsi.HeadingDisplay._fmt_heading
    assert f(30) == "030°"
    assert f(0) == "000°"
    assert f(360) == "000°"        # wraps
    assert f(359.7) == "359°"


def test_hdg_cat_numeric_invalid_annunciation(fix, qtbot):
    """HDG-TC-003 | HDG-ANN-001 | The numeric heading readout annunciates invalid HEAD:
    fail -> red XXX, old/bad -> amber blank. AC 23.1311-1C sec 8.6.a; ref sec 2."""
    _set_quality(fix.db.get_item("HEAD"))
    widget = hsi.HeadingDisplay(fg_color=Qt.GlobalColor.white)
    qtbot.addWidget(widget)
    widget.resize(200, 80)
    widget.show()
    qtbot.waitExposed(widget)
    event = QPaintEvent(widget.rect())

    with track_calls(QPen, "__init__") as tracker:
        widget.setFail(True)
        widget.paintEvent(event)
    assert tracker.was_called_with("__init__", QColor(Qt.GlobalColor.red))

    widget.setFail(False)
    with track_calls(QPen, "__init__") as tracker:
        widget.setBad(True)
        widget.paintEvent(event)
    assert tracker.was_called_with("__init__", QColor(255, 150, 0))


def test_hdg_cat_tape_invalid_annunciation(fix, qtbot):
    """HDG-TC-004 | HDG-ANN-001 | The heading tape must annunciate invalid HEAD (fail -> red
    flag, old/bad -> grey/amber) rather than keep scrolling a frozen tape. AC 23.1311-1C
    sec 8.6.a; ref sec 2. Contract: DG_Tape wires HEAD old/bad/fail (w._fail etc.) and
    paintEvent flags it."""
    _set_quality(fix.db.get_item("HEAD"))
    widget = hsi.DG_Tape()
    qtbot.addWidget(widget)
    widget.resize(300, 100)
    widget.show()
    qtbot.waitExposed(widget)
    event = QPaintEvent(widget.rect())

    fix.db.get_item("HEAD").fail = True
    assert widget._fail is True                           # quality wired
    with track_calls(QPen, "__init__") as tracker:
        widget.paintEvent(event)
    assert tracker.was_called_with("__init__", QColor(Qt.GlobalColor.red))   # red flag


# --- HSI bearing pointers (P5b.2) --------------------------------------------

def _define_bearing_keys(fix, brg1=None, brg2=None, src1=None, src2=None):
    """Define the P5b.1 bearing keys on the mock db so an enabled pointer's
    defensive subscribe finds them. Values optional; flags cleared."""
    for key, val in (("BRG1", brg1), ("BRG2", brg2),
                     ("BRG1SRC", src1), ("BRG2SRC", src2)):
        if val is None:
            continue
        fix.db.define_item(key, key, "float", 0.0, 359.9, "deg", 50000, "")
        fix.db.set_value(key, val)
        fix.db.get_item(key).old = False
        fix.db.get_item(key).bad = False
        fix.db.get_item(key).fail = False


def test_bearing_angle_tracks_heading_and_wraps(fix, qtbot):
    """The needle sits at (BRGn - heading) on the heading-up card, wrapped to
    [0, 360). This is the gap the widget must get right; unit-level, no paint."""
    _define_bearing_keys(fix, brg1=90.0, src1=2.0)
    widget = hsi.HSI(font_percent=0.1)
    qtbot.addWidget(widget)

    widget._heading = 0.0
    widget._brg[1] = 90.0
    assert widget._bearing_angle_deg(1) == 90.0
    widget._heading = 30.0
    assert widget._bearing_angle_deg(1) == 60.0
    # wrap: 10 - 350 = -340 -> 20
    widget._heading = 350.0
    widget._brg[1] = 10.0
    assert widget._bearing_angle_deg(1) == 20.0


def test_bearing_visibility_gated_by_enable_heading_and_quality(fix, qtbot):
    _define_bearing_keys(fix, brg1=120.0, src1=2.0)
    widget = hsi.HSI(font_percent=0.1)
    qtbot.addWidget(widget)
    widget.bearing1_enabled = True
    # good state -> visible
    widget._HeadFail = widget._HeadBad = False
    widget._brgOld[1] = widget._brgBad[1] = widget._brgFail[1] = False
    assert widget._bearing_visible(1) is True
    # disabled -> hidden
    widget.bearing1_enabled = False
    assert widget._bearing_visible(1) is False
    widget.bearing1_enabled = True
    # heading invalid hides all heading-referenced needles (HSI-ANN-001)
    widget._HeadBad = True
    assert widget._bearing_visible(1) is False
    widget._HeadBad = False
    widget._HeadFail = True
    assert widget._bearing_visible(1) is False
    widget._HeadFail = False
    # the pointer's own BRGn quality hides just that needle (HSI-FAIL-001)
    for flag in ("_brgOld", "_brgBad", "_brgFail"):
        getattr(widget, flag)[1] = True
        assert widget._bearing_visible(1) is False
        getattr(widget, flag)[1] = False
    assert widget._bearing_visible(1) is True
    # pointer 2 absent (BRG2 never defined) -> never visible even if enabled
    widget.bearing2_enabled = True
    assert widget._bearing_visible(2) is False


def test_bearing_color_follows_source(fix, qtbot):
    _define_bearing_keys(fix, brg1=10.0, src1=2.0, brg2=20.0, src2=0.0)
    widget = hsi.HSI(font_percent=0.1)
    qtbot.addWidget(widget)
    widget._brgSrc[1] = 2.0                       # GPS -> magenta (course_color)
    assert widget._bearing_color(1) == QColor(widget.course_color)
    widget._brgSrc[1] = 0.0                       # VOR1 -> green (vloc_color)
    assert widget._bearing_color(1) == QColor(widget.vloc_color)
    widget._brgSrc[1] = 1.0                       # VOR2 -> green
    assert widget._bearing_color(1) == QColor(widget.vloc_color)
    widget._brgSrc[1] = None                      # unknown -> generic bearing_color
    assert widget._bearing_color(1) == QColor(widget.bearing_color)


def test_bearing_source_cycle_writes_key(fix, qtbot):
    _define_bearing_keys(fix, brg1=10.0, src1=0.0)
    widget = hsi.HSI(font_percent=0.1)
    qtbot.addWidget(widget)
    widget._brgSrc[1] = 0.0
    widget._cycle_bearing_src(1)                  # VOR1 -> VOR2
    assert fix.db.get_item("BRG1SRC").value == 1.0
    widget._brgSrc[1] = 1.0
    widget._cycle_bearing_src(1)                  # VOR2 -> GPS
    assert fix.db.get_item("BRG1SRC").value == 2.0
    widget._brgSrc[1] = 2.0
    widget._cycle_bearing_src(1)                  # GPS -> VOR1 (wrap)
    assert fix.db.get_item("BRG1SRC").value == 0.0


def test_bearing_source_label_text(fix, qtbot):
    _define_bearing_keys(fix, brg1=10.0, src1=0.0)
    widget = hsi.HSI(font_percent=0.1)
    qtbot.addWidget(widget)
    widget._brgSrc[1] = 0.0
    assert widget._bearing_src_label(1) == "1 VOR1"
    widget._brgSrc[1] = 1.0
    assert widget._bearing_src_label(1) == "1 VOR2"
    widget._brgSrc[2] = 2.0
    assert widget._bearing_src_label(2) == "2 GPS"
    widget._brgSrc[1] = None
    assert widget._bearing_src_label(1) == ""


def test_bearing_enabled_paint_never_raises_with_keys(fix, qtbot):
    """Both needles enabled with valid keys: construct + paint must not raise
    and the needles must be drawable (a source-coloured pen is created)."""
    _define_bearing_keys(fix, brg1=45.0, src1=2.0, brg2=250.0, src2=0.0)
    widget = hsi.HSI(font_percent=0.1, cdi_enabled=True, gsi_enabled=True)
    qtbot.addWidget(widget)
    widget.bearing1_enabled = True
    widget.bearing2_enabled = True
    widget.resize(300, 300)
    widget.show()
    qtbot.waitExposed(widget)
    widget._HeadFail = widget._HeadBad = False
    for n in (1, 2):
        widget._brgOld[n] = widget._brgBad[n] = widget._brgFail[n] = False
    event = QPaintEvent(widget.rect())
    widget.paintEvent(event)                       # must not raise
    assert widget._bearing_visible(1) is True
    assert widget._bearing_visible(2) is True


def test_bearing_construct_and_paint_never_raises_without_keys(fix, qtbot):
    """Pointers enabled but BRG keys undefined (a panel whose fix-gateway lacks
    the P5b.1 data layer): construct + paint must not raise and no needle shows
    (construct-never-raises)."""
    widget = hsi.HSI(font_percent=0.1)
    qtbot.addWidget(widget)
    widget.bearing1_enabled = True
    widget.bearing2_enabled = True
    widget.resize(300, 300)
    widget.show()
    qtbot.waitExposed(widget)
    assert widget.brgdb[1] is None and widget.brgdb[2] is None
    event = QPaintEvent(widget.rect())
    widget.paintEvent(event)                       # must not raise
    assert widget._bearing_visible(1) is False
    assert widget._bearing_visible(2) is False


# --- HSI arc orientation mode (P5b.3) ----------------------------------------

def test_hsi_orientation_default_is_heading_up(fix, qtbot):
    """Default orientation renders the existing rose (non-arc), so every existing
    rotation/paint test exercises the unchanged path."""
    widget = hsi.HSI()
    qtbot.addWidget(widget)
    assert widget.orientation == "heading_up"


def test_arc_rel_angle_wraps_shortest(fix, qtbot):
    """_rel_angle is the shortest signed delta in (-180, 180]."""
    f = hsi.HSI._rel_angle
    assert f(90, 0) == 90
    assert f(0, 30) == -30
    assert f(10, 350) == 20            # wrap forward
    assert f(350, 10) == -20           # wrap back
    assert f(0, 180) == 180


def test_arc_geometry_lubber_symmetry_and_scale(fix, qtbot):
    """Arc band: rel=0 sits at the top lubber; +/-rel are mirror images; the
    forward sector is clipped at +/-ARC_HALF_DEG; and the arc angular scale is
    EXPANDED relative to the full rose (proof of the 'new scale factor')."""
    import math
    widget = hsi.HSI()                             # default font -> fontSize 15
    qtbot.addWidget(widget)
    widget.orientation = "arc"
    widget.resize(300, 300)
    widget.show()
    qtbot.waitExposed(widget)
    widget._heading = 0.0

    cx, top_y, own_y, half_w, sag = widget._arc_params()
    # straight ahead -> top lubber
    x0, y0 = widget._arc_band_point(0.0)
    assert abs(x0 - cx) < 1e-6 and abs(y0 - top_y) < 1e-6
    # symmetry about the lubber
    xr, yr = widget._arc_band_point(30.0)
    xl, yl = widget._arc_band_point(330.0)          # -30
    assert abs((xr - cx) + (xl - cx)) < 1e-6        # mirror in x
    assert abs(yr - yl) < 1e-6                        # same bow
    assert xr > cx > xl                              # +rel right, -rel left
    # monotonic x across the sector
    assert widget._arc_band_point(10.0)[0] < widget._arc_band_point(50.0)[0]
    # forward clip: edge in, just past out, rear out
    assert widget._arc_in_sector(60.0) is True
    assert widget._arc_in_sector(61.0) is False
    assert widget._arc_in_sector(180.0) is False
    assert widget._arc_in_sector(300.0) is True     # -60
    # expanded scale: arc px/deg exceeds the rose's edge scale (r * pi/180)
    assert widget._arc_scale() > widget.r * math.pi / 180.0


def test_arc_band_point_tracks_heading(fix, qtbot):
    """The band is heading-referenced: a fixed world bearing moves across the arc
    as heading changes, and a bearing at the current heading stays at the lubber."""
    widget = hsi.HSI()
    qtbot.addWidget(widget)
    widget.orientation = "arc"
    widget.resize(300, 300)
    widget.show()
    qtbot.waitExposed(widget)
    cx = widget._arc_params()[0]
    widget._heading = 90.0
    x_ahead, _ = widget._arc_band_point(90.0)       # dead ahead
    assert abs(x_ahead - cx) < 1e-6
    x_right, _ = widget._arc_band_point(120.0)      # 30 deg right of nose
    assert x_right > cx
    assert widget._arc_in_sector(200.0) is False    # behind-ish, clipped


def test_arc_paint_never_raises_full_panel(fix, qtbot):
    """Arc paint with CDI+GSI, both bearing needles, heading bug and track diamond
    all live must not raise, and the source tap rect is still set (tappable)."""
    _define_bearing_keys(fix, brg1=45.0, src1=2.0, brg2=330.0, src2=0.0)
    widget = hsi.HSI(cdi_enabled=True, gsi_enabled=True)
    qtbot.addWidget(widget)
    widget.orientation = "arc"
    widget.bearing1_enabled = True
    widget.bearing2_enabled = True
    widget.heading_bug_enabled = True
    widget.resize(320, 320)
    widget.show()
    qtbot.waitExposed(widget)
    widget._HeadFail = widget._HeadBad = False
    widget._CdiOld = widget._CdiBad = widget._GsiOld = widget._GsiBad = widget._GsiFail = False
    for n in (1, 2):
        widget._brgOld[n] = widget._brgBad[n] = widget._brgFail[n] = False
    widget.setGsv(1)
    widget._hdgBug = 20.0
    widget._track = 350.0
    widget._TrackOld = widget._TrackBad = widget._TrackFail = False
    widget.navsrcdb = object()
    widget._navsrc = 2
    widget.paintEvent(QPaintEvent(widget.rect()))    # must not raise
    assert widget._showCDI is True
    assert widget._source_label_rect is not None      # nav-source tap target set


def test_arc_paint_never_raises_on_fail(fix, qtbot):
    """Arc paint annunciates a failed heading (red HDG flag) and does not raise;
    numerals are suppressed on fail, matching the rose path."""
    widget = hsi.HSI(cdi_enabled=True)
    qtbot.addWidget(widget)
    widget.orientation = "arc"
    widget.resize(300, 300)
    widget.show()
    qtbot.waitExposed(widget)
    widget.setHeadFail(True)
    widget.paintEvent(QPaintEvent(widget.rect()))    # must not raise
    assert widget._showHdgFlag is True


def test_arc_forward_clip_hides_rear_bearing(fix, qtbot):
    """A bearing needle whose station is behind the aircraft is clipped out of the
    arc (forward sector only), while a forward one is shown."""
    _define_bearing_keys(fix, brg1=10.0, src1=2.0, brg2=180.0, src2=2.0)
    widget = hsi.HSI()
    qtbot.addWidget(widget)
    widget.orientation = "arc"
    widget.bearing1_enabled = True
    widget.bearing2_enabled = True
    widget.resize(300, 300)
    widget.show()
    qtbot.waitExposed(widget)
    widget._HeadFail = widget._HeadBad = False
    for n in (1, 2):
        widget._brgOld[n] = widget._brgBad[n] = widget._brgFail[n] = False
    widget._heading = 0.0
    assert widget._arc_in_sector(widget._brg[1]) is True     # 10 deg ahead
    assert widget._arc_in_sector(widget._brg[2]) is False    # 180 behind
    widget.paintEvent(QPaintEvent(widget.rect()))            # must not raise


# --- Arc-mode CDI: course-bound, not screen-fixed (decision record, #133) ----

def test_arc_cdi_is_course_bound_not_screen_fixed(fix, qtbot):
    """Decision record for #133: this widget is an HSI, so its arc-mode CDI
    stays COURSE-BOUND (the deviation bar runs parallel to the course line and
    rotates with it) rather than adopting the Navigation Display idiom of a
    screen-fixed scale at the display edge. A screen-fixed scale would draw the
    same bar orientation regardless of the selected course; a course-bound one
    rotates the bar as COURSE changes. Assert the latter -- if arc mode is ever
    made screen-fixed, this test must be deliberately changed, not silently
    broken."""
    import math
    widget = hsi.HSI(cdi_enabled=True)
    qtbot.addWidget(widget)
    widget.orientation = "arc"
    widget.resize(300, 300)
    widget.show()
    qtbot.waitExposed(widget)
    widget._heading = 0.0
    widget._CdiOld = widget._CdiBad = False
    widget._courseDeviation = 0.5
    widget._showCDI = True
    ox, oy = widget._arc_params()[0], widget._arc_params()[2]

    def cdi_bar_angle(course):
        widget.coursePointer = course
        painter = mock.Mock()
        widget._draw_arc_course(painter, ox, oy)
        # The CDI bar is the second drawLine call: the first is the course
        # pointer shaft, the second (when _showCDI) is the deviation bar --
        # both share _draw_arc_course's local (ux, uy)/(px, py) frame.
        line = painter.drawLine.call_args_list[1].args[0]
        return math.atan2(line.y2() - line.y1(), line.x2() - line.x1())

    angle_ahead = cdi_bar_angle(0.0)     # course dead ahead
    angle_right = cdi_bar_angle(30.0)    # course 30 deg right of nose
    # A screen-fixed ND-style scale would hold this angle constant across a
    # COURSE change; course-bound HSI behaviour rotates it with the course.
    assert abs(angle_ahead - angle_right) > 0.1


def test_arc_bearing_label_hidden_when_pointer_clipped_out_of_sector(fix, qtbot):
    """Regression for #133: a valid bearing pointer clipped outside the
    forward sector must not leave its source label lit -- the label used to be
    gated only on the pointer being enabled and its data healthy, never on
    _arc_in_sector, so the display could read e.g. "1 GPS" with no pointer 1
    anywhere on screen. The label should disappear with its needle."""
    _define_bearing_keys(fix, brg1=10.0, src1=2.0, brg2=180.0, src2=2.0)
    widget = hsi.HSI()
    qtbot.addWidget(widget)
    widget.orientation = "arc"
    widget.bearing1_enabled = True
    widget.bearing2_enabled = True
    widget.resize(300, 300)
    widget.show()
    qtbot.waitExposed(widget)
    widget._HeadFail = widget._HeadBad = False
    for n in (1, 2):
        widget._brgOld[n] = widget._brgBad[n] = widget._brgFail[n] = False
    widget._heading = 0.0
    assert widget._arc_in_sector(widget._brg[1]) is True      # pointer 1: on screen
    assert widget._arc_in_sector(widget._brg[2]) is False     # pointer 2: clipped, valid data

    widget.paintEvent(QPaintEvent(widget.rect()))     # must not raise

    assert widget._brg_label_rect[1] is not None     # in-sector pointer keeps its label
    assert widget._brg_label_rect[2] is None          # clipped-but-valid pointer: no label


def test_arc_bearing_label_stays_when_invalid_regardless_of_sector(fix, qtbot):
    """Invalid bearing data still annunciates ("... X") even when the stale
    bearing happens to fall outside the forward sector -- the failure is real
    regardless of where a stale value points, so it must not be suppressed by
    the clipping fix above."""
    _define_bearing_keys(fix, brg1=180.0, src1=2.0)
    widget = hsi.HSI()
    qtbot.addWidget(widget)
    widget.orientation = "arc"
    widget.bearing1_enabled = True
    widget.resize(300, 300)
    widget.show()
    qtbot.waitExposed(widget)
    widget._heading = 0.0
    widget._brgOld[1] = True                          # stale -- invalid
    assert widget._arc_in_sector(widget._brg[1]) is False

    widget.paintEvent(QPaintEvent(widget.rect()))     # must not raise

    assert widget._brg_label_rect[1] is not None


# --- Nav-source tab on the HDG | MAG | CRS panel (pyEfis#140) ---------------

def _wcag_contrast(fg_rgb, bg_rgb):
    """Same WCAG 2.x formula as tests/instruments/test_readout_panel.py,
    duplicated locally (both fill colours here are opaque, so no source-over
    compositing step is needed)."""
    def _linear(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    def _luminance(rgb):
        r, g, b = (_linear(c) for c in rgb)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    l1, l2 = _luminance(fg_rgb), _luminance(bg_rgb)
    if l1 < l2:
        l1, l2 = l2, l1
    return (l1 + 0.05) / (l2 + 0.05)


def _expected_tab_rect(widget):
    """Recompute the pyEfis#140 geometry table independently of
    HSI._draw_source_tab, from the same inputs _draw_readouts uses."""
    from pyefis.instruments import helpers
    W = widget.width()
    g = widget._gutter
    ph = g * 0.76
    pw = widget.fontSize * 12.5
    px = W / 2.0 - pw / 2.0
    py = (g - ph) / 2.0
    rr = widget.fontSize * helpers.READOUT_RADIUS_RATIO
    top = py + rr
    height = ph - 2.0 * rr
    return px, top, height


def test_hsi_source_tab_geometry_matches_panel(fix, qtbot):
    """pyEfis#140 acceptance #2/#3: in the default `top_panel` layout the tab's
    height is the panel height less both corner radii, its top is the bottom
    of the panel's top-left arc, and its right edge sits flush at the panel's
    left edge (`px`) -- the formulas in HSI._draw_source_tab must match the
    #140 geometry table, not just "look right"."""
    widget = _mk_hsi(qtbot, font_percent=0.08)
    widget.navsrcdb = object()
    widget._navsrc = 2                              # GPS
    widget.paintEvent(QPaintEvent(widget.rect()))
    px, top, height = _expected_tab_rect(widget)
    r = widget._source_label_rect
    assert r is not None
    left, rtop, rw, rh = r
    assert rtop == pytest.approx(top)
    assert rh == pytest.approx(height)
    assert left + rw == pytest.approx(px)            # right edge flush, square


def test_hsi_source_tab_geometry_also_applies_in_arc_mode(fix, qtbot):
    """The tab is drawn by _draw_readouts, which both paint paths call -- the
    arc orientation must get the same tab, not the old floating label."""
    widget = _mk_hsi(qtbot, font_percent=0.08)
    widget.orientation = "arc"
    widget.navsrcdb = object()
    widget._navsrc = 0                               # VLOC1
    widget._navtype = None
    widget.paintEvent(QPaintEvent(widget.rect()))
    px, top, height = _expected_tab_rect(widget)
    r = widget._source_label_rect
    assert r is not None
    left, rtop, rw, rh = r
    assert rtop == pytest.approx(top)
    assert rh == pytest.approx(height)
    assert left + rw == pytest.approx(px)


@pytest.mark.parametrize("layout", ["corners", "split", "none"])
def test_hsi_non_top_panel_layouts_keep_floating_label(fix, qtbot, layout):
    """pyEfis#140 acceptance #6: corners/split/none draw no HDG | MAG | CRS
    panel, so they keep today's plain top-left label (not a tab) -- verified
    by checking the tap-target rect against the OLD label formula, distinct
    from the tab's panel-derived geometry."""
    widget = _mk_hsi(qtbot, font_percent=0.08)
    widget.readout_layout = layout
    widget.navsrcdb = object()
    widget._navsrc = 2
    widget.paintEvent(QPaintEvent(widget.rect()))
    r = widget._source_label_rect
    assert r is not None
    pad = int(widget.fontSize * 0.5)
    expected_x = qRound(widget.width() * 0.03) - pad
    assert r[0] == expected_x


def test_hsi_source_tab_tap_target_is_whole_tab(fix, qtbot, monkeypatch):
    """pyEfis#140 acceptance #5: the whole tab rect (not just the glyphs) is
    the tap target, and mousePressEvent still cycles NAVSRC unchanged."""
    widget = _mk_hsi(qtbot, font_percent=0.08)
    widget.navsrcdb = object()
    widget._navsrc = 2                               # GPS
    widget.paintEvent(QPaintEvent(widget.rect()))
    r = widget._source_label_rect
    assert r is not None

    written = []
    monkeypatch.setattr(hsi.fix.db, "set_value", lambda k, v: written.append((k, v)))

    class _P:
        def __init__(s, x, y): s._x, s._y = x, y
        def x(s): return s._x
        def y(s): return s._y

    class _Ev:
        def __init__(s, x, y): s._p = _P(x, y)
        def pos(s): return s._p
        def accept(s): pass

    # A point near the tab's rounded-left edge (not just its text glyphs).
    widget.mousePressEvent(_Ev(r[0] + 2, r[1] + r[3] / 2))
    assert written == [("NAVSRC", 0.0)]


def test_hsi_source_tab_white_on_source_colour_contrast(fix, qtbot):
    """pyEfis#140 acceptance #9: MEASURE (not just assert-pass) the white-on-
    magenta and white-on-green ratios against the WCAG 4.5:1 floor, the same
    pattern tests/instruments/test_readout_panel.py uses for the translucent
    readout fill. Both measure poor per the #140 fit/contrast note in
    docs/hsi_widget_spec.md sec 7.4 -- white text stands (Bill's call); if this
    is ever fixed, it will be via a darker fill, and this test's numbers are
    the ones that should move. Locked as a value assertion (not just `< 4.5`)
    so a silent fill-colour change gets caught here first."""
    widget = _mk_hsi(qtbot, font_percent=0.08)
    white = (255, 255, 255)
    magenta = QColor(widget.course_color).getRgb()[:3]
    green = QColor(widget.vloc_color).getRgb()[:3]
    gps_contrast = _wcag_contrast(white, magenta)
    vloc_contrast = _wcag_contrast(white, green)
    assert gps_contrast == pytest.approx(3.14, abs=0.02)
    assert vloc_contrast == pytest.approx(1.37, abs=0.02)
    assert gps_contrast < 4.5 and vloc_contrast < 4.5      # both fail the floor


# --------------------------------------------------------------------------
# Static-element drop shadow (AER-392 / pyEfis#142)
# --------------------------------------------------------------------------

def test_shadow_disabled_by_default(fix, qtbot):
    widget = hsi.HSI()
    qtbot.addWidget(widget)
    assert widget.shadow_enabled is False
    widget.resize(300, 300)
    widget.show()
    qtbot.waitExposed(widget)
    assert widget._rose_shadow_blur == 0.0
    widget.paintEvent(QPaintEvent(widget.rect()))     # must not raise


def test_shadow_reserves_rose_margin_and_bakes_halo_behind_disc(fix, qtbot):
    """Enabling the shadow shrinks the rose (clearance for the halo, gotcha
    #2) and bakes the halo via helpers.bake_blurred_silhouette (AER-439 --
    replaced a QGraphicsDropShadowEffect attached directly to the disc item,
    which had no way to punch its own shape back out of its own shadow, see
    test_shadow_rose_disc_translucent_fill_unchanged_by_shadow below) as its
    OWN scene item strictly behind the disc fill: z=-2 for the halo vs z=-1
    for the disc, so the disc's own fill is never composited over its own
    unpunched shadow."""
    plain = hsi.HSI()
    qtbot.addWidget(plain)
    plain.resize(400, 400)
    plain.show()
    qtbot.waitExposed(plain)

    shadowed = hsi.HSI()
    qtbot.addWidget(shadowed)
    shadowed.shadow_enabled = True
    shadowed.resize(400, 400)
    shadowed.show()
    qtbot.waitExposed(shadowed)

    assert shadowed._rose_shadow_blur > 0.0
    assert shadowed.r < plain.r                       # room reserved for the halo

    bgitems = [i for i in shadowed.scene.items()
               if isinstance(i, QGraphicsEllipseItem)]
    assert bgitems, "expected the compass-disc background item"
    assert bgitems[0].graphicsEffect() is None         # no per-item Qt effect anymore
    assert bgitems[0].zValue() == -1

    haloitems = [i for i in shadowed.scene.items()
                 if isinstance(i, QGraphicsPixmapItem)]
    assert haloitems, "expected a baked halo pixmap item behind the disc"
    assert haloitems[0].zValue() < bgitems[0].zValue()

    plain_haloitems = [i for i in plain.scene.items()
                       if isinstance(i, QGraphicsPixmapItem)]
    assert not plain_haloitems, "no halo item should exist with shadows off"


def test_shadow_rose_disc_translucent_fill_unchanged_by_shadow(fix, qtbot):
    """AER-439: the rose-disc shadow used a QGraphicsDropShadowEffect
    attached directly to the disc background item. Qt's effect draws the
    item's own source back on top of an UNPUNCHED blurred halo at zero
    offset, so on a translucent disc fill (bg_opacity between 0 and 100)
    that halo reads straight through and darkens the whole disc interior --
    the identical defect class AER-415 fixed in bake_blurred_silhouette,
    just via Qt's compositor instead of pyEfis's own. It does not show at
    bg_opacity 0 (no background item is even created) or bg_opacity 100
    (the opaque fill fully occludes the halo underneath it) -- only a
    partial opacity exercises it, per the AER-415 rose-disc probe
    (interior (160,180,202) shadow-off vs (137,151,167) shadow-on at
    bg_opacity 50, a uniform ~14% darkening).

    Fails on the pre-AER-439 QGraphicsDropShadowEffect-on-the-disc-item
    code (interior darkens), passes once the halo is baked+punched via
    bake_blurred_silhouette and drawn as its own item strictly behind the
    disc fill.
    """
    def _disc_interior_pixel(shadow_enabled):
        widget = hsi.HSI(font_percent=0.1, bg_color="#aaaaaa")
        qtbot.addWidget(widget)
        widget.bg_opacity = 50
        widget.shadow_enabled = shadow_enabled
        widget.resize(400, 400)
        widget.show()
        qtbot.waitExposed(widget)
        img = widget._rose_image()                    # unrotated 2x bake
        ss = 2
        # A point well inside the disc, away from ticks/labels/needles.
        x = int(widget.cx * ss + widget.r * ss * 0.5)
        y = int(widget.cy * ss)
        return img.pixelColor(x, y)

    off = _disc_interior_pixel(False)
    on = _disc_interior_pixel(True)
    assert (off.red(), off.green(), off.blue()) == (on.red(), on.green(), on.blue()), (
        f"disc interior tinted by its own shadow: shadow-off {off.getRgb()} "
        f"-> shadow-on {on.getRgb()}"
    )


def test_shadow_rose_halo_is_radially_symmetric(fix, qtbot, monkeypatch):
    """The disc shadow is baked into the SAME layer _rotated_rose_image()
    rotates per heading. A halo with any directional offset would make the
    implied light source appear to orbit as the card turns; sampling the
    halo ring at several angles around the UNROTATED bake and finding them
    alike proves it is symmetric, so any later rotation leaves it looking
    identical -- the two-heading acceptance criterion, made deterministic.

    The production blur ratio is subtle by design (a soft accent, not a
    heavy vignette); scaled up here via monkeypatch purely so the halo is
    a few pixels wide and trivially sampled -- the symmetry property being
    tested does not depend on the exact ratio.
    """
    from pyefis.instruments import helpers
    monkeypatch.setattr(helpers, "SHADOW_BLUR_RATIO", 0.5)

    widget = hsi.HSI(font_percent=0.1)
    qtbot.addWidget(widget)
    widget.shadow_enabled = True
    widget.resize(400, 400)
    widget.show()
    qtbot.waitExposed(widget)

    img = widget._rose_image()                        # unrotated 2x bake
    ss = 2
    cx, cy = widget.cx * ss, widget.cy * ss
    sample_r = widget.r * ss + widget._rose_shadow_blur * ss * 0.15

    alphas = []
    for deg in range(0, 360, 15):
        th = math.radians(deg)
        x = int(cx + sample_r * math.cos(th))
        y = int(cy + sample_r * math.sin(th))
        alphas.append(img.pixelColor(x, y).alpha())

    assert max(alphas) > 0                             # the halo is actually there
    assert max(alphas) - min(alphas) <= 10              # uniform within AA noise


def test_shadow_rotated_rose_matches_unrotated_in_halo_band(fix, qtbot, monkeypatch):
    """Direct two-heading check: the pre-rotated rose blit (what paintEvent
    actually draws) sampled in the halo band is the same at two headings
    45+ degrees apart -- the light does not appear to move. Blur scaled up
    for the same reason as the symmetry test above."""
    from pyefis.instruments import helpers
    monkeypatch.setattr(helpers, "SHADOW_BLUR_RATIO", 0.5)

    widget = hsi.HSI(font_percent=0.1)
    qtbot.addWidget(widget)
    widget.shadow_enabled = True
    widget.resize(400, 400)
    widget.show()
    qtbot.waitExposed(widget)

    sample_r = widget.r + widget._rose_shadow_blur * 0.25

    def halo_alphas(heading):
        widget._heading = heading
        img = widget._rotated_rose_image()
        alphas = []
        for deg in range(0, 360, 15):
            th = math.radians(deg)
            x = int(widget.cx + sample_r * math.cos(th))
            y = int(widget.cy + sample_r * math.sin(th))
            alphas.append(img.pixelColor(x, y).alpha())
        return alphas

    a0 = halo_alphas(0.0)
    a1 = halo_alphas(87.0)                              # > 45 deg apart
    assert max(a0) > 0 and max(a1) > 0
    for x, y in zip(sorted(a0), sorted(a1)):
        assert abs(x - y) <= 3                          # same halo, any heading


def test_shadow_readout_panel_shadow_bakes_once_and_caches(fix, qtbot):
    """Option 4: the panel shell shadow is baked ONCE and reused -- same rect
    -> same cached (image, pad); a geometry change invalidates it."""
    widget = hsi.HSI()
    qtbot.addWidget(widget)
    widget.shadow_enabled = True
    widget.resize(400, 400)
    widget.show()
    qtbot.waitExposed(widget)

    rect = QRectF(100, 100, 150, 60)
    radius = 10.0
    first = widget._readout_shadow_image(rect, radius)
    second = widget._readout_shadow_image(rect, radius)
    assert first is not None
    assert first is second                              # cache hit, no rebake

    moved = widget._readout_shadow_image(QRectF(90, 100, 150, 60), radius)
    assert moved is not None
    assert moved is not first


def test_shadow_readout_panel_shadow_none_without_clearance(fix, qtbot):
    """A rect flush against the widget edge has no room for the halo to
    resolve without hard-clipping (gotcha #2) -- no shadow is baked rather
    than clipping it into a square edge."""
    widget = hsi.HSI()
    qtbot.addWidget(widget)
    widget.shadow_enabled = True
    widget.resize(400, 400)
    widget.show()
    qtbot.waitExposed(widget)

    flush = widget._readout_shadow_image(QRectF(0, 0, 150, 60), 10.0)
    assert flush is None


def test_shadow_baked_silhouette_leaves_shape_interior_unchanged(qtbot):
    """AER-415: bake_blurred_silhouette must punch its own shape back out of
    the blurred halo. An unpunched (filled) silhouette blits a flat second
    layer under the readout panel's translucent fill (READOUT_FILL_ALPHA =
    0.62) and reads straight through, tinting the WHOLE interior instead of
    only the edge falloff -- exactly the regression Bill's PR-render
    arithmetic found (AER-412: shadow-on interior backed out to a second
    black layer at alpha 0.597 ~= SHADOW_ALPHA across the entire panel body).

    Composite the baked shadow under a translucent stand-in of the exact
    shape it was baked for and assert the interior is byte-for-byte
    unchanged from the no-shadow case -- only the halo OUTSIDE the shape's
    own edge may differ. Fails on the pre-punch-out bake, passes after.
    """
    from PyQt6.QtCore import QPointF
    from PyQt6.QtGui import QImage, QPainter
    from pyefis.instruments import helpers

    W, H = 200, 100
    rect = QRectF(10, 10, 160, 60)
    radius = 10.0
    blur = 8.0

    def paint_shape(p):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(Qt.GlobalColor.black))
        p.drawRoundedRect(rect, radius, radius)

    img, pad = helpers.bake_blurred_silhouette(W, H, paint_shape, blur)

    def render(with_shadow):
        canvas = QImage(W, H, QImage.Format.Format_ARGB32_Premultiplied)
        canvas.fill(QColor(150, 190, 235))     # opaque "sky" stand-in
        p = QPainter(canvas)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if with_shadow:
            p.drawImage(QPointF(-pad, -pad), img)
        helpers.draw_readout_panel(p, rect, radius, QColor("white"),
                                    fill_alpha=helpers.READOUT_FILL_ALPHA)
        p.end()
        return canvas

    no_shadow = render(False)
    with_shadow = render(True)

    cx, cy = int(rect.center().x()), int(rect.center().y())
    for dx in (-60, -30, 0, 30, 60):
        for dy in (-15, 0, 15):
            x, y = cx + dx, cy + dy
            assert no_shadow.pixelColor(x, y) == with_shadow.pixelColor(x, y), (
                f"interior pixel ({x},{y}) changed by the baked shadow: "
                f"{no_shadow.pixelColor(x, y).getRgb()} -> "
                f"{with_shadow.pixelColor(x, y).getRgb()}"
            )


@pytest.mark.parametrize("layout", ["top_panel", "corners", "split"])
def test_shadow_enabled_paint_never_raises_any_readout_layout(fix, qtbot, layout):
    widget = hsi.HSI(cdi_enabled=True, gsi_enabled=True)
    qtbot.addWidget(widget)
    widget.shadow_enabled = True
    widget.readout_layout = layout
    widget.resize(400, 400)
    widget.show()
    qtbot.waitExposed(widget)

    widget.paintEvent(QPaintEvent(widget.rect()))     # must not raise
