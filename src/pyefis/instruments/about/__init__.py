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
software version, and the ``notice`` field (L1) of each installed data pack.
It is the screen a builder points a passenger at.

Everything here is read from local files -- no network. The pack list comes
from the same ``status.json`` the ``pyefis-data`` updater writes for the Data
Status screen; a pack row with no ``notice`` (every pack published before the
field existed) says so rather than borrowing the software notice. A missing
or malformed status file yields an "unavailable" line and never raises.
"""

import logging
import os

from PyQt6.QtCore import Qt, qRound
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (QWidget, QPushButton, QScrollArea, QVBoxLayout,
                             QHBoxLayout, QLabel)

import pyefis
from pyefis.instruments.data_status import DEFAULT_STATUS_PATH, load_status

log = logging.getLogger(__name__)

# Bill approved this text 2026-10-30 (BACKLOG L2/L3/L4). Verbatim; changing it
# is his call, not a wording to tune.
NOTICE = ("pyEfis is experimental software for Experimental / Amateur-Built "
          "aircraft. It is not certified. It is provided as-is with no "
          "warranty, and any use of it is at your own risk.")

NO_PACK_NOTICE = "No notice in this pack's manifest entry."

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


class AboutSystem(QWidget):
    def __init__(self, parent=None, font_family="DejaVu Sans Condensed",
                 status_path=DEFAULT_STATUS_PATH, back_screen="DataStatus"):
        super().__init__(parent)
        self.font_family = font_family
        self.status_path = os.path.expanduser(status_path)
        self.back_screen = back_screen
        self.setStyleSheet("background-color: #0B1015;")

        self.title = QLabel("About pyEfis")
        self.version = QLabel(f"Version {pyefis.__version__}")
        self.notice = QLabel(NOTICE)
        self.packs_title = QLabel("Installed data packs")
        self.notice.setWordWrap(True)
        self.title.setStyleSheet("color:#EBEBEB;")
        self.version.setStyleSheet("color:#969696;")
        self.notice.setStyleSheet("color:#EBEBEB;")
        self.packs_title.setStyleSheet("color:#EBEBEB;")

        self._packs_box = QWidget()
        self._packs_col = QVBoxLayout(self._packs_box)
        self._packs_col.setContentsMargins(0, 0, 0, 0)
        self._pack_labels = []

        content = QWidget()
        col = QVBoxLayout(content)
        col.setContentsMargins(16, 12, 16, 12)
        col.addWidget(self.title)
        col.addWidget(self.version)
        col.addSpacing(10)
        col.addWidget(self.notice)
        col.addSpacing(16)
        col.addWidget(self.packs_title)
        col.addWidget(self._packs_box)
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
        for text, heading in texts:
            lbl = QLabel(text)
            lbl.setWordWrap(True)
            lbl.setStyleSheet("color:#EBEBEB;" if heading else "color:#AFBBC4;")
            lbl.setProperty("heading", heading)
            self._packs_col.addWidget(lbl)
            self._pack_labels.append(lbl)
        self._apply_fonts()

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
        for lbl in self._pack_labels:
            lbl.setFont(self._f(row * (0.60 if lbl.property("heading") else 0.55)))
        self.btn_back.setFont(self._f(row * 0.70))
        self.btn_back.setMinimumSize(qRound(self.width() * 0.22),
                                     max(44, qRound(self.height() * 0.10)))

    def resizeEvent(self, event):
        self._apply_fonts()
        super().resizeEvent(event)
