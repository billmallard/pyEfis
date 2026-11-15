import pytest
from unittest import mock
from PyQt6.QtWidgets import (
    QApplication, QGraphicsRectItem, QGraphicsLineItem,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QBrush, QPaintEvent
from pyefis.instruments import airspeed
import pyefis.hmi as hmi


@pytest.fixture
def app(qtbot):
    test_app = QApplication.instance()
    if test_app is None:
        test_app = QApplication([])
    return test_app

def test_aux_not_set_for_airspeed(fix, qtbot):
    fix.db.get_item("IAS").set_aux_value("Vs", None)
    fix.db.get_item("IAS").set_aux_value("Vs0", None)
    fix.db.get_item("IAS").set_aux_value("Vno", None)
    fix.db.get_item("IAS").set_aux_value("Vne", None)
    fix.db.get_item("IAS").set_aux_value("Vfe", None)
    widget = airspeed.Airspeed()
    assert widget.Vs == 0
    assert widget.Vs0 == 0
    assert widget.Vno == 0
    assert widget.Vne == 200
    assert widget.Vfe == 0

def test_aux_not_set_for_airspeed_tape(fix, qtbot):
    fix.db.get_item("IAS").set_aux_value("Vs", None)
    fix.db.get_item("IAS").set_aux_value("Vs0", None)
    fix.db.get_item("IAS").set_aux_value("Vno", None)
    fix.db.get_item("IAS").set_aux_value("Vne", None)
    fix.db.get_item("IAS").set_aux_value("Vfe", None)
    widget = airspeed.Airspeed_Tape()
    assert widget.Vs == 0
    assert widget.Vs0 == 0
    assert widget.Vno == 0
    assert widget.Vne == 200
    assert widget.Vfe == 0

def test_numerical_airspeed(fix, qtbot):
    widget = airspeed.Airspeed()
    assert widget.getRatio() == 1
    qtbot.addWidget(widget)
    widget.resize(201, 200)
    widget.show()
    qtbot.waitExposed(widget)
    qtbot.wait(500)
    widget.resize(200, 201)
    widget.paintEvent(None)
    assert widget.item.key == "IAS"
    assert widget.Vs == 45
    fix.db.get_item("IAS").fail = True
    fix.db.get_item("IAS").fail = False
    fix.db.get_item("IAS").old = True
    fix.db.get_item("IAS").old = False
    fix.db.set_value("IAS", "20")
    widget.paintEvent(None)
    widget.setAsOld(True)
    widget.setAsBad(True)
    widget.setAsFail(True)
    assert widget.getAirspeed() == 20
    # Test branch
    widget.setAirspeed(20)
    widget.setAirspeed(41)
    assert widget._airspeed == 41
    qtbot.wait(200)


def test_numerical_airspeed_tape(qtbot):
    widget = airspeed.Airspeed_Tape(font_percent=0.5)
    qtbot.addWidget(widget)
    widget.redraw()
    widget.resize(50, 200)
    widget.show()
    event = QPaintEvent(widget.rect())
    widget.paintEvent(event)
    assert widget.Vs0 == 40
    assert widget.getAirspeed() == 20
    widget.setAirspeed(40)  # redraw()
    widget.keyPressEvent(None)
    widget.wheelEvent(None)
    assert widget._airspeed == 40
    # Test branch
    widget.setAirspeed(40)
    widget.setAirspeed(41)
    assert widget._airspeed == 41


def test_airspeed_tape_without_font_percent_uses_default_font_size(qtbot):
    widget = airspeed.Airspeed_Tape()
    qtbot.addWidget(widget)

    widget.font_mask = ""
    widget.resize(80, 200)
    widget.resizeEvent(None)

    assert widget.font_percent is None
    assert widget.fontsize == 15
    assert widget.scene is not None
    assert widget.numerical_display.value == widget._airspeed


def test_airspeed_tape_resize_twice_connects_signals_once(fix, qtbot):
    """Regression (#45): Airspeed_Tape connects its IAS FIX signals inside
    resizeEvent, which Qt fires repeatedly. Re-connecting on every resize with
    Qt.ConnectionType.UniqueConnection raised TypeError inside the Qt virtual
    and aborted the process under PyQt6; a bare re-connect would instead stack
    duplicate slots. Firing resizeEvent several times must not raise and must
    leave exactly one connection."""
    widget = airspeed.Airspeed_Tape()
    qtbot.addWidget(widget)
    widget.font_mask = ""

    # Spy on the IAS value slot before any connection is made.
    calls = []
    widget.setAirspeed = lambda v: calls.append(v)

    widget.resize(80, 300)
    widget.resizeEvent(None)   # connects the (spied) IAS signals
    widget.resizeEvent(None)   # would raise TypeError under UniqueConnection
    widget.resizeEvent(None)
    assert widget._signals_connected is True

    # Exactly one connection: a single value change fires the slot once.
    calls.clear()
    fix.db.set_value("IAS", 123.0)
    assert calls == [123.0]


def test_numerical_airspeed_box(fix, qtbot):
    hmi.initialize({})
    widget = airspeed.Airspeed_Box()
    qtbot.addWidget(widget)
    widget.resize(50, 50)
    widget.show()
    fix.db.set_value("TAS", 100)
    widget.setMode(1)
    widget.setMode(0)
    assert widget.modeText == "TAS"
    assert widget.valueText == "100"
    fix.db.set_value("GS", 80)
    widget.setMode(1)
    assert widget.modeText == "GS"
    assert widget.valueText == "80"
    assert widget._modeIndicator == 1
    fix.db.set_value("IAS", 140)
    widget.setMode(2)
    assert widget.modeText == "IAS"
    assert widget.valueText == "140"
    widget.setMode("")
    assert widget._modeIndicator == 0
    widget.setMode("")
    assert widget._modeIndicator == 1
    widget.setMode("")
    assert widget._modeIndicator == 2
    widget.setMode("")
    assert widget._modeIndicator == 0
    widget.setMode(0)
    fix.db.get_item("TAS").fail = True
    fix.db.set_value("TAS", 101)
    assert widget.valueText == "XXX"
    fix.db.get_item("TAS").fail = False
    fix.db.get_item("TAS").bad = True
    fix.db.set_value("TAS", 102)
    assert widget.valueText == ""
    widget.paintEvent(None)


def test_airspeed_box_explicit_ias_mode_and_hidden_updates(fix, qtbot):
    hmi.initialize({})
    widget = airspeed.Airspeed_Box()
    qtbot.addWidget(widget)
    widget.resize(50, 50)

    widget.update = mock.Mock()
    widget.setMode(2)

    assert widget._modeIndicator == 2
    assert widget.modeText == "IAS"
    assert widget.fix_item.key == "IAS"
    assert widget.valueText == "110"

    widget.setMode(99)
    assert widget._modeIndicator == 2
    assert widget.modeText == "IAS"

    widget.setASData(111.4)

    assert widget.valueText == "111"
    widget.update.assert_called()


# =============================================================================
# Airspeed-tape requirements test catalog -- keyed to airspeed_widget_spec.md
# sec 4 (Markings, Awareness Cues & Annunciation) and avionics_reference.md sec 6.
#
# Docstrings: AS-TC-NNN | requirement ID | intent.
# Passing tests verify shipped behaviour. The xfail(strict) tests are the
# executable gap tracker for the unimplemented low/high-speed red awareness
# bands (AC 23.1311-1C sec 17.7.1): they fail today and flip the run red when
# the band is implemented, forcing removal of the marker. Spec sec 5 carries the
# case<->requirement map. The fix fixture seeds IAS aux V-speeds: Vs=45, Vs0=40,
# Vno=125, Vne=140, Vfe=70.
# =============================================================================


def _show_tape(qtbot, **kwargs):
    """Build a tape and drive resizeEvent so the QGraphicsScene (arcs, bands,
    ticks) is constructed at a real size."""
    widget = airspeed.Airspeed_Tape(**kwargs)
    qtbot.addWidget(widget)
    widget.resize(120, 400)
    widget.show()
    qtbot.waitExposed(widget)
    return widget


def _rect_rgb(widget):
    """(r,g,b) of every filled rect item in the scene."""
    return [it.brush().color().getRgb()[:3]
            for it in widget.scene.items() if isinstance(it, QGraphicsRectItem)]


def _green_rect(widget):
    """Scene rect of the single green normal-operating arc, found by colour."""
    greens = [it for it in widget.scene.items() if isinstance(it, QGraphicsRectItem)
              and it.brush().color().getRgb()[:3] == (0, 155, 0)]
    assert len(greens) == 1
    return greens[0].sceneBoundingRect()


def _tape_y(widget, v):
    """The tape's own speed -> scene-y mapping."""
    tape_start = widget.max * widget.pph + widget.height() / 2
    return -v * widget.pph + tape_start


def test_as_cat_moving_scale_tape_format(fix, qtbot):
    """AS-TC-001 | AS-DISP-001 | Moving-scale tape: a scrolling scale under a fixed pointer
    with a digital read-out; the scale scrolls with IAS. AC 23.1311-1C sec 17.6 (p.40)."""
    widget = _show_tape(qtbot)
    assert widget.scene is not None                       # a scale was built
    assert widget.numerical_display is not None           # digital read-out
    assert widget.max == int(round(widget.Vne * 1.25))    # tape spans past VNE

    # Present value drives the read-out and scrolls the scale.
    widget.setAirspeed(90)
    assert widget.numerical_display.value == 90
    assert widget.getAirspeed() == 90


def test_as_cat_conventional_vspeed_arcs(fix, qtbot):
    """AS-TC-002 | AS-MARK-001 | Conventional arcs are present: white flap arc, green
    normal arc, yellow caution arc, and a red VNE radial. sec 23.1545; sec 22.2 Table 4."""
    widget = _show_tape(qtbot)
    rgb = _rect_rgb(widget)
    assert (0, 155, 0) in rgb                              # green normal-operating arc
    assert (255, 255, 0) in rgb                            # yellow caution arc (VNO->VNE)
    assert (255, 255, 255) in rgb                          # white flap arc (VS0->VFE)
    # Red VNE radial line.
    red_lines = [it for it in widget.scene.items()
                 if isinstance(it, QGraphicsLineItem)
                 and it.pen().color().getRgb()[:3] == (255, 0, 0)]
    assert red_lines


def test_as_cat_green_arc_starts_at_vs1(fix, qtbot):
    """AS-TC-004 | AS-MARK-001 | The green normal-operating arc runs from VS1 (the IAS aux
    "Vs", clean stall) up to VNO, not from VS0. sec 23.1545(b)(3); pyEfis #396."""
    assert fix.db.get_item("IAS").get_aux_value("Vs") == 45   # fixture: Vs=45, Vs0=40
    widget = _show_tape(qtbot)
    r = _green_rect(widget)
    assert r.bottom() == pytest.approx(_tape_y(widget, 45), abs=1)    # from VS1
    assert r.top() == pytest.approx(_tape_y(widget, widget.Vno), abs=1)  # up to VNO


def test_as_cat_green_arc_falls_back_to_vs0_without_vs(fix, qtbot):
    """AS-TC-005 | AS-MARK-001 | With "Vs" unset the green arc's lower edge falls back to
    VS0 rather than running down to 0. pyEfis #396."""
    fix.db.get_item("IAS").set_aux_value("Vs", None)
    widget = _show_tape(qtbot)
    assert widget.Vs == 0
    r = _green_rect(widget)
    assert r.bottom() == pytest.approx(_tape_y(widget, 40), abs=1)    # VS0
    assert r.top() == pytest.approx(_tape_y(widget, widget.Vno), abs=1)


def test_as_cat_airspeed_invalid_annunciation(fix, qtbot):
    """AS-TC-003 | AS-ANN-001 | Invalid airspeed is annunciated on the read-out: fail ->
    XXX, old/bad -> not a stale number. AC 23.1311-1C sec 18; ref sec 2 governing rule."""
    widget = _show_tape(qtbot)
    widget.setAsFail(True)
    assert widget.numerical_display.fail is True
    widget.setAsFail(False)
    widget.setAsOld(True)
    assert widget.numerical_display.old is True
    widget.setAsBad(True)
    assert widget.numerical_display.bad is True


def test_as_cat_low_speed_red_band(fix, qtbot):
    """AS-TC-101 | AS-LSA-001 | A moving-scale tape must show a red band from VSO down to
    zero for low-speed awareness. AC 23.1311-1C sec 17.7.1.a (Fig 2, p.40-41). Contract:
    resizeEvent builds w.low_speed_band spanning y(Vs0)..y(0), red-filled."""
    widget = _show_tape(qtbot)
    band = getattr(widget, "low_speed_band", None)
    assert band is not None
    assert band.brush().color().getRgb()[:3] == (255, 0, 0)          # red
    r = band.sceneBoundingRect()
    assert r.top() == pytest.approx(_tape_y(widget, widget.Vs0), abs=3)   # from VSO
    assert r.bottom() == pytest.approx(_tape_y(widget, 0), abs=3)         # down to 0


def test_as_cat_high_speed_red_band(fix, qtbot):
    """AS-TC-102 | AS-HSA-001 | A moving-scale tape must show a red band (not just a
    hairline radial) from VNE up to the top of the tape. AC 23.1311-1C sec 17.7.1.b
    (Fig 2, p.40-41). Contract: resizeEvent builds w.high_speed_band spanning y(Vne)..0."""
    widget = _show_tape(qtbot)
    band = getattr(widget, "high_speed_band", None)
    assert band is not None
    assert band.brush().color().getRgb()[:3] == (255, 0, 0)          # red
    r = band.sceneBoundingRect()
    assert r.bottom() == pytest.approx(_tape_y(widget, widget.Vne), abs=3)  # from VNE
    assert r.top() == pytest.approx(0, abs=3)                               # up to tape top


# --- CERT1d: Airspeed_Box quality flags and the failed-IAS rule for TAS -----

def _show_box(qtbot, mode):
    hmi.initialize({})
    widget = airspeed.Airspeed_Box()
    qtbot.addWidget(widget)
    widget.resize(50, 50)
    widget.show()
    widget.setMode(mode)
    return widget


@pytest.mark.parametrize("mode,key", [(0, "TAS"), (1, "GS"), (2, "IAS")])
@pytest.mark.parametrize("flag,text", [("fail", "XXX"), ("old", ""), ("bad", "")])
def test_airspeed_box_flag_change_with_steady_value(fix, qtbot, mode, key, flag, text):
    """CERT1d: a flag that changes while the value holds steady repaints the
    box at once, and clearing it brings the number back."""
    fix.db.set_value(key, 97)
    widget = _show_box(qtbot, mode)
    assert widget.valueText == "97"
    widget.update = mock.Mock()
    setattr(fix.db.get_item(key), flag, True)
    assert widget.valueText == text
    widget.update.assert_called()
    setattr(fix.db.get_item(key), flag, False)
    assert widget.valueText == "97"


@pytest.mark.parametrize("flag", ["fail", "old"])
def test_airspeed_box_no_tas_under_failed_or_old_ias(fix, qtbot, flag):
    """CERT1d: in TAS mode the box shows no TAS under a failed or expired IAS,
    the tape's TAS-box rule (CERT1b), and the number returns with IAS."""
    fix.db.set_value("TAS", 120)
    widget = _show_box(qtbot, 0)
    assert widget.valueText == "120"
    setattr(fix.db.get_item("IAS"), flag, True)
    assert widget.valueText == "---"
    fix.db.set_value("TAS", 121)
    assert widget.valueText == "---"
    setattr(fix.db.get_item("IAS"), flag, False)
    assert widget.valueText == "121"


def test_airspeed_box_tas_rule_scope(fix, qtbot):
    """CERT1d: a suspect (bad) IAS does not blank TAS, as on the tape; GS does
    not come off the pitot and keeps its number under a failed IAS; a failed
    TAS itself still reads XXX."""
    fix.db.set_value("TAS", 120)
    fix.db.set_value("GS", 130)
    widget = _show_box(qtbot, 0)
    fix.db.get_item("IAS").bad = True
    assert widget.valueText == "120"
    fix.db.get_item("IAS").bad = False
    fix.db.get_item("IAS").fail = True
    widget.setMode(1)
    assert widget.valueText == "130"
    widget.setMode(0)
    assert widget.valueText == "---"
    fix.db.get_item("TAS").fail = True
    assert widget.valueText == "XXX"


def test_airspeed_box_constructed_under_failed_key(fix, qtbot):
    """CERT1d: a box built while its key is already failed starts at XXX,
    not at the frozen number."""
    fix.db.set_value("TAS", 120)
    fix.db.get_item("TAS").fail = True
    hmi.initialize({})
    widget = airspeed.Airspeed_Box()
    qtbot.addWidget(widget)
    assert widget.valueText == "XXX"
