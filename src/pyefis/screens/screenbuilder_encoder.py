#  Copyright (c) 2026 Eric Blevins
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.

import logging
import time
from operator import itemgetter

from PyQt6.QtCore import QTimer

logger = logging.getLogger(__name__)


class EncoderController:
    """Routes the screen's encoder keys to the instrument that holds control.

    Long push (opt-in): an instrument in control that defines both
    ``enc_long_clicked()`` and a positive ``enc_long_press_ms`` gets its clicks
    on RELEASE instead of press -- ``enc_clicked()`` for a short hold,
    ``enc_long_clicked()`` once the hold reaches ``enc_long_press_ms`` (fired
    from a timer, so it does not wait for the release). Every other
    instrument keeps the original act-on-press behaviour.

    Outer ring (optional): a screen may also name ``encoder_outer``, the outer
    ring of a dual-concentric knob. Its turns go to the instrument in control
    as ``enc_outer_changed(steps)`` (same return contract as ``enc_changed``),
    and only while it holds control; outside control, and for instruments
    without the method, the outer ring is ignored. Every enrolled instrument
    that defines ``enc_outer_changed`` gets ``enc_has_outer = True``, so it
    can drop the one-knob fallbacks it needs without an outer ring. A missing
    ``encoder_outer`` FIX key logs a warning and leaves the outer ring off.
    """

    def __init__(self, screen):
        self.screen = screen
        self._press_pending = False
        self._long_timer = QTimer()
        self._long_timer.setSingleShot(True)
        self._long_timer.timeout.connect(self._long_press_fired)

    def configure_inputs(self, fix_module):
        if len(self.screen.encoder_list) == 0:
            return

        if self.screen.encoder and self.screen.encoder_button:
            self.screen.encoder_list_sorted = [
                inst["inst"]
                for inst in sorted(self.screen.encoder_list, key=itemgetter("order"))
            ]
            self.screen.encoder_current_selection = 0

            self.screen.encoder_input = fix_module.db.get_item(self.screen.encoder)
            self.screen.encoder_input.valueWrite[int].connect(
                self.screen.encoderChanged
            )

            self.screen.encoder_button_input = fix_module.db.get_item(
                self.screen.encoder_button
            )
            self.screen.encoder_button_input.valueChanged[bool].connect(
                self.screen.encoderButtonChanged
            )

            self.screen.encoder_timer.timeout.connect(self.screen.encoderChanged)
            self._configure_outer(fix_module)

    def _configure_outer(self, fix_module):
        key = getattr(self.screen, "encoder_outer", None)
        if not key:
            return
        try:
            item = fix_module.db.get_item(key)
        except KeyError:
            logger.warning("encoder_outer key %s not in the FIX database; "
                           "outer ring disabled", key)
            return
        self.screen.encoder_outer_input = item
        item.valueWrite[int].connect(self.screen.encoderOuterChanged)
        for index in self.screen.encoder_list_sorted:
            inst = self.screen.instruments[index]
            if callable(getattr(inst, "enc_outer_changed", None)):
                inst.enc_has_outer = True

    def outer_changed(self, value=0):
        if not value or not self.screen.isVisible():
            return
        if not self.screen.encoder_control:
            return
        handler = getattr(self._selected_instrument(), "enc_outer_changed", None)
        if not callable(handler):
            return
        curr_time = time.time_ns() // 1000000
        self.screen.encoder_control = handler(value)
        if self.screen.encoder_control:
            self.screen.encoder_timestamp = curr_time
            self.screen.encoder_timer.start(self.screen.encoder_timeout + 500)
        else:
            self.screen.encoder_timer.stop()
            self.screen.encoder_timestamp = 0
            self._selected_instrument().enc_highlight(False)

    def changed(self, value=0):
        curr_time = time.time_ns() // 1000000
        if value == 0:
            if curr_time - self.screen.encoder_timeout >= self.screen.encoder_timestamp:
                self._selected_instrument().enc_highlight(False)
                self.screen.encoder_control = False
                self.screen.encoder_timer.stop()
                self.screen.encoder_timestamp = 0
            return

        if not self.screen.isVisible():
            return

        if self.screen.encoder_control:
            self.screen.encoder_control = self._selected_instrument().enc_changed(value)
            if self.screen.encoder_control:
                self.screen.encoder_timestamp = curr_time
                self.screen.encoder_timer.start(self.screen.encoder_timeout + 500)
            else:
                self.screen.encoder_timer.stop()
                self.screen.encoder_timestamp = 0
                self._selected_instrument().enc_highlight(False)
            return

        val = self.screen.encoder_current_selection
        if not (
            curr_time - self.screen.encoder_timeout >= self.screen.encoder_timestamp
        ):
            val = self.screen.encoder_current_selection + value

        val = self._wrap_selection(val)

        loop = 0
        if not self.screen.instruments[
            self.screen.encoder_list_sorted[val]
        ].isEnabled():
            while (
                not self.screen.instruments[
                    self.screen.encoder_list_sorted[val]
                ].isEnabled()
                and loop < 2
            ):
                adder = -1
                if value > 0:
                    adder = 1

                val = val + adder

                if val < 0:
                    val = len(self.screen.encoder_list_sorted) - 1
                    loop += 1
                elif val == len(self.screen.encoder_list_sorted):
                    val = 0
                    loop += 1

        self._selected_instrument().enc_highlight(False)
        self.screen.encoder_control = False
        self.screen.encoder_current_selection = val
        if loop < 2:
            self._selected_instrument().enc_highlight(True)
            self.screen.encoder_timestamp = curr_time
            self.screen.encoder_timer.start(self.screen.encoder_timeout + 500)

    def button_changed(self, value):
        if not self.screen.isVisible():
            return

        if self.screen.encoder_control and self._long_press_ms() > 0:
            self._long_press_button(value)
            return

        if value and not (
            (time.time_ns() // 1000000) - self.screen.encoder_timeout
            >= self.screen.encoder_timestamp
        ):
            if self.screen.encoder_control:
                self.screen.encoder_control = self._selected_instrument().enc_clicked()
                if self.screen.encoder_control:
                    self.screen.encoder_timestamp = time.time_ns() // 1000000
                    self.screen.encoder_timer.start(self.screen.encoder_timeout + 500)
                else:
                    self.screen.encoder_timer.stop()
                    self.screen.encoder_timestamp = 0
                    self._selected_instrument().enc_highlight(False)
            else:
                self.screen.encoder_control = self._selected_instrument().enc_select()
                if self.screen.encoder_control:
                    self.screen.encoder_timestamp = time.time_ns() // 1000000
                    self.screen.encoder_timer.start(self.screen.encoder_timeout + 500)
                else:
                    self.screen.encoder_timer.stop()
                    self.screen.encoder_timestamp = 0
                    self._selected_instrument().enc_highlight(False)

    def _long_press_ms(self):
        try:
            inst = self._selected_instrument()
        except (IndexError, KeyError, TypeError):
            return 0
        if not callable(getattr(inst, "enc_long_clicked", None)):
            return 0
        try:
            return int(getattr(inst, "enc_long_press_ms", 0) or 0)
        except (TypeError, ValueError):
            return 0

    def _long_press_button(self, value):
        if value:
            if (time.time_ns() // 1000000) - self.screen.encoder_timeout \
                    >= self.screen.encoder_timestamp:
                return
            self._press_pending = True
            self._long_timer.start(self._long_press_ms())
            return
        if not self._press_pending:
            # Release after the long push already fired, or a stray release.
            return
        self._press_pending = False
        self._long_timer.stop()
        self._dispatch_click(self._selected_instrument().enc_clicked)

    def _long_press_fired(self):
        if not self._press_pending or not self.screen.encoder_control:
            self._press_pending = False
            return
        self._press_pending = False
        self._dispatch_click(self._selected_instrument().enc_long_clicked)

    def _dispatch_click(self, handler):
        self.screen.encoder_control = handler()
        if self.screen.encoder_control:
            self.screen.encoder_timestamp = time.time_ns() // 1000000
            self.screen.encoder_timer.start(self.screen.encoder_timeout + 500)
        else:
            self.screen.encoder_timer.stop()
            self.screen.encoder_timestamp = 0
            self._selected_instrument().enc_highlight(False)

    def _selected_instrument(self):
        return self.screen.instruments[
            self.screen.encoder_list_sorted[self.screen.encoder_current_selection]
        ]

    def _wrap_selection(self, val):
        if val < 0:
            while val < 0:
                val = len(self.screen.encoder_list_sorted) + val
        elif val > len(self.screen.encoder_list_sorted) - 1:
            while val > len(self.screen.encoder_list_sorted) - 1:
                val = val - len(self.screen.encoder_list_sorted)
        return val
