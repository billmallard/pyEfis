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

"""Startup notice (BACKLOG L3): the acknowledgment record only ever selects
between two NON-blocking banners, every failure falls toward the banner and is
logged, and the banner never takes input away from the instruments."""

import json
import logging

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QWidget

from pyefis import startup_notice as sn

VERSION = "2.2.1"
PACKS = {"airports-us": "2610", "terrain-na": "2026.09"}


@pytest.fixture
def app(qtbot):
    return QApplication.instance() or QApplication([])


def _record(**over):
    rec = {"schema": 1, "timestamp": "2026-10-31T14:02:11Z",
           "software": {"pyefis": VERSION}, "packs": dict(PACKS),
           "user": "pilot", "host": "efis"}
    rec.update(over)
    return rec


def _write(path, *lines):
    path.write_text("".join(
        (l if isinstance(l, str) else json.dumps(l)) + "\n" for l in lines))
    return path


def test_notice_text_is_the_approved_wording():
    assert sn.NOTICE_TEXT == (
        "pyEfis is experimental software for Experimental / Amateur-Built "
        "aircraft. It is not certified. It is provided as-is with no warranty, "
        "and any use of it is at your own risk.")


def test_matching_record_is_acknowledged(tmp_path, caplog):
    p = _write(tmp_path / "ack.jsonl", _record())
    with caplog.at_level(logging.INFO, logger=sn.__name__):
        st = sn.evaluate(p, VERSION, PACKS)
    assert st == sn.NoticeState(True, "acknowledged")
    assert st.duration_ms == sn.ACKNOWLEDGED_MS
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_any_earlier_matching_record_counts(tmp_path):
    p = _write(tmp_path / "ack.jsonl", _record(),
               _record(software={"pyefis": "9.9.9"}))
    assert sn.evaluate(p, VERSION, PACKS).acknowledged


def test_missing_record_gives_banner_and_log(tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger=sn.__name__):
        st = sn.evaluate(tmp_path / "nope.jsonl", VERSION, PACKS)
    assert st == sn.NoticeState(False, "missing")
    assert st.duration_ms == sn.UNACKNOWLEDGED_MS
    assert "missing" in caplog.text


@pytest.mark.parametrize("content", [
    b"{not json at all\n",
    b'{"schema": 1, "software": "2.2.1"}\n',        # wrong shape
    b'{"schema": 99, "timestamp": "t", "software": {"pyefis": "2.2.1"},'
    b' "packs": {}}\n',                               # unknown schema
    b"\x00\x00\x00\x00",                              # zero-filled after power loss
    b"[1, 2, 3]\n",
])
def test_corrupt_record_gives_banner_and_log(tmp_path, caplog, content):
    p = tmp_path / "ack.jsonl"
    p.write_bytes(content)
    with caplog.at_level(logging.WARNING, logger=sn.__name__):
        st = sn.evaluate(p, VERSION, PACKS)
    assert st == sn.NoticeState(False, "corrupt")
    assert "corrupt" in caplog.text


def test_torn_last_line_keeps_the_valid_records(tmp_path, caplog):
    p = tmp_path / "ack.jsonl"
    p.write_text(json.dumps(_record()) + "\n" + '{"schema": 1, "times')
    with caplog.at_level(logging.WARNING, logger=sn.__name__):
        st = sn.evaluate(p, VERSION, PACKS)
    assert st.acknowledged
    assert "1 corrupt line" in caplog.text


def test_unreadable_record_gives_banner_and_log(tmp_path, caplog):
    p = tmp_path / "ack.jsonl"
    p.write_bytes(b"\xff\xfe\xfa not utf-8")
    with caplog.at_level(logging.WARNING, logger=sn.__name__):
        st = sn.evaluate(p, VERSION, PACKS)
    assert st == sn.NoticeState(False, "unreadable")
    assert "unreadable" in caplog.text


def test_record_path_is_a_directory(tmp_path):
    assert sn.evaluate(tmp_path, VERSION, PACKS) == \
        sn.NoticeState(False, "unreadable")


def test_unexpected_failure_never_raises(tmp_path, monkeypatch):
    p = _write(tmp_path / "ack.jsonl", _record())
    monkeypatch.setattr(sn, "_matches", lambda *a: 1 / 0)
    assert sn.evaluate(p, VERSION, PACKS) == \
        sn.NoticeState(False, "unreadable")


@pytest.mark.parametrize("version,packs", [
    ("2.3.0", PACKS),                                   # software updated
    (VERSION, {**PACKS, "terrain-na": "2026.10"}),      # pack updated
    (VERSION, {"airports-us": "2610"}),                 # pack removed
    (VERSION, None),                                    # pack state unknown
])
def test_other_versions_are_not_acknowledged(tmp_path, caplog, version, packs):
    p = _write(tmp_path / "ack.jsonl", _record())
    with caplog.at_level(logging.WARNING, logger=sn.__name__):
        st = sn.evaluate(p, version, packs)
    assert st == sn.NoticeState(False, "not-acknowledged")
    assert st.duration_ms == sn.UNACKNOWLEDGED_MS
    assert "no acknowledgment" in caplog.text


def test_installed_packs_from_status(tmp_path):
    p = tmp_path / "status.json"
    p.write_text(json.dumps({"ok": True, "packs": [
        {"id": "airports-us", "cycle": "2610"},
        {"id": "terrain-na", "cycle": "2026.09"}]}))
    assert sn.installed_packs(p) == PACKS
    assert sn.installed_packs(tmp_path / "missing.json") is None
    p.write_text('{"ok": false}')
    assert sn.installed_packs(p) is None


def test_banner_overlays_bottom_passes_input_and_self_dismisses(app, qtbot):
    parent = QWidget()
    parent.resize(800, 480)
    parent.show()
    banner = sn.StartupNoticeBanner(parent, duration_ms=50)
    banner.show()
    assert banner.isVisible()
    assert banner.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert banner.focusPolicy() == Qt.FocusPolicy.NoFocus
    g = banner.geometry()
    assert (g.x(), g.width(), g.bottom() + 1) == (0, 800, 480)
    assert g.height() < 480 // 4          # a strip, not a screen
    qtbot.waitUntil(lambda: not banner.isVisible(), timeout=2000)
    parent.close()


def test_show_banner_with_corrupt_record_shows_long_banner(app, tmp_path):
    p = tmp_path / "ack.jsonl"
    p.write_text("garbage\n")
    parent = QWidget()
    parent.resize(320, 240)
    parent.show()
    banner = sn.show_banner(parent, ack_path=p,
                            status_path=tmp_path / "status.json")
    assert banner is not None and banner.isVisible()
    assert banner._timer.interval() == sn.UNACKNOWLEDGED_MS
    parent.close()


def test_show_banner_failure_never_propagates(app, monkeypatch, caplog):
    def boom(*a, **k):
        raise RuntimeError("no paint for you")
    monkeypatch.setattr(sn, "StartupNoticeBanner", boom)
    parent = QWidget()
    with caplog.at_level(logging.ERROR, logger=sn.__name__):
        assert sn.show_banner(parent, ack_path="/nonexistent/ack") is None
    assert "could not show the banner" in caplog.text
