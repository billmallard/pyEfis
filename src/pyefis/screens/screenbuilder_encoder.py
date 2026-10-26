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

from pyefis.instruments import edit_focus

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

    Touch focus (pyEfis #308): an instrument may call :meth:`touch_focus` from
    its ``mousePressEvent`` to take control directly, without the knob walk
    through ``encoder_order`` -- the same ``enc_highlight(True)`` +
    ``enc_select()`` a knob push would make, landing in the same in-control
    state, so the inner knob, the outer ring, the push and the timeout all
    behave identically after a touch. The instrument does not need an
    ``encoder_order``. Entering control by either path claims the panel-wide
    focus (``edit_focus.claim``): only one value has focus across every
    screen, a press anywhere else releases it, and so does hiding the screen.
    """

    def __init__(self, screen):
        self.screen = screen
        # An instrument focused by touch that is not in encoder_list_sorted;
        # while set it is the instrument in control.
        self._touch_inst = None
        self._timer_connected = False
        self._press_pending = False
        self._long_timer = QTimer()
        self._long_timer.setSingleShot(True)
        self._long_timer.timeout.connect(self._long_press_fired)

    def configure_inputs(self, fix_module):
        touch = self._touch_instruments()
        if len(self.screen.encoder_list) == 0 and not touch:
            return

        # The timeout has to run for a touch focus even on a screen without
        # encoder keys (nothing would ever clear it otherwise).
        self._connect_timer()

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

            self._configure_outer(fix_module)

    def _touch_instruments(self):
        insts = getattr(self.screen, "instruments", None) or {}
        return [i for i in insts.values()
                if getattr(i, "touch_edit", False)
                and callable(getattr(i, "enc_select", None))]

    def _connect_timer(self):
        if not self._timer_connected:
            self.screen.encoder_timer.timeout.connect(self.screen.encoderChanged)
            self._timer_connected = True

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
        enrolled = [self.screen.instruments[i]
                    for i in self.screen.encoder_list_sorted]
        for inst in enrolled + self._touch_instruments():
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
        self._after_handler(handler(value))

    def changed(self, value=0):
        curr_time = time.time_ns() // 1000000
        if value == 0:
            if curr_time - self.screen.encoder_timeout >= self.screen.encoder_timestamp:
                if self._has_selection():
                    self._end_control()
                else:
                    self.screen.encoder_control = False
                    self.screen.encoder_timer.stop()
                    self.screen.encoder_timestamp = 0
            return

        if not self.screen.isVisible():
            return

        if self.screen.encoder_control:
            self._after_handler(self._selected_instrument().enc_changed(value))
            return

        if not self.screen.encoder_list_sorted:
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
                self._after_handler(self._selected_instrument().enc_clicked())
            elif self.screen.encoder_list_sorted:
                inst = self._selected_instrument()
                if inst.enc_select():
                    edit_focus.claim(self)
                    self.screen.encoder_control = True
                    self._keep_control()
                else:
                    self.screen.encoder_control = False
                    self._end_control()

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
        self._after_handler(handler())

    def _after_handler(self, keep):
        """An enc_* handler in control returned ``keep``: restart the timeout,
        or end control."""
        self.screen.encoder_control = keep
        if keep:
            self._keep_control()
        else:
            self._end_control()

    def _keep_control(self):
        self.screen.encoder_timestamp = time.time_ns() // 1000000
        self.screen.encoder_timer.start(self.screen.encoder_timeout + 500)

    def _end_control(self):
        """Leave control (or a knob-walk highlight): stop the timeout, clear
        the instrument's highlight, drop any touch override and the panel-wide
        focus. The single exit every path goes through."""
        self.screen.encoder_timer.stop()
        self.screen.encoder_timestamp = 0
        self.screen.encoder_control = False
        inst = self._selected_instrument() if self._has_selection() else None
        self._touch_inst = None
        edit_focus.release(self)
        if inst is not None:
            inst.enc_highlight(False)

    # --- touch focus (pyEfis #308) -------------------------------------------

    def touch_focus(self, inst):
        """``inst`` was touched: give it control, as a knob push would. Returns
        True when it took control. Touching the value already in control
        just restarts the timeout."""
        if not self.screen.isVisible():
            return False
        if self.screen.encoder_control and self._has_selection() \
                and self._selected_instrument() is inst:
            self._keep_control()
            return True
        if self.screen.encoder_control or self._walk_highlight_live():
            self._end_control()
        self._connect_timer()
        index = self._sorted_index(inst)
        if index is None:
            self._touch_inst = inst
        else:
            self.screen.encoder_current_selection = index
        edit_focus.claim(self)
        inst.enc_highlight(True)
        if inst.enc_select():
            self.screen.encoder_control = True
            self._keep_control()
            return True
        self._end_control()
        return False

    def release_focus(self):
        """Clear focus from outside the knob path: touch-away, a screen
        change, or another value taking the panel-wide focus."""
        if self.screen.encoder_control or self._touch_inst is not None:
            try:
                self._end_control()
            except RuntimeError:   # the instrument's Qt object is gone
                self._touch_inst = None
                self.screen.encoder_control = False
                edit_focus.release(self)
        else:
            edit_focus.release(self)

    def focus_hit(self, global_pos):
        """Is a press at ``global_pos`` on the focused value? An instrument
        with several values answers through ``edit_focus_hit``; otherwise the
        whole widget counts."""
        if not self._has_selection():
            return False
        inst = self._selected_instrument()
        hit = getattr(inst, "edit_focus_hit", None)
        if callable(hit):
            return bool(hit(global_pos))
        try:
            local = inst.mapFromGlobal(global_pos)
            return inst.rect().contains(local.toPoint())
        except (AttributeError, RuntimeError):
            return False

    def focused_instrument(self):
        """The instrument holding edit focus on this screen, or None."""
        if self.screen.encoder_control and self._has_selection():
            return self._selected_instrument()
        return None

    def _walk_highlight_live(self):
        """A knob-walk highlight (not in control) that has not timed out."""
        if not self.screen.encoder_list_sorted or not self.screen.encoder_timestamp:
            return False
        now = time.time_ns() // 1000000
        return now - self.screen.encoder_timeout < self.screen.encoder_timestamp

    def _sorted_index(self, inst):
        for pos, index in enumerate(self.screen.encoder_list_sorted):
            if self.screen.instruments.get(index) is inst:
                return pos
        return None

    def _has_selection(self):
        if self._touch_inst is not None:
            return True
        sel = self.screen.encoder_current_selection
        return bool(self.screen.encoder_list_sorted) and sel is not None \
            and 0 <= sel < len(self.screen.encoder_list_sorted)

    def _selected_instrument(self):
        if self._touch_inst is not None:
            return self._touch_inst
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
