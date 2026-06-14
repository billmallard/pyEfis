"""Headless render tests for the Data Status instrument.

Uses the Qt 'offscreen' platform so paintEvent runs with no display. The
key guarantees: the instrument constructs and paints from a good status
file, and a missing/malformed file is handled silently (construct-never-
raises) rather than crashing the EFIS at boot."""

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication

from pyefis.instruments import data_status


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


SAMPLE = {
    "ok": True, "generated": "2026-06-14T00:00:00Z", "worst": "amber",
    "any_attention": True,
    "packs": [
        {"id": "airports-conus", "name": "Airports & Runways", "kind": "navdata",
         "status": "current", "severity": "none", "cycle": "2606",
         "expires": "2026-07-09", "days": 25, "detail": "2606"},
        {"id": "obstacles-conus", "name": "Obstacles", "kind": "obstacles",
         "status": "EXPIRED", "severity": "amber", "cycle": "260500",
         "expires": "2026-06-11", "days": -3, "detail": "260500 expired 2026-06-11"},
    ],
}


def _write(tmp_path, doc):
    p = tmp_path / "status.json"
    p.write_text(json.dumps(doc))
    return p


def test_constructs_and_paints(app, tmp_path):
    w = data_status.DataStatus(status_path=str(_write(tmp_path, SAMPLE)))
    w.resize(800, 480)
    assert w.status["ok"] is True and len(w.status["packs"]) == 2
    pm = w.grab()                       # forces paintEvent offscreen
    assert not pm.isNull() and pm.width() == 800


def test_missing_file_is_safe(app, tmp_path):
    w = data_status.DataStatus(status_path=str(tmp_path / "nope.json"))
    w.resize(400, 300)
    assert w.status is None             # never raised
    assert not w.grab().isNull()        # paints the "unavailable" message


def test_malformed_file_is_safe(app, tmp_path):
    p = tmp_path / "status.json"
    p.write_text("{ not valid json ][")
    w = data_status.DataStatus(status_path=str(p))
    w.resize(400, 300)
    assert w.status is None
    assert not w.grab().isNull()


def test_reload_picks_up_changes(app, tmp_path):
    p = _write(tmp_path, {"ok": True, "packs": []})
    w = data_status.DataStatus(status_path=str(p))
    assert w.status["packs"] == []
    p.write_text(json.dumps(SAMPLE))
    w.reload()
    assert len(w.status["packs"]) == 2


def test_severity_color_keys(app):
    assert set(data_status.SEVERITY_COLORS) == {"amber", "white", "none"}


def test_continue_without_hmi_does_not_raise(app, tmp_path):
    # _on_continue must be safe even when hmi.actions isn't initialised.
    w = data_status.DataStatus(status_path=str(_write(tmp_path, SAMPLE)))
    w._on_continue()                    # no exception


def test_update_command_is_expanduser(app, tmp_path, monkeypatch):
    # The Update button must launch an absolute/~-expanded path (systemd PATH
    # excludes ~/.local/bin), not a bare name.
    from PyQt6.QtCore import QProcess
    captured = {}
    monkeypatch.setattr(QProcess, "start",
                        lambda self, prog, args: captured.update(prog=prog, args=args))
    w = data_status.DataStatus(status_path=str(_write(tmp_path, SAMPLE)),
                               update_command="~/.local/bin/pyefis-data")
    w._on_update()
    assert captured["prog"] == os.path.expanduser("~/.local/bin/pyefis-data")
    assert captured["args"] == ["update"]


# --- DataAnnunciation (persistent PFD flag) ---

def test_worst_severity():
    assert data_status.worst_severity(None) == "none"
    assert data_status.worst_severity({"ok": False}) == "none"
    assert data_status.worst_severity(SAMPLE) == "amber"   # has an expired pack
    all_current = {"ok": True, "packs": [{"severity": "none"}, {"severity": "none"}]}
    assert data_status.worst_severity(all_current) == "none"
    soon = {"ok": True, "packs": [{"severity": "none"}, {"severity": "white"}]}
    assert data_status.worst_severity(soon) == "white"


def test_annunciation_hidden_when_current(app, tmp_path):
    doc = {"ok": True, "packs": [{"name": "Airports", "severity": "none"}]}
    a = data_status.DataAnnunciation(status_path=str(_write(tmp_path, doc)))
    a.resize(120, 40)
    assert data_status.worst_severity(a.status) == "none"
    assert not a.grab().isNull()        # paints nothing, but does not crash


def test_annunciation_shows_when_expired(app, tmp_path):
    a = data_status.DataAnnunciation(status_path=str(_write(tmp_path, SAMPLE)))
    a.resize(120, 40)
    assert data_status.worst_severity(a.status) == "amber"
    assert not a.grab().isNull()


def test_annunciation_unavailable_is_hidden(app, tmp_path):
    a = data_status.DataAnnunciation(status_path=str(tmp_path / "nope.json"))
    a.resize(120, 40)
    assert a.status is None
    assert data_status.worst_severity(a.status) == "none"   # no updater -> no flag


def test_annunciation_tap_without_hmi_is_safe(app, tmp_path):
    from PyQt6.QtGui import QMouseEvent
    from PyQt6.QtCore import QEvent, QPointF, Qt
    a = data_status.DataAnnunciation(status_path=str(_write(tmp_path, SAMPLE)))
    ev = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(1, 1),
                     Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier)
    a.mousePressEvent(ev)               # no exception
