#  SPDX-License-Identifier: GPL-2.0-or-later
"""Target-bank bug on the attitude indicator (AER-5149, ATT1 item 2).

The bug is the FIX key BANKBUG (0 = off), drawn on both sides of the bank
scale with a +/-bankBugTolerance band, so holding a steep turn reads as "the
roll pointer is inside the band". The pilot sets it by touching the bank scale
and turning the knob (pyEfis #308 focus model): 5 deg detents, 0 .. 60, capped
at the excessive-bank caution when that is lower.
"""

import numpy as np
import pytest
from PyQt6.QtCore import QPoint, QPointF, QTimer, Qt
from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtWidgets import QWidget

from pyefis.instruments import edit_focus
from pyefis.instruments.ai import AI
from pyefis.screens.screenbuilder_encoder import EncoderController

W, H = 480, 360


@pytest.fixture(autouse=True)
def _clean_registry():
    edit_focus.set_at_rest_hint(False)
    yield
    owner = edit_focus.owner()
    if owner is not None:
        owner.release_focus()
    edit_focus.release(edit_focus.owner())
    edit_focus.set_at_rest_hint(False)


def _good(fix, *keys):
    for key in keys:
        item = fix.db.get_item(key)
        item.old = item.bad = item.fail = False


@pytest.fixture
def bankbug(fix, monkeypatch):
    """BANKBUG as fix-gateway defines it (float 0..65, tol 0), plus a recorder
    on what is sent to the gateway."""
    fix.db.define_item("BANKBUG", "Selected Target Bank Angle", "float",
                       0.0, 65.0, "deg", 0, "")
    fix.db.set_value("BANKBUG", 0.0)
    _good(fix, "BANKBUG", "PITCH", "ROLL", "ALAT", "TAS")
    sent = []
    monkeypatch.setattr(fix.db, "queue_out", lambda b: sent.append(b.decode()))
    fix.sent = sent
    return fix


class _Host(QWidget):
    """Stands in for a Screen: the AI finds encoder_controller by walking up
    its parents, as on a real screen."""

    def __init__(self):
        super().__init__()
        self.instruments = {}
        self.encoder_list = []
        self.encoder_list_sorted = []
        self.encoder_current_selection = None
        self.encoder_timeout = 10_000
        self.encoder_timestamp = 0
        self.encoder_control = False
        self.encoder_timer = QTimer(self)
        self.encoder = None
        self.encoder_button = None
        self.encoder_controller = EncoderController(self)

    def encoderChanged(self, value=0):
        self.encoder_controller.changed(value)


def _ai(qtbot, host=None):
    w = AI(host)
    if host is not None:
        host.instruments[0] = w
        qtbot.addWidget(host)
        host.resize(W, H)
        w.setGeometry(0, 0, W, H)
        host.show()
        qtbot.waitExposed(host)
    else:
        qtbot.addWidget(w)
        w.resize(W, H)
        w.show()
        qtbot.waitExposed(w)
    _overlays(w)
    return w


def _overlays(w):
    img = QImage(w.width(), w.height(), QImage.Format.Format_RGB32)
    img.fill(0)
    p = QPainter(img)
    w._paint_overlays(p)
    p.end()
    ptr = img.constBits()
    ptr.setsize(img.sizeInBytes())
    return np.frombuffer(ptr, np.uint8).reshape(
        img.height(), img.bytesPerLine() // 4, 4).copy()


def _sent(fix):
    return [float(m.split(";")[1]) for m in fix.sent if m.startswith("BANKBUG;")]


def _scale_point(w, deg_from_up, radius):
    """Viewport point at ``radius`` from the bank-arc centre, ``deg_from_up``
    clockwise from straight up (screen frame, not the rolled scale)."""
    import math
    a = math.radians(deg_from_up)
    cx, cy = w.width() / 2.0, w._bank_anchor_y(w.height())
    return QPointF(cx + radius * math.sin(a), cy - radius * math.cos(a))


def _is_band(px):
    # The band is translucent cyan (alpha 140): over black or over the white
    # fixed pointer mark it leaves green and blue well above red.
    b, g, r = int(px[0]), int(px[1]), int(px[2])
    return g > r + 80 and b > r + 80


def _pointer_band_pixel(w):
    """The pixel just under the fixed roll pointer's apex, on the short-tick
    ring the band covers. The pointer is white; this point is clear of it."""
    r, m = float(w.bankAngleRadius), float(w.bankMarkSize)
    img = _overlays(w)
    pt = _scale_point(w, 0.0, r - 0.8 * m)
    return img[int(round(pt.y())), int(round(pt.x()))]


# --- the key ---------------------------------------------------------------

def test_missing_key_draws_no_bug_and_is_not_editable(fix, qtbot):
    """No BANKBUG in the database: the AI builds, draws no bug, and the
    bank scale is not touch-editable. There is no local fallback."""
    _good(fix, "PITCH", "ROLL", "ALAT", "TAS")
    w = _ai(qtbot)
    assert w._bank_bug.item is None
    assert w.bank_bug_target() == 0.0
    assert w.bank_bug_editable() is False
    assert w.bank_bug_step(1) is False


def test_off_draws_no_band(bankbug, qtbot):
    w = _ai(qtbot)
    w.rollAngle = 0
    assert not _is_band(_pointer_band_pixel(w))
    assert w.bank_bug_target() == 0.0


def test_failed_key_draws_no_bug(bankbug, qtbot):
    bankbug.db.set_value("BANKBUG", 45.0)
    w = _ai(qtbot)
    assert w.bank_bug_target() == 45.0
    bankbug.db.get_item("BANKBUG").fail = True
    assert w.bank_bug_target() == 0.0


# --- the band reads against the fixed roll pointer --------------------------

@pytest.mark.parametrize("bank", [-49, -45, -41, 41, 45, 49])
def test_pointer_inside_the_band_within_tolerance(bankbug, qtbot, bank):
    """Bug 45, tolerance 5: at a bank inside 40 to 50 deg, either direction,
    the band sits under the fixed roll pointer (the exact edge, 40 or 50, is
    left to antialiasing and not asserted)."""
    bankbug.db.set_value("BANKBUG", 45.0)
    w = _ai(qtbot)
    w.rollAngle = bank
    assert _is_band(_pointer_band_pixel(w))


@pytest.mark.parametrize("bank", [-60, -35, 0, 35, 60])
def test_pointer_outside_the_band_off_target(bankbug, qtbot, bank):
    bankbug.db.set_value("BANKBUG", 45.0)
    w = _ai(qtbot)
    w.rollAngle = bank
    assert not _is_band(_pointer_band_pixel(w))


def test_tolerance_setting_widens_the_band(bankbug, qtbot):
    bankbug.db.set_value("BANKBUG", 45.0)
    w = _ai(qtbot)
    w.rollAngle = 37
    assert not _is_band(_pointer_band_pixel(w))
    w.bankBugTolerance = "10"   # configurator values may arrive quoted
    assert _is_band(_pointer_band_pixel(w))


def test_bug_hidden_by_the_unusual_attitude_declutter(bankbug, qtbot):
    bankbug.db.set_value("BANKBUG", 60.0)
    w = _ai(qtbot)
    # A 50..70 band, so 66 is inside it: only the de-clutter can hide it.
    w.bankBugTolerance = 10
    w.rollAngle = 64
    assert _is_band(_pointer_band_pixel(w))
    w.rollAngle = 66
    assert not _is_band(_pointer_band_pixel(w))


# --- the knob ----------------------------------------------------------------

def test_knob_steps_five_degrees_from_off_and_sends(bankbug, qtbot):
    w = _ai(qtbot)
    assert w.enc_changed(1) is True
    assert w.bank_bug_target() == 5.0
    w.enc_changed(8)
    assert w.bank_bug_target() == 45.0
    assert _sent(bankbug) == [5.0, 45.0]


def test_knob_stops_at_off_and_at_60(bankbug, qtbot):
    w = _ai(qtbot)
    w.enc_changed(-3)
    assert w.bank_bug_target() == 0.0
    w.enc_changed(20)
    assert w.bank_bug_target() == 60.0


def test_knob_capped_at_the_excessive_bank_caution(bankbug, qtbot):
    """A bug past the caution would ask the pilot to fly in it: with the
    caution at 47 the knob stops at 45."""
    w = _ai(qtbot)
    w.excessiveBankDeg = 47
    assert w.bank_bug_cap() == 45
    w.enc_changed(20)
    assert w.bank_bug_target() == 45.0


def test_knob_snaps_an_odd_value_to_the_step(bankbug, qtbot):
    bankbug.db.set_value("BANKBUG", 47.0)   # written by another display
    w = _ai(qtbot)
    w.enc_changed(1)
    assert w.bank_bug_target() == 50.0


def test_push_ends_the_edit_and_keeps_the_value(bankbug, qtbot):
    bankbug.db.set_value("BANKBUG", 45.0)
    w = _ai(qtbot)
    assert w.enc_clicked() is False
    assert w.bank_bug_target() == 45.0


# --- touch focus ---------------------------------------------------------------

def test_touching_the_bank_scale_takes_edit_focus(bankbug, qtbot):
    host = _Host()
    w = _ai(qtbot, host)
    r = float(w.bankAngleRadius)
    pt = _scale_point(w, 20.0, r).toPoint()
    qtbot.mouseClick(w.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(pt))
    assert host.encoder_controller.focused_instrument() is w
    assert w._bank_bug_focused is True
    host.encoder_controller.wheel_turn(9)
    assert w.bank_bug_target() == 45.0


def test_touching_the_centre_does_not_focus(bankbug, qtbot):
    host = _Host()
    w = _ai(qtbot, host)
    qtbot.mouseClick(w.viewport(), Qt.MouseButton.LeftButton,
                     pos=QPoint(W // 2, H // 2))
    assert host.encoder_controller.focused_instrument() is None


def test_touch_edit_off_leaves_the_scale_inert(bankbug, qtbot):
    host = _Host()
    w = _ai(qtbot, host)
    w.touch_edit = "false"
    pt = _scale_point(w, 0.0, float(w.bankAngleRadius)).toPoint()
    qtbot.mouseClick(w.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(pt))
    assert host.encoder_controller.focused_instrument() is None


def test_no_touch_target_while_decluttered(bankbug, qtbot):
    w = _ai(qtbot)
    pt = _scale_point(w, 0.0, float(w.bankAngleRadius))
    assert w._bank_scale_hit(pt) is True
    w.rollAngle = 70
    _overlays(w)
    assert w._bank_scale_hit(pt) is False


# --- configurator -------------------------------------------------------------

@pytest.mark.parametrize("itype", ["atitude_indicator", "virtual_vfr"])
def test_configurator_offers_tolerance_and_touch(itype):
    from pyefis.screens import screenbuilder_factory as factory
    props = {p.name: p for p in factory.REGISTRY[itype].properties}
    tol = props["bankBugTolerance"]
    assert (tol.default, tol.minimum, tol.maximum) == (5, 1, 10)
    assert props["touch_edit"].default is True
