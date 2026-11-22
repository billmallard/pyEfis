#  SPDX-License-Identifier: GPL-2.0-or-later
"""Selected-airspeed (IASSEL) edit rules for the box at the top of the airspeed
tape (AFC4, AER-5808).

Bill, 2026-11-16 (AER-5808): the IAS box is "touch and knob editable like the
ALTSEL box". So the tape takes the edit focus the same way the altimeter tape
does (a touch through the screen's ``EncoderController``, pyEfis #308, or the
knob walk), and these rules are the twin of :class:`altimeter.altsel.AltSelEditor`,
apart from Qt painting so they can be tested headless:

- inner knob 1 kt, outer ring 10 kt, clamped to the key's range but never
  below 1 kt: ``IASSEL`` 0 means "not set" (AFC1), and a knob must not unset
  the target the autopilot is flying;
- push syncs to the current airspeed, rounded to the knot;
- from "not set" (or no usable value) the first step starts from the synced
  airspeed.

Every edit is written to the bus at once with ``output_value()``; the AFC1
contract lets the PFD boxes write the targets, like the control head.
"""

FINE_STEP_KT = 1
COARSE_STEP_KT = 10
#: The lowest settable target: 0 is "not set".
MIN_SET_KT = 1


class IasSelEditor:
    """The IASSEL edit rules, over a :class:`bugs.BugBinding`.

    ``current_ias`` returns ``(airspeed_kt, valid)`` for the sync; the tape
    passes its own IAS item."""

    def __init__(self, binding, current_ias):
        self.binding = binding
        self.current_ias = current_ias

    @property
    def writable(self):
        return self.binding.item is not None

    def limits(self):
        item = self.binding.item
        lo = getattr(item, "min", None)
        hi = getattr(item, "max", None)
        lo = MIN_SET_KT if lo is None else max(MIN_SET_KT, lo)
        return lo, (999 if hi is None else int(hi))

    def clamp(self, value):
        lo, hi = self.limits()
        return int(max(lo, min(hi, value)))

    def is_set(self):
        b = self.binding
        return b.drawable() and b.value is not None and b.value > 0

    def synced_value(self):
        """The current airspeed rounded to the knot, or None when IAS is not
        usable (failed or bad)."""
        ias, valid = self.current_ias()
        if not valid or ias is None:
            return None
        return self.clamp(int(ias + 0.5))

    def step(self, delta_kt):
        """Add ``delta_kt`` and write. From "not set", start from the synced
        airspeed; with no usable airspeed either, write nothing."""
        if not self.writable:
            return False
        if self.is_set():
            base = self.binding.value
        else:
            base = self.synced_value()
            if base is None:
                return False
        self.write(int(round(base)) + delta_kt)
        return True

    def sync(self):
        """Push: set the target to the current airspeed. Returns False (and
        writes nothing) when there is no valid airspeed to sync to."""
        if not self.writable:
            return False
        v = self.synced_value()
        if v is None:
            return False
        self.write(v)
        return True

    def write(self, value):
        item = self.binding.item
        item.bad = False
        item.fail = False
        item.value = float(self.clamp(value))
        item.output_value()
