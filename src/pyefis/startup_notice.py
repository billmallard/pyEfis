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

"""Startup notice: a self-dismissing banner drawn OVER the live flight screen.

pyEfis can restart in flight (brownout, power glitch, a pilot cycling the box),
so nothing shown at boot may stand between the pilot and the PFD. The notice is
therefore never a modal: the flight screen boots and draws immediately, the
banner sits on top of it, lets every touch through to the instruments beneath,
and hides itself on a timer. There is nothing to clear.

The blocking, provable acknowledgment happens on the ground, in the installer /
updater (BACKLOG L2, ``pyefis-data``), which appends a record to the log at
``ack_log_path()``. This module only READS that record, to decide how the
banner behaves:

* a record accepts THIS notice text (``notice_sha256``) for THIS pyEfis version
  (``software.pyefis``) -> short banner, logged at INFO;
* anything else -- log missing, unreadable, corrupt, or no such record -> the
  longer banner plus a WARNING naming the condition.

Neither outcome blocks. Every failure path falls toward the non-blocking banner:
``evaluate`` never raises, and an unreadable state file never blanks the PFD.

The record is defined by makerplane-data ``docs/install_acknowledgment.md``:
JSON Lines, append-only, schema 1, one ``{"event": "accept", ...}`` object per
accept. ``software.pyefis`` is present only when the pyEfis installer names it
(``pyefis-data accept --software pyefis=<ver>``); a record written by a plain
``pyefis-data update`` carries only ``pyefis-data`` and does not count here.
Pack cycles are deliberately not matched: ``packs`` is the state BEFORE the
install the accept gated, and a pack-only timer update adds no record.
"""

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, QRectF
from PyQt6.QtGui import QColor, QFont, QPainter
from PyQt6.QtWidgets import QWidget

import pyefis

log = logging.getLogger(__name__)

# Bill approved this text 2026-10-30 (BACKLOG L3). Use it verbatim.
NOTICE_TEXT = (
    "pyEfis is experimental software for Experimental / Amateur-Built aircraft. "
    "It is not certified. It is provided as-is with no warranty, and any use of "
    "it is at your own risk."
)

# Byte-identical to pyefis_data.acknowledge.NOTICE_TEXT: a record covers the
# notice only if its notice_sha256 equals this.
NOTICE_SHA256 = hashlib.sha256(NOTICE_TEXT.encode("utf-8")).hexdigest()

ACK_SCHEMA = 1


def ack_log_path():
    """Resolve the log the way the writer does: ``MAKERPLANE_ACK_LOG``, else
    ``$XDG_STATE_HOME/makerplane/acknowledgments.jsonl``, else
    ``~/.local/state/makerplane/acknowledgments.jsonl``. Outside both config
    trees, so resetting either does not erase it."""
    env = os.environ.get("MAKERPLANE_ACK_LOG")
    if env:
        return Path(os.path.expanduser(env))
    state = os.environ.get("XDG_STATE_HOME")
    base = Path(os.path.expanduser(state)) if state else \
        Path(os.path.expanduser("~/.local/state"))
    return base / "makerplane" / "acknowledgments.jsonl"

# How long the banner stays up. Acknowledged installs get the short one.
ACKNOWLEDGED_MS = 8_000
UNACKNOWLEDGED_MS = 20_000


@dataclass(frozen=True)
class NoticeState:
    """Result of reading the acknowledgment record.

    ``reason`` is one of: ``acknowledged``, ``missing``, ``unreadable``,
    ``corrupt``, ``not-acknowledged`` (valid records, none for this version).
    """
    acknowledged: bool
    reason: str

    @property
    def duration_ms(self):
        return ACKNOWLEDGED_MS if self.acknowledged else UNACKNOWLEDGED_MS


def _valid_record(rec):
    """An accept line this reader understands. Later schemas and other event
    types are skipped, as is a line whose sha256 does not cover its own text."""
    if not (isinstance(rec, dict)
            and rec.get("schema") == ACK_SCHEMA
            and rec.get("event") == "accept"
            and isinstance(rec.get("timestamp"), str)
            and isinstance(rec.get("notice_text"), str)
            and isinstance(rec.get("notice_sha256"), str)
            and isinstance(rec.get("software"), dict)):
        return False
    return hashlib.sha256(rec["notice_text"].encode("utf-8")).hexdigest() \
        == rec["notice_sha256"]


def read_records(ack_path=None):
    """Every valid accept record in the log, in file (oldest-first) order, for
    display (the About screen, L4). ``None`` if the log is missing or
    unreadable; invalid lines are skipped as ``evaluate`` skips them. Never
    raises."""
    path = Path(os.path.expanduser(str(ack_path))) if ack_path else \
        ack_log_path()
    try:
        text = path.read_text("utf-8")
    except Exception:
        return None
    out = []
    for line in text.splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if _valid_record(rec):
            out.append(rec)
    return out


def _matches(rec, software_version):
    return (rec["notice_sha256"] == NOTICE_SHA256
            and rec["software"].get("pyefis") == software_version)


def evaluate(ack_path=None, software_version=None):
    """Decide the notice state from the acknowledgment record.

    Never raises: any unexpected failure returns the not-acknowledged state,
    which is the non-blocking banner. Every non-acknowledged outcome is logged
    at WARNING with the path and the condition."""
    if software_version is None:
        software_version = pyefis.__version__
    path = Path(os.path.expanduser(str(ack_path))) if ack_path else \
        ack_log_path()
    try:
        try:
            text = path.read_text("utf-8")
        except FileNotFoundError:
            log.warning("startup notice: acknowledgment record %s is missing; "
                        "showing the non-blocking banner", path)
            return NoticeState(False, "missing")
        except (OSError, UnicodeDecodeError) as e:
            log.warning("startup notice: acknowledgment record %s is unreadable "
                        "(%s); showing the non-blocking banner", path, e)
            return NoticeState(False, "unreadable")

        valid, bad = [], 0
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                bad += 1
                continue
            if _valid_record(rec):
                valid.append(rec)
            else:
                bad += 1
        if bad:
            # A torn final line after a power loss is the expected case; the
            # other records are still usable.
            log.warning("startup notice: %d corrupt line(s) in acknowledgment "
                        "record %s ignored", bad, path)
        if not valid:
            log.warning("startup notice: acknowledgment record %s holds no "
                        "valid record (corrupt); showing the non-blocking "
                        "banner", path)
            return NoticeState(False, "corrupt")
        if any(_matches(r, software_version) for r in valid):
            log.info("startup notice: this notice is accepted for pyEfis %s "
                     "in %s", software_version, path)
            return NoticeState(True, "acknowledged")
        log.warning("startup notice: no record in %s accepts this notice for "
                    "pyEfis %s; showing the non-blocking banner",
                    path, software_version)
        return NoticeState(False, "not-acknowledged")
    except Exception as e:
        log.warning("startup notice: could not evaluate acknowledgment record "
                    "%s (%s); showing the non-blocking banner", path, e)
        return NoticeState(False, "unreadable")


class StartupNoticeBanner(QWidget):
    """A translucent strip across the bottom of the window carrying the notice.

    Transparent to mouse/touch input, so the instruments underneath keep
    working while it is up, and hides itself after ``duration_ms``."""

    def __init__(self, parent, duration_ms, text=NOTICE_TEXT,
                 font_family="DejaVu Sans Condensed"):
        super().__init__(parent)
        self.text = text
        self.font_family = font_family
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)
        self._timer.start(int(duration_ms))
        self.fit_to_parent()

    def fit_to_parent(self):
        p = self.parentWidget()
        if p is None:
            return
        # size(), not width()/height(): gui.initialize assigns plain ints over
        # mainWindow.width/height in windowed mode.
        w, h = p.size().width(), p.size().height()
        bh = max(48, int(h * 0.16))
        self.setGeometry(0, h - bh, w, bh)

    def dismiss(self):
        self._timer.stop()
        self.hide()

    def paintEvent(self, event):
        qp = QPainter(self)
        qp.setRenderHint(QPainter.RenderHint.Antialiasing)
        qp.fillRect(self.rect(), QColor(0, 0, 0, 200))
        qp.setPen(QColor(235, 235, 235))
        font = QFont(self.font_family)
        font.setPixelSize(max(12, int(self.height() * 0.2)))
        qp.setFont(font)
        margin = self.height() * 0.1
        qp.drawText(QRectF(margin, margin, self.width() - 2 * margin,
                           self.height() - 2 * margin),
                    Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                    self.text)


def show_banner(parent, ack_path=None):
    """Evaluate the record and put the banner over ``parent``. Returns the
    banner, or None if it could not be built -- a failure here is logged and
    never propagates into boot."""
    try:
        state = evaluate(ack_path)
        banner = StartupNoticeBanner(parent, state.duration_ms)
        banner.show()
        banner.raise_()
        return banner
    except Exception as e:
        log.error("startup notice: could not show the banner (%s)", e)
        return None
