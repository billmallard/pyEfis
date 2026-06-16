import pytest
from unittest import mock
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, qRound
from PyQt6.QtGui import QColor, QBrush, QPen, QFont, QPainter, QPaintEvent, QFontMetrics
from PyQt6 import QtGui
from pyefis.instruments import altimeter
import pyefis.hmi as hmi
from tests.utils import track_calls

funcAltitudeMeters = lambda x: x / 3.28084 
funcAltitudeFeet = lambda x: x             


@pytest.fixture
def app(qtbot):
    test_app = QApplication.instance()
    if test_app is None:
        test_app = QApplication([])
    return test_app


def test_altimeter(fix,qtbot):
    widget = altimeter.Altimeter()
    assert widget.getRatio() == 1
    qtbot.addWidget(widget)
    assert widget.item.value == 0
    widget.resize(200,200)
    widget.show()
    qtbot.waitExposed(widget)
    with track_calls(QPen, "setColor") as tracker:
        widget.paintEvent(None)
        assert tracker.was_called_with("setColor",QColor(Qt.GlobalColor.white))
        fix.db.get_item("ALT").bad = True
        widget.paintEvent(None)
        assert tracker.was_called_with("setColor",QColor(Qt.GlobalColor.gray))
        fix.db.get_item("ALT").bad = False
        fix.db.get_item("ALT").old = True
        widget.paintEvent(None)
        assert tracker.was_called_with("setColor",QColor(Qt.GlobalColor.gray))
        fix.db.get_item("ALT").old = False
        fix.db.get_item("ALT").fail = True
        with track_calls(QPainter, "setBrush") as tracker2:
            widget.paintEvent(None)
            assert tracker2.was_called_with("setBrush",QBrush(QColor(Qt.GlobalColor.red)))

def test_altimeter_unit_switching(fix,qtbot):
    hmi.initialize({})
    widget = altimeter.Altimeter()
    qtbot.addWidget(widget)
    assert widget.conversionFunction1(100) == 100
    assert widget.conversionFunction2(100) == 100
    assert widget.conversionFunction(100) == 100

    widget.conversionFunction1 = funcAltitudeFeet
    widget.unitsOverride1 = 'Ft'
    widget.conversionFunction2 = funcAltitudeMeters
    widget.unitsOverride2 = 'M'
    widget.unitGroup = 'Altitude'
    widget.setUnitSwitching()
    fix.db.get_item("ALT").value = 1100
    widget.resize(200,200)
    widget.show()
    qtbot.waitExposed(widget)
    widget.paintEvent(None)
    hmi.actions.trigger("Set Instrument Units","Altitude:Toggle")
    widget.paintEvent(None)
    assert widget._altimeter != 1100
    hmi.actions.trigger("Set Instrument Units","Altitude:Toggle")
    assert widget._altimeter == 1100
    # Test branches that should do nothing:
    hmi.actions.trigger("Set Instrument Units","Altitude:Toggl")
    hmi.actions.trigger("Set Instrument Units","IAS:Toggle")

    assert widget.getAltimeter() == 1100


def test_altimeter_tape(fix,qtbot):
    widget = altimeter.Altimeter_Tape()
    widget.redraw()
    qtbot.addWidget(widget)
    assert widget.item.value == 0
    assert widget.pph == 0.3
    widget = altimeter.Altimeter_Tape(font_percent=0.5)
    qtbot.addWidget(widget)
    assert widget.pph != 0.3
    widget.resize(100,200)
    widget.show()
    qtbot.waitExposed(widget)
    widget.font_mask = None
    widget.resize(90,200)
    #widget.paintEvent(None)


def test_altimeter_tape_honors_div_options(fix, qtbot):
    """The tape's tick spacing / decimals / mask are configurable; they used to
    be hardcoded, so YAML options like minorDiv were silently ignored."""
    widget = altimeter.Altimeter_Tape(
        majorDiv=500, minorDiv=200, total_decimals=3, font_mask="000")
    qtbot.addWidget(widget)
    assert widget.majorDiv == 500
    assert widget.minorDiv == 200
    assert widget.total_decimals == 3
    assert widget.font_mask == "000"
    # defaults preserved when not supplied
    d = altimeter.Altimeter_Tape()
    qtbot.addWidget(d)
    assert (d.majorDiv, d.minorDiv, d.total_decimals) == (200, 100, 5)


def test_build_altimeter_tape_forwards_options(monkeypatch):
    """build_altimeter_tape must forward the supported tape options (and only
    those present) to the widget — the bug was that only dbkey was passed."""
    from pyefis.screens import screenbuilder_factory as sf
    captured = {}

    def fake_tape(screen, **kwargs):
        captured.update(kwargs)
        return mock.Mock()

    monkeypatch.setattr(sf.altimeter, "Altimeter_Tape", fake_tape)
    sf.build_altimeter_tape(None, {"options": {
        "dbkey": "VS", "minorDiv": 50, "majorDiv": 100,
        "total_decimals": 5, "font_mask": "00000"}}, font_family="DejaVu")
    assert captured["dbkey"] == "VS"
    assert captured["minorDiv"] == 50 and captured["majorDiv"] == 100
    assert captured["total_decimals"] == 5 and captured["font_mask"] == "00000"

    # a config that omits the div keys forwards none of them (defaults apply)
    captured.clear()
    sf.build_altimeter_tape(None, {"options": {"dbkey": "ALT"}}, font_family="x")
    assert captured.get("dbkey") == "ALT"
    assert "minorDiv" not in captured and "majorDiv" not in captured


def test_altimeter_tape_unit_switching(fix,qtbot):
    hmi.initialize({})
    widget = altimeter.Altimeter_Tape()
    qtbot.addWidget(widget)
    assert widget.conversionFunction1(100) == 100
    assert widget.conversionFunction2(100) == 100
    assert widget.conversionFunction(100) == 100

    widget.conversionFunction1 = funcAltitudeFeet
    widget.unitsOverride1 = 'Ft'
    widget.conversionFunction2 = funcAltitudeMeters
    widget.unitsOverride2 = 'M'
    widget.unitGroup = 'Altitude'
    fix.db.get_item("ALT").value = 1100
    widget.resize(200,200)
    widget.show()
    qtbot.waitExposed(widget)
    widget.setUnitSwitching()
    event = QPaintEvent(widget.rect())
    widget.paintEvent(event)
    hmi.actions.trigger("Set Instrument Units","Altitude:Toggle")
    widget.paintEvent(event)
    assert widget._altimeter != 1100
    hmi.actions.trigger("Set Instrument Units","Altitude:Toggle")
    assert widget._altimeter == 1100
    # Test branches that should do nothing:
    hmi.actions.trigger("Set Instrument Units","Altitude:Toggl")
    hmi.actions.trigger("Set Instrument Units","IAS:Toggle")

    assert widget.getAltimeter() == 1100
    widget.paintEvent(event)
    widget.setUnitSwitching()
    widget.keyPressEvent(None)
    widget.wheelEvent(None)
    widget.hide()
    widget.setUnitSwitching()
