"""About / System screen (BACKLOG L4).

Guards: the notice is Bill's approved text verbatim; each installed pack's
``notice`` (L1) is shown, and a pack without one says so instead of borrowing
the software notice; the L2 acknowledgment history is rendered newest first,
with bench auto-accepts and other notice wordings labelled; a missing/malformed
status file or acknowledgment log never raises; the screen is built in (injected when a config drops it); and the Data Status
screen's About button routes to it."""

import hashlib
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


@pytest.fixture(autouse=True)
def _no_host_ack_log(tmp_path, monkeypatch):
    # Never read the developer's / CI host's real acknowledgment log.
    monkeypatch.setenv("MAKERPLANE_ACK_LOG", str(tmp_path / "no-acks.jsonl"))


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


# --- L2 acknowledgment history -------------------------------------------

def _ack(**kw):
    """A schema-1 accept as makerplane-data docs/install_acknowledgment.md
    defines it."""
    text = kw.pop("notice_text", APPROVED)
    rec = {"schema": 1, "event": "accept", "timestamp": "2026-10-31T14:05:09Z",
           "notice_id": "pyefis-software-2026-10-30",
           "notice_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
           "notice_text": text,
           "software": {"pyefis-data": "0.4.0", "pyefis": "2.2.1"},
           "packs": {"obstacles-conus": "260611", "airports-conus": "2606"},
           "user": "pi", "host": "pyefis", "via": "tty", "trigger": "update"}
    rec.update(kw)
    return rec


def _write_acks(tmp_path, recs, tail=""):
    p = tmp_path / "acknowledgments.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in recs) + tail)
    return str(p)


def test_ack_history_renders_one_record_in_full():
    assert about.ack_history([_ack()]) == [(
        "2026-10-31 14:05:09 UTC  accepted by pi@pyefis",
        "Typed \"accept\" at a terminal (trigger: update). "
        "Software: pyefis 2.2.1, pyefis-data 0.4.0. "
        "Packs at the time: airports-conus 2606, obstacles-conus 260611.")]


def test_ack_history_is_newest_first_and_labels_bench_and_old_wording():
    recs = [_ack(timestamp="2026-10-01T00:00:00Z", notice_text="older words"),
            _ack(timestamp="2026-10-02T00:00:00Z", via="bench", packs={}),
            _ack(timestamp="2026-10-03T00:00:00Z", via="caller",
                 trigger="pyefis-install", software={"pyefis-data": "0.4.0"})]
    hist = about.ack_history(recs)
    assert [h[0][:10] for h in hist] == ["2026-10-03", "2026-10-02",
                                        "2026-10-01"]
    assert hist[0][1].startswith("Accepted on screen in the installer or "
                                 "pack picker (trigger: pyefis-install).")
    assert "pyefis 2" not in hist[0][1]
    assert "not a person's accept" in hist[1][1]
    assert "No packs were installed yet." in hist[1][1]
    assert "different wording" in hist[2][1]
    assert not any("different wording" in d for _, d in hist[:2])


def test_ack_history_tolerates_odd_optional_fields():
    rec = _ack(user=None, host=7, via=None, trigger="", packs="junk",
               software={"pyefis-data": "0.4.0", "x": 3})
    assert about.ack_history([rec]) == [(
        "2026-10-31 14:05:09 UTC  accepted",
        "Accepted. Software: pyefis-data 0.4.0.")]


def test_screen_shows_ack_history_and_skips_bad_lines(app, tmp_path):
    bad = dict(_ack(), notice_sha256="0" * 64)        # sha does not cover text
    path = _write_acks(tmp_path, [_ack(), {"schema": 2, "event": "accept"},
                                  bad], tail='{"schema": 1, "ev')  # torn line
    w = about.AboutSystem(status_path=_write(tmp_path, STATUS), ack_path=path)
    w.resize(800, 480)
    texts = _texts(w)
    assert "Notice acknowledgments" in texts
    assert texts.count("2026-10-31 14:05:09 UTC  accepted by pi@pyefis") == 1
    assert about.NO_ACK_RECORD not in texts
    # The notice is still shown once; history never repeats its text.
    assert texts.count(APPROVED) == 1


@pytest.mark.parametrize("content", [None, "", "garbage\n", b"\xff\xfe"])
def test_missing_or_unreadable_ack_log_never_raises(app, tmp_path, content):
    p = tmp_path / "acknowledgments.jsonl"
    if isinstance(content, bytes):
        p.write_bytes(content)
    elif content is not None:
        p.write_text(content)
    w = about.AboutSystem(status_path=_write(tmp_path, STATUS), ack_path=str(p))
    w.resize(800, 480)
    texts = _texts(w)
    assert about.NO_ACK_RECORD in texts
    assert APPROVED in texts


def test_ack_history_defaults_to_the_writers_path(app, tmp_path, monkeypatch):
    path = _write_acks(tmp_path, [_ack()])
    monkeypatch.setenv("MAKERPLANE_ACK_LOG", path)
    w = about.AboutSystem(status_path=_write(tmp_path, STATUS))
    assert "2026-10-31 14:05:09 UTC  accepted by pi@pyefis" in _texts(w)


def test_reload_picks_up_a_new_acceptance(app, tmp_path):
    p = tmp_path / "acknowledgments.jsonl"
    w = about.AboutSystem(status_path=_write(tmp_path, STATUS), ack_path=str(p))
    assert about.NO_ACK_RECORD in _texts(w)
    _write_acks(tmp_path, [_ack()])
    w.reload()
    texts = _texts(w)
    assert about.NO_ACK_RECORD not in texts
    assert "2026-10-31 14:05:09 UTC  accepted by pi@pyefis" in texts
