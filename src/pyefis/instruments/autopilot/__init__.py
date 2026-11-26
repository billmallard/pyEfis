#  Copyright (c) 2026 Bill Mallard
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

"""The ``autopilot_panel`` instrument (AFC3): a generic autopilot mode
controller (brief ``makerplane/briefs/autopilot_control_head_plan.md``
sections 5.1, 5.3 and 5.4; the FIX contract is fix-gateway
``doc/autopilot_keys.md``, AFC1).

Three groups, laid out the way pilots expect a mode controller:

- lateral: the HDG box; APR, NAV, HDG, TRK;
- centre: AP, FD, YD, LVL;
- vertical: the VS, IAS and ALT SEL boxes; IAS, VNAV, VS, ALT.

``layout: full`` is three columns; ``compact`` is two rows (boxes, then
buttons) for small panels and side strips. ``buttons`` is the comma list of
keys shown; TRK is left out by default (Bill, D6).

**The head asks, the autopilot decides** (brief section 3). A press writes
``APCMD`` and then bumps ``APCMDSEQ``; it never lights anything. Each key's
indicator bar is drawn from the state the autopilot source reports, and only
from it (:func:`reported_state`):

- off: the bar dark;
- armed: the bar a white outline (the mode is in ``APLATARM``/``APVERTARM``);
- active: the bar solid green (``APLAT``/``APVERT`` or the ``*ENG`` flag);
- request pending: the key's border flashes for about 2 s after a press
  while that key's reported state has not changed; then it turns amber once
  and the message line shows ``APMSG`` (or that the request was not taken);
- unavailable: the key greyed, never hidden, when ``APCAPS`` does not list it.

Each key reads one state name per axis, never a combination: NAV lights for
a lateral navigation mode (GPS, VOR, LOC, BC), APR for vertical approach
guidance (GS, GP). So on a coupled ILS both NAV and APR are lit, and a
localizer-only approach lights NAV alone. Telling "NAV" from "APR" on the
lateral axis needs a key the AFC1 contract does not have; the panel does not
guess it.

A press always writes its request, whatever the key shows: greyed is a look,
and the source refuses what it cannot fly, saying why in ``APMSG``. That
keeps LVL one press always (brief section 5.7): no focus is consulted and
nothing asks for confirmation.

When any state or health key is old, bad or failed (or the gateway does not
define it), the panel shows an explicit "no autopilot data" state: every
indicator dark, every key greyed, the message line amber. It never keeps the
last state (brief section 5.7, "stale is removed, not frozen").

The four value boxes are TK1 consumers (pyEfis #308): touch to focus, the edit
icon, inner/outer knob, push to sync (section 5.3 table). The panel is ONE
encoder instrument carrying four boxes, the pattern the altimeter tape uses
for ALTSEL and baro. VS and IAS are both always shown (D2); the box of the
active vertical mode carries the active accent.
"""

import logging
import time

from PyQt6.QtCore import QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from pyavtools import fix
from pyefis.instruments import edit_focus, helpers
from pyefis.instruments.airspeed import iassel
from pyefis.instruments.altimeter.altsel import AltSelEditor, round_to_step
from pyefis.instruments.autopilot.state import APState
from pyefis.instruments.helpers import bugs

logger = logging.getLogger(__name__)

# --- the keys and the groups -------------------------------------------------

LATERAL = ("APR", "NAV", "HDG", "TRK")
CENTRE = ("AP", "FD", "YD", "LVL")
VERTICAL = ("IAS", "VNAV", "VS", "ALT")
GROUPS = (LATERAL, CENTRE, VERTICAL)
ALL_BUTTONS = LATERAL + CENTRE + VERTICAL
#: TRK is hidden by default (D6); every other key is shown.
DEFAULT_BUTTONS = ",".join(b for b in ALL_BUTTONS if b != "TRK")

REQUEST_KEY = "APCMD"
SEQUENCE_KEY = "APCMDSEQ"
#: The state and health keys, read through :class:`state.APState`. Any of
#: them old, bad, failed or undefined puts the panel in the "no autopilot
#: data" state. The panel also reads FDENG, APCAPS and APMSG, which the mode
#: annunciation does not.
STATE_KEYS = ("APENG", "FDENG", "YDENG", "APLAT", "APLATARM", "APVERT",
              "APVERTARM", "APALTCAP", "APCAPS", "APMSG")

#: Lateral state names a NAV press produces (doc/autopilot_keys.md, State).
NAV_LATERAL = ("GPS", "VOR", "LOC", "BC")
#: Vertical approach guidance an APR press produces.
APPROACH_VERTICAL = ("GS", "GP")

OFF = "off"
ARMED = "armed"
ACTIVE = "active"
PENDING = "pending"
REFUSED = "refused"
UNAVAILABLE = "unavailable"
NO_DATA = "no_data"

#: A request with no change to its key's reported state for this long is
#: shown as not taken (brief section 5.4, "about 2 s").
PENDING_S = 2.0
#: How long the amber "not taken" look and its message stay up.
REFUSED_HOLD_S = 3.0
#: Pending flash period (on + off).
FLASH_PERIOD_S = 0.5
_TICK_MS = 100

NO_DATA_TEXT = "NO AUTOPILOT DATA"
NOT_TAKEN_TEXT = "%s NOT TAKEN"

# --- the value boxes (section 5.3) --------------------------------------------

BOX_HDG = "hdg"
BOX_VS = "vs"
BOX_IAS = "ias"
BOX_ALT = "altsel"
BOXES = (BOX_HDG, BOX_VS, BOX_IAS, BOX_ALT)
BOX_KEYS = {BOX_HDG: "HEADBUG", BOX_VS: "VSSEL", BOX_IAS: "IASSEL",
            BOX_ALT: "ALTSEL"}
BOX_LABELS = {BOX_HDG: "HDG", BOX_VS: "VS", BOX_IAS: "IAS",
              BOX_ALT: "ALT SEL"}
#: The aircraft value a push syncs each target to.
SYNC_KEYS = {BOX_HDG: "HEAD", BOX_VS: "VS", BOX_IAS: "IAS", BOX_ALT: "ALT"}
#: (inner, outer) knob steps. IAS matches the airspeed tape, 1 and 10 kt (G98).
BOX_STEPS = {BOX_HDG: (1, 10), BOX_VS: (100, 500), BOX_IAS: (1, 10),
             BOX_ALT: (100, 1000)}
#: The vertical mode whose box carries the active accent.
BOX_ACCENT_MODE = {BOX_VS: "VS", BOX_IAS: "IAS"}
BOX_TEXT_MASK = {BOX_HDG: "000", BOX_VS: "-0000", BOX_IAS: "000",
                 BOX_ALT: "00000"}
DASHES = "---"


def _names(text):
    """A comma list (``GS,ALT``) as a tuple of names; "" is empty."""
    if not text:
        return ()
    return tuple(n.strip() for n in str(text).split(",") if n.strip())


def parse_buttons(value):
    """The ``buttons`` option (a comma string or a list) as the known keys,
    in group order. An unknown name is ignored with a warning."""
    if isinstance(value, str):
        wanted = _names(value.upper())
    else:
        wanted = tuple(str(v).strip().upper() for v in (value or ()))
    for name in wanted:
        if name not in ALL_BUTTONS:
            logger.warning("autopilot_panel: unknown button %r ignored", name)
    return tuple(b for b in ALL_BUTTONS if b in wanted)


class Snapshot:
    """The autopilot source's reported state, as read from the bus."""

    def __init__(self, ap=False, fd=False, yd=False, lat="", latarm="",
                 vert="", vertarm="", altcap=False, caps=""):
        self.ap = bool(ap)
        self.fd = bool(fd)
        self.yd = bool(yd)
        self.lat = lat or ""
        self.latarm = _names(latarm)
        self.vert = vert or ""
        self.vertarm = _names(vertarm)
        self.altcap = bool(altcap)
        self.caps = _names(caps)


def reported_state(button, s):
    """OFF, ARMED or ACTIVE for ``button`` from the reported state ``s``
    alone. A press has no input here: that is the point."""
    if button == "AP":
        return ACTIVE if s.ap else OFF
    if button == "FD":
        return ACTIVE if s.fd else OFF
    if button == "YD":
        return ACTIVE if s.yd else OFF
    if button == "LVL":
        return ACTIVE if "LVL" in (s.lat, s.vert) else OFF
    if button in ("HDG", "TRK"):
        return _axis(s.lat, s.latarm, (button,))
    if button == "NAV":
        return _axis(s.lat, s.latarm, NAV_LATERAL)
    if button == "APR":
        return _axis(s.vert, s.vertarm, APPROACH_VERTICAL)
    if button == "ALT":
        st = _axis(s.vert, s.vertarm, ("ALT",))
        if st == OFF and s.altcap:
            return ARMED
        return st
    if button in ("VS", "IAS", "VNAV"):
        return _axis(s.vert, s.vertarm, (button,))
    return OFF


def _axis(active, armed, names):
    if active in names:
        return ACTIVE
    if any(n in names for n in armed):
        return ARMED
    return OFF


class _Request:
    def __init__(self, at, before):
        self.at = at
        self.before = before


class TargetEditor:
    """Knob and push rules for a HDG, VS or IAS target over a
    :class:`bugs.BugBinding` (ALT SEL uses TK5's :class:`AltSelEditor`, so
    its rules are the altimeter box's exactly).

    ``current`` returns ``(value, valid)`` for the push sync. ``wrap`` makes
    the value wrap through 0..359 (the heading bug, as the HSI writes it).
    ``unset`` is the value that means "no target" (``IASSEL`` 0): it draws
    dashes, and the first knob step starts from the synced value; with no
    synced value either, a step writes nothing. ``floor`` is the lowest value
    ever written, over the key's own min: the IAS box passes 1 so it never
    writes ``IASSEL`` 0 and unsets the autopilot's target (G98, pyEfis #556,
    the airspeed tape's rule in :mod:`airspeed.iassel`)."""

    def __init__(self, binding, current, sync_round=1, wrap=False,
                 unset=None, limits=(None, None), floor=None):
        self.binding = binding
        self.current = current
        self.sync_round = sync_round
        self.wrap = wrap
        self.unset = unset
        self._limits = limits
        self.floor = floor

    @property
    def writable(self):
        return self.binding.item is not None

    def value(self):
        """The target worth showing, or None."""
        if not self.binding.drawable():
            return None
        v = self.binding.value
        if v is None or (self.unset is not None and v == self.unset):
            return None
        return v

    def limits(self):
        item = self.binding.item
        lo = getattr(item, "min", None)
        hi = getattr(item, "max", None)
        dlo, dhi = self._limits
        lo = dlo if lo is None else lo
        if self.floor is not None:
            lo = self.floor if lo is None else max(self.floor, lo)
        return lo, (dhi if hi is None else hi)

    def clamp(self, value):
        if self.wrap:
            return int(round(value)) % 360
        lo, hi = self.limits()
        if lo is not None:
            value = max(lo, value)
        if hi is not None:
            value = min(hi, value)
        return value

    def synced_value(self):
        v, valid = self.current()
        if not valid or v is None:
            return None
        return self.clamp(round_to_step(float(v), self.sync_round))

    def step(self, delta):
        if not self.writable:
            return False
        base = self.value()
        if base is None:
            base = self.synced_value()
            if base is None:
                if self.unset is not None:
                    return False
                base = 0
        self.write(base + delta)
        return True

    def sync(self):
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
        item.value = self.clamp(value)
        item.output_value()


class TargetBox(QWidget):
    """One value box: a small label over the value, the edit marks, and a
    press that becomes a touch focus for the panel."""

    def __init__(self, panel, which):
        super().__init__(panel)
        self.panel = panel
        self.which = which
        self.highlighted = False
        self.focused = False
        self._font_pt = None
        self._label_pt = None

    def resizeEvent(self, event):
        self._font_pt = None
        self._label_pt = None
        super().resizeEvent(event)

    def value_rect(self):
        r = edit_focus.inset_for_marks(QRectF(self.rect()))
        lh = r.height() * 0.30
        return QRectF(r.left(), r.top() + lh, r.width(), r.height() - lh)

    def label_rect(self):
        r = edit_focus.inset_for_marks(QRectF(self.rect()))
        return QRectF(r.left(), r.top(), r.width(), r.height() * 0.30)

    def text(self):
        return self.panel.box_text(self.which)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        panel = self.panel
        lr = self.label_rect()
        r = self.value_rect()
        if self._label_pt is None:
            self._label_pt = helpers.fit_to_mask(
                lr.width() * 0.9, lr.height() * 0.85, "ALT SEL",
                panel.font_family)
            self._font_pt = helpers.fit_to_mask(
                r.width() * 0.82, r.height() * 0.72,
                BOX_TEXT_MASK[self.which], panel.font_family)
        accent = panel.box_accent(self.which)
        f = QFont(panel.font_family)
        f.setPointSizeF(max(1.0, self._label_pt * panel._font_scale()))
        p.setFont(f)
        p.setPen(QColor(panel.active_color if accent else panel.muted_color))
        p.drawText(lr, Qt.AlignmentFlag.AlignCenter, BOX_LABELS[self.which])
        border = QColor(panel.active_color) if accent \
            else QColor(panel.line_color)
        helpers.draw_readout_panel(
            p, r, helpers.READOUT_RADIUS_RATIO * r.height(), border,
            pen_width=max(1.0, r.height() * (0.09 if accent else 0.04)),
            fill_alpha=1.0)
        if self.highlighted and not self.focused:
            fg = QColor("orange")   # knob-walk highlight, as the gauges use
        else:
            fg = panel.box_color(self.which)
        f = QFont(panel.font_family)
        f.setPointSizeF(max(1.0, self._font_pt * panel._font_scale()))
        p.setFont(f)
        p.setPen(fg)
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, self.text())
        if panel.box_editable(self.which) or self.focused:
            edit_focus.draw_edit_marks(p, r, focused=self.focused,
                                       bounds=QRectF(self.rect()))
        p.end()

    def mousePressEvent(self, event):
        if self.panel.box_editable(self.which) \
                and self.panel._touch_box(self.which):
            event.accept()
            return
        super().mousePressEvent(event)


class ModeButton(QWidget):
    """One mode key: an indicator bar over a label. All of its look comes
    from :meth:`AutopilotPanel.display_state`."""

    def __init__(self, panel, name):
        super().__init__(panel)
        self.panel = panel
        self.name = name
        self._font_pt = None

    def resizeEvent(self, event):
        self._font_pt = None
        super().resizeEvent(event)

    def key_rect(self):
        r = QRectF(self.rect())
        m = max(1.0, min(r.width(), r.height()) * 0.06)
        return r.adjusted(m, m, -m, -m)

    def bar_rect(self):
        k = self.key_rect()
        h = max(3.0, k.height() * 0.16)
        inset = k.width() * 0.18
        top = k.top() + k.height() * 0.12
        return QRectF(k.left() + inset, top, k.width() - 2 * inset, h)

    def label_rect(self):
        k = self.key_rect()
        b = self.bar_rect()
        return QRectF(k.left(), b.bottom(), k.width(), k.bottom() - b.bottom())

    def colors(self):
        """(face, border, border_width_scale, label, bar_fill, bar_line) for
        the current display state; ``None`` is "do not draw"."""
        panel = self.panel
        state = panel.display_state(self.name)
        reported = panel.reported(self.name)
        lvl = self.name == "LVL"
        face = QColor(panel.level_color if lvl else panel.key_color)
        border = QColor(panel.line_color)
        border.setAlpha(110)
        width = 1.0
        label = QColor(panel.text_color)
        bar_fill = None
        bar_line = QColor(panel.muted_color)
        bar_line.setAlpha(90)
        if state in (NO_DATA, UNAVAILABLE):
            label = QColor(panel.muted_color)
            if lvl:
                face.setAlpha(110)
            return face, border, width, label, None, bar_line
        if reported == ACTIVE:
            bar_fill = QColor(panel.active_color)
            bar_line = None
        elif reported == ARMED:
            bar_line = QColor(panel.armed_color)
        if state == PENDING:
            if panel.flash_on(self.name):
                border = QColor(panel.text_color)
                width = 2.5
        elif state == REFUSED:
            border = QColor(panel.caution_color)
            width = 2.5
            if bar_fill is None:
                bar_line = QColor(panel.caution_color)
        return face, border, width, label, bar_fill, bar_line

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        face, border, width, label, bar_fill, bar_line = self.colors()
        k = self.key_rect()
        radius = min(k.width(), k.height()) * 0.12
        pw = max(1.0, k.height() * 0.035) * width
        p.setPen(QPen(border, pw))
        p.setBrush(face)
        p.drawRoundedRect(k.adjusted(pw / 2, pw / 2, -pw / 2, -pw / 2),
                          radius, radius)
        b = self.bar_rect()
        if bar_fill is not None:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(bar_fill)
            p.drawRoundedRect(b, b.height() * 0.3, b.height() * 0.3)
        elif bar_line is not None:
            lw = max(1.0, b.height() * 0.22)
            p.setPen(QPen(bar_line, lw))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(b.adjusted(lw / 2, lw / 2, -lw / 2, -lw / 2),
                              b.height() * 0.3, b.height() * 0.3)
        lr = self.label_rect()
        if self._font_pt is None:
            self._font_pt = helpers.fit_to_mask(
                lr.width() * 0.8, lr.height() * 0.62, "VNAV",
                self.panel.font_family)
        f = QFont(self.panel.font_family)
        f.setPointSizeF(max(1.0, self._font_pt * self.panel._font_scale()))
        f.setBold(True)
        p.setFont(f)
        p.setPen(label)
        p.drawText(lr, Qt.AlignmentFlag.AlignCenter, self.name)
        p.end()

    def mousePressEvent(self, event):
        self.panel.press(self.name)
        event.accept()


class AutopilotPanel(QWidget):
    def __init__(self, parent=None, font_family="DejaVu Sans Condensed",
                 font_percent=None):
        super().__init__(parent)
        self.font_family = font_family
        self.font_percent = font_percent
        # Panel options (InstrumentSpec Props in screenbuilder_factory).
        self._layout = "full"
        self._buttons = parse_buttons(DEFAULT_BUTTONS)
        self.active_color = "#00ff00"
        self.armed_color = "#ffffff"
        self.caution_color = "#ffaa00"
        self.key_color = "#101418"
        self.level_color = "#1f5fbf"
        self.text_color = "#ffffff"
        self.muted_color = "#aaaaaa"
        self.line_color = "#ffffff"
        self.target_color = "#00ffff"
        self.bg_color = "#000000"
        self.touch_edit = True

        self._clock = time.monotonic
        self._requests = {}       # button -> _Request
        self._timer = QTimer(self)
        self._timer.setInterval(_TICK_MS)
        self._timer.timeout.connect(self._tick)

        self._state = APState(STATE_KEYS, self)
        self._state.changed.connect(self._state_changed)
        self._cmd = self._get_item(REQUEST_KEY)
        self._seq = self._get_item(SEQUENCE_KEY)

        self._bindings = {}
        self._editors = {}
        self._sync_items = {}
        for box in BOXES:
            self._sync_items[box] = self._get_item(SYNC_KEYS[box], quiet=True)
            binding = bugs.BugBinding(BOX_KEYS[box], self)
            binding.changed.connect(self._repaint_boxes)
            self._bindings[box] = binding
            current = self._current_fn(box)
            if box == BOX_ALT:
                self._editors[box] = AltSelEditor(binding, current)
            elif box == BOX_HDG:
                self._editors[box] = TargetEditor(binding, current, wrap=True)
            elif box == BOX_VS:
                self._editors[box] = TargetEditor(
                    binding, current, sync_round=100,
                    limits=(-30000, 30000))
            else:
                self._editors[box] = TargetEditor(
                    binding, current, unset=0, limits=(0, 999.9),
                    floor=iassel.MIN_SET_KT)
        for item in self._sync_items.values():
            if item is not None:
                item.failChanged.connect(self._repaint_boxes)

        self._edit_box = None
        self._touch_pending = None
        self.boxes = {box: TargetBox(self, box) for box in BOXES}
        self.button_widgets = {}
        self._build_buttons()

    # --- options ---------------------------------------------------------

    # ``layout`` would shadow QWidget.layout(), so that option arrives
    # through this setter (``apply="setter:setPanelLayout"``).
    @property
    def panel_layout(self):
        return self._layout

    def setPanelLayout(self, value):
        value = str(value or "full").lower()
        if value not in ("full", "compact"):
            logger.warning("autopilot_panel: unknown layout %r, using full",
                           value)
            value = "full"
        self._layout = value
        self._place()

    @property
    def buttons(self):
        return ",".join(self._buttons)

    @buttons.setter
    def buttons(self, value):
        self._buttons = parse_buttons(value)
        self._build_buttons()

    def _font_scale(self):
        try:
            return float(self.font_percent) if self.font_percent else 1.0
        except (TypeError, ValueError):
            return 1.0

    # --- FIX plumbing ----------------------------------------------------

    def _get_item(self, key, quiet=False):
        try:
            return fix.db.get_item(key)
        except KeyError:
            if not quiet:
                logger.warning("autopilot_panel: FIX key %s not defined by "
                               "the gateway", key)
            return None

    def _current_fn(self, box):
        def current():
            item = self._sync_items.get(box)
            if item is None or item.fail or item.bad:
                return None, False
            return item.value, True
        return current

    # --- reported state --------------------------------------------------

    def has_data(self):
        """Every state and health key defined and fresh."""
        return self._state.fresh

    def snapshot(self):
        v = {k: self._state.value(k) for k in STATE_KEYS}
        return Snapshot(ap=v.get("APENG"), fd=v.get("FDENG"),
                        yd=v.get("YDENG"), lat=v.get("APLAT"),
                        latarm=v.get("APLATARM"), vert=v.get("APVERT"),
                        vertarm=v.get("APVERTARM"),
                        altcap=v.get("APALTCAP"), caps=v.get("APCAPS"))

    def reported(self, button):
        """The key's reported state, OFF while there is no autopilot data."""
        if not self.has_data():
            return OFF
        return reported_state(button, self.snapshot())

    def display_state(self, button):
        """What the key shows: NO_DATA, PENDING, REFUSED, ACTIVE, ARMED,
        UNAVAILABLE or OFF. ACTIVE and ARMED come from the bus only."""
        if not self.has_data():
            return NO_DATA
        self._expire()
        req = self._requests.get(button)
        if req is not None:
            return PENDING if self._clock() - req.at < PENDING_S else REFUSED
        s = self.snapshot()
        st = reported_state(button, s)
        if st != OFF:
            return st
        if button not in s.caps:
            return UNAVAILABLE
        return OFF

    def flash_on(self, button):
        req = self._requests.get(button)
        if req is None:
            return False
        phase = ((self._clock() - req.at) % FLASH_PERIOD_S) / FLASH_PERIOD_S
        return phase < 0.5

    def message(self):
        """(text, colour) for the message line, or ("", None)."""
        if not self.has_data():
            return NO_DATA_TEXT, QColor(self.caution_color)
        self._expire()
        now = self._clock()
        msg = self._state.value("APMSG") or ""
        refused = [b for b, r in self._requests.items()
                   if now - r.at >= PENDING_S]
        if refused:
            text = msg or NOT_TAKEN_TEXT % refused[-1]
            return text, QColor(self.caution_color)
        if msg:
            return msg, QColor(self.text_color)
        return "", None

    def _state_changed(self, *_):
        if self.has_data():
            s = self.snapshot()
            for button in list(self._requests):
                if reported_state(button, s) != self._requests[button].before:
                    del self._requests[button]
        self._repaint_all()

    def _expire(self):
        now = self._clock()
        for button in [b for b, r in self._requests.items()
                       if now - r.at >= PENDING_S + REFUSED_HOLD_S]:
            del self._requests[button]

    def _tick(self):
        self._expire()
        if not self._requests:
            self._timer.stop()
        self._repaint_all()

    # --- requests --------------------------------------------------------

    def press(self, button):
        """A press of ``button``: write the request, then mark it pending.
        Never consults focus and never asks to confirm (LVL is one press,
        always). Returns True when the request was written."""
        if self._cmd is None or self._seq is None:
            logger.warning("autopilot_panel: %s press dropped, the gateway "
                           "has no %s/%s", button, REQUEST_KEY, SEQUENCE_KEY)
            return False
        before = self.reported(button)
        self._cmd.bad = False
        self._cmd.fail = False
        self._cmd.value = button
        self._cmd.output_value()
        try:
            seq = int(self._seq.value or 0)
        except (TypeError, ValueError):
            seq = 0
        nxt = seq + 1
        hi = getattr(self._seq, "max", None)
        if hi is not None and nxt > hi:
            nxt = 0
        self._seq.bad = False
        self._seq.fail = False
        self._seq.value = nxt
        self._seq.output_value()
        self._requests[button] = _Request(self._clock(), before)
        if not self._timer.isActive():
            self._timer.start()
        self._repaint_all()
        return True

    # --- the boxes -------------------------------------------------------

    def box_text(self, which):
        ed = self._editors[which]
        if which == BOX_ALT:
            if not ed.binding.drawable():
                return DASHES
            return str(int(round(ed.binding.value)))
        v = ed.value()
        if v is None:
            return DASHES
        v = int(round(float(v)))
        if which == BOX_HDG:
            return "%03d" % (v % 360)
        if which == BOX_VS:
            return "%+d" % v if v else "0"
        return str(v)

    def box_color(self, which):
        return self._bindings[which].color(QColor(self.target_color))

    def box_accent(self, which):
        mode = BOX_ACCENT_MODE.get(which)
        return mode is not None and self.has_data() \
            and self.snapshot().vert == mode

    def box_editable(self, which):
        return bool(self.touch_edit) and self._editors[which].writable

    def _repaint_boxes(self, *_):
        for box in self.boxes.values():
            box.update()

    def _repaint_all(self):
        self.update()
        for w in self.button_widgets.values():
            w.update()
        self._repaint_boxes()

    # --- layout ----------------------------------------------------------

    def _build_buttons(self):
        for w in self.button_widgets.values():
            w.hide()
            w.deleteLater()
        self.button_widgets = {name: ModeButton(self, name)
                               for name in self._buttons}
        for w in self.button_widgets.values():
            w.show()
        self._place()

    def resizeEvent(self, event):
        self._place()
        super().resizeEvent(event)

    def message_rect(self):
        return QRectF(self._message_rect)

    def _place(self):
        if not hasattr(self, "boxes"):
            return
        w, h = float(self.width()), float(self.height())
        if self._layout == "compact":
            self._place_compact(w, h)
        else:
            self._place_full(w, h)

    def _place_full(self, w, h):
        # Columns of two keys each: lateral, centre, vertical. The HDG box
        # sits over the lateral keys; VS, IAS and ALT SEL share the span over
        # the centre and vertical keys, so all four boxes are one size. The
        # message strip runs along the bottom.
        gap = max(2.0, min(w, h) * 0.02)
        col_w = (w - 4 * gap) / 3.0
        cols = [gap + i * (col_w + gap) for i in range(3)]
        top_h = h * 0.36
        msg_h = h * 0.14
        box_h = top_h - gap
        span = cols[2] + col_w - cols[1]
        box_w = (span - 2 * gap) / 3.0
        self.boxes[BOX_HDG].setGeometry(
            int(cols[0] + (col_w - box_w) / 2.0), int(gap), int(box_w),
            int(box_h))
        for i, box in enumerate((BOX_VS, BOX_IAS, BOX_ALT)):
            self.boxes[box].setGeometry(
                int(cols[1] + i * (box_w + gap)), int(gap), int(box_w),
                int(box_h))
        rows_top = top_h + gap
        row_h = (h - rows_top - msg_h - gap) / 2.0
        self._message_rect = QRectF(gap, rows_top + 2 * row_h,
                                    w - 2 * gap, msg_h)
        key_w = col_w / 2.0
        for c, group in enumerate(GROUPS):
            shown = [b for b in group if b in self.button_widgets]
            for i, name in enumerate(shown):
                x = cols[c] + (i % 2) * key_w
                y = rows_top + (i // 2) * row_h
                self.button_widgets[name].setGeometry(
                    int(x), int(y), int(key_w), int(row_h))

    def _place_compact(self, w, h):
        gap = max(2.0, min(w, h) * 0.03)
        top_h = h * 0.45
        n_box = len(BOXES)
        box_w = (w - gap) * 0.62 / n_box
        for i, box in enumerate(BOXES):
            self.boxes[box].setGeometry(
                int(gap + i * box_w), int(gap / 2), int(box_w - gap),
                int(top_h - gap))
        mx = gap + n_box * box_w
        self._message_rect = QRectF(mx, gap / 2, w - mx - gap, top_h - gap)
        groups = [[b for b in g if b in self.button_widgets] for g in GROUPS]
        groups = [g for g in groups if g]
        n = sum(len(g) for g in groups)
        if not n:
            return
        group_gap = gap * 2
        key_w = (w - gap - group_gap * (len(groups) - 1)) / n
        x = gap / 2
        for group in groups:
            for name in group:
                self.button_widgets[name].setGeometry(
                    int(x), int(top_h), int(key_w), int(h - top_h - gap / 2))
                x += key_w
            x += group_gap

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(self.bg_color))
        text, color = self.message()
        if not text:
            p.end()
            return
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.message_rect()
        f = QFont(self.font_family)
        f.setPixelSize(max(8, int(min(r.height() * 0.62,
                                      r.width() / 22.0)
                                  * self._font_scale())))
        f.setBold(True)
        p.setFont(f)
        p.setPen(color)
        p.drawText(r, Qt.AlignmentFlag.AlignCenter
                   | Qt.TextFlag.TextWordWrap, text)
        p.end()

    # --- the EncoderController protocol (#308), dispatched per box ------
    #
    # Like the altimeter tape: ONE encoder instrument, several boxes. A touch
    # names its box; the knob walk lands on the first box. edit_focus_hit
    # counts only the focused box, so a press on a key or another box
    # releases focus (and still reaches what was pressed).

    def _edit_boxes(self):
        return [b for b in BOXES if self._editors[b].writable]

    def _encoder_controller(self):
        w = self.parent()
        while w is not None:
            ctl = getattr(w, "encoder_controller", None)
            if ctl is not None:
                return ctl
            w = w.parent()
        return None

    def _touch_box(self, which):
        ctl = self._encoder_controller()
        if ctl is None:
            return False
        if ctl.focused_instrument() is self and self._edit_box != which:
            ctl.release_focus()
        self._touch_pending = which
        try:
            ctl.touch_focus(self)
        finally:
            self._touch_pending = None
        return True

    def edit_focus_key(self, key):
        """The ``focus`` action (EncoderController.focus_key): take focus on
        the shown target box that edits ``key``, as a touch on it would."""
        for which in BOXES:
            if BOX_KEYS[which] == key and self.box_editable(which):
                return self._touch_box(which)
        return False

    def _active_box(self):
        if self._edit_box is not None:
            return self._edit_box
        boxes = self._edit_boxes()
        return boxes[0] if boxes else None

    def enc_selectable(self):
        return bool(self._edit_boxes())

    def enc_highlight(self, onoff):
        if onoff:
            if self._touch_pending is not None:
                self._edit_box = self._touch_pending
            box = self._active_box()
            if box is not None:
                self.boxes[box].highlighted = True
                self.boxes[box].repaint()
            return
        for box in self.boxes.values():
            box.highlighted = False
            box.focused = False
            box.repaint()
        self._edit_box = None

    def enc_select(self):
        if self._touch_pending is not None:
            self._edit_box = self._touch_pending
        box = self._active_box()
        if box is None:
            return False
        self._edit_box = box
        self.boxes[box].focused = True
        self.boxes[box].repaint()
        return True

    def _step(self, steps, outer):
        box = self._edit_box
        if box is None:
            return False
        fine, coarse = BOX_STEPS[box]
        ok = self._editors[box].step((coarse if outer else fine) * steps)
        self.boxes[box].repaint()
        return ok

    def enc_changed(self, steps):
        return self._step(steps, False)

    def enc_outer_changed(self, steps):
        return self._step(steps, True)

    def enc_clicked(self):
        """Push: sync to the aircraft's value and end the edit (TK5's
        rule). With nothing valid to sync to, nothing is written and the box
        keeps focus."""
        box = self._edit_box
        if box is None:
            return False
        synced = self._editors[box].sync()
        self.boxes[box].repaint()
        return not synced

    def edit_focus_hit(self, global_pos):
        if self._edit_box is None:
            return False
        box = self.boxes[self._edit_box]
        if not box.isVisible():
            return False
        return box.rect().contains(box.mapFromGlobal(global_pos).toPoint())

    def keyPressEvent(self, event):
        pass

    def wheelEvent(self, event):
        pass
