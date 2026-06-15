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
from PyQt6.QtWidgets import (QWidget, QPushButton, QCheckBox, QScrollArea,
                             QVBoxLayout, QHBoxLayout, QLabel)

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

_SEV_RANK = {"none": 0, "white": 1, "amber": 2}


def load_status(status_path):
    """Read the updater's status JSON. Returns the parsed dict, or None on any
    problem (missing/malformed). Never raises — shared by the screen and the
    annunciation."""
    try:
        return json.loads(Path(os.path.expanduser(str(status_path))).read_text("utf-8"))
    except Exception:
        return None


def _parse_json(text):
    """Parse the last JSON object printed by a pyefis-data command. The updater
    may emit progress lines before the JSON, so scan from the first '{'. Returns
    None on any problem (the caller degrades gracefully)."""
    if not text:
        return None
    i = text.find("{")
    if i < 0:
        return None
    try:
        return json.loads(text[i:])
    except Exception:
        return None


def worst_severity(status):
    """The most-severe pack severity. 'none' when there is nothing to show
    (no status file, or every pack current) so the PFD annunciation can hide
    rather than clutter a healthy display."""
    if not status or not status.get("ok"):
        return "none"
    return max((p.get("severity", "white") for p in status.get("packs", [])),
               key=lambda s: _SEV_RANK.get(s, 1), default="none")


def fmt_bytes(n):
    """Human size for the picker (decimal-ish, GB/MB/KB)."""
    n = n or 0
    if n >= 1 << 30:
        return f"{n / (1 << 30):.1f} GB"
    if n >= 1 << 20:
        return f"{n / (1 << 20):.0f} MB"
    if n >= 1 << 10:
        return f"{n / (1 << 10):.0f} KB"
    return f"{n} B" if n else "-"


# Pack kinds collapsed into display groups for the picker, in display order.
_KIND_GROUP = {
    "navdata": "Navigation Data", "obstacles": "Navigation Data",
    "cifp": "Navigation Data", "water": "Water", "highways": "Roads",
    "terrain": "Terrain", "charts": "Charts",
}
_GROUP_ORDER = ["Navigation Data", "Water", "Roads", "Terrain", "Charts"]


def _row_label(p):
    """Per-row label: region for the region-split kinds (terrain), else the
    pack's friendly name."""
    if p.get("kind") == "terrain" and p.get("regions"):
        return p["regions"][0]
    return p.get("name") or p.get("id", "")


class _PackRow(QWidget):
    """A full-width touch target for one pack: tapping anywhere on the row
    toggles its checkbox. The checkbox (and labels) are made mouse-transparent
    so every tap lands on the row, not the tiny indicator — essential on the
    eglfs touchscreen, where a precise tap on a 24px box is unreliable and is
    easily mistaken for the start of a scroll drag. Toggling on *press* (not
    release) keeps it responsive and side-steps the tap-vs-drag ambiguity;
    single-finger taps select, two-finger gestures scroll."""

    def __init__(self, checkbox, parent=None):
        super().__init__(parent)
        self._cb = checkbox

    def mousePressEvent(self, event):
        self._cb.toggle()
        event.accept()


class PackPicker(QWidget):
    """Touch list of every available pack, grouped by kind, pre-checked from
    the device's current selection. Emits the chosen ids to install. Built from
    a ``catalog --json`` doc; no network of its own.

    Callbacks: ``on_install(ids)``, ``on_cancel()``, ``on_switch()`` (swap
    source when both Internet and USB are available)."""

    def __init__(self, parent=None, *, doc=None, source_label="Internet",
                 alt_source_label=None, font_family="DejaVu Sans Condensed",
                 on_install=None, on_cancel=None, on_switch=None):
        super().__init__(parent)
        self.font_family = font_family
        self._on_install = on_install or (lambda ids: None)
        self._on_cancel = on_cancel or (lambda: None)
        self._on_switch = on_switch or (lambda: None)
        doc = doc or {}
        self.packs = doc.get("packs", []) or []
        self.storage = doc.get("storage", {}) or {}
        self.checks = {}                                  # id -> QCheckBox
        self.rows = {}                                     # id -> _PackRow
        self.bytes_by_id = {p["id"]: p.get("bytes", 0) for p in self.packs}
        self.setStyleSheet("background:#0B1015;")
        self._build(source_label, alt_source_label)

    def _f(self, px, bold=False):
        f = QFont(self.font_family)
        f.setPixelSize(px)
        f.setBold(bold)
        return f

    def _build(self, source_label, alt_source_label):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(8)

        head = QHBoxLayout()
        title = QLabel("Select data to install")
        title.setStyleSheet("color:#EEEEEE;")
        title.setFont(self._f(19, bold=True))
        head.addWidget(title)
        head.addStretch(1)
        src = QLabel(f"Source: {source_label}")
        src.setStyleSheet("color:#9FBBC9;")
        src.setFont(self._f(14))
        head.addWidget(src)
        if alt_source_label:
            sw = QPushButton(f"Use {alt_source_label}")
            sw.setStyleSheet(_BTN_STYLE)
            sw.setFont(self._f(13))
            sw.setMinimumHeight(34)
            sw.clicked.connect(lambda: self._on_switch())
            head.addWidget(sw)
        outer.addLayout(head)

        st = self.storage
        if st.get("free_bytes") is not None:
            stxt = (f"Installing to {st.get('root')}  -  "
                    f"{fmt_bytes(st['free_bytes'])} free of {fmt_bytes(st.get('total_bytes'))}")
        else:
            stxt = f"Installing to {st.get('root', '(default location)')}"
        self.storage_label = QLabel(stxt)
        self.storage_label.setStyleSheet("color:#8FA0AB;")
        self.storage_label.setFont(self._f(13))
        outer.addWidget(self.storage_label)

        area = QScrollArea(self)
        area.setWidgetResizable(True)
        area.setStyleSheet("QScrollArea{border:1px solid #2B3742;border-radius:8px;"
                           "background:#0E141A;}")
        content = QWidget()
        col = QVBoxLayout(content)
        col.setContentsMargins(10, 6, 10, 8)
        col.setSpacing(2)
        groups = {}
        for p in self.packs:
            groups.setdefault(_KIND_GROUP.get(p.get("kind"), "Other"), []).append(p)
        for g in _GROUP_ORDER + [g for g in groups if g not in _GROUP_ORDER]:
            items = groups.get(g)
            if not items:
                continue
            hdr = QLabel(g)
            hdr.setStyleSheet("color:#79C7A0; padding-top:8px;")
            hdr.setFont(self._f(14, bold=True))
            col.addWidget(hdr)
            for p in sorted(items, key=lambda x: x.get("id", "")):
                col.addWidget(self._row(p))
        col.addStretch(1)
        area.setWidget(content)
        outer.addWidget(area, 1)

        foot = QHBoxLayout()
        self.summary = QLabel("")
        self.summary.setFont(self._f(14))
        foot.addWidget(self.summary)
        foot.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.setStyleSheet(_BTN_STYLE)
        cancel.clicked.connect(lambda: self._on_cancel())
        self.btn_install = QPushButton("Install selected")
        self.btn_install.setStyleSheet(_BTN_STYLE)
        self.btn_install.clicked.connect(self._do_install)
        for b in (cancel, self.btn_install):
            b.setFont(self._f(15))
            b.setMinimumHeight(42)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
        foot.addWidget(cancel)
        foot.addWidget(self.btn_install)
        outer.addLayout(foot)
        self._update_summary()

    def _row(self, p):
        cb = QCheckBox()
        cb.setChecked(bool(p.get("tracked")))
        cb.setStyleSheet("QCheckBox::indicator{width:26px;height:26px;}")
        cb.stateChanged.connect(self._update_summary)
        self.checks[p["id"]] = cb
        name = QLabel(_row_label(p))
        name.setStyleSheet("color:#EAEAEA;")
        name.setFont(self._f(15))
        sev = p.get("severity", "white")
        col = {"amber": "#FFB000", "white": "#DDDDDD", "none": "#78BE78"}.get(sev, "#DDDDDD")
        meta = QLabel(f"{fmt_bytes(p.get('bytes', 0))}    {p.get('status', '')}")
        meta.setStyleSheet(f"color:{col};")
        meta.setFont(self._f(13))
        # The whole row is the touch target; children must not intercept taps.
        for child in (cb, name, meta):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        row = _PackRow(cb)
        row.setMinimumHeight(48)                          # generous touch target
        row.setStyleSheet("_PackRow:hover{background:#141C24;}")
        h = QHBoxLayout(row)
        h.setContentsMargins(4, 6, 4, 6)
        h.setSpacing(10)
        h.addWidget(cb)
        h.addWidget(name, 1)
        h.addWidget(meta)
        self.rows[p["id"]] = row
        return row

    def selected_ids(self):
        return [pid for pid, cb in self.checks.items() if cb.isChecked()]

    def _selected_bytes(self):
        return sum(self.bytes_by_id.get(pid, 0) for pid in self.selected_ids())

    def _update_summary(self, *_):
        ids = self.selected_ids()
        total = self._selected_bytes()
        free = self.storage.get("free_bytes")
        over = free is not None and total > free
        msg = f"{len(ids)} selected  -  {fmt_bytes(total)}"
        if over:
            msg += f"   needs more than the {fmt_bytes(free)} free"
        self.summary.setText(msg)
        self.summary.setStyleSheet("color:#FFB000;" if over else "color:#CCCCCC;")
        self.btn_install.setEnabled(bool(ids) and not over)

    def _do_install(self):
        self.btn_install.setEnabled(False)
        self._on_install(self.selected_ids())


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
        # picker flow: "status" (default), "picker" (choose packs), "busy"
        # (installing). `_sources` is the last `sources` probe; `_source` is the
        # chosen source (None = Internet, else a USB dir path).
        self.mode = "status"
        self.picker = None
        self._sources = None
        self._source = None

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
        self.status = load_status(self.status_path)   # construct-never-raises
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

    # --- subprocess plumbing ---
    def _run(self, args, on_finish):
        """Run ``pyefis-data <args>`` asynchronously and call
        ``on_finish(code, stdout_text)`` exactly once. A failure to even start
        the updater routes to ``_fail`` (never blocks the screen)."""
        if self._proc is not None:
            return
        proc = QProcess(self)
        self._proc = proc
        state = {"done": False}

        def finish(code, _status):
            if state["done"]:
                return
            state["done"] = True
            out = bytes(proc.readAllStandardOutput()).decode("utf-8", "replace")
            self._proc = None
            on_finish(code, out)

        def errored(_e):
            if state["done"]:
                return
            state["done"] = True
            self._proc = None
            self._fail("Updater unavailable on this device.")

        proc.finished.connect(finish)
        proc.errorOccurred.connect(errored)
        # Expand ~ so a config can use ~/.local/bin/pyefis-data. An absolute
        # path is required when pyEfis runs as a systemd service, whose minimal
        # PATH excludes ~/.local/bin (a bare name would fail to start).
        proc.start(os.path.expanduser(self.update_command), args)

    def _fail(self, message):
        self._close_picker()
        self.mode = "status"
        self.message = message
        self.btn_update.setEnabled(True)
        self._sync_visibility()
        self.update()

    # --- Update flow: sources -> catalog -> picker -> install ---
    def _on_update(self):
        """Tapping Update no longer blindly runs an OTA update; it first asks
        what sources are available, then shows the pack picker."""
        if self._proc is not None or self.mode != "status":
            return
        self.message = "Checking for updates…"
        self.btn_update.setEnabled(False)
        self.update()
        self._run(["sources", "--json"], self._after_sources)

    def _after_sources(self, code, out):
        info = _parse_json(out) or {}
        net = bool(info.get("network"))
        usb = list(info.get("usb") or [])
        self._sources = {"network": net, "usb": usb}
        if not net and not usb:
            self._fail("No internet connection and no USB drive found. "
                       "Your current data is unchanged.")
            return
        # Default source: USB if it's the only one, else Internet (freshest).
        self._source = (usb[0] if (usb and not net) else None)
        self._load_catalog()

    def _load_catalog(self):
        self.message = "Loading available data…"
        self.update()
        args = ["catalog", "--json"]
        if self._source:
            args += ["--source", self._source]
        self._run(args, self._after_catalog)

    def _after_catalog(self, code, out):
        doc = _parse_json(out)
        if not doc or not doc.get("ok"):
            self._fail("Couldn't read the data catalog from that source.")
            return
        self._show_picker(doc)

    def _source_labels(self):
        """(current label, the-other-available label or None)."""
        net = self._sources.get("network")
        usb = self._sources.get("usb") or []
        on_usb = self._source is not None
        cur = "USB drive" if on_usb else "Internet"
        alt = None
        if on_usb and net:
            alt = "Internet"
        elif (not on_usb) and usb:
            alt = "USB drive"
        return cur, alt

    def _show_picker(self, doc):
        self._close_picker()
        cur, alt = self._source_labels()
        self.picker = PackPicker(
            self, doc=doc, source_label=cur, alt_source_label=alt,
            font_family=self.font_family,
            on_install=self._install_selected,
            on_cancel=self._cancel_picker,
            on_switch=self._switch_source)
        self.mode = "picker"
        self.message = ""
        self._sync_visibility()
        self.picker.setGeometry(0, 0, self.width(), self.height())
        self.picker.show()
        self.picker.raise_()

    def _switch_source(self):
        usb = self._sources.get("usb") or []
        # toggle Internet <-> first USB
        self._source = (usb[0] if self._source is None and usb else None)
        self._load_catalog()

    def _cancel_picker(self):
        self._fail("")                # back to status, no message

    def _install_selected(self, ids):
        if not ids:
            return
        self.mode = "busy"
        self.message = "Installing… large packs can take several minutes."
        self._sync_visibility()
        self.update()
        args = ["update", "--only", ",".join(ids)]
        if self._source:
            args += ["--source", self._source]
        self._run(args, self._after_install)

    def _after_install(self, code, out):
        self._close_picker()
        self.mode = "status"
        self.btn_update.setEnabled(True)
        self.message = ("Update complete." if code == 0 else
                        "Update finished with problems — your previous data is "
                        "still in place. See the rows above.")
        self._sync_visibility()
        self.reload()                 # the updater also rewrote status.json

    def _close_picker(self):
        if self.picker is not None:
            self.picker.hide()
            self.picker.deleteLater()
            self.picker = None

    # --- layout ---
    def _sync_visibility(self):
        """Show the status buttons only in status mode; the picker covers the
        whole widget in picker mode."""
        status_mode = self.mode == "status"
        self.btn_continue.setVisible(status_mode)
        self.btn_update.setVisible(status_mode)
        if self.picker is not None:
            self.picker.setVisible(self.mode == "picker")
            if self.mode == "picker":
                self.picker.setGeometry(0, 0, self.width(), self.height())

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
        if self.picker is not None:
            self.picker.setGeometry(0, 0, w, h)

    # --- paint ---
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        if self.mode == "busy":
            # Installing: a calm centred message; the picker is hidden and the
            # buttons are too, so nothing competes with it.
            p.fillRect(self.rect(), QColor(11, 16, 21))
            p.setFont(self.title_font)
            p.setPen(_TITLE_COLOR)
            p.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter),
                       self.message or "Installing…")
            return

        # Single-line so a long detail string clips at its column instead of
        # wrapping down into the next pack's row.
        flags = int(Qt.TextFlag.TextSingleLine | Qt.AlignmentFlag.AlignLeft
                    | Qt.AlignmentFlag.AlignVCenter)
        x = qRound(w * 0.10)
        col_status = qRound(w * 0.42)
        col_detail = qRound(w * 0.58)
        y = qRound(h * 0.10)

        p.setFont(self.title_font)
        p.setPen(_TITLE_COLOR)
        p.drawText(QRectF(x, y, w * 0.8, self.row_h), flags, "NAVIGATION DATA")
        gen = (self.status or {}).get("generated")
        if gen:
            p.setFont(self.font)
            p.setPen(_DIM)
            p.drawText(QRectF(col_detail, y, w - col_detail - x, self.row_h), flags,
                       f"catalog {gen[:10]}")
        y += qRound(self.row_h * 1.8)

        p.setFont(self.font)
        if not self.status or not self.status.get("ok"):
            p.setPen(SEVERITY_COLORS["white"])
            p.drawText(QRectF(x, y, w - 2 * x, self.row_h), flags,
                       "Data status unavailable — run an update to populate it.")
        else:
            for pk in self.status.get("packs", []):
                color = SEVERITY_COLORS.get(pk.get("severity", "white"),
                                            SEVERITY_COLORS["white"])
                p.setPen(color)
                p.drawText(QRectF(x, y, col_status - x, self.row_h), flags,
                           str(pk.get("name", pk.get("id", ""))))
                p.drawText(QRectF(col_status, y, col_detail - col_status, self.row_h), flags,
                           str(pk.get("status", "")))
                p.drawText(QRectF(col_detail, y, w - col_detail - x, self.row_h), flags,
                           str(pk.get("detail", "")))
                y += self.row_h

        if self.message:
            p.setFont(self.font)
            p.setPen(SEVERITY_COLORS["white"])
            p.drawText(QRectF(x, h * 0.74, w - 2 * x, self.row_h), flags, self.message)


class DataAnnunciation(QWidget):
    """A small, persistent 'DATA' flag for the flight (PFD) view.

    Subtle by design: amber when any installed navdata is expired, white when
    expiring soon or missing, and **hidden** when everything is current (or no
    updater is present) so a healthy display is never cluttered. Tapping it
    jumps to the Data Status screen.
    """

    def __init__(self, parent=None, font_family="DejaVu Sans Condensed",
                 status_path=DEFAULT_STATUS_PATH, target_screen="DataStatus"):
        super().__init__(parent)
        self.font_family = font_family
        self.status_path = os.path.expanduser(status_path)
        self.target_screen = target_screen
        self.status = None
        self.font = QFont(font_family)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.reload)
        self._timer.start(60_000)
        self.reload()

    def reload(self):
        self.status = load_status(self.status_path)
        self.update()

    def showEvent(self, event):
        self.reload()
        super().showEvent(event)

    def mousePressEvent(self, event):
        from pyefis import hmi
        if getattr(hmi, "actions", None) is not None:
            try:
                hmi.actions.trigger("show screen", self.target_screen)
            except Exception as e:
                log.warning("DATA annunciation tap failed: %s", e)

    def resizeEvent(self, event):
        self.font = QFont(self.font_family)
        self.font.setPixelSize(max(8, qRound(self.height() * 0.7)))

    def paintEvent(self, event):
        sev = worst_severity(self.status)
        if sev == "none":
            return                      # healthy / no updater -> show nothing
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = SEVERITY_COLORS.get(sev, SEVERITY_COLORS["white"])
        rect = QRectF(1, 1, self.width() - 2, self.height() - 2)
        pen = p.pen()
        pen.setColor(color)
        p.setPen(pen)
        p.drawRoundedRect(rect, 3, 3)
        p.setFont(self.font)
        p.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), "DATA")
