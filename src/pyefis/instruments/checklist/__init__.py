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
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.

"""Interactive checklist instrument (CAP-115, backlog P1.1 -- Phase 1).

A scrolling challenge-response checklist the pilot works through with the
encoder or a soft/physical button. This is the pyEfis-only Phase 1 of the
cross-repo checklist feature (plan: ``makerplane/briefs/checklist_instrument_plan.md``):
config is an **inline** structured payload, so the widget is provable on the
bench with hand-written YAML before any configurator work exists. Phase 3 will
replace the inline payload with a ``checklist_ref`` binding to a checklist set
authored per-aircraft in the configurator -- but the widget's *internal*
interface (it consumes a resolved checklist set) is unchanged, so no rewrite.

The widget reads **no FIX keys** -- checklist state is entirely local. It is
driven two ways:

  * the encoder HMI protocol (``enc_*`` methods), modelled on ``listbox`` --
    turn to move the current item, click to acknowledge + auto-advance;
  * HMI actions (``pyefis.hmi.actionclass``), so a Button or a real panel key
    can advance/acknowledge/reset the checklist without the widget owning a FIX
    key. Each action carries an optional target group (``hmi_group``); an empty
    target addresses every checklist on the screen (the ``set airspeed mode``
    precedent).

Acknowledged state is **in-memory and resets on restart** -- this is intended
(a fresh checklist every flight), not a gap (plan section 2.6).

The parsing / traversal / acknowledge logic lives in :class:`ChecklistModel`,
a pure (Qt-free) class so it can be unit-tested headless (the ``zoom_by_core``
pattern). The :class:`Checklist` widget is a thin QPainter view over it.

Everything is construct-never-raises: a missing / empty / malformed config
yields an empty "No checklist" state rather than an exception
(``pyEfis/CLAUDE.md`` convention).
"""

import logging

from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from pyefis import hmi

logger = logging.getLogger(__name__)

# Category -> the header / complete-line colour. The one place category is
# load-bearing (plan section 2.2): normal green, abnormal amber, emergency red.
_CATEGORY_COLORS = {
    "normal": "#00ff00",
    "abnormal": "#ffbf00",
    "emergency": "#ff0000",
}


class ChecklistModel:
    """Pure, Qt-free checklist state: the parsed set, the active checklist, the
    current row, and the acknowledged flags. Every method is total -- it never
    raises on empty / out-of-range state, so the widget can call it blindly."""

    def __init__(self, payload=None):
        self.checklists = []   # list of {id, title, category, entries}
        self.active = 0        # index into self.checklists
        self.current = 0       # index into the active checklist's SELECTABLE rows
        self.load(payload)

    # -- loading ----------------------------------------------------------
    def load(self, payload):
        """(Re)load from an inline payload. Accepts either a raw list of
        checklist objects (the Phase 1 inline form) or a set object
        ``{schema_version, checklists: [...]}`` (the delivered form), so the
        same widget serves both without a rewrite. Anything malformed is
        skipped; a wholly unusable payload yields zero checklists."""
        self.checklists = []
        self.active = 0
        self.current = 0
        items = payload
        if isinstance(payload, dict):
            items = payload.get("checklists")
        if not isinstance(items, (list, tuple)):
            return
        for c in items:
            parsed = self._parse_checklist(c)
            if parsed is not None:
                self.checklists.append(parsed)
        self._clamp()

    def _parse_checklist(self, c):
        if not isinstance(c, dict):
            return None
        entries = []
        sections = c.get("sections")
        if isinstance(sections, (list, tuple)):
            for s in sections:
                if not isinstance(s, dict):
                    continue
                title = s.get("title")
                if title:
                    entries.append({"kind": "section", "text": str(title)})
                for it in self._items_of(s):
                    entry = self._parse_item(it)
                    if entry is not None:
                        entries.append(entry)
        # Flat items (no sections) are also allowed (plan section 2.2).
        for it in self._items_of(c):
            entry = self._parse_item(it)
            if entry is not None:
                entries.append(entry)
        return {
            "id": str(c.get("id", "")),
            "title": str(c.get("title", "")),
            "category": str(c.get("category", "normal")),
            "entries": entries,
        }

    @staticmethod
    def _items_of(d):
        items = d.get("items")
        return items if isinstance(items, (list, tuple)) else []

    @staticmethod
    def _parse_item(it):
        """An item is ``{text, response?, note?}``. A row with text is an
        acknowledgeable challenge-response item; a row that is only a ``note``
        is an informational line that cannot be acknowledged (plan 2.2)."""
        if not isinstance(it, dict):
            return None
        text = it.get("text")
        if text:
            response = it.get("response")
            return {
                "kind": "item",
                "text": str(text),
                "response": "" if response is None else str(response),
                "acked": False,
            }
        note = it.get("note")
        if note:
            return {"kind": "note", "text": str(note)}
        return None

    # -- active-checklist helpers ----------------------------------------
    def _entries(self):
        if not self.checklists:
            return []
        return self.checklists[self.active]["entries"]

    def selectable(self):
        """Rows the current-item cursor can land on: items and notes, never
        section headers."""
        return [e for e in self._entries() if e["kind"] in ("item", "note")]

    def current_entry(self):
        sel = self.selectable()
        if not sel:
            return None
        return sel[self.current]

    def _clamp(self):
        if self.checklists:
            self.active %= len(self.checklists)
        else:
            self.active = 0
        n = len(self.selectable())
        if n:
            self.current %= n
        else:
            self.current = 0

    # -- traversal / acknowledge -----------------------------------------
    def move(self, delta):
        """Move the current row by ``delta`` selectable rows, wrapping."""
        sel = self.selectable()
        if not sel:
            self.current = 0
            return
        self.current = (self.current + int(delta)) % len(sel)

    def toggle(self):
        """Flip the acknowledged flag of the current item (no-op on a section
        header or an informational note)."""
        entry = self.current_entry()
        if entry is not None and entry["kind"] == "item":
            entry["acked"] = not entry["acked"]

    def acknowledge_advance(self):
        """The encoder-click behaviour: acknowledge the current item, then jump
        to the next un-acknowledged item. Toggling an item back off does not
        jump (you are correcting, not progressing)."""
        entry = self.current_entry()
        if entry is None or entry["kind"] != "item":
            return
        was = entry["acked"]
        entry["acked"] = not entry["acked"]
        if entry["acked"] and not was:
            self.next_unacked()

    def next_unacked(self):
        """Move the current row to the next un-acknowledged item, wrapping. No
        change when every item is already acknowledged (or there are none)."""
        sel = self.selectable()
        n = len(sel)
        if not n:
            return
        for step in range(1, n + 1):
            idx = (self.current + step) % n
            e = sel[idx]
            if e["kind"] == "item" and not e["acked"]:
                self.current = idx
                return

    # -- multi-checklist selection ---------------------------------------
    def next_list(self):
        self._switch(1)

    def prev_list(self):
        self._switch(-1)

    def _switch(self, delta):
        if len(self.checklists) <= 1:
            return
        self.active = (self.active + int(delta)) % len(self.checklists)
        self.current = 0

    def select(self, slug):
        """Activate the checklist whose id matches ``slug``. Returns True on a
        hit, False if no checklist has that id."""
        for i, c in enumerate(self.checklists):
            if c["id"] == str(slug):
                self.active = i
                self.current = 0
                return True
        return False

    def reset_active(self):
        """Clear every acknowledgement in the active checklist and return the
        cursor to the top -- 'start this checklist over'."""
        for e in self._entries():
            if e["kind"] == "item":
                e["acked"] = False
        self.current = 0

    # -- read-outs --------------------------------------------------------
    def progress(self):
        """``(acknowledged, total)`` over the active checklist's items."""
        items = [e for e in self._entries() if e["kind"] == "item"]
        done = sum(1 for e in items if e["acked"])
        return done, len(items)

    def is_complete(self):
        done, total = self.progress()
        return total > 0 and done == total

    def active_checklist(self):
        if not self.checklists:
            return None
        return self.checklists[self.active]


class Checklist(QWidget):
    """The checklist instrument. A thin QPainter view over
    :class:`ChecklistModel` wired to the encoder and the HMI action hub."""

    def __init__(self, parent=None, checklists=None,
                 font_family="DejaVu Sans Condensed"):
        super().__init__(parent)
        self.parent = parent
        self.font_family = font_family
        # apply="attr" appearance defaults (kept in lockstep with the
        # InstrumentSpec Props -- the registry gate asserts these match).
        self.hmi_group = ""
        self.text_color = "#ffffff"
        self.response_color = "#00ffff"
        self.done_color = "#00ff00"
        self.current_color = "#ffaa00"
        self.section_color = "#aaaaaa"

        self._selected = False   # encoder highlight state
        self.model = ChecklistModel(checklists)
        self._connect_hmi()

    # -- HMI action hub ---------------------------------------------------
    def _connect_hmi(self):
        """Subscribe to the checklist HMI actions so a Button / panel key can
        drive this widget. Guarded so construction never depends on the hub
        being initialised (construct-never-raises)."""
        if hmi.actions is None:
            return
        a = hmi.actions
        for signal, handler in (
            (a.checklistNextItem, self._act_next_item),
            (a.checklistPrevItem, self._act_prev_item),
            (a.checklistToggleItem, self._act_toggle_item),
            (a.checklistNextUnacked, self._act_next_unacked),
            (a.checklistNextList, self._act_next_list),
            (a.checklistPrevList, self._act_prev_list),
            (a.checklistReset, self._act_reset),
        ):
            try:
                signal.connect(handler)
            except Exception:
                logger.warning("checklist: could not connect HMI action",
                               exc_info=True)

    def _targeted(self, target):
        """Does an HMI action addressed to ``target`` apply to this widget? An
        empty / '*' target addresses every checklist; otherwise the target must
        match this widget's ``hmi_group`` (the ``setInstUnits`` name filter)."""
        t = "" if target is None else str(target).strip()
        return t in ("", "*") or t == self.hmi_group

    def _act_next_item(self, target=""):
        if self._targeted(target):
            self.model.move(1)
            self.update()

    def _act_prev_item(self, target=""):
        if self._targeted(target):
            self.model.move(-1)
            self.update()

    def _act_toggle_item(self, target=""):
        if self._targeted(target):
            self.model.toggle()
            self.update()

    def _act_next_unacked(self, target=""):
        if self._targeted(target):
            self.model.next_unacked()
            self.update()

    def _act_next_list(self, target=""):
        if self._targeted(target):
            self.model.next_list()
            self.update()

    def _act_prev_list(self, target=""):
        if self._targeted(target):
            self.model.prev_list()
            self.update()

    def _act_reset(self, target=""):
        if self._targeted(target):
            self.model.reset_active()
            self.update()

    # -- encoder HMI protocol (mirrors listbox) --------------------------
    def enc_selectable(self):
        return True

    def enc_highlight(self, onoff):
        self._selected = bool(onoff)
        self.update()

    def enc_select(self):
        # Enter control mode: subsequent encoder turns/clicks drive the list.
        return True

    def enc_changed(self, data):
        self.model.move(data)
        self.update()
        return True

    def enc_clicked(self):
        self.model.acknowledge_advance()
        self.update()
        return True

    # -- painting ---------------------------------------------------------
    def paintEvent(self, event):
        try:
            self._paint()
        except Exception:
            # A checklist must never take down the panel on a paint error.
            logger.warning("checklist: paint error", exc_info=True)

    def _paint(self):
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            w = self.width()
            h = self.height()
            p.fillRect(0, 0, w, h, QColor("#000000"))

            checklist = self.model.active_checklist()
            if checklist is None:
                self._draw_centered(p, "No checklist", QColor(self.text_color),
                                    w, h)
                return

            line_h = max(12.0, h / 16.0)
            font = QFont(self.font_family)
            font.setPixelSize(max(8, int(line_h * 0.7)))
            p.setFont(font)

            # Header: title in the category colour + progress.
            cat_color = QColor(_CATEGORY_COLORS.get(
                checklist["category"], self.text_color))
            done, total = self.model.progress()
            if self.model.is_complete():
                progress = "COMPLETE"
            else:
                progress = f"{done} of {total} complete"
            header = checklist["title"] or "Checklist"
            p.setPen(QPen(cat_color))
            p.drawText(QRectF(4, 0, w - 8, line_h),
                       int(Qt.AlignmentFlag.AlignLeft
                           | Qt.AlignmentFlag.AlignVCenter), header)
            p.setPen(QPen(QColor(self.section_color)))
            p.drawText(QRectF(4, line_h, w - 8, line_h),
                       int(Qt.AlignmentFlag.AlignLeft
                           | Qt.AlignmentFlag.AlignVCenter), progress)

            # Rows. The current cursor position is over the SELECTABLE rows, so
            # track that index as we walk the full entry list.
            entries = checklist["entries"]
            current_entry = self.model.current_entry()
            y = line_h * 2.2
            for entry in entries:
                if y > h:
                    break
                rect = QRectF(4, y, w - 8, line_h)
                is_current = (entry is current_entry
                              and self._selected)
                if is_current:
                    p.fillRect(rect, QColor(self.current_color))
                if entry["kind"] == "section":
                    p.setPen(QPen(QColor(self.section_color)))
                    p.drawText(rect, int(Qt.AlignmentFlag.AlignLeft
                                         | Qt.AlignmentFlag.AlignVCenter),
                               entry["text"])
                elif entry["kind"] == "note":
                    p.setPen(QPen(QColor(
                        "#000000" if is_current else self.text_color)))
                    p.drawText(rect, int(Qt.AlignmentFlag.AlignLeft
                                         | Qt.AlignmentFlag.AlignVCenter),
                               entry["text"])
                else:  # item
                    self._draw_item(p, rect, entry, is_current)
                y += line_h
        finally:
            p.end()

    def _draw_item(self, p, rect, entry, is_current):
        acked = entry["acked"]
        if is_current:
            text_c = QColor("#000000")
            resp_c = QColor("#000000")
        elif acked:
            text_c = QColor(self.done_color)
            resp_c = QColor(self.done_color)
        else:
            text_c = QColor(self.text_color)
            resp_c = QColor(self.response_color)
        mark = "✓ " if acked else "   "  # check when acknowledged
        p.setPen(QPen(text_c))
        p.drawText(rect, int(Qt.AlignmentFlag.AlignLeft
                             | Qt.AlignmentFlag.AlignVCenter),
                   mark + entry["text"])
        if entry["response"]:
            p.setPen(QPen(resp_c))
            p.drawText(rect, int(Qt.AlignmentFlag.AlignRight
                                 | Qt.AlignmentFlag.AlignVCenter),
                       entry["response"] + " ")

    @staticmethod
    def _draw_centered(p, text, color, w, h):
        font = QFont()
        font.setPixelSize(max(10, int(h / 12)))
        p.setFont(font)
        p.setPen(QPen(color))
        p.drawText(QRectF(0, 0, w, h),
                   int(Qt.AlignmentFlag.AlignCenter), text)
