"""About / System screen (BACKLOG L4).

Guards: the notice is Bill's approved text verbatim; each installed pack's
``notice`` (L1) is shown, and a pack without one says so instead of borrowing
the software notice; a missing/malformed status file never raises; the
screen is built in (injected when a config drops it); and the Data Status
screen's About button routes to it."""

import json
import logging
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication, QLabel

from pyefis import gui
from pyefis.instruments import about, data_status


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


# BACKLOG L4 "Notice text (Bill approved it 2026-10-30 ... use it verbatim)".
APPROVED = ("pyEfis is experimental software for Experimental / Amateur-Built "
            "aircraft. It is not certified. It is provided as-is with no "
            "warranty, and any use of it is at your own risk.")

PACK_NOTICE = ("Experimental / Amateur-Built use only. Not certified. This data "
               "is provided as-is with no warranty and any use of the data is "
               "at your own risk.")

STATUS = {
    "ok": True, "generated": "2026-10-30T00:00:00Z", "worst": "none",
    "any_attention": False,
    "packs": [
        {"id": "navaids-conus", "name": "navaids-conus", "kind": "navaids",
         "status": "current", "severity": "none", "cycle": "2612",
         "notice": PACK_NOTICE},
        # Published before the notice field existed: the manifest carries "".
        {"id": "water-na", "name": "water-na", "kind": "water",
         "status": "current", "severity": "none", "cycle": "2026q2r6",
         "notice": ""},
        # Tracked but not installed: no cycle, so not on this device.
        {"id": "terrain-us-west", "name": "terrain-us-west", "kind": "terrain",
         "status": "missing", "severity": "white", "cycle": ""},
    ],
}


def _write(tmp_path, doc):
    p = tmp_path / "status.json"
    p.write_text(doc if isinstance(doc, str) else json.dumps(doc))
    return str(p)


def _texts(w):
    return [lbl.text() for lbl in w.findChildren(QLabel)]


def test_notice_is_the_approved_text_verbatim():
    assert about.NOTICE == APPROVED


def test_pack_notices_reads_installed_packs_only():
    assert about.pack_notices(STATUS) == [
        ("navaids-conus", "2612", PACK_NOTICE),
        ("water-na", "2026q2r6", None),
    ]


def test_pack_label_adds_the_id_when_the_name_repeats():
    status = {"ok": True, "packs": [
        {"id": "terrain-us-west", "name": "Terrain", "cycle": "2024edr1"},
        {"id": "terrain-us-east", "name": "Terrain", "cycle": "2024edr1"},
        {"id": "water-na", "cycle": "2026q2r6"},
    ]}
    assert [r[0] for r in about.pack_notices(status)] == [
        "Terrain (terrain-us-west)", "Terrain (terrain-us-east)", "water-na"]


@pytest.mark.parametrize("status", [None, {}, {"ok": False},
                                    {"ok": True, "packs": None},
                                    {"ok": True, "packs": ["junk", 3]}])
def test_pack_notices_tolerates_bad_status(status):
    assert about.pack_notices(status) == []


def test_screen_shows_notice_version_and_pack_notices(app, tmp_path):
    w = about.AboutSystem(status_path=_write(tmp_path, STATUS))
    w.resize(800, 480)
    texts = _texts(w)
    assert APPROVED in texts
    assert any("2.2" in t and t.startswith("Version") for t in texts)
    assert "navaids-conus  2612" in texts
    assert PACK_NOTICE in texts
    # The pre-L1 pack says it has no notice; it never borrows the software one.
    i = texts.index("water-na  2026q2r6")
    assert texts[i + 1] == about.NO_PACK_NOTICE
    assert texts.count(APPROVED) == 1
    assert not any("terrain-us-west" in t for t in texts)


@pytest.mark.parametrize("content", [None, "{not json"])
def test_missing_or_malformed_status_never_raises(app, tmp_path, content):
    path = (str(tmp_path / "absent.json") if content is None
            else _write(tmp_path, content))
    w = about.AboutSystem(status_path=path)
    w.resize(800, 480)
    texts = _texts(w)
    assert APPROVED in texts
    assert "Data pack status unavailable on this device." in texts


def test_reload_picks_up_a_new_status_without_rebuilding(app, tmp_path):
    path = _write(tmp_path, {"ok": True, "packs": []})
    w = about.AboutSystem(status_path=path)
    assert "No data packs installed." in _texts(w)
    _write(tmp_path, STATUS)
    w.reload()
    texts = _texts(w)
    assert "No data packs installed." not in texts
    assert PACK_NOTICE in texts


class _Actions:
    def __init__(self):
        self.calls = []

    def trigger(self, action, arg=None):
        self.calls.append((action, arg))


def test_back_and_data_status_about_route_through_show_screen(
        app, tmp_path, monkeypatch):
    from pyefis import hmi
    acts = _Actions()
    monkeypatch.setattr(hmi, "actions", acts, raising=False)
    path = _write(tmp_path, STATUS)

    a = about.AboutSystem(status_path=path, back_screen="DataStatus")
    a.btn_back.click()
    ds = data_status.DataStatus(status_path=path)
    ds.resize(800, 480)
    ds.show()
    assert ds.btn_about.isVisible()
    ds.btn_about.click()
    assert acts.calls == [("show screen", "DataStatus"),
                          ("show screen", "About")]
    ds.hide()


def test_data_status_about_button_hidden_outside_status_mode(app, tmp_path):
    ds = data_status.DataStatus(status_path=_write(tmp_path, STATUS))
    ds.show()
    ds.mode = "busy"
    ds._sync_visibility()
    assert not ds.btn_about.isVisible()
    ds.hide()


class _FakeScreen:
    def __init__(self, name, module, config):
        self.name = name


def test_about_screen_injected_when_config_drops_it(monkeypatch):
    gui.log = logging.getLogger("test_about")
    monkeypatch.setattr(gui, "Screen", _FakeScreen)
    monkeypatch.setattr(gui, "screens", [])
    cfg = {"screens": {"PFD": {"module": "pyefis.screens.screenbuilder"}}}
    assert gui._ensure_about_screen(cfg) is True
    assert cfg["screens"]["About"]["instruments"][0]["type"] == "about"
    assert [s.name for s in gui.screens] == ["About"]
    # Idempotent, and a config that defines its own About is left alone.
    assert gui._ensure_about_screen(cfg) is True
    assert [s.name for s in gui.screens] == ["About"]


def test_about_screen_failure_never_breaks_boot(monkeypatch):
    gui.log = logging.getLogger("test_about")

    def boom(*a, **k):
        raise RuntimeError("bad module")
    monkeypatch.setattr(gui, "Screen", boom)
    monkeypatch.setattr(gui, "screens", [])
    assert gui._ensure_about_screen({"screens": {}}) is False
