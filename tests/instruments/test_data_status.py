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
    # The updater must launch an absolute/~-expanded path (systemd PATH excludes
    # ~/.local/bin), not a bare name. The Update button now starts the flow with
    # a `sources` probe.
    from PyQt6.QtCore import QProcess
    captured = {}
    monkeypatch.setattr(QProcess, "start",
                        lambda self, prog, args: captured.update(prog=prog, args=args))
    w = data_status.DataStatus(status_path=str(_write(tmp_path, SAMPLE)),
                               update_command="~/.local/bin/pyefis-data")
    w._on_update()
    assert captured["prog"] == os.path.expanduser("~/.local/bin/pyefis-data")
    assert captured["args"] == ["sources", "--json"]


# --- PackPicker + the Update -> sources -> catalog -> install flow ---

CATALOG = {
    "ok": True, "generated": "2026-06-15T00:00:00Z",
    "storage": {"root": "/data/makerplane-data",
                "free_bytes": 350_000_000_000, "total_bytes": 460_000_000_000},
    "packs": [
        {"id": "airports-conus", "name": "Airports & Runways", "kind": "navdata",
         "status": "current", "severity": "none", "bytes": 6_000_000,
         "regions": ["conus"], "tracked": True, "installed": True},
        {"id": "terrain-us-west", "name": "Terrain", "kind": "terrain",
         "status": "MISSING", "severity": "white", "bytes": 9_984_793_161,
         "regions": ["us-west"], "tracked": False, "installed": False},
        {"id": "water-na", "name": "Water", "kind": "water",
         "status": "MISSING", "severity": "white", "bytes": 2_460_000_000,
         "regions": ["conus", "us-west"], "tracked": False, "installed": False},
    ],
}


DRIVES = {"drives": [
    {"mount": "/data", "device": "/dev/mmcblk0p1", "fstype": "ext4",
     "free_bytes": 360_000_000_000, "total_bytes": 460_000_000_000, "removable": False},
    {"mount": "/media/wpballard/SSD", "device": "/dev/sda1", "fstype": "exfat",
     "free_bytes": 900_000_000_000, "total_bytes": 1_000_000_000_000, "removable": True},
]}


def test_parse_json_skips_leading_lines():
    out = "  fetch http://x\n  build ...\n" + json.dumps({"ok": True})
    assert data_status._parse_json(out) == {"ok": True}
    assert data_status._parse_json("no json here") is None


def test_picker_prechecks_tracked_and_renders(app):
    pk = data_status.PackPicker(doc=CATALOG)
    pk.resize(800, 480)
    assert pk.selected_ids() == ["airports-conus"]      # only the tracked pack
    assert not pk.grab().isNull()                        # paints offscreen


def test_procedures_kind_groups_under_navigation_data(app):
    # PA5 (AER-1604): the procedures-conus pack must group with the other
    # navdata packs, not fall into "Other" for want of a _KIND_GROUP entry.
    assert data_status._KIND_GROUP["procedures"] == "Navigation Data"
    doc = {
        "ok": True, "generated": CATALOG["generated"], "storage": CATALOG["storage"],
        "packs": CATALOG["packs"] + [
            {"id": "procedures-conus", "name": "SIDs, STARs & Approaches",
             "kind": "procedures", "status": "current", "severity": "none",
             "bytes": 4_000_000, "tracked": True, "installed": True},
        ],
    }
    pk = data_status.PackPicker(doc=doc)
    pk.resize(800, 480)
    assert "procedures-conus" in pk.rows
    assert not pk.grab().isNull()


def test_picker_row_tap_toggles_checkbox(app):
    # On the touchscreen the whole row must toggle (tapping the tiny indicator
    # is unreliable); children are mouse-transparent and the row toggles on tap.
    # A tap is press+release on (nearly) the same spot — the row toggles on
    # release within a small slop so that two-finger scroll drags don't select.
    from PyQt6.QtGui import QMouseEvent
    from PyQt6.QtCore import QEvent, QPointF, Qt

    def tap(row, x=5, y=5):
        for kind in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
            ev = QMouseEvent(kind, QPointF(x, y),
                             Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                             Qt.KeyboardModifier.NoModifier)
            (row.mousePressEvent if kind == QEvent.Type.MouseButtonPress
             else row.mouseReleaseEvent)(ev)

    pk = data_status.PackPicker(doc=CATALOG)
    pk.resize(800, 480)
    assert "water-na" not in pk.selected_ids()
    assert pk.checks["water-na"].testAttribute(
        Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    tap(pk.rows["water-na"])
    assert "water-na" in pk.selected_ids()               # tap selected it
    tap(pk.rows["water-na"])
    assert "water-na" not in pk.selected_ids()           # tap again deselects


def test_picker_install_emits_selection(app):
    got = {}
    pk = data_status.PackPicker(doc=CATALOG, on_install=lambda ids: got.update(ids=ids))
    pk.resize(800, 480)
    pk.checks["water-na"].setChecked(True)
    pk._do_install()
    assert set(got["ids"]) == {"airports-conus", "water-na"}


def test_picker_free_space_guard_disables_install(app):
    tight = {**CATALOG, "storage": {"root": "/x",
             "free_bytes": 1_000_000_000, "total_bytes": 2_000_000_000}}
    pk = data_status.PackPicker(doc=tight)
    pk.resize(800, 480)
    pk.checks["terrain-us-west"].setChecked(True)        # 9.9 GB > 1 GB free
    assert pk.btn_install.isEnabled() is False


def _stub_run(w):
    """Replace DataStatus._run with a capture that records (args, on_finish)."""
    calls = []
    w._run = lambda args, on_finish, on_line=None: calls.append((list(args), on_finish))
    return calls


def test_update_flow_sources_catalog_picker(app, tmp_path):
    w = data_status.DataStatus(status_path=str(_write(tmp_path, SAMPLE)))
    w.resize(800, 480)
    calls = _stub_run(w)
    w._on_update()
    assert calls[0][0] == ["sources", "--json"]
    calls[0][1](0, json.dumps({"network": True, "usb": []}))   # sources result
    assert calls[1][0] == ["catalog", "--json"]                # default: Internet
    calls[1][1](0, json.dumps(CATALOG))                        # catalog result
    assert w.mode == "picker" and w.picker is not None
    assert w.picker.selected_ids() == ["airports-conus"]


def test_update_flow_no_sources_is_clean(app, tmp_path):
    w = data_status.DataStatus(status_path=str(_write(tmp_path, SAMPLE)))
    w.resize(800, 480)
    calls = _stub_run(w)
    w._on_update()
    calls[0][1](0, json.dumps({"network": False, "usb": []}))
    assert w.mode == "status"
    assert "No internet" in w.message and w.btn_update.isEnabled()


def test_update_flow_usb_only_uses_source(app, tmp_path):
    w = data_status.DataStatus(status_path=str(_write(tmp_path, SAMPLE)))
    w.resize(800, 480)
    calls = _stub_run(w)
    w._on_update()
    calls[0][1](0, json.dumps({"network": False, "usb": ["/media/u/stick/makerplane-data"]}))
    assert calls[1][0] == ["catalog", "--json", "--source",
                           "/media/u/stick/makerplane-data"]


def test_update_flow_install_then_back_to_status(app, tmp_path):
    w = data_status.DataStatus(status_path=str(_write(tmp_path, SAMPLE)))
    w.resize(800, 480)
    calls = _stub_run(w)
    w._on_update()
    calls[0][1](0, json.dumps({"network": True, "usb": []}))
    calls[1][1](0, json.dumps(CATALOG))
    w.picker.checks["water-na"].setChecked(True)
    w._install_selected(w.picker.selected_ids())
    assert w.mode == "busy"
    assert calls[2][0] == ["update", "--only", "airports-conus,water-na", "--progress"]
    calls[2][1](0, "  airports-conus  installed 2606\n")        # success
    assert w.mode == "status" and "complete" in w.message.lower()
    assert w.picker is None


def test_picker_storage_chooser_removable_warns(app):
    pk = data_status.PackPicker(doc=CATALOG, on_change_storage=lambda: None)
    pk.resize(900, 560)
    assert pk.chosen_root is None
    pk.open_drive_chooser(DRIVES["drives"])
    assert pk._chooser is not None and not pk.grab().isNull()
    pk._apply_storage(DRIVES["drives"][1])               # the removable SSD
    assert pk.chosen_root == "/media/wpballard/SSD/makerplane-data"
    assert pk._chooser is None                            # overlay closed
    assert not pk.warn_label.isHidden()                   # removable warning shown
    assert "/media/wpballard/SSD/makerplane-data" in pk.storage_label.text()


def test_picker_storage_internal_no_warning(app):
    pk = data_status.PackPicker(doc=CATALOG, on_change_storage=lambda: None)
    pk.resize(900, 560)
    pk._apply_storage(DRIVES["drives"][0])                # internal /data
    assert pk.chosen_root == "/data/makerplane-data"
    assert pk.warn_label.isHidden() is True


def test_update_flow_storage_chooser_passes_root(app, tmp_path):
    w = data_status.DataStatus(status_path=str(_write(tmp_path, SAMPLE)))
    w.resize(900, 560)
    calls = _stub_run(w)
    w._on_update()
    calls[0][1](0, json.dumps({"network": True, "usb": []}))   # sources
    calls[1][1](0, json.dumps(CATALOG))                        # catalog
    w._choose_storage()
    assert calls[2][0] == ["drives", "--json"]
    calls[2][1](0, json.dumps(DRIVES))                         # drives
    assert w.picker._chooser is not None
    w.picker._apply_storage(DRIVES["drives"][0])               # pick /data
    w._install_selected(w.picker.selected_ids())
    assert "--root" in calls[3][0]
    assert calls[3][0][calls[3][0].index("--root") + 1] == "/data/makerplane-data"


def test_progress_line_parsing_updates_bar(app, tmp_path):
    w = data_status.DataStatus(status_path=str(_write(tmp_path, SAMPLE)))
    w.resize(900, 560)
    w.mode = "busy"
    w._on_progress_line(json.dumps({"event": "begin", "total": 3}))
    assert w._prog["total"] == 3 and w._prog["pct"] is None
    w._on_progress_line(json.dumps({"event": "pack", "index": 2, "total": 3,
                                    "id": "terrain-us-west", "name": "Terrain"}))
    assert w._prog["index"] == 2 and w._prog["name"] == "Terrain"
    w._on_progress_line(json.dumps({"event": "progress", "id": "terrain-us-west",
                                    "done": 5, "total": 10, "pct": 50}))
    assert w._prog["pct"] == 50
    w._on_progress_line("  some plain log line, not json")    # ignored, no raise
    assert w._prog["pct"] == 50
    assert not w.grab().isNull()                                # busy bar renders


def test_install_passes_progress_flag_and_streams(app, tmp_path):
    w = data_status.DataStatus(status_path=str(_write(tmp_path, SAMPLE)))
    w.resize(900, 560)
    captured = {}
    w._run = lambda args, on_finish, on_line=None: captured.update(
        args=args, on_finish=on_finish, on_line=on_line)
    w.picker = None
    w._install_selected(["airports-conus", "water-na"])
    assert "--progress" in captured["args"]
    assert captured["on_line"] == w._on_progress_line       # progress is streamed
    # a progress event flowing through the streamed callback updates the bar
    captured["on_line"](json.dumps({"event": "begin", "total": 2}))
    assert w._prog["total"] == 2


def test_update_flow_cancel_returns_to_status(app, tmp_path):
    w = data_status.DataStatus(status_path=str(_write(tmp_path, SAMPLE)))
    w.resize(800, 480)
    calls = _stub_run(w)
    w._on_update()
    calls[0][1](0, json.dumps({"network": True, "usb": []}))
    calls[1][1](0, json.dumps(CATALOG))
    assert w.mode == "picker"
    w._cancel_picker()
    assert w.mode == "status" and w.picker is None


class _FakeProc:
    """Stand-in for the install QProcess so the cancel path is testable without
    a real subprocess: it just records that terminate()/kill() were called."""
    def __init__(self):
        self.terminated = False
        self.killed = False

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True


def _drive_to_busy(w, calls):
    w._on_update()
    calls[0][1](0, json.dumps({"network": True, "usb": []}))
    calls[1][1](0, json.dumps(CATALOG))
    w.picker.checks["water-na"].setChecked(True)
    w._install_selected(w.picker.selected_ids())
    assert w.mode == "busy"


def test_cancel_download_returns_to_picker(app, tmp_path):
    """Cancel on the progress screen terminates the updater and drops back to
    the pack picker with the selection intact (the 'don't feel trapped' path)."""
    w = data_status.DataStatus(status_path=str(_write(tmp_path, SAMPLE)))
    w.resize(800, 480)
    calls = _stub_run(w)
    _drive_to_busy(w, calls)
    w._proc = _FakeProc()                          # the running updater process
    w._cancel_download()
    assert w._canceling is True
    assert w._proc.terminated is True              # SIGTERM delivered
    assert "cancel" in w.message.lower()
    assert not w.grab().isNull()                   # "Canceling…" screen renders
    # the terminated process now exits non-zero -> back to the picker
    w._proc = None
    calls[2][1](-1, "")
    assert w.mode == "picker"
    assert w._canceling is False
    assert "water-na" in w.picker.selected_ids()   # selection preserved
    assert w.picker.btn_install.isEnabled()        # install re-enabled for retry
    assert w.btn_cancel_dl.isHidden()              # cancel hidden off the busy screen


def test_cancel_race_completion_counts_as_success(app, tmp_path):
    """If the install actually finishes in the race before SIGTERM lands (exit
    0), it's treated as a completed update, not a cancel."""
    w = data_status.DataStatus(status_path=str(_write(tmp_path, SAMPLE)))
    w.resize(800, 480)
    calls = _stub_run(w)
    _drive_to_busy(w, calls)
    w._proc = _FakeProc()
    w._cancel_download()
    w._proc = None
    calls[2][1](0, "  water-na  installed 2026q2r4\n")     # finished cleanly
    assert w.mode == "status" and "complete" in w.message.lower()
    assert w._canceling is False


def test_cancel_button_only_visible_when_busy(app, tmp_path):
    w = data_status.DataStatus(status_path=str(_write(tmp_path, SAMPLE)))
    w.resize(800, 480)
    assert w.btn_cancel_dl.isHidden()              # status mode: hidden
    w.mode = "busy"
    w._sync_visibility()
    assert not w.btn_cancel_dl.isHidden()          # busy mode: shown


# --- Software-notice gate (BACKLOG L2): `update` refuses with notice_required ---

NOTICE = ("pyEfis is experimental software for Experimental / Amateur-Built "
          "aircraft. It is not certified. It is provided as-is with no warranty, "
          "and any use of it is at your own risk.")


def _refuse_with_notice(w, calls, index=2):
    """The updater's refusal: one notice_required line, then exit 3."""
    w._on_progress_line(json.dumps({"event": "notice_required", "notice": NOTICE,
                                    "notice_id": "pyefis-software-2026-10-30"}))
    calls[index][1](data_status.NOTICE_RC, "")


def test_notice_required_shows_full_notice_not_failure(app, tmp_path):
    w = data_status.DataStatus(status_path=str(_write(tmp_path, SAMPLE)))
    w.resize(800, 480)
    calls = _stub_run(w)
    _drive_to_busy(w, calls)
    _refuse_with_notice(w, calls)
    assert w.mode == "notice" and w.notice_panel is not None
    assert w.notice_panel.text_label.text() == NOTICE        # the full text, verbatim
    assert w.notice_panel.geometry() == w.rect()             # covers the screen
    assert w.btn_continue.isHidden() and w.btn_update.isHidden()
    assert w.btn_cancel_dl.isHidden()
    assert w.picker is not None and w.picker.isHidden()      # kept for the re-run
    assert "problems" not in w.message                       # not reported as a failure
    assert not w.grab().isNull()


def test_notice_accept_reruns_same_install_with_accept_flag(app, tmp_path):
    w = data_status.DataStatus(status_path=str(_write(tmp_path, SAMPLE)))
    w.resize(800, 480)
    calls = _stub_run(w)
    _drive_to_busy(w, calls)
    first = calls[2][0]
    _refuse_with_notice(w, calls)
    w.notice_panel.btn_accept.click()
    assert w.notice_panel is None and w.mode == "busy"
    assert calls[3][0] == first + ["--accept-notice"]        # same selection, accepted
    calls[3][1](0, "  water-na  installed 2026q2r4\n")
    assert w.mode == "status" and "complete" in w.message.lower()
    assert w.picker is None and w.btn_update.isEnabled()


def test_notice_decline_installs_nothing(app, tmp_path):
    w = data_status.DataStatus(status_path=str(_write(tmp_path, SAMPLE)))
    w.resize(800, 480)
    calls = _stub_run(w)
    _drive_to_busy(w, calls)
    _refuse_with_notice(w, calls)
    w.notice_panel.btn_decline.click()
    assert len(calls) == 3                                   # no re-run
    assert w.mode == "status" and w.notice_panel is None and w.picker is None
    assert "nothing was installed" in w.message
    assert w.btn_update.isEnabled()


def test_exit_3_without_notice_text_is_a_plain_failure(app, tmp_path):
    """No notice to show (an older updater, a lost line): never offer an Accept
    for text the user has not seen."""
    w = data_status.DataStatus(status_path=str(_write(tmp_path, SAMPLE)))
    w.resize(800, 480)
    calls = _stub_run(w)
    _drive_to_busy(w, calls)
    calls[2][1](data_status.NOTICE_RC, "")
    assert w.mode == "status" and w.notice_panel is None
    assert "problems" in w.message


def test_notice_from_an_earlier_run_does_not_leak(app, tmp_path):
    w = data_status.DataStatus(status_path=str(_write(tmp_path, SAMPLE)))
    w.resize(800, 480)
    calls = _stub_run(w)
    _drive_to_busy(w, calls)
    _refuse_with_notice(w, calls)
    w.notice_panel.btn_accept.click()
    calls[3][1](data_status.NOTICE_RC, "")                   # re-run refused, no event
    assert w.mode == "status" and w.notice_panel is None


def test_notice_panel_follows_resize(app, tmp_path):
    w = data_status.DataStatus(status_path=str(_write(tmp_path, SAMPLE)))
    w.resize(800, 480)
    calls = _stub_run(w)
    _drive_to_busy(w, calls)
    _refuse_with_notice(w, calls)
    w.show()                       # Qt defers resize events for hidden widgets
    w.resize(1024, 600)
    app.processEvents()
    assert w.notice_panel.geometry() == w.rect()
    w.hide()


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


# --- Panel-change cue (CERT17; makerplane-data docs/panel_change_cue.md) ---

HASH = "9f2c4b7a01de" + "5" * 52
NEWER = "a1b2c3d4e5f6" + "6" * 52


def _pending(h=HASH, trigger="boot", **extra):
    block = {"pending": True, "config_hash": h, "config_version": 8,
             "changed": "2026-11-12T14:03:22Z", "trigger": trigger,
             "acknowledged": None}
    block.update(extra)
    return dict(SAMPLE, panel_change=block)


_CLEAR = {"pending": False, "config_hash": None, "config_version": None,
          "changed": None, "trigger": None, "acknowledged": None}


def _banner_shown(w):
    """The banner is up iff the Acknowledge button is (it is only shown
    with a pending change) and the paint path draws it."""
    return not w.btn_ack.isHidden()


def _amber_pixels_in_banner(w):
    img = w.grab().toImage()
    r = w._banner_rect
    n = 0
    for x in range(int(r.left()) + 2, int(r.right()) - 2, 4):
        for y in (int(r.top()), int(r.bottom()) - 1):
            c = img.pixelColor(x, y)
            # Amber hue (red well above blue), blended over whatever the
            # offscreen palette paints behind the widget.
            if c.red() > 200 and c.red() - c.blue() > 100:
                n += 1
    return n


def test_panel_change_banner_shown_when_pending(app, tmp_path):
    w = data_status.DataStatus(status_path=str(_write(tmp_path, _pending())))
    w.resize(800, 480)
    w.show()
    assert _banner_shown(w)
    assert w.btn_ack.isEnabled()
    assert _amber_pixels_in_banner(w) > 20          # amber border painted
    title, body = data_status.panel_change_text(w.status["panel_change"])
    assert title == "PANEL CHANGED AT BOOT"
    assert body == ("Config v8 installed 2026-11-12 14:03Z, hash 9f2c4b7a01de. "
                    "Check every instrument shows the right source before flight.")
    assert w.btn_continue.isVisible()               # Continue stays available


@pytest.mark.parametrize("doc", [
    SAMPLE,                                          # key absent
    dict(SAMPLE, panel_change=_CLEAR),               # pending false
    dict(SAMPLE, panel_change={"pending": "yes"}),   # not literally true
    dict(SAMPLE, panel_change=None),
    dict(SAMPLE, panel_change=[1, 2]),
], ids=["absent", "false", "truthy-string", "null", "not-a-dict"])
def test_panel_change_banner_hidden_when_not_pending(app, tmp_path, doc):
    w = data_status.DataStatus(status_path=str(_write(tmp_path, doc)))
    w.resize(800, 480)
    w.show()
    assert not _banner_shown(w)
    assert _amber_pixels_in_banner(w) == 0
    assert data_status.panel_change(w.status) is None


def test_panel_change_missing_file_no_banner(app, tmp_path):
    w = data_status.DataStatus(status_path=str(tmp_path / "nope.json"))
    w.resize(800, 480)
    w.show()
    assert not _banner_shown(w) and not w.grab().isNull()


def test_panel_change_shown_even_when_status_not_ok(app, tmp_path):
    # config-pull writes {"ok": false} with no packs when status.json did not
    # exist yet; the pack list reads unknown but the cue still shows.
    doc = {"ok": False, "packs": [], "panel_change": _pending()["panel_change"]}
    w = data_status.DataStatus(status_path=str(_write(tmp_path, doc)))
    w.resize(800, 480)
    w.show()
    assert _banner_shown(w) and _amber_pixels_in_banner(w) > 20


def test_panel_change_manual_trigger_title(app):
    t, _ = data_status.panel_change_text(_pending(trigger="manual")["panel_change"])
    assert t == "PANEL CHANGED"


def test_panel_change_without_hash_cannot_acknowledge(app, tmp_path):
    w = data_status.DataStatus(status_path=str(_write(tmp_path, _pending(h=None))))
    w.resize(800, 480)
    w.show()
    calls = _stub_run(w)
    assert _banner_shown(w) and not w.btn_ack.isEnabled()
    w._on_ack()
    assert calls == []


def test_acknowledge_runs_panel_ack_with_displayed_hash(app, tmp_path):
    p = _write(tmp_path, _pending())
    w = data_status.DataStatus(status_path=str(p))
    w.resize(800, 480)
    w.show()
    calls = _stub_run(w)
    w.btn_ack.click()
    assert calls[0][0] == ["panel-ack", "--yes", "--hash", HASH, "--json"]
    # The 12 digits on the banner are the prefix of the hash acknowledged.
    _, body = data_status.panel_change_text(w.status["panel_change"])
    assert f"hash {calls[0][0][3][:12]}." in body
    assert not w.btn_ack.isEnabled()                # no double submit
    p.write_text(json.dumps(dict(SAMPLE, panel_change=_CLEAR)))   # panel-ack rewrote it
    calls[0][1](0, json.dumps(_CLEAR))
    assert not _banner_shown(w)
    assert w.message == "Panel change acknowledged."


def test_acknowledge_exit_2_shows_the_newer_change(app, tmp_path):
    p = _write(tmp_path, _pending())
    w = data_status.DataStatus(status_path=str(p))
    w.resize(800, 480)
    w.show()
    calls = _stub_run(w)
    w._on_ack()
    p.write_text(json.dumps(_pending(h=NEWER)))     # a later pull landed
    calls[0][1](2, "")
    assert _banner_shown(w) and w.btn_ack.isEnabled()
    assert "newer panel change" in w.message
    w._on_ack()
    assert calls[1][0] == ["panel-ack", "--yes", "--hash", NEWER, "--json"]


def test_acknowledge_exit_2_same_change_is_not_recorded(app, tmp_path):
    w = data_status.DataStatus(status_path=str(_write(tmp_path, _pending())))
    w.resize(800, 480)
    w.show()
    calls = _stub_run(w)
    w._on_ack()
    calls[0][1](2, "")
    assert _banner_shown(w) and w.btn_ack.isEnabled()
    assert w.message.startswith("Couldn't record")


def test_acknowledge_updater_missing_keeps_banner(app, tmp_path):
    w = data_status.DataStatus(status_path=str(_write(tmp_path, _pending())),
                               update_command=str(tmp_path / "no-such-updater"))
    w.resize(800, 480)
    w.show()
    w._on_ack()
    for _ in range(50):
        app.processEvents()
        if w._proc is None:
            break
        import time; time.sleep(0.02)
    assert w._proc is None and _banner_shown(w) and w.btn_ack.isEnabled()


def test_ack_hidden_while_picker_open(app, tmp_path):
    w = data_status.DataStatus(status_path=str(_write(tmp_path, _pending())))
    w.resize(800, 480)
    w.show()
    calls = _stub_run(w)
    w._on_update()
    calls[0][1](0, json.dumps({"network": True, "usb": []}))
    calls[1][1](0, json.dumps(CATALOG))
    assert w.mode == "picker" and w.btn_ack.isHidden()


# --- Pack list fits above the buttons (bench look, AER-5481) ---

def _many_packs(n=12):
    return [{"id": f"p{i}", "name": f"Pack {i}", "status": "current",
             "severity": "amber" if i == n - 1 else "none", "detail": "2611"}
            for i in range(n)]


@pytest.mark.parametrize("size", [(800, 480), (1024, 600), (1920, 1080)])
@pytest.mark.parametrize("pending", [True, False], ids=["banner", "no-banner"])
def test_long_pack_list_ends_above_the_buttons(app, tmp_path, size, pending):
    # The bench's status.json has 12 packs; under the banner the last five
    # used to paint behind Continue/About/Update, an expired one included.
    doc = dict(SAMPLE, packs=_many_packs())
    if pending:
        doc = dict(doc, panel_change=_pending()["panel_change"])
    w = data_status.DataStatus(status_path=str(_write(tmp_path, doc)))
    w.resize(*size)
    w.show()
    w.grab()
    top, bottom = w._pack_span
    assert bottom <= w.btn_continue.y()
    assert (bottom - top) / 12 > 0                    # every row has room
    if pending:
        assert top >= w._banner_rect.bottom()


def test_long_pack_list_ends_above_the_message(app, tmp_path):
    doc = dict(SAMPLE, packs=_many_packs(), panel_change=_pending()["panel_change"])
    w = data_status.DataStatus(status_path=str(_write(tmp_path, doc)))
    w.resize(800, 480)
    w.show()
    w.message = "Panel change acknowledged."
    w.grab()
    assert w._pack_span[1] <= 480 * 0.74


def test_short_pack_list_keeps_full_row_height(app, tmp_path):
    w = data_status.DataStatus(status_path=str(_write(tmp_path, SAMPLE)))
    w.resize(800, 480)
    w.show()
    w.grab()
    top, bottom = w._pack_span
    assert bottom - top == 2 * w.row_h


# --- PFD DATA flag lights for a pending panel change (Bill, AER-5481) ---

def _flag_pixels(a):
    """Count amber pixels the DATA flag painted."""
    img = a.grab().toImage()
    n = 0
    for x in range(img.width()):
        for y in range(img.height()):
            c = img.pixelColor(x, y)
            if c.red() > 200 and c.red() - c.blue() > 100:
                n += 1
    return n


_CURRENT = {"ok": True, "packs": [{"name": "Airports", "severity": "none"}]}


def test_annunciation_amber_for_pending_panel_change(app, tmp_path):
    doc = dict(_CURRENT, panel_change=_pending()["panel_change"])
    a = data_status.DataAnnunciation(status_path=str(_write(tmp_path, doc)))
    a.resize(120, 40)
    assert data_status.worst_severity(a.status) == "none"      # packs current
    assert data_status.annunciation_severity(a.status) == "amber"
    assert _flag_pixels(a) > 20


def test_annunciation_amber_for_panel_change_when_status_not_ok(app, tmp_path):
    # config-pull's own status.json: ok false, no packs, cue pending.
    doc = {"ok": False, "packs": [], "panel_change": _pending()["panel_change"]}
    a = data_status.DataAnnunciation(status_path=str(_write(tmp_path, doc)))
    a.resize(120, 40)
    assert data_status.annunciation_severity(a.status) == "amber"
    assert _flag_pixels(a) > 20


@pytest.mark.parametrize("block", [None, _CLEAR, {"pending": "yes"}],
                         ids=["absent", "acknowledged", "truthy-string"])
def test_annunciation_hidden_without_pending_panel_change(app, tmp_path, block):
    doc = dict(_CURRENT) if block is None else dict(_CURRENT, panel_change=block)
    a = data_status.DataAnnunciation(status_path=str(_write(tmp_path, doc)))
    a.resize(120, 40)
    assert data_status.annunciation_severity(a.status) == "none"
    assert _flag_pixels(a) == 0


def test_annunciation_severity_falls_back_to_packs(app):
    assert data_status.annunciation_severity(None) == "none"
    assert data_status.annunciation_severity(SAMPLE) == "amber"
    soon = {"ok": True, "packs": [{"severity": "white"}]}
    assert data_status.annunciation_severity(soon) == "white"
