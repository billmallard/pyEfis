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

"""Data Status instrument.

Reads the navigation-data status JSON written by the ``pyefis-data`` updater
(Phase F of makerplane-data) and presents a boot-time Data Status screen:
per-pack currency with a subtle amber/white/healthy colour, a Continue
button (always available — the EFIS informs, it never restricts), and an
Update button that runs the updater over-the-air (USB sticks are picked up
automatically by the updater's udev hook; this screen reflects them on its
next refresh).

The status file is read defensively: a missing or malformed file yields a
quiet "unavailable" state and never raises — the screen must never be the
thing that stops the aircraft from booting.
"""

import json
import logging
import os
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, QRectF, QProcess, qRound
from PyQt6.QtGui import QColor, QFont, QPainter
from PyQt6.QtWidgets import QWidget, QPushButton

log = logging.getLogger(__name__)

# Fixed, well-known path the updater writes (mirrors pyefis_data.config).
DEFAULT_STATUS_PATH = "~/.makerplane/pyefis/status.json"

# Subtle by design. Expired/out-of-window is amber; soon-to-expire or missing
# is white; healthy is a calm green. Nothing here is alarming.
SEVERITY_COLORS = {
    "amber": QColor(255, 176, 0),
    "white": QColor(235, 235, 235),
    "none": QColor(120, 190, 120),
}
_TITLE_COLOR = QColor(235, 235, 235)
_DIM = QColor(150, 150, 150)

_BTN_STYLE = (
    "QPushButton { color: #EEEEEE; background-color: #202830;"
    " border: 1px solid #4A5A6A; border-radius: 6px; }"
    "QPushButton:pressed { background-color: #38444F; }"
    "QPushButton:disabled { color: #777777; border-color: #333333; }"
)


class DataStatus(QWidget):
    def __init__(self, parent=None, font_family="DejaVu Sans Condensed",
                 status_path=DEFAULT_STATUS_PATH, continue_screen="PFD",
                 update_command="pyefis-data"):
        super().__init__(parent)
        self.font_family = font_family
        self.status_path = Path(os.path.expanduser(status_path))
        self.continue_screen = continue_screen
        self.update_command = update_command
        self.status = None            # parsed dict, or None when unavailable
        self.message = ""             # transient line (e.g. "Updating…")
        self._proc = None
        self.row_h = 24

        self.btn_continue = QPushButton("Continue", self)
        self.btn_update = QPushButton("Update", self)
        for b in (self.btn_continue, self.btn_update):
            b.setStyleSheet(_BTN_STYLE)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_continue.clicked.connect(self._on_continue)
        self.btn_update.clicked.connect(self._on_update)

        # Refresh periodically so a USB import (handled by the updater's udev
        # hook) or a background timer update shows up without interaction.
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.reload)
        self._timer.start(60_000)
        self.reload()

    # --- data ---
    def reload(self):
        try:
            self.status = json.loads(self.status_path.read_text(encoding="utf-8"))
        except Exception:
            self.status = None        # construct-never-raises
        self.update()

    def showEvent(self, event):
        self.reload()
        super().showEvent(event)

    # --- actions ---
    def _on_continue(self):
        from pyefis import hmi       # lazy: avoids import-time app dependency
        if getattr(hmi, "actions", None) is not None:
            try:
                hmi.actions.trigger("show screen", self.continue_screen)
                return
            except Exception as e:
                log.warning("Continue action failed: %s", e)
        log.info("Continue pressed (no HMI action available)")

    def _on_update(self):
        if self._proc is not None:
            return
        self.message = "Updating over the air…"
        self.btn_update.setEnabled(False)
        self.update()
        self._proc = QProcess(self)
        self._proc.finished.connect(self._on_update_done)
        self._proc.errorOccurred.connect(self._on_update_error)
        self._proc.start(self.update_command, ["update"])

    def _on_update_done(self, code, _status):
        self._proc = None
        self.btn_update.setEnabled(True)
        self.message = ("Update complete." if code == 0 else
                        "No update applied — if there is no network, "
                        "insert a USB stick with the data.")
        self.reload()                 # the updater also rewrote status.json

    def _on_update_error(self, _err):
        self._proc = None
        self.btn_update.setEnabled(True)
        self.message = "Updater unavailable on this device."
        self.update()

    # --- layout ---
    def resizeEvent(self, event):
        w, h = self.width(), self.height()
        self.row_h = max(16, qRound(h * 0.055))
        self.font = QFont(self.font_family)
        self.font.setPixelSize(qRound(self.row_h * 0.62))
        self.title_font = QFont(self.font_family)
        self.title_font.setPixelSize(qRound(self.row_h * 0.85))
        self.font.setPixelSize(qRound(self.row_h * 0.62))

        bw, bh = qRound(w * 0.22), qRound(h * 0.10)
        by = h - bh - qRound(h * 0.05)
        self.btn_continue.setGeometry(qRound(w * 0.10), by, bw, bh)
        self.btn_update.setGeometry(qRound(w * 0.68), by, bw, bh)
        f = QFont(self.font_family)
        f.setPixelSize(qRound(bh * 0.4))
        self.btn_continue.setFont(f)
        self.btn_update.setFont(f)

    # --- paint ---
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        x = qRound(w * 0.10)
        col_status = qRound(w * 0.42)
        col_detail = qRound(w * 0.58)
        y = qRound(h * 0.10)

        p.setFont(self.title_font)
        p.setPen(_TITLE_COLOR)
        p.drawText(QRectF(x, y, w * 0.8, self.row_h), "NAVIGATION DATA")
        gen = (self.status or {}).get("generated")
        if gen:
            p.setFont(self.font)
            p.setPen(_DIM)
            p.drawText(QRectF(col_detail, y, w * 0.35, self.row_h),
                       f"catalog {gen[:10]}")
        y += qRound(self.row_h * 1.8)

        p.setFont(self.font)
        if not self.status or not self.status.get("ok"):
            p.setPen(SEVERITY_COLORS["white"])
            p.drawText(QRectF(x, y, w * 0.8, self.row_h),
                       "Data status unavailable — run an update to populate it.")
        else:
            for pk in self.status.get("packs", []):
                color = SEVERITY_COLORS.get(pk.get("severity", "white"),
                                            SEVERITY_COLORS["white"])
                p.setPen(color)
                p.drawText(QRectF(x, y, col_status - x, self.row_h),
                           str(pk.get("name", pk.get("id", ""))))
                p.drawText(QRectF(col_status, y, col_detail - col_status, self.row_h),
                           str(pk.get("status", "")))
                p.drawText(QRectF(col_detail, y, w - col_detail - x, self.row_h),
                           str(pk.get("detail", "")))
                y += self.row_h

        if self.message:
            p.setFont(self.font)
            p.setPen(SEVERITY_COLORS["white"])
            p.drawText(QRectF(x, h * 0.74, w * 0.8, self.row_h), self.message)
