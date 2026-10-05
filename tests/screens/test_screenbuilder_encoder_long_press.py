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
