#  Copyright (c) 2026 MakerPlane
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

"""About / System instrument (BACKLOG L4).

A permanent, always-reachable screen carrying the pyEfis notice, the running
software version, the ``notice`` field (L1) of each installed data pack, and
the history of notice acknowledgments written by the installer/updater (L2).
It is the screen a builder points a passenger at, and the one that makes an
acknowledgment legible after the fact.

Everything here is read from local files -- no network. The pack list comes
from the same ``status.json`` the ``pyefis-data`` updater writes for the Data
Status screen; a pack row with no ``notice`` (every pack published before the
field existed) says so rather than borrowing the software notice. A missing
or malformed status file yields an "unavailable" line and never raises.

Safety advisories (L5) come from the ``advisories`` block of the same file,
settled against the running version by ``pyefis.advisories.resolve``, and sit
directly under the version so they are on screen without scrolling. Each one
shows its severity, title, description and required action. The normal case,
an empty list, shows nothing at all; a channel the user has not opted into
shows one quiet "off" line.

The acknowledgment history is read from the append-only log defined by
makerplane-data ``docs/install_acknowledgment.md`` through the same reader the
startup banner uses (``startup_notice.read_records``), newest first. pyEfis
never writes it. A ``via: bench`` record is labelled as a bench auto-accept,
not a person's, and a record for a different notice wording says so.
"""

import logging
import os

from PyQt6.QtCore import Qt, qRound
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (QWidget, QPushButton, QScrollArea, QVBoxLayout,
                             QHBoxLayout, QLabel)

import pyefis
from pyefis import advisories, startup_notice
from pyefis.instruments.data_status import DEFAULT_STATUS_PATH, load_status

log = logging.getLogger(__name__)

# Bill approved this text 2026-10-30 (BACKLOG L2/L3/L4). Verbatim; changing it
# is his call, not a wording to tune.
NOTICE = ("pyEfis is experimental software for Experimental / Amateur-Built "
          "aircraft. It is not certified. It is provided as-is with no "
          "warranty, and any use of it is at your own risk.")

NO_PACK_NOTICE = "No notice in this pack's manifest entry."

NO_ACK_RECORD = "No acknowledgment on record on this device."

_VIA = {
    "tty": "Typed \"accept\" at a terminal",
    "caller": "Accepted on screen in the installer or pack picker",
    "bench": "Auto-accepted on a bench unit; not a person's accept",
}

ADVISORIES_OFF = "Safety advisories: off"

# Annunciator colours for the feed's annunciator words.
_ADV_COLOUR = {"warning": "#FF4D4D", "caution": "#FFB000", "advisory": "#EBEBEB"}

_BTN_STYLE = (
    "QPushButton { color: #EEEEEE; background-color: #202830;"
    " border: 1px solid #4A5A6A; border-radius: 6px; }"
    "QPushButton:pressed { background-color: #38444F; }"
)


def pack_notices(status):
    """``[(label, cycle, notice_or_None), ...]`` for each pack in a parsed
    status document, in the updater's order. Packs with no installed cycle
    are skipped (they are in the catalog, not on the device). Never raises."""
    if not status or not status.get("ok"):
        return []
    out = []
    for p in status.get("packs") or []:
        if not isinstance(p, dict) or not p.get("cycle"):
            continue
        notice = p.get("notice")
        notice = notice.strip() if isinstance(notice, str) else ""
        # Friendly names repeat (every terrain region is "Terrain"), so add
        # the pack id whenever it says something the name does not.
        name, pid = str(p.get("name") or ""), str(p.get("id") or "")
        label = f"{name} ({pid})" if name and pid and pid != name else (name or pid)
        out.append((label, str(p["cycle"]), notice or None))
    return out


def advisory_rows(status, version=None, now=None):
    """``[(text, role), ...]`` for the advisory section, from a parsed status
    document; role is a severity word, "heading", "body", "action" or
    "quiet". Empty when there is nothing to say -- the normal state. Never
    raises."""
    block = status.get("advisories") if isinstance(status, dict) else None
    if isinstance(block, dict) and block.get("enabled") is False:
        return [(ADVISORIES_OFF, "quiet")]
    active = advisories.resolve(block, version) or []
    health = advisories.feed_health(block, now)
    rows = [("Safety advisories", "heading")] if active or health else []
    for a in active:
        sev = a["severity"]
        rows.append((f"{sev.upper()}  {a.get('title') or a.get('id') or ''}", sev))
        meta = ", ".join(str(a[k]) for k in ("id", "issued") if a.get(k))
        if a["applies"] != advisories.YES:
            names = advisories.unknown_components(a)
            may = "May apply to this device"
            meta = (f"{meta}. " if meta else "") + (
                f"{may}: could not tell the installed version of {', '.join(names)}."
                if names else f"{may}.")
        if meta:
            rows.append((meta, "quiet"))
        if isinstance(a.get("description"), str) and a["description"].strip():
            rows.append((a["description"].strip(), "body"))
        if isinstance(a.get("action"), str) and a["action"].strip():
            rows.append((f"Required action: {a['action'].strip()}", "action"))
    if health:
        rows.append((health, "quiet"))
    return rows


def _str_map(d):
    """``"a 1, b 2"`` from a str->str mapping, skipping anything else."""
    if not isinstance(d, dict):
        return ""
    return ", ".join(f"{k} {v}" for k, v in sorted(d.items())
                     if isinstance(k, str) and isinstance(v, str))


def ack_history(records):
    """``[(heading, detail), ...]`` for each acceptance record, newest first.
    ``records`` is ``startup_notice.read_records()`` output (valid schema-1
    accepts only); optional fields of the wrong type are left out rather than
    raising."""
    out = []
    for rec in reversed(records or []):
        ts = rec["timestamp"].replace("T", " ").replace("Z", " UTC")
        who = "@".join(v for v in (rec.get("user"), rec.get("host"))
                       if isinstance(v, str) and v)
        heading = f"{ts}  accepted by {who}" if who else f"{ts}  accepted"
        via = rec.get("via")
        how = _VIA.get(via, f"Accepted via {via}" if isinstance(via, str)
                       else "Accepted")
        trigger = rec.get("trigger")
        parts = [f"{how} (trigger: {trigger})." if isinstance(trigger, str)
                 and trigger else f"{how}."]
        if rec["notice_sha256"] != startup_notice.NOTICE_SHA256:
            parts.append("This was a different wording of the notice.")
        sw = _str_map(rec["software"])
        if sw:
            parts.append(f"Software: {sw}.")
        packs = rec.get("packs")
        if isinstance(packs, dict):
            pk = _str_map(packs)
            parts.append(f"Packs at the time: {pk}." if pk
                         else "No packs were installed yet.")
        out.append((heading, " ".join(parts)))
    return out


class AboutSystem(QWidget):
    def __init__(self, parent=None, font_family="DejaVu Sans Condensed",
                 status_path=DEFAULT_STATUS_PATH, back_screen="DataStatus",
                 ack_path=None):
        super().__init__(parent)
        self.font_family = font_family
        self.status_path = os.path.expanduser(status_path)
        self.back_screen = back_screen
        # None = resolve the writer's path (MAKERPLANE_ACK_LOG / XDG state).
        self.ack_path = ack_path
        self.setStyleSheet("background-color: #0B1015;")

        self.title = QLabel("About pyEfis")
        self.version = QLabel(f"Version {pyefis.__version__}")
        self.notice = QLabel(NOTICE)
        self.packs_title = QLabel("Installed data packs")
        self.ack_title = QLabel("Notice acknowledgments")
        self.notice.setWordWrap(True)
        self.title.setStyleSheet("color:#EBEBEB;")
        self.version.setStyleSheet("color:#969696;")
        self.notice.setStyleSheet("color:#EBEBEB;")
        self.packs_title.setStyleSheet("color:#EBEBEB;")
        self.ack_title.setStyleSheet("color:#EBEBEB;")

        self._adv_box = QWidget()
        self._adv_col = QVBoxLayout(self._adv_box)
        self._adv_col.setContentsMargins(0, 10, 0, 0)
        self._adv_labels = []

        self._packs_box = QWidget()
        self._packs_col = QVBoxLayout(self._packs_box)
        self._packs_col.setContentsMargins(0, 0, 0, 0)
        self._pack_labels = []
        self._ack_box = QWidget()
        self._ack_col = QVBoxLayout(self._ack_box)
        self._ack_col.setContentsMargins(0, 0, 0, 0)
        self._ack_labels = []

        content = QWidget()
        col = QVBoxLayout(content)
        col.setContentsMargins(16, 12, 16, 12)
        col.addWidget(self.title)
        col.addWidget(self.version)
        col.addWidget(self._adv_box)
        col.addSpacing(10)
        col.addWidget(self.notice)
        col.addSpacing(16)
        col.addWidget(self.packs_title)
        col.addWidget(self._packs_box)
        col.addSpacing(16)
        col.addWidget(self.ack_title)
        col.addWidget(self._ack_box)
        col.addStretch(1)

        self.area = QScrollArea()
        self.area.setWidgetResizable(True)
        self.area.setStyleSheet("QScrollArea{border:none;}")
        self.area.setWidget(content)

        self.btn_back = QPushButton("Back")
        self.btn_back.setStyleSheet(_BTN_STYLE)
        self.btn_back.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_back.clicked.connect(self._on_back)
        brow = QHBoxLayout()
        brow.addStretch(1)
        brow.addWidget(self.btn_back)
        brow.setContentsMargins(16, 0, 16, 12)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.area, 1)
        root.addLayout(brow)
        self.reload()

    # --- data ---
    def reload(self):
        for lbl in self._pack_labels:
            lbl.setParent(None)
            lbl.deleteLater()
        self._pack_labels = []
        status = load_status(self.status_path)        # construct-never-raises
        self._fill_advisories(advisory_rows(status))
        rows = pack_notices(status)
        if status is None:
            texts = [("Data pack status unavailable on this device.", False)]
        elif not rows:
            texts = [("No data packs installed.", False)]
        else:
            texts = []
            for label, cycle, notice in rows:
                texts.append((f"{label}  {cycle}", True))
                texts.append((notice or NO_PACK_NOTICE, False))
        self._fill(self._packs_col, self._pack_labels, texts)

        for lbl in self._ack_labels:
            lbl.setParent(None)
            lbl.deleteLater()
        self._ack_labels = []
        records = startup_notice.read_records(self.ack_path)  # never raises
        history = ack_history(records)
        if not history:
            texts = [(NO_ACK_RECORD, False)]
        else:
            texts = []
            for heading, detail in history:
                texts.append((heading, True))
                texts.append((detail, False))
        self._fill(self._ack_col, self._ack_labels, texts)
        self._apply_fonts()

    def _fill_advisories(self, rows):
        for lbl in self._adv_labels:
            lbl.setParent(None)
            lbl.deleteLater()
        self._adv_labels = []
        while self._adv_col.count():          # spacers left by the last fill
            self._adv_col.takeAt(0)
        for i, (text, role) in enumerate(rows):
            if role in _ADV_COLOUR and i > 1:
                self._adv_col.addSpacing(8)   # keep consecutive advisories apart
            lbl = QLabel(text)
            lbl.setWordWrap(True)
            colour = _ADV_COLOUR.get(role) or {
                "heading": "#EBEBEB", "action": "#EBEBEB", "quiet": "#969696",
            }.get(role, "#AFBBC4")
            lbl.setStyleSheet(f"color:{colour};")
            lbl.setProperty("heading", role in _ADV_COLOUR)
            lbl.setProperty("role", role)
            self._adv_col.addWidget(lbl)
            self._adv_labels.append(lbl)
        # Nothing to say takes no space: the normal case is silence.
        self._adv_box.setVisible(bool(rows))

    @staticmethod
    def _fill(column, labels, texts):
        for text, heading in texts:
            lbl = QLabel(text)
            lbl.setWordWrap(True)
            lbl.setStyleSheet("color:#EBEBEB;" if heading else "color:#AFBBC4;")
            lbl.setProperty("heading", heading)
            column.addWidget(lbl)
            labels.append(lbl)

    def showEvent(self, event):
        self.reload()
        super().showEvent(event)

    def _on_back(self):
        from pyefis import hmi       # lazy: avoids import-time app dependency
        if getattr(hmi, "actions", None) is not None:
            try:
                hmi.actions.trigger("show screen", self.back_screen)
            except Exception as e:
                log.warning("About Back action failed: %s", e)

    # --- layout ---
    def _f(self, px):
        f = QFont(self.font_family)
        f.setPixelSize(max(8, qRound(px)))
        return f

    def _apply_fonts(self):
        row = max(16, qRound(self.height() * 0.055))
        self.title.setFont(self._f(row * 0.85))
        self.version.setFont(self._f(row * 0.55))
        self.notice.setFont(self._f(row * 0.70))
        self.packs_title.setFont(self._f(row * 0.70))
        self.ack_title.setFont(self._f(row * 0.70))
        for lbl in self._pack_labels + self._ack_labels + self._adv_labels:
            size = (0.70 if lbl.property("role") == "heading"   # the section title
                    else 0.60 if lbl.property("heading") else 0.55)
            lbl.setFont(self._f(row * size))
        self.btn_back.setFont(self._f(row * 0.70))
        self.btn_back.setMinimumSize(qRound(self.width() * 0.22),
                                     max(44, qRound(self.height() * 0.10)))

    def resizeEvent(self, event):
        self._apply_fonts()
        super().resizeEvent(event)
