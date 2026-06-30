from unittest import mock

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPaintEvent, QPen
from PyQt6.QtWidgets import QApplication

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
