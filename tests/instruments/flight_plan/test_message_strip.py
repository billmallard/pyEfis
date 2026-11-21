#  SPDX-License-Identifier: GPL-2.0-or-later
"""AER-6156: an FPL-page message never prints on the header.

The message (STORED, NO AIRWAYS AT x, ROUTE FULL, an OBS refusal) was drawn
at pane fractions -- y ``h*0.02`` to ``h*0.08``, full width, centred -- while
the header is physical (``_chrome_h``). On the Beelink's 649x993 tab it
wedged under the top line; on an 800x480 or 649x400 pane it printed over the
LEG/DIRECT badge. Bill's ruling (AER-6156 card, 2026-11-21): the message goes
in a strip above the soft keys, where the refused-commit banner sits.

Pinned at all three pane sizes: the header's pixels are unchanged by a
message, no header text rect meets the message's, the strip stacks above the
soft keys and the alert strips, and a tap on it only dismisses it.
"""

from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QPoint, QRectF, Qt
from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtTest import QTest

from pyefis.flightplan import model as fp_model
from pyefis.instruments import flight_plan
from tests.instruments.flight_plan import test_flight_plan as base

BEELINK = SimpleNamespace(screenWidth=1920, screenHeight=1080,
                          screenDiagonalInches=21.5)
# The served Flight Plan tab, the pane AER-6156 was filed from, a short pane.
SIZES = [(649, 993), (800, 480), (649, 400)]
LONG = "OBS NOT AVAILABLE: NO ACTIVE WAYPOINT"
MESSAGES = ["STORED", "ROUTE FULL -- V27 NEEDS 3 MORE SLOTS", LONG]


class _InkRecorder(QPainter):
    """Each drawText as ``(text, rect the glyphs cover)``."""
    log = []

    def drawText(self, *args):
        if len(args) == 3 and isinstance(args[0], QRectF):
            rect, flags, text = args
            ink = self.boundingRect(rect, int(getattr(flags, "value", flags)), text)
            _InkRecorder.log.append((text, ink))
        return super().drawText(*args)


def _flying(fix, qtbot, size, apr=2, integ=False):
    """A widget flying KSBA -> GVO -> KSMX, header full: LEG, the remaining
    readout, LNAV (*apr*) and LOI (*integ* False)."""
    base._define_all_fp1_keys(fix)
    w = flight_plan.FlightPlan(None, font_percent=0.8)
    qtbot.addWidget(w)
    w.parent = SimpleNamespace(parent=BEELINK)
    w.resize(*size)
    w.toast_ms = 10 ** 8
    w._plan = fp_model.FlightPlan(waypoints=[
        fp_model.Waypoint(id="KSBA", type="airport", lat=34.42621, lon=-119.84037),
        fp_model.Waypoint(id="GVO", type="vor", lat=34.53131944, lon=-120.09108889),
        fp_model.Waypoint(id="KSMX", type="airport", lat=34.89892, lon=-120.45758),
    ])
    w._commit()
    for key, value in (("FPLSTATE", 1), ("FPLACTLEG", 2), ("FPLREMDIS", 48.0),
                       ("FPLREMETE", 1440), ("FPLAPR", apr), ("FPLINTEG", integ)):
        fix.db.set_value(key, value)
    w._sync_engine_from_bridge()
    return w


def _render(w, monkeypatch=None):
    if monkeypatch is not None:
        _InkRecorder.log = []
        monkeypatch.setattr(flight_plan, "QPainter", _InkRecorder)
    img = QImage(w.width(), w.height(), QImage.Format.Format_RGB32)
    w._paint(img)
    return img


def _header_h(w):
    return int(w._chrome_h(w.height(), 2.0, 0.26))


def _footer_h(w):
    return int(w._chrome_h(w.height(), 1.3, 0.18))


@pytest.mark.parametrize("size", SIZES)
@pytest.mark.parametrize("message", MESSAGES)
def test_message_leaves_the_header_pixels_unchanged(fix, qtbot, size, message):
    w = _flying(fix, qtbot, size)
    bare = _render(w)
    w._message = message
    shown = _render(w)
    band = _header_h(w)
    assert shown.copy(0, 0, w.width(), band) == bare.copy(0, 0, w.width(), band)
    # ...and the message did draw somewhere.
    assert shown != bare


@pytest.mark.parametrize("size", SIZES)
def test_message_rect_meets_no_header_text(fix, qtbot, monkeypatch, size):
    w = _flying(fix, qtbot, size)
    w._message = LONG
    _render(w, monkeypatch)
    header = [(t, r) for t, r in _InkRecorder.log
              if t != LONG and r.top() < _header_h(w)]
    texts = [t for t, _r in header]
    # The badge, the readout, LNAV and LOI were all drawn.
    assert "LEG" in texts and "LNAV" in texts and "LOI" in texts
    assert any(" NM " in t for t in texts)
    msg = [r for t, r in _InkRecorder.log if t == LONG]
    assert len(msg) == 1
    for text, rect in header:
        assert not msg[0].intersects(rect), (text, rect, msg[0])


@pytest.mark.parametrize("size", SIZES)
def test_strip_sits_on_the_soft_keys_and_holds_the_text(fix, qtbot, monkeypatch, size):
    w = _flying(fix, qtbot, size)
    w._message = LONG
    _render(w, monkeypatch)
    strip = w._message_rect
    footer_top = w.height() - _footer_h(w)
    assert strip.bottom() <= footer_top
    assert strip.bottom() >= footer_top - 2
    assert strip.top() >= _header_h(w)
    ink = next(r for t, r in _InkRecorder.log if t == LONG)
    assert strip.top() <= ink.top() and ink.bottom() <= strip.bottom() + 1
    assert ink.left() >= 0 and ink.right() <= w.width()


def test_strip_stacks_above_the_refusal_banner(fix, qtbot):
    w = _flying(fix, qtbot, (649, 993))
    w._refusal = (2, "TURN DIRECTION MISSING")
    w._message = "STORED"
    _render(w)
    footer_h = _footer_h(w)
    refusal_top = w.height() - footer_h - footer_h
    assert w._message_rect.bottom() <= refusal_top
    assert w._message_rect.bottom() >= refusal_top - 2


def test_tap_on_strip_dismisses_without_selecting_the_row_under_it(fix, qtbot):
    w = _flying(fix, qtbot, (649, 400))
    w._message = "STORED"
    w.grab()
    centre = w._message_rect.center()
    # Whatever lies under the strip must not fire: a target over the whole
    # page, outside any list viewport, stands in for the hidden row.
    fired = []
    w._list_view = None
    w._tap_targets = [(0, 0, w.width(), w.height(), lambda: fired.append(1))]
    w._tap_kinds = [None]
    QTest.mouseClick(w, Qt.MouseButton.LeftButton,
                     pos=QPoint(int(centre.x()), int(centre.y())))
    qtbot.wait(150)
    assert w._message == ""
    assert fired == []


def test_tap_elsewhere_still_dismisses_and_acts(fix, qtbot):
    w = _flying(fix, qtbot, (649, 993))
    w._message = "STORED"
    w.grab()
    fired = []
    w._list_view = None
    w._tap_targets = [(0, 0, w.width(), 50, lambda: fired.append(1))]
    w._tap_kinds = [None]
    QTest.mouseClick(w, Qt.MouseButton.LeftButton, pos=QPoint(20, 20))
    assert w._message == ""
    assert fired == [1]


@pytest.mark.parametrize("size", SIZES)
def test_a_message_too_long_for_two_lines_shrinks_into_the_strip(fix, qtbot, monkeypatch, size):
    # Plan notices are joined into one message ("; ".join(plan.notices)).
    # Six notices, about 190 characters: four lines at the banner's size on
    # the 800 and 649x400 panes.
    text = "; ".join(["ROUTE FULL -- V27 NEEDS 3 MORE SLOTS", "NO AIRWAYS AT GVO", LONG] * 2)
    w = _flying(fix, qtbot, size)
    w._message = text
    _render(w, monkeypatch)
    ink = next(r for t, r in _InkRecorder.log if t == text)
    strip = w._message_rect
    assert strip.top() <= ink.top() and ink.bottom() <= strip.bottom() + 1
