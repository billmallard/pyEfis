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

import hashlib
import json
import logging

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QWidget

from pyefis import startup_notice as sn

VERSION = "2.2.1"
# sha256 of pyefis_data.acknowledge.NOTICE_TEXT (makerplane-data #131). If this
# moves, the two repos no longer show the same words and no record will match.
WRITER_NOTICE_SHA256 = \
    "6f9882fe66c4084b33381282439d971766762377c3208258a870695c19c722ab"


@pytest.fixture
def app(qtbot):
    return QApplication.instance() or QApplication([])


def _record(**over):
    """A schema-1 accept as pyefis-data writes it (install_acknowledgment.md)."""
    rec = {"schema": 1, "event": "accept", "timestamp": "2026-10-31T14:05:09Z",
           "notice_id": "pyefis-software-2026-10-30",
           "notice_sha256": sn.NOTICE_SHA256, "notice_text": sn.NOTICE_TEXT,
           "software": {"pyefis-data": "0.4.0", "pyefis": VERSION},
           "packs": {}, "user": "pi", "host": "pyefis", "via": "caller",
           "trigger": "pyefis-install"}
    rec.update(over)
    return rec


def _other_notice(text="Some other wording."):
    return {"notice_text": text,
            "notice_sha256": hashlib.sha256(text.encode()).hexdigest()}


def _write(path, *lines):
    path.write_text("".join(
        (l if isinstance(l, str) else json.dumps(l)) + "\n" for l in lines))
    return path


def test_notice_text_is_the_approved_wording():
    assert sn.NOTICE_TEXT == (
        "pyEfis is experimental software for Experimental / Amateur-Built "
        "aircraft. It is not certified. It is provided as-is with no warranty, "
        "and any use of it is at your own risk.")
    assert sn.NOTICE_SHA256 == WRITER_NOTICE_SHA256


def test_log_path_resolves_like_the_writer(monkeypatch, tmp_path):
    monkeypatch.delenv("MAKERPLANE_ACK_LOG", raising=False)
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert sn.ack_log_path() == \
        tmp_path / ".local/state/makerplane/acknowledgments.jsonl"
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    assert sn.ack_log_path() == tmp_path / "st/makerplane/acknowledgments.jsonl"
    monkeypatch.setenv("MAKERPLANE_ACK_LOG", str(tmp_path / "x.jsonl"))
    assert sn.ack_log_path() == tmp_path / "x.jsonl"


def test_evaluate_defaults_to_the_resolved_log(monkeypatch, tmp_path):
    p = _write(tmp_path / "ack.jsonl", _record())
    monkeypatch.setenv("MAKERPLANE_ACK_LOG", str(p))
    assert sn.evaluate(software_version=VERSION).acknowledged


def test_matching_record_is_acknowledged(tmp_path, caplog):
    p = _write(tmp_path / "ack.jsonl", _record())
    with caplog.at_level(logging.INFO, logger=sn.__name__):
        st = sn.evaluate(p, VERSION)
    assert st == sn.NoticeState(True, "acknowledged")
    assert st.duration_ms == sn.ACKNOWLEDGED_MS
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_any_earlier_matching_record_counts(tmp_path):
    p = _write(tmp_path / "ack.jsonl", _record(),
               _record(software={"pyefis": "9.9.9"}))
    assert sn.evaluate(p, VERSION).acknowledged


def test_missing_record_gives_banner_and_log(tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger=sn.__name__):
        st = sn.evaluate(tmp_path / "nope.jsonl", VERSION)
    assert st == sn.NoticeState(False, "missing")
    assert st.duration_ms == sn.UNACKNOWLEDGED_MS
    assert "missing" in caplog.text


@pytest.mark.parametrize("content", [
    b"{not json at all\n",
    b'{"schema": 1, "software": "2.2.1"}\n',        # wrong shape
    json.dumps(_record(schema=99)).encode() + b"\n",            # unknown schema
    json.dumps(_record(event="revoke")).encode() + b"\n",       # not an accept
    json.dumps(_record(notice_sha256="0" * 64)).encode() + b"\n",  # hash != text
    b"\x00\x00\x00\x00",                              # zero-filled after power loss
    b"[1, 2, 3]\n",
])
def test_corrupt_record_gives_banner_and_log(tmp_path, caplog, content):
    p = tmp_path / "ack.jsonl"
    p.write_bytes(content)
    with caplog.at_level(logging.WARNING, logger=sn.__name__):
        st = sn.evaluate(p, VERSION)
    assert st == sn.NoticeState(False, "corrupt")
    assert "corrupt" in caplog.text


def test_torn_last_line_keeps_the_valid_records(tmp_path, caplog):
    p = tmp_path / "ack.jsonl"
    p.write_text(json.dumps(_record()) + "\n" + '{"schema": 1, "times')
    with caplog.at_level(logging.WARNING, logger=sn.__name__):
        st = sn.evaluate(p, VERSION)
    assert st.acknowledged
    assert "1 corrupt line" in caplog.text


def test_unreadable_record_gives_banner_and_log(tmp_path, caplog):
    p = tmp_path / "ack.jsonl"
    p.write_bytes(b"\xff\xfe\xfa not utf-8")
    with caplog.at_level(logging.WARNING, logger=sn.__name__):
        st = sn.evaluate(p, VERSION)
    assert st == sn.NoticeState(False, "unreadable")
    assert "unreadable" in caplog.text


def test_record_path_is_a_directory(tmp_path):
    assert sn.evaluate(tmp_path, VERSION) == \
        sn.NoticeState(False, "unreadable")


def test_unexpected_failure_never_raises(tmp_path, monkeypatch):
    p = _write(tmp_path / "ack.jsonl", _record())
    monkeypatch.setattr(sn, "_matches", lambda *a: 1 / 0)
    assert sn.evaluate(p, VERSION) == \
        sn.NoticeState(False, "unreadable")


@pytest.mark.parametrize("record", [
    _record(software={"pyefis-data": "0.4.0", "pyefis": "2.1.0"}),  # older pyEfis
    _record(software={"pyefis-data": "0.4.0"}),      # plain `pyefis-data update`
    _record(**_other_notice()),                      # a different notice wording
])
def test_records_not_for_this_notice_and_version_do_not_count(
        tmp_path, caplog, record):
    p = _write(tmp_path / "ack.jsonl", record)
    with caplog.at_level(logging.WARNING, logger=sn.__name__):
        st = sn.evaluate(p, VERSION)
    assert st == sn.NoticeState(False, "not-acknowledged")
    assert st.duration_ms == sn.UNACKNOWLEDGED_MS
    assert "no record" in caplog.text


def test_pack_state_is_not_matched(tmp_path):
    # packs is the state before the gated install; a timer pack update adds no
    # record. Neither may turn an accepted version into a long banner.
    p = _write(tmp_path / "ack.jsonl",
               _record(packs={"airports-conus": "2606"}))
    assert sn.evaluate(p, VERSION).acknowledged


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
    banner = sn.show_banner(parent, ack_path=p)
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
