"""HSIARC1 (AER-5920): the arc HSI's compass band sits on true compass marks.

`_paint_arc` used to step its tick and numeral loops from the rounded heading,
so at heading 123 every tick landed on 123, 128, 133 ... and no numeral or
cardinal was drawn at all; the numerals showed only when the heading was a
multiple of 5, so in a turn they blinked on and off.
"""
import pytest
from PyQt6.QtGui import QPainter, QPaintEvent

from pyefis.instruments import hsi


def _arc_widget(qtbot, heading):
    w = hsi.HSI()
    qtbot.addWidget(w)
    w.orientation = "arc"
    w.resize(320, 320)
    w.show()
    qtbot.waitExposed(w)
    w._HeadFail = w._HeadBad = False
    w._heading = heading
    assert not w.isFail()
    return w


def _paint_recording(w, monkeypatch):
    """Paint once; return (band bearings drawn, drawText strings). With no CDI,
    bearing needle, heading bug or track diamond enabled, only the tick and
    numeral loops place anything on the band."""
    bearings, texts = [], []
    real_band = w._arc_band_point

    def spy_band(bearing):
        bearings.append(bearing)
        return real_band(bearing)

    real_text = QPainter.drawText

    def spy_text(self, *args):
        texts.append(args[-1])
        return real_text(self, *args)

    monkeypatch.setattr(w, "_arc_band_point", spy_band)
    monkeypatch.setattr(QPainter, "drawText", spy_text)
    w.paintEvent(QPaintEvent(w.rect()))
    return bearings, texts


def _expected_marks(heading):
    return {m for m in range(0, 360, 5)
            if abs(hsi.HSI._rel_angle(m, heading)) <= hsi.HSI.ARC_HALF_DEG}


@pytest.mark.parametrize("heading", [120.0, 123.0, 2.6, 357.4, 271.5])
def test_arc_ticks_sit_on_every_5_degree_mark(fix, qtbot, monkeypatch, heading):
    w = _arc_widget(qtbot, heading)
    bearings, _ = _paint_recording(w, monkeypatch)
    assert bearings, "the arc band drew nothing"
    assert all(b % 5 == 0 for b in bearings), sorted(set(bearings))
    assert set(bearings) == _expected_marks(heading)


@pytest.mark.parametrize("heading, labels", [
    (120.0, {"6", "E", "12", "15", "S"}),
    (123.0, {"E", "12", "15", "S"}),       # off a 5-deg multiple
    (357.4, {"30", "33", "N", "3"}),      # across the 360/0 wrap
])
def test_arc_numerals_drawn_off_5_degree_headings(fix, qtbot, monkeypatch,
                                                  heading, labels):
    w = _arc_widget(qtbot, heading)
    _, texts = _paint_recording(w, monkeypatch)
    compass = set(w.cardinal) | {str(n) for n in range(1, 36)}
    assert {t for t in texts if t in compass} == labels
