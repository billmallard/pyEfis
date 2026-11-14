import math
from unittest import mock

import pytest
from PyQt6.QtCore import Qt, QPointF, QRectF, qRound
from PyQt6.QtGui import QColor, QImage, QPaintEvent, QPainter, QPen
from PyQt6.QtWidgets import (
    QApplication, QGraphicsEllipseItem, QGraphicsPathItem, QGraphicsPixmapItem,
)

from pyefis.instruments import helpers, hsi
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
    widget._CdiFail = widget._GsiFail = False

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
    widget._CdiOld = widget._CdiBad = widget._CdiFail = widget._GsiOld = widget._GsiBad = widget._GsiFail = False

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
    fix.db.define_item("NAVSRC", "NAVSRC", "float", 0.0, 3.0, "", 0, "")
    widget.navsrcdb = object()             # simulate a panel with a nav source
    widget._navsrc = 2                      # GPS
    widget.paintEvent(QPaintEvent(widget.rect()))   # sets the tap rect
    assert widget._source_label_rect is not None

    # Record what is queued for fix-gateway, not the local value: a local
    # set_value() never left pyEfis (pyEfis #294), and a test patched on it
    # passed while the bench gateway never saw a tap (AER-5548).
    written = []
    monkeypatch.setattr(hsi.fix.db, "queue_out", lambda b: written.append(
        tuple(b.decode().split(";")[:2])))

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
    assert written == [("NAVSRC", "0.0")]  # GPS(2) -> NAV1(0)


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
    w._CdiOld = w._CdiBad = w._CdiFail = w._GsiOld = w._GsiBad = w._GsiFail = False
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
    w._CdiOld = w._CdiBad = w._CdiFail = w._GsiOld = w._GsiBad = w._GsiFail = False
    w.setGsv(0)
    w.paintEvent(QPaintEvent(w.rect()))
    assert w._showGSI is False
    assert w._showCDI is True


def test_hsi_cat_cdi_full_scale_boundary(fix, qtbot):
    """HSI-TC-060 | HSI-DEV-001 (edge) | The normalized CDI at +/-1.0 full-scale (and 0)
    paints without error and stays shown; the source owns full-scale (spec sec 4.2)."""
    w = _mk_hsi(qtbot, cdi_enabled=True)
    w._CdiOld = w._CdiBad = w._CdiFail = False
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


def test_hsi_cat_nav_flag_on_no_lateral_signal(fix, qtbot):
    """HSI-TC-104 | HSI-ANN-002 (no-signal case) | A localizer tuned but not received
    (CDIV=0, fix-gateway#20) removes the CDI bar and shows the NAV flag, instead of a
    centred bar from no signal. CDIV=1 shows the bar on its own quality; an absent
    CDIV (older gateway) leaves the CDI exactly as before."""
    w = _mk_hsi(qtbot, cdi_enabled=True, gsi_enabled=True)
    assert w.cdivdb is None and w._cdiv is None       # the fixture has no CDIV key
    w._CdiOld = w._CdiBad = w._CdiFail = False
    w.setCdi(0.0)                                     # the centred bar from #20

    w.paintEvent(QPaintEvent(w.rect()))               # absent -> own quality
    assert w._showCDI is True and w._showNavFlag is False

    w.setCdiv(0)                                      # tuned, not received
    w.paintEvent(QPaintEvent(w.rect()))
    assert w._showCDI is False
    assert w._showNavFlag is True

    w.setCdiv(1)                                      # receiving
    w.paintEvent(QPaintEvent(w.rect()))
    assert w._showCDI is True and w._showNavFlag is False

    w.setCdiv(0)
    w.setTofrom(1)                                    # no TO/FROM without a signal
    w.paintEvent(QPaintEvent(w.rect()))
    assert w._showCDI is False


def _count_colour(img, colour, xs, ys, tol=60):
    """Pixels in the box xs x ys within `tol` (summed RGB distance) of colour."""
    n = 0
    for y in ys:
        for x in xs:
            p = img.pixelColor(x, y)
            if (abs(p.red() - colour.red()) + abs(p.green() - colour.green())
                    + abs(p.blue() - colour.blue())) < tol:
                n += 1
    return n


def _mk_course_hsi(qtbot, orientation="heading_up"):
    """A CDI-enabled HSI on heading 000, course 000, centred CDI, every signal
    valid: the course pointer runs straight up through the centre and the
    deviation bar sits on it."""
    w = _mk_hsi(qtbot, cdi_enabled=True)
    w.orientation = orientation
    w._heading = 0.0
    w._courseSelect = 0.0
    w._courseDeviation = 0.0
    w._CdiOld = w._CdiBad = w._CdiFail = False
    w._CourseOld = w._CourseBad = w._CourseFail = False
    return w


def _rose_bar_pixels(w):
    # The bar's own span along the pointer axis: the pointer head and tail stop
    # at +/-bar, so only the deviation bar is drawn in this box.
    img = w.viewport().grab().toImage()
    xs = range(int(w.cx) - 3, int(w.cx) + 4)
    ys = range(int(w.cy - w.cdippw * 0.8), int(w.cy + w.cdippw * 0.8))
    return _count_colour(img, QColor(w._course_pointer_color()), xs, ys)


def _rose_pointer_head_pixels(w):
    img = w.viewport().grab().toImage()
    ext = w.r - w.fontSize * 2.0
    xs = range(int(w.cx) - 3, int(w.cx) + 4)
    ys = range(int(w.cy - ext), int(w.cy - w.cdippw * 1.2))
    return _count_colour(img, QColor(w._course_pointer_color()), xs, ys)


def test_hsi_g66_fail_only_cdi_removes_bar_under_nav_flag(fix, qtbot):
    """G66 (pyEfis#392) | HSI-ANN-002 + HSI-FAIL-001 (CDI fail) | A fail-only CDI
    (bad false, fail true -- the flight-plan engine failing GPS guidance on
    stale LAT/LONG) raises the NAV flag, and the bar is gone whenever NAV shows:
    no centred "on course" bar at the failed value of 0 under the flag. TO/FROM
    goes with it. The course pointer itself stays: COURSE is still valid."""
    w = _mk_course_hsi(qtbot)
    w.setTofrom(1)
    assert _rose_bar_pixels(w) > 0                    # control: valid -> bar drawn
    assert w._showCDI is True and w._showNavFlag is False

    w.setCdiFail(True)                                # bad stays False
    assert w._CdiBad is False
    assert _rose_bar_pixels(w) == 0
    assert w._showCDI is False and w._showNavFlag is True
    assert _rose_pointer_head_pixels(w) > 0           # course pointer unaffected


def test_hsi_g66_arc_fail_only_cdi_removes_bar(fix, qtbot):
    """G66 | the arc paint path applies the same rule: on a fail-only CDI the
    arc draws the course pointer shaft but no deviation bar."""
    w = _mk_course_hsi(qtbot, orientation="arc")
    ox, oy = w._arc_params()[0], w._arc_params()[2]

    def lines_drawn():
        w.paintEvent(QPaintEvent(w.rect()))           # sets _showCDI, NAV flag
        painter = mock.Mock()
        w._draw_arc_course(painter, ox, oy)
        return len(painter.drawLine.call_args_list)

    assert lines_drawn() == 2                         # pointer shaft + bar
    w.setCdiFail(True)
    assert lines_drawn() == 1                         # shaft only
    assert w._showCDI is False and w._showNavFlag is True


@pytest.mark.parametrize("flag", ["bad", "fail"])
def test_hsi_g66_invalid_course_hides_pointer_bar_and_dashes_crs(fix, qtbot, flag):
    """G66 | HSI-FAIL-001 (COURSE bad/fail) | A bad or failed COURSE has no
    direction: the course pointer and the bar rotated to it are not drawn at the
    failed value (000), and the CRS readout shows dashes instead of "000"."""
    w = _mk_course_hsi(qtbot)
    panels = []
    w._draw_readout_panel = lambda c, *a: panels.append(a[-1])
    assert _rose_pointer_head_pixels(w) > 0 and _rose_bar_pixels(w) > 0
    assert panels[-1][2][:2] == ("CRS", "000°")

    getattr(w, "setCourseBad" if flag == "bad" else "setCourseFail")(True)
    assert _rose_pointer_head_pixels(w) == 0
    assert _rose_bar_pixels(w) == 0
    assert w._showCDI is False
    assert panels[-1][2][:2] == ("CRS", "---°")

    w.orientation = "arc"
    ox, oy = w._arc_params()[0], w._arc_params()[2]
    w.paintEvent(QPaintEvent(w.rect()))
    painter = mock.Mock()
    w._draw_arc_course(painter, ox, oy)
    assert painter.drawLine.call_count == 0 and painter.drawPolygon.call_count == 0


@pytest.mark.parametrize("orientation", ["heading_up", "arc"])
@pytest.mark.parametrize("flag", ["bad", "fail"])
def test_hsi_g66_invalid_course_raises_nav_flag(fix, qtbot, orientation, flag):
    """G66 rework (Bill, 2026-11-08) | HSI-ANN-002 | A bad or failed COURSE
    removes the pointer and the bar, so it raises the NAV flag: the CRS dashes
    alone do not say why the pointer is gone."""
    w = _mk_course_hsi(qtbot, orientation=orientation)
    w.setCdiv(1)
    w.paintEvent(QPaintEvent(w.rect()))
    assert w._showNavFlag is False                    # control: all valid
    getattr(w, "setCourseBad" if flag == "bad" else "setCourseFail")(True)
    w.paintEvent(QPaintEvent(w.rect()))
    assert w._showCDI is False and w._showNavFlag is True


@pytest.mark.parametrize("orientation", ["heading_up", "arc"])
def test_hsi_g66_stale_cdi_raises_nav_flag(fix, qtbot, orientation):
    """G66 rework | A stale CDI removed the bar with no flag. It now raises NAV."""
    w = _mk_course_hsi(qtbot, orientation=orientation)
    w.setCdiOld(True)
    w.paintEvent(QPaintEvent(w.rect()))
    assert w._showCDI is False and w._showNavFlag is True


@pytest.mark.parametrize("orientation", ["heading_up", "arc"])
@pytest.mark.parametrize("gsv", [None, 1])
@pytest.mark.parametrize("flag", ["old", "bad", "fail"])
def test_hsi_g66_lost_glideslope_raises_gs_flag(fix, qtbot, orientation, gsv, flag):
    """G66 rework | HSI-ANN-003 | A stale, invalid or failed GSI with a
    glideslope expected removes the diamond and raises the GS flag. That holds
    with GSV absent (an older gateway) too, where the diamond already showed on
    its own quality but the flag needed GSV."""
    w = _mk_hsi(qtbot, cdi_enabled=True, gsi_enabled=True)
    w.orientation = orientation
    w._GsiOld = w._GsiBad = w._GsiFail = False
    w._gsv = gsv
    w.paintEvent(QPaintEvent(w.rect()))
    assert w._showGSI is True and w._showGsFlag is False
    setattr(w, {"old": "_GsiOld", "bad": "_GsiBad", "fail": "_GsiFail"}[flag], True)
    w.paintEvent(QPaintEvent(w.rect()))
    assert w._showGSI is False and w._showGsFlag is True


@pytest.mark.parametrize("orientation", ["heading_up", "arc"])
@pytest.mark.parametrize("flag", ["bad", "fail"])
def test_hsi_g66_failed_heading_raises_hdg_flag(fix, qtbot, orientation, flag):
    """G66 rework | HSI-ANN-001 | A bad or failed HEAD raises the HDG flag on
    both layouts."""
    w = _mk_course_hsi(qtbot, orientation=orientation)
    w._HeadOld = w._HeadBad = w._HeadFail = False
    w.paintEvent(QPaintEvent(w.rect()))
    assert w._showHdgFlag is False
    if flag == "bad":
        w.setHeadBad(True)
    else:
        w.setHeadFail(True)
    w.paintEvent(QPaintEvent(w.rect()))
    assert w._showHdgFlag is True


def test_hsi_g66_fail_change_after_a_second_resize_does_not_crash(fix, qtbot):
    """G66 | Every resize builds a new scene and frees the old one, but the
    label items stayed in self.labels; the next fail-flag change called
    setOpacity on freed items and segfaulted the whole process. Only the
    current scene's labels remain."""
    w = _mk_course_hsi(qtbot)
    first = len(w.labels)
    w.resize(320, 300)
    qtbot.wait(10)
    assert len(w.labels) == first
    w.setHeadFail(not w._HeadFail)                    # used to segfault here
    w.setCdiFail(not w._CdiFail)
    assert all(l.scene() is w.scene for l in w.labels)


@pytest.mark.parametrize("layout", ["top_panel", "corners", "split"])
def test_hsi_g66_rose_hdg_flag_clear_of_the_readouts(fix, qtbot, layout):
    """G66 rework | HSI-ANN-001 | The rose HDG flag was drawn at the top centre,
    where the readout panels (painted after the flags) covered it. It now sits
    inside the card, clear of every readout box in every layout."""
    w = _mk_course_hsi(qtbot)
    w.readout_layout = layout
    w.resize(301, 300)                                # real resize: re-lay the rose
    qtbot.wait(10)
    w.setHeadFail(True)
    spots = []
    real = w._draw_flag
    w._draw_flag = lambda c, text, x, y: (spots.append((text, x, y)),
                                          real(c, text, x, y))
    w.paintEvent(QPaintEvent(w.rect()))
    (x, y), = [(x, y) for t, x, y in spots if t == "HDG"]
    assert math.hypot(x - w.cx, y - w.cy) < w.r * 0.8        # inside the card
    for field, rects in w._edit_rects.items():
        box = QRectF(rects[0])
        assert not box.adjusted(-w.fontSize, -w.fontSize,
                                w.fontSize, w.fontSize).contains(QPointF(x, y)), field


@pytest.mark.parametrize("orientation", ["heading_up", "arc"])
def test_hsi_g66_no_symbol_removed_without_its_flag(fix, qtbot, orientation):
    """G66 rework invariant | Over every combination of CDI, COURSE, CDIV, GSI
    and GSV quality, the deviation bar is never removed without the NAV flag,
    and an expected GS diamond never without the GS flag."""
    import itertools
    w = _mk_hsi(qtbot, cdi_enabled=True, gsi_enabled=True)
    w.orientation = orientation
    states = {"valid": (False, False, False), "old": (True, False, False),
              "bad": (False, True, False), "fail": (False, False, True)}
    for cdi, crs, cdiv, gsi, gsv in itertools.product(
            states, ("valid", "bad", "fail"), (None, 0, 1), states, (None, 0, 1)):
        w._CdiOld, w._CdiBad, w._CdiFail = states[cdi]
        w._CourseBad, w._CourseFail = crs == "bad", crs == "fail"
        w._cdiv, w._gsv = cdiv, gsv
        w._GsiOld, w._GsiBad, w._GsiFail = states[gsi]
        w.paintEvent(QPaintEvent(w.rect()))
        assert w._showCDI or w._showNavFlag
        assert not (w._showCDI and w._showNavFlag)
        if gsv is None or gsv >= 0.5:
            assert w._showGSI or w._showGsFlag
            assert not (w._showGSI and w._showGsFlag)
        else:
            assert not w._showGSI and not w._showGsFlag


def test_hsi_g66_cdi_and_course_quality_setters_repaint(fix, qtbot):
    """G66 | a quality change alone (value unchanged) must repaint: the NAV flag
    and the bar removal otherwise wait for the next unrelated update."""
    w = _mk_course_hsi(qtbot)
    for setter in ("setCdiFail", "setCourseBad", "setCourseFail"):
        w.update = mock.Mock()
        getattr(w, setter)(True)
        assert w.update.called, setter


def test_hsi_cdiv_read_from_the_fix_key(fix, qtbot):
    """The widget reads a published CDIV at construction and follows its changes."""
    fix.db.define_item("CDIV", "CDI valid", "float", 0, 1, "", 2000, "")
    fix.db.set_value("CDIV", 0.0)
    w = _mk_hsi(qtbot, cdi_enabled=True)
    assert w.cdivdb is not None and w._cdiv == 0.0
    fix.db.set_value("CDIV", 1.0)
    assert w._cdiv == 1.0
    fix.db.set_value("CDIV", 0.0)
    assert w._cdiv == 0.0


def test_hsi_arc_layout_gates_cdi_on_cdiv(fix, qtbot):
    """The arc (ND-style) paint path applies the same CDIV gate as the rose."""
    w = _mk_hsi(qtbot, cdi_enabled=True)
    w.orientation = "arc"
    w._CdiOld = w._CdiBad = w._CdiFail = False
    w.setCdiv(0)
    w.paintEvent(QPaintEvent(w.rect()))
    assert w._showCDI is False and w._showNavFlag is True
    w.setCdiv(1)
    w.paintEvent(QPaintEvent(w.rect()))
    assert w._showCDI is True and w._showNavFlag is False


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
    widget._HeadFail = widget._HeadBad = False
    widget._brgOld[1] = widget._brgBad[1] = widget._brgFail[1] = False
    # available but not stepped on: Off is the default (HSIBRG1)
    assert widget._bearing_visible(1) is False
    widget._brgOn[1] = True
    # good state -> visible
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


@pytest.mark.parametrize("src", [0.0, 1.0, 2.0, None])
def test_bearing_color_is_cyan_whatever_the_source(fix, qtbot, src):
    """HSIBRG1: source colour is the CDI's alone (HSI-COLOR-001). A GPS
    bearing needle used to take the course pointer's magenta and read as the
    course pointer drawn twice; every needle is now bearing_color (cyan)."""
    _define_bearing_keys(fix, brg1=10.0, src1=2.0, brg2=20.0, src2=0.0)
    widget = hsi.HSI(font_percent=0.1)
    qtbot.addWidget(widget)
    widget._brgSrc[1] = src
    assert widget._bearing_color(1) == QColor(widget.bearing_color)
    assert widget._bearing_color(1) == QColor("#00ffff")
    assert widget._bearing_color(1) != QColor(widget.course_color)
    assert widget._bearing_color(1) != QColor(widget.vloc_color)


@pytest.mark.parametrize("navsrc, cycle", [
    (None, [0.0, 1.0, 2.0]),     # no NAVSRC: every source
    (2.0, [0.0, 1.0]),           # CDI on GPS: VOR1, VOR2
    (0.0, [1.0, 2.0]),           # CDI on NAV1: VOR2, GPS
    (1.0, [0.0, 2.0]),           # CDI on NAV2: VOR1, GPS
])
def test_bearing_cycle_steps_off_sources_off_skipping_the_cdi(fix, qtbot, navsrc, cycle):
    """A tap steps a pointer Off -> each source that is not the CDI's -> Off.
    A source step writes BRGnSRC; Off is the display's own state and leaves
    BRGnSRC alone."""
    _define_bearing_keys(fix, brg1=10.0, src1=2.0)
    widget = hsi.HSI(font_percent=0.1)
    qtbot.addWidget(widget)
    widget.bearing1_enabled = True
    widget._navsrc = navsrc
    assert widget._bearing_selected(1) is False             # Off by default
    seen = []
    for _ in cycle:
        widget._cycle_bearing_src(1)
        assert widget._bearing_selected(1) is True
        seen.append(fix.db.get_item("BRG1SRC").value)
    assert seen == cycle
    widget._cycle_bearing_src(1)                            # past the last -> Off
    assert widget._bearing_selected(1) is False
    assert fix.db.get_item("BRG1SRC").value == cycle[-1]    # untouched by Off
    widget._cycle_bearing_src(1)                            # and round again
    assert widget._bearing_selected(1) is True
    assert fix.db.get_item("BRG1SRC").value == cycle[0]


def test_bearing_cycle_needs_the_layout_switch_and_the_key(fix, qtbot):
    """bearingN_enabled is the layout switch that makes a pointer available
    at all; without it, or without BRGnSRC to carry the source, a tap does
    nothing."""
    _define_bearing_keys(fix, brg1=10.0, src1=0.0)
    widget = hsi.HSI(font_percent=0.1)
    qtbot.addWidget(widget)
    widget._cycle_bearing_src(1)
    assert widget._brgOn[1] is False
    widget.bearing2_enabled = True                 # BRG2SRC never defined
    widget._cycle_bearing_src(2)
    assert widget._brgOn[2] is False


@pytest.mark.parametrize("navsrc", [0.0, 1.0, 2.0])
def test_bearing_on_the_cdi_source_is_never_drawn(fix, qtbot, navsrc):
    """Bill's rule (HSIBRG1): no needle repeats the CDI. A pointer whose
    source becomes NAVSRC -- by a NAVSRC change or by BRGnSRC written
    elsewhere -- is turned Off, not just hidden, so it does not come back
    unasked when the CDI source moves on."""
    _define_bearing_keys(fix, brg1=10.0, src1=navsrc)
    widget = hsi.HSI(font_percent=0.1)
    qtbot.addWidget(widget)
    widget.bearing1_enabled = True
    widget._HeadFail = widget._HeadBad = False
    widget._brgOld[1] = widget._brgBad[1] = widget._brgFail[1] = False
    widget._brgSrc[1] = navsrc
    other = (navsrc + 1.0) % 3.0
    widget.setNavsrc(other)
    widget._brgOn[1] = True
    assert widget._bearing_visible(1) is True
    # the CDI moves onto the pointer's source
    widget.setNavsrc(navsrc)
    assert widget._bearing_visible(1) is False
    assert widget._brgOn[1] is False
    widget.setNavsrc(other)                        # moving away does not revive it
    assert widget._bearing_visible(1) is False
    # the pointer's source is written onto the CDI's from elsewhere
    widget._brgSrc[1] = (other + 1.0) % 3.0
    widget._brgOn[1] = True
    assert widget._bearing_visible(1) is True
    widget._setBrgSrc(1, other)
    assert widget._bearing_visible(1) is False
    assert widget._brgOn[1] is False
    # and the draw rule holds on its own, whatever path set the state
    widget._brgOn[1] = True
    widget._brgSrc[1] = navsrc
    widget._navsrc = navsrc
    assert widget._bearing_visible(1) is False


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
        widget._brgOn[n] = True
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
    widget._CdiOld = widget._CdiBad = widget._CdiFail = widget._GsiOld = widget._GsiBad = widget._GsiFail = False
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
        widget._brgOn[n] = True
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
        widget._brgOn[n] = True
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
    widget._brgOn[1] = True
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
    # Corner radius is keyed to the panel's OWN height (AER-413), not fontSize.
    rr = ph * helpers.READOUT_RADIUS_RATIO
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


def _corner_box(w, h_anchor, v_anchor):
    """The rect _draw_readout_box draws for a corner box (same formula)."""
    m = w.fontSize * 0.5
    bw, bh = w.fontSize * 3.6, w.fontSize * 2.4
    x = m if h_anchor == "l" else w.width() - m - bw
    y = m if v_anchor == "t" else w.height() - m - bh
    return QRectF(x, y, bw, bh)


@pytest.mark.parametrize("orientation", ["heading_up", "arc"])
def test_hsi_corners_source_label_is_not_hidden_under_the_hdg_box(fix, qtbot, orientation):
    """In corners the HDG box owns the top-left corner. The plain source
    label used to be drawn underneath it, hidden, with its tap target over
    most of the box; it now sits below the box."""
    widget = _mk_hsi(qtbot, font_percent=0.08)
    widget.readout_layout = "corners"
    widget.orientation = orientation
    widget.navsrcdb = object()
    widget._navsrc = 2
    widget.paintEvent(QPaintEvent(widget.rect()))
    label = QRectF(*widget._source_label_rect)
    box = _corner_box(widget, "l", "t")
    assert not label.intersects(box)
    assert label.top() >= box.bottom()


@pytest.mark.parametrize("orientation", ["heading_up", "arc"])
def test_hsi_split_bearing_labels_are_not_hidden_under_the_bottom_boxes(fix, qtbot, orientation):
    """In split the CRS and HDG boxes own the bottom corners; the bearing-
    source labels now sit above them instead of underneath."""
    widget = _mk_hsi(qtbot, font_percent=0.08)
    widget.readout_layout = "split"
    widget.orientation = orientation
    for n in (1, 2):
        setattr(widget, "bearing%d_enabled" % n, True)
        widget.brgdb[n] = object()
        widget.brgsrcdb[n] = object()
        widget._brgOn[n] = True
        widget._brg[n] = 0.0
        widget._brgOld[n] = widget._brgBad[n] = widget._brgFail[n] = False
        widget._brgSrc[n] = 0
    widget._HeadFail = widget._HeadBad = widget._HeadOld = False
    widget.paintEvent(QPaintEvent(widget.rect()))
    for n, h_anchor in ((1, "l"), (2, "r")):
        assert widget._brg_label_rect[n] is not None
        label = QRectF(*widget._brg_label_rect[n])
        assert not label.intersects(_corner_box(widget, h_anchor, "b")), n


def test_hsi_source_tab_tap_target_is_whole_tab(fix, qtbot, monkeypatch):
    """pyEfis#140 acceptance #5: the whole tab rect (not just the glyphs) is
    the tap target, and mousePressEvent still cycles NAVSRC unchanged."""
    widget = _mk_hsi(qtbot, font_percent=0.08)
    fix.db.define_item("NAVSRC", "NAVSRC", "float", 0.0, 3.0, "", 0, "")
    widget.navsrcdb = object()
    widget._navsrc = 2                               # GPS
    widget.paintEvent(QPaintEvent(widget.rect()))
    r = widget._source_label_rect
    assert r is not None

    # Record what is queued for fix-gateway, not the local value: a local
    # set_value() never left pyEfis (pyEfis #294), and a test patched on it
    # passed while the bench gateway never saw a tap (AER-5548).
    written = []
    monkeypatch.setattr(hsi.fix.db, "queue_out", lambda b: written.append(
        tuple(b.decode().split(";")[:2])))

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
    assert written == [("NAVSRC", "0.0")]


def _painted_source_label_pen(widget, px, py, ph):
    """Drive HSI._draw_source_tab directly against a real QPainter (needed for
    real fontMetrics(), unlike the bare mock.Mock() used for _draw_arc_course
    elsewhere in this file) and return the pen colour it left set -- drawText
    for the label is the method's last painter call, so painter.pen() after
    the call is exactly the label colour it used."""
    image = QImage(400, 400, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    try:
        widget._draw_source_tab(painter, px, py, ph)
        return QColor(painter.pen().color())
    finally:
        painter.end()


def test_hsi_source_tab_label_colour_is_derived_and_clears_wcag_floor(fix, qtbot):
    """pyEfis#147 (AER-473): white-on-source-colour used to measure 3.14:1
    (GPS/magenta) and 1.37:1 (VLOC/green) -- both WCAG AA fails, previously
    accepted as "Bill's call" pending a fix (superseded #140-era test). The
    label is now darkened from the tab's own fill via
    helpers.darken_to_contrast(), independently reproduced here, so both
    stock colours clear helpers.SOURCE_LABEL_MIN_CONTRAST (4.5:1)."""
    from pyefis.instruments import helpers
    widget = _mk_hsi(qtbot, font_percent=0.08)
    px, top, height = _expected_tab_rect(widget)

    for fill_hex, navsrc, navtype in (
        (widget.course_color, 2, None),      # GPS
        (widget.vloc_color, 0, None),        # VLOC1
    ):
        widget._navsrc, widget._navtype = navsrc, navtype
        painted = _painted_source_label_pen(widget, px, top, height)
        fill = QColor(fill_hex)
        expected = helpers.darken_to_contrast(fill)
        assert painted.getRgb()[:3] == expected.getRgb()[:3]
        assert painted.getRgb()[:3] != (255, 255, 255)     # no longer hardcoded white
        contrast = _wcag_contrast(painted.getRgb()[:3], fill.getRgb()[:3])
        assert contrast >= helpers.SOURCE_LABEL_MIN_CONTRAST


def test_hsi_source_tab_label_colour_tracks_custom_source_colour(fix, qtbot):
    """The derivation must be parametric, not two hardcoded dark hexes --
    vloc_color/course_color are config-selectable (pyEfis#147 anchor #1), so a
    custom source colour must still clear the same WCAG floor."""
    from pyefis.instruments import helpers
    widget = _mk_hsi(qtbot, font_percent=0.08)
    widget.vloc_color = "#00ccff"
    px, top, height = _expected_tab_rect(widget)
    widget._navsrc, widget._navtype = 0, None
    painted = _painted_source_label_pen(widget, px, top, height)
    fill = QColor(widget.vloc_color)
    assert _wcag_contrast(painted.getRgb()[:3], fill.getRgb()[:3]) >= helpers.SOURCE_LABEL_MIN_CONTRAST


def test_hsi_source_tab_fill_is_not_darkened(fix, qtbot):
    """HSI-COLOR-001: darkening is for the LABEL only -- the fill (the source
    annunciation itself) must stay at the configured, full-brightness colour
    so it still reads at a glance."""
    widget = _mk_hsi(qtbot, font_percent=0.08)
    widget._navsrc, widget._navtype = 2, None          # GPS
    assert widget._source_color() == QColor(widget.course_color)


def test_hsi_source_tab_width_is_constant_across_labels(fix, qtbot):
    """pyEfis#148 (AER-473): tab width must not track the current label -- it
    is the widest of GPS/VOR{n}/LOC{n}/VLOC{n} at the tab font, so the tab
    doesn't breathe as NAVSRC cycles and the label centring falls out for
    free (drawText already uses AlignCenter into (left, top, tab_w, th))."""
    widget = _mk_hsi(qtbot, font_percent=0.08)
    px, top, height = _expected_tab_rect(widget)

    def tab_width(navsrc, navtype=None):
        widget._navsrc, widget._navtype = navsrc, navtype
        image = QImage(400, 400, QImage.Format.Format_ARGB32)
        painter = QPainter(image)
        try:
            widget._draw_source_tab(painter, px, top, height)
        finally:
            painter.end()
        return widget._source_label_rect[2]

    widths = {
        "GPS": tab_width(2),
        "VOR1": tab_width(0, 1),
        "LOC1": tab_width(0, 2),
        "VLOC1": tab_width(0, None),
        "VLOC2": tab_width(1, None),
    }
    assert len(set(widths.values())) == 1, widths


# --- BRG tab: bearing-pointer selector on the panel's right edge (HSIBRG1) ---

class _TapPos:
    def __init__(self, x, y): self._x, self._y = x, y
    def x(self): return self._x
    def y(self): return self._y


class _Tap:
    def __init__(self, x, y): self._p = _TapPos(x, y)
    def pos(self): return self._p
    def position(self): return QPointF(self._p.x(), self._p.y())
    def accept(self): pass


def _mk_brg_hsi(qtbot, fix, pointers=(1,), **kw):
    _define_bearing_keys(fix, brg1=10.0, src1=2.0, brg2=20.0, src2=0.0)
    widget = _mk_hsi(qtbot, font_percent=0.05, **kw)
    for n in pointers:
        setattr(widget, "bearing%d_enabled" % n, True)
    widget._HeadFail = widget._HeadBad = widget._HeadOld = False
    widget.navsrcdb = object()
    widget._navsrc = 2                               # CDI on GPS
    return widget


def _tap_rect(widget, rect):
    x, y, w, h = rect
    widget.mousePressEvent(_Tap(x + w * 0.9, y + h * 0.5))


def test_brg_tab_only_when_a_pointer_is_available(fix, qtbot):
    widget = _mk_brg_hsi(qtbot, fix, pointers=())
    widget.paintEvent(QPaintEvent(widget.rect()))
    assert widget._brg_tab_rects == {}
    widget.bearing1_enabled = True
    widget.paintEvent(QPaintEvent(widget.rect()))
    assert list(widget._brg_tab_rects) == [1]
    widget.bearing2_enabled = True
    widget.paintEvent(QPaintEvent(widget.rect()))
    assert list(widget._brg_tab_rects) == [1, 2]
    widget.readout_layout = "corners"                 # no top panel, no tab
    widget.paintEvent(QPaintEvent(widget.rect()))
    assert widget._brg_tab_rects == {}


@pytest.mark.parametrize("orientation", ["heading_up", "arc"])
def test_brg_tab_mirrors_the_source_tab_on_the_right(fix, qtbot, orientation):
    """Same top and height as the nav-source tab, left edge flush with the
    panel's right edge; two pointers split that height into two rows."""
    widget = _mk_brg_hsi(qtbot, fix, pointers=(1, 2))
    widget.orientation = orientation
    widget.resize(600, 400)
    widget.paintEvent(QPaintEvent(widget.rect()))
    px, top, height = _expected_tab_rect(widget)
    pw = widget.fontSize * 12.5
    r1 = widget._brg_tab_rects[1]
    r2 = widget._brg_tab_rects[2]
    assert r1[0] == pytest.approx(px + pw) == r2[0]
    assert r1[1] == pytest.approx(top)
    assert r1[3] + r2[3] == pytest.approx(height)
    assert r2[1] == pytest.approx(top + r1[3])
    assert r1[0] + r1[2] <= widget.width()           # inside the widget


def test_brg_tab_labels(fix, qtbot):
    widget = _mk_brg_hsi(qtbot, fix, pointers=(1,))
    assert widget._bearing_tab_label(1, True) == "BRG OFF"
    widget._cycle_bearing_src(1)
    assert widget._bearing_tab_label(1, True) == "BRG1 VOR1"
    widget.bearing2_enabled = True
    assert widget._bearing_tab_label(2, False) == "BRG2 OFF"
    widget._navsrc = 0.0                                  # CDI on NAV1
    widget._brgOn[2] = True
    widget._brgSrc[2] = 2.0
    assert widget._bearing_tab_label(2, False) == "BRG2 GPS"


def test_brg_tab_tap_steps_that_rows_pointer(fix, qtbot, monkeypatch):
    """Each row is its own tap target: tapping row 2 steps pointer 2 only.
    A source step reaches fix-gateway (queued), not just the local copy."""
    widget = _mk_brg_hsi(qtbot, fix, pointers=(1, 2))
    sent = []
    monkeypatch.setattr(hsi.fix.db, "queue_out", lambda b: sent.append(
        tuple(b.decode().split(";")[:2])))
    widget.paintEvent(QPaintEvent(widget.rect()))
    _tap_rect(widget, widget._brg_tab_rects[2])
    assert widget._brgOn == {1: False, 2: True}
    assert fix.db.get_item("BRG2SRC").value == 0.0       # VOR1 (CDI is GPS)
    assert sent == []                                     # already VOR1
    widget.paintEvent(QPaintEvent(widget.rect()))
    _tap_rect(widget, widget._brg_tab_rects[1])
    assert widget._brgOn == {1: True, 2: True}
    assert fix.db.get_item("BRG1SRC").value == 0.0
    assert sent == [("BRG1SRC", "0.0")]                   # GPS -> VOR1, sent
    for _ in range(2):                                    # VOR2, then Off
        widget.paintEvent(QPaintEvent(widget.rect()))
        _tap_rect(widget, widget._brg_tab_rects[1])
    assert widget._brgOn == {1: False, 2: True}


def test_brg_corner_labels_with_and_without_the_tab(fix, qtbot):
    """Under top_panel the tab carries Off and a corner label only names an
    on pointer's source; without the top panel an Off pointer keeps a "1 OFF"
    corner label, which takes the tap."""
    widget = _mk_brg_hsi(qtbot, fix, pointers=(1,))
    widget.paintEvent(QPaintEvent(widget.rect()))
    assert widget._brg_label_rect[1] is None
    _tap_rect(widget, widget._brg_tab_rects[1])
    widget.paintEvent(QPaintEvent(widget.rect()))
    assert widget._bearing_corner_label(1) == ("1 VOR1", False)
    assert widget._brg_label_rect[1] is not None
    widget._brgOn[1] = False
    for layout in ("corners", "split", "none"):
        widget.readout_layout = layout
        widget.paintEvent(QPaintEvent(widget.rect()))
        assert widget._bearing_corner_label(1) == ("1 OFF", False)
        _tap_rect(widget, widget._brg_label_rect[1])
        assert widget._brgOn[1] is True, layout
        widget._brgOn[1] = False


def test_brg_needle_paint_uses_cyan_on_a_gps_cdi(fix, qtbot):
    """The case Bill reported: CDI on GPS with a GPS bearing pointer drew two
    magenta pointers at the waypoint. Now that pointer cannot be on; a VOR1
    pointer beside the GPS CDI paints in cyan, and no bearing pen is magenta."""
    widget = _mk_brg_hsi(qtbot, fix, pointers=(1,), cdi_enabled=True)
    widget.source_auto_color = True
    widget._brgOld[1] = widget._brgBad[1] = widget._brgFail[1] = False
    widget._brgSrc[1] = 2.0
    widget._brgOn[1] = True
    widget._drop_bearings_on_cdi_source()
    assert widget._bearing_visible(1) is False
    widget._cycle_bearing_src(1)                          # -> VOR1
    assert widget._bearing_visible(1) is True
    painter = mock.MagicMock()
    widget._draw_bearing_needle(painter, 1)
    pens = [call.args[0].color() for call in painter.setPen.call_args_list]
    assert pens and all(c == QColor("#00ffff") for c in pens)


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
    assert widget._rose_glow_width == 0.0
    widget.paintEvent(QPaintEvent(widget.rect()))     # must not raise


def test_shadow_draws_the_glow_ring_behind_the_disc(fix, qtbot):
    """The glow is its OWN scene item strictly behind the disc fill: z=-2 for
    the glow vs z=-1 for the disc, never a QGraphicsDropShadowEffect attached
    to the disc item (AER-439 -- Qt's effect draws the item's own source back
    over an unpunched halo, so it tints a translucent disc; see
    test_shadow_rose_disc_translucent_fill_unchanged_by_shadow below)."""
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

    assert shadowed._rose_glow_width > 0.0

    bgitems = [i for i in shadowed.scene.items()
               if isinstance(i, QGraphicsEllipseItem)]
    assert bgitems, "expected the compass-disc background item"
    assert bgitems[0].graphicsEffect() is None         # no per-item Qt effect anymore
    assert bgitems[0].zValue() == -1

    glowitems = [i for i in shadowed.scene.items()
                 if isinstance(i, QGraphicsPathItem)]
    assert glowitems, "expected the rim-glow ring item behind the disc"
    assert glowitems[0].zValue() < bgitems[0].zValue()

    plain_glowitems = [i for i in plain.scene.items()
                       if isinstance(i, QGraphicsPathItem)]
    assert not plain_glowitems, "no glow item should exist with shadows off"


def test_rim_glow_costs_no_radius_while_it_fits_the_edge_margin(fix, qtbot,
                                                                monkeypatch):
    """A glow narrower than ROSE_EDGE_MARGIN is free: the gap the rose already
    holds to the widget edge absorbs it, so the rose keeps its full radius.

    This is the pyEfis#158 guarantee, and it is what makes the reservation
    HONEST -- the rose gives up radius only when the glow genuinely has
    nowhere else to go, never as a fixed tax on enabling the option (the old
    code charged blur * SHADOW_CANVAS_PAD_RATIO unconditionally, 6.3% of the
    rose's area, for a halo nobody could see)."""
    monkeypatch.setattr(hsi, "ROSE_GLOW_WIDTH_RATIO", 0.02)

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

    assert 0.0 < shadowed._rose_glow_width <= hsi.ROSE_EDGE_MARGIN
    assert shadowed.r == plain.r


def test_shipped_rim_glow_width_is_wider_than_the_edge_margin(fix, qtbot):
    """The width actually shipped (ROSE_GLOW_WIDTH_RATIO, ~10px at panel
    scale) is DELIBERATELY wider than ROSE_EDGE_MARGIN, so it does cost the
    rose some radius -- a trade Bill accepted on the bench display, not an
    oversight. Pinned so that reading the two constants together cannot
    silently become a no-op again: if someone narrows the glow back under the
    margin, the sizing tests above still describe the truth but this one says
    the shipped look changed.

    At real panel geometry the rose is edge-constrained, so a wider glow
    cannot extend outward -- it grows inward and both widths end at the same
    outer edge. That is the whole content of the trade."""
    widget = hsi.HSI()
    qtbot.addWidget(widget)
    widget.shadow_enabled = True
    widget.resize(528, 402)                    # the HSI's real size on the panel
    widget.show()
    qtbot.waitExposed(widget)

    assert widget._rose_glow_width > hsi.ROSE_EDGE_MARGIN
    # ...and the reservation it triggers is exactly the overflow, no more.
    plain = hsi.HSI()
    qtbot.addWidget(plain)
    plain.resize(528, 402)
    plain.show()
    qtbot.waitExposed(plain)
    overflow = widget._rose_glow_width - hsi.ROSE_EDGE_MARGIN
    assert widget.r == pytest.approx(plain.r - overflow)
    # Both roses' glows still end at the same outer edge -- the rose is
    # edge-constrained, so widening only moves the glow's INNER limit.
    assert widget.r + widget._rose_glow_width == pytest.approx(
        plain.r + hsi.ROSE_EDGE_MARGIN)


def test_rim_glow_is_a_ring_that_never_covers_the_disc_interior(fix, qtbot):
    """The glow is clipped to an annulus, so the AER-415 guarantee holds
    geometrically rather than by punching a baked silhouette: there is simply
    nothing inside self.r for a translucent disc fill to read through. Assert
    it on the path's own geometry -- a filled circle here would tint the whole
    rose at any bg_opacity below 100."""
    widget = hsi.HSI()
    qtbot.addWidget(widget)
    widget.shadow_enabled = True
    widget.resize(400, 400)
    widget.show()
    qtbot.waitExposed(widget)

    glow = [i for i in widget.scene.items()
            if isinstance(i, QGraphicsPathItem)][0]
    path = glow.path()
    # Dead centre and most of the way to the rim must both be OUTSIDE the ring.
    assert not path.contains(QPointF(widget.cx, widget.cy))
    assert not path.contains(QPointF(widget.cx + widget.r * 0.9, widget.cy))
    # A point just past the disc edge must be INSIDE it.
    assert path.contains(
        QPointF(widget.cx + widget.r + widget._rose_glow_width * 0.5, widget.cy))


def test_rim_glow_width_scales_with_the_rose_not_the_label_font(fix, qtbot):
    """pyEfis#158 root cause: the rose blur was self.fontSize *
    SHADOW_BLUR_RATIO. That ratio is calibrated for the readout boxes, whose
    geometry really is font-derived; the rose is a widget-sized disc, so a
    font-derived blur came out around 1.75px against a ~160px radius and was
    invisible (<=1.7/255 outside the disc, and still invisible at 8x the
    font). Blur must track the rose's radius and ignore the label font."""
    big_font = hsi.HSI()
    qtbot.addWidget(big_font)
    big_font.shadow_enabled = True
    big_font.font_percent = 0.08
    big_font.resize(400, 400)
    big_font.show()
    qtbot.waitExposed(big_font)

    small_font = hsi.HSI()
    qtbot.addWidget(small_font)
    small_font.shadow_enabled = True
    small_font.font_percent = 0.02
    small_font.resize(400, 400)
    small_font.show()
    qtbot.waitExposed(small_font)

    # Same widget size, 4x the font: the glow must not move.
    assert big_font.fontSize != small_font.fontSize
    assert big_font._rose_glow_width == small_font._rose_glow_width
    # The width is taken from the rose radius BEFORE the clearance reservation
    # subtracts from it, so reconstruct that radius rather than asserting
    # against the final one -- at the shipped width the two differ.
    reserved = max(0.0, big_font._rose_glow_width - hsi.ROSE_EDGE_MARGIN)
    assert big_font._rose_glow_width == pytest.approx(
        (big_font.r + reserved) * hsi.ROSE_GLOW_WIDTH_RATIO)

    # ...and it must scale with the rose itself.
    larger = hsi.HSI()
    qtbot.addWidget(larger)
    larger.shadow_enabled = True
    larger.font_percent = 0.02
    larger.resize(800, 800)
    larger.show()
    qtbot.waitExposed(larger)
    assert larger._rose_glow_width > small_font._rose_glow_width


def test_shadow_reserves_only_the_overflow_past_the_edge_margin(fix, qtbot):
    """When the rose is large enough that its glow outgrows ROSE_EDGE_MARGIN,
    the reservation is exactly the overflow -- and no more. The glow's width is
    now literal (a gradient stop, not a Gaussian tail), so the reservation is
    simply the part the margin cannot absorb. Guards the pyEfis#158 3x
    over-reservation from coming back via SHADOW_CANVAS_PAD_RATIO."""
    plain = hsi.HSI()
    qtbot.addWidget(plain)
    plain.resize(800, 800)
    plain.show()
    qtbot.waitExposed(plain)

    shadowed = hsi.HSI()
    qtbot.addWidget(shadowed)
    shadowed.shadow_enabled = True
    shadowed.resize(800, 800)
    shadowed.show()
    qtbot.waitExposed(shadowed)

    width = plain.r * hsi.ROSE_GLOW_WIDTH_RATIO
    overflow = width - hsi.ROSE_EDGE_MARGIN
    assert overflow > 0, "pick a size where the glow actually outgrows the margin"
    assert shadowed.r == pytest.approx(plain.r - overflow)
    # Strictly cheaper than the pre-#158 reservation it replaces.
    assert shadowed.r > plain.r - width * helpers.SHADOW_CANVAS_PAD_RATIO


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

    pyEfis#158 moved the knob: the rose sizes its halo from its own radius
    (ROSE_GLOW_WIDTH_RATIO), not from the label font, so scaling
    helpers.SHADOW_BLUR_RATIO here no longer widens it -- that patch was
    silently inert and left this sampling the steep edge of a ~2px halo.
    """
    monkeypatch.setattr(hsi, "ROSE_GLOW_WIDTH_RATIO", 0.5)

    widget = hsi.HSI(font_percent=0.1)
    qtbot.addWidget(widget)
    widget.shadow_enabled = True
    widget.resize(400, 400)
    widget.show()
    qtbot.waitExposed(widget)

    img = widget._rose_image()                        # unrotated 2x bake
    ss = 2
    cx, cy = widget.cx * ss, widget.cy * ss
    sample_r = widget.r * ss + widget._rose_glow_width * ss * 0.15

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
    via the rose's own ratio, for the same reason as the symmetry test
    above (and see its note on pyEfis#158 moving that knob)."""
    monkeypatch.setattr(hsi, "ROSE_GLOW_WIDTH_RATIO", 0.5)

    widget = hsi.HSI(font_percent=0.1)
    qtbot.addWidget(widget)
    widget.shadow_enabled = True
    widget.resize(400, 400)
    widget.show()
    qtbot.waitExposed(widget)

    sample_r = widget.r + widget._rose_glow_width * 0.25

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
