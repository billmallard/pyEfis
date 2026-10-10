#  SPDX-License-Identifier: GPL-2.0-or-later
"""Opt-in long-push routing in ``EncoderController`` (FP5c, pyEfis#188).

An instrument in control that defines ``enc_long_clicked()`` and a positive
``enc_long_press_ms`` gets its pushes on release (short) or from a timer once
the hold reaches the threshold (long); every other instrument keeps the
original act-on-press behaviour.
"""

import time

from pyefis.screens.screenbuilder_encoder import EncoderController


class _FakeScreen:
    def __init__(self, inst):
        from PyQt6.QtCore import QTimer
        self.instruments = {0: inst}
        self.encoder_list_sorted = [0]
        self.encoder_current_selection = 0
        self.encoder_timeout = 10_000
        self.encoder_timestamp = time.time_ns() // 1_000_000
        self.encoder_control = True
        self.encoder_timer = QTimer()

    def isVisible(self):
        return True


class _LongPressInst:
    enc_long_press_ms = 50

    def __init__(self):
        self.calls = []
        self.highlight = []
        self.long_return = True

    def enc_clicked(self):
        self.calls.append("short")
        return True

    def enc_long_clicked(self):
        self.calls.append("long")
        return self.long_return

    def enc_highlight(self, onoff):
        self.highlight.append(onoff)


def test_controller_short_push_fires_on_release_not_press(qtbot):
    inst = _LongPressInst()
    ctl = EncoderController(_FakeScreen(inst))
    ctl.button_changed(True)
    assert inst.calls == []
    ctl.button_changed(False)
    assert inst.calls == ["short"]


def test_controller_long_push_fires_on_the_timer_and_eats_the_release(qtbot):
    inst = _LongPressInst()
    screen = _FakeScreen(inst)
    ctl = EncoderController(screen)
    ctl.button_changed(True)
    qtbot.waitUntil(lambda: inst.calls == ["long"], timeout=1000)
    ctl.button_changed(False)
    assert inst.calls == ["long"]
    assert screen.encoder_control is True


def test_controller_long_push_returning_false_releases_control(qtbot):
    inst = _LongPressInst()
    inst.long_return = False
    screen = _FakeScreen(inst)
    ctl = EncoderController(screen)
    ctl.button_changed(True)
    qtbot.waitUntil(lambda: inst.calls == ["long"], timeout=1000)
    assert screen.encoder_control is False
    assert inst.highlight == [False]
    ctl.button_changed(False)            # the release must not re-enter anything
    assert inst.calls == ["long"]


def test_controller_keeps_act_on_press_for_instruments_without_long_push(qtbot):
    class Plain:
        def __init__(self):
            self.clicks = 0

        def enc_clicked(self):
            self.clicks += 1
            return True

        def enc_highlight(self, onoff):
            pass

    inst = Plain()
    ctl = EncoderController(_FakeScreen(inst))
    ctl.button_changed(True)
    assert inst.clicks == 1
    ctl.button_changed(False)
    assert inst.clicks == 1


# ---------------------------------------------------------------------------
# encoder_outer routing
# ---------------------------------------------------------------------------
class _OuterInst(_LongPressInst):
    def __init__(self):
        super().__init__()
        self.outer = []
        self.outer_return = True

    def enc_outer_changed(self, data):
        self.outer.append(data)
        return self.outer_return


def test_outer_ring_goes_to_the_instrument_in_control(qtbot):
    inst = _OuterInst()
    screen = _FakeScreen(inst)
    ctl = EncoderController(screen)
    ctl.outer_changed(1)
    ctl.outer_changed(-2)
    assert inst.outer == [1, -2]
    assert screen.encoder_control is True


def test_outer_ring_is_ignored_outside_control(qtbot):
    inst = _OuterInst()
    screen = _FakeScreen(inst)
    screen.encoder_control = False
    EncoderController(screen).outer_changed(1)
    assert inst.outer == []


def test_outer_ring_false_return_releases_control(qtbot):
    inst = _OuterInst()
    inst.outer_return = False
    screen = _FakeScreen(inst)
    EncoderController(screen).outer_changed(1)
    assert screen.encoder_control is False
    assert inst.highlight == [False]


def test_outer_ring_ignored_by_instruments_without_the_method(qtbot):
    inst = _LongPressInst()
    screen = _FakeScreen(inst)
    EncoderController(screen).outer_changed(1)
    assert screen.encoder_control is True
    assert inst.calls == []


class _FixItem:
    def __init__(self):
        self.connected = []

        class _Sig:
            def __getitem__(s, _t):
                return s

            def connect(s, fn):
                self.connected.append(fn)
        self.valueWrite = _Sig()


class _FixDB:
    def __init__(self, keys):
        self.items = {k: _FixItem() for k in keys}

    def get_item(self, key):
        return self.items[key]


def test_configure_outer_connects_and_flags_capable_instruments(qtbot):
    inst, plain = _OuterInst(), _LongPressInst()
    screen = _FakeScreen(inst)
    screen.instruments = {0: inst, 1: plain}
    screen.encoder_list_sorted = [0, 1]
    screen.encoder_outer = "ENC4"
    screen.encoderOuterChanged = lambda v: None
    fixmod = type("F", (), {"db": _FixDB(["ENC4"])})()
    EncoderController(screen)._configure_outer(fixmod)
    assert fixmod.db.items["ENC4"].connected == [screen.encoderOuterChanged]
    assert inst.enc_has_outer is True
    assert not hasattr(plain, "enc_has_outer")


def test_configure_outer_missing_key_warns_and_stays_off(qtbot, caplog):
    inst = _OuterInst()
    screen = _FakeScreen(inst)
    screen.encoder_outer = "ENC9"
    screen.encoder_outer_input = None
    fixmod = type("F", (), {"db": _FixDB([])})()
    EncoderController(screen)._configure_outer(fixmod)
    assert screen.encoder_outer_input is None
    assert "ENC9" in caplog.text
    assert not hasattr(inst, "enc_has_outer")
