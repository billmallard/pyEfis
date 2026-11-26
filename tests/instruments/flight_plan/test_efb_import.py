#  SPDX-License-Identifier: GPL-2.0-or-later
"""EFB4b (AER-6706): a flight plan imported from ForeFlight is offered on
the FPL page, and only the pilot's Accept makes it the route.

fix-gateway's ``fpl_exchange`` plugin writes an uploaded ``.fpl`` to the
pending-import block (``FPLIMP*``, fix-gateway ``doc/flightplan_keys.md``,
"Pending import"): every point, then ``FPLIMPCOUNT`` and ``FPLIMPNAME``,
then ``FPLIMPSEQ`` last. A plan is pending while ``FPLIMPSEQ > 0`` and
``FPLIMPDONE`` differs from it. On Accept the editor commits the points as
any edit (route block, ``FPLSEQ``); on Reject it does not; either way it
then writes ``FPLIMPDONE = FPLIMPSEQ``. The plugin is played by hand here.
"""

import pytest
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtTest import QTest

from pyefis.flightplan import fixbridge
from pyefis.flightplan import model as fp_model
from pyefis.instruments import flight_plan
from tests.instruments.flight_plan import test_flight_plan as base
from tests.instruments.flight_plan import test_refused_commit as refused

# The first points of fix-gateway's tests/plugins/fpl_exchange/data/
# foreflight/ksba_kpmd.fpl (Bill's iPad export), plus a Garmin user
# waypoint longer than an FPLfID holds.
IMPORT = [
    ("KSBA", 34.426192, -119.841493, 1),
    ("FLOUT", 34.257589, -119.953203, 4),
    ("VTU", 34.115064, -119.0495, 2),
    ("BIGBEAR12", 34.2, -118.9, 5),
    ("KPMD", 34.629392, -118.084536, 1),
]


def _define_import_keys(fix):
    for key, dtype, blank in fixbridge.import_key_specs():
        base._define(fix, key, dtype, blank)


def _upload(fix, points=IMPORT, name="KSBA TO KPMD"):
    """What fpl_exchange writes for one accepted upload, in its order."""
    for n, (ident, lat, lon, typ) in enumerate(points, start=1):
        fix.db.set_value(f"FPLIMP{n}ID", ident)
        fix.db.set_value(f"FPLIMP{n}LAT", lat)
        fix.db.set_value(f"FPLIMP{n}LON", lon)
        fix.db.set_value(f"FPLIMP{n}TYPE", typ)
    fix.db.set_value("FPLIMPCOUNT", len(points))
    fix.db.set_value("FPLIMPNAME", name)
    seq = int(fix.db.get_item("FPLIMPSEQ").value) + 1
    fix.db.set_value("FPLIMPSEQ", seq)
    return seq


def _flying_with_imports(fix, qtbot):
    """A widget flying refused._flown(), on a gateway with the import block."""
    refused._bus(fix)
    _define_import_keys(fix)
    refused._other_display(fix).publish(refused._flown())
    refused._accept(fix)
    return refused._widget(qtbot)


def _value(fix, key):
    return fix.db.get_item(key).value


def _bus_route_ids(fix):
    return [_value(fix, f"FPL{n}ID") for n in range(1, int(_value(fix, "FPLCOUNT")) + 1)]


def _tap(w, action):
    """Tap the topmost target that runs *action* (the sheet's own Later
    button, not the tap-off-the-sheet catcher under it)."""
    w.grab()
    for (x, y, tw, th, cb) in reversed(w._tap_targets):
        if cb == action:
            QTest.mouseClick(w, Qt.MouseButton.LeftButton,
                             pos=QPoint(int(x + tw / 2), int(y + th / 2)))
            return
    raise AssertionError("no tap target for %r" % action)


def _open_review(w):
    _tap(w, w._open_offer)
    assert w._offer_open


# ---------------------------------------------------------------------------
# the bridge
# ---------------------------------------------------------------------------
def test_bridge_without_the_import_block_stays_available(fix):
    """A gateway that predates EFB4: the route bridge works, nothing is
    pending, and answering writes nothing."""
    base._define_all_fp1_keys(fix)
    bridge = fixbridge.FixBridge(fix)
    assert bridge.available is True
    assert bridge.imports_available is False
    assert bridge.import_seq() is None
    assert bridge.read_import() is None
    bridge.finish_import(3)  # must not raise


def test_bridge_reads_the_pending_import_and_answers_it(fix):
    base._define_all_fp1_keys(fix)
    _define_import_keys(fix)
    bridge = fixbridge.FixBridge(fix)
    assert bridge.import_seq() is None  # FPLIMPSEQ 0: nothing received
    seq = _upload(fix)
    pending = bridge.read_import()
    assert pending.seq == seq
    assert pending.name == "KSBA TO KPMD"
    assert [(p.id, p.type) for p in pending.points] == [
        ("KSBA", "airport"), ("FLOUT", "fix"), ("VTU", "vor"), ("BIGBEAR12", "user"),
        ("KPMD", "airport")]
    bridge.finish_import(seq)
    assert _value(fix, "FPLIMPDONE") == seq
    assert bridge.import_seq() is None


def test_import_to_plan_cuts_a_long_ident_and_keeps_it_as_the_name(fix):
    pending = fixbridge.PendingImport(seq=1, name="KSBA TO KPMD", points=[
        fixbridge.ImportPoint(id=i, lat=lat, lon=lon,
                              type=fixbridge.FPLTYPE_TO_TYPE[t])
        for i, lat, lon, t in IMPORT])
    plan = fixbridge.import_to_plan(pending)
    assert [wp.id for wp in plan.waypoints] == ["KSBA", "FLOUT", "VTU", "BIGBEA", "KPMD"]
    assert plan.waypoints[3].name == "BIGBEAR12"
    assert plan.waypoints[0].name == ""
    assert all(wp.pt == "TF" and wp.alt == "" and wp.spd == 0 for wp in plan.waypoints)
    assert [s.kind for s in plan.segments] == ["waypoint"] * 5
    assert plan.source == "efb"
    assert plan.name == "KSBA TO KPMD"


# ---------------------------------------------------------------------------
# the page: offered, never taken by itself
# ---------------------------------------------------------------------------
def test_pending_import_is_offered_and_does_not_replace_the_route(fix, qtbot, monkeypatch):
    w = _flying_with_imports(fix, qtbot)
    seq_before = int(_value(fix, "FPLSEQ"))
    _upload(fix)
    assert _value(fix, "FPLSEQ") == seq_before
    assert _bus_route_ids(fix) == ["ALPHA", "BRAVO", "CHARL"]
    assert [wp.id for wp in w._plan.waypoints] == ["ALPHA", "BRAVO", "CHARL"]
    assert w._offer is not None
    texts = refused._painted_text(w, monkeypatch)
    assert any("PLAN FROM EFB: KSBA TO KPMD" in t for t in texts)
    assert "Review" in texts


def test_review_sheet_lists_the_waypoints_and_the_note(fix, qtbot, monkeypatch):
    w = _flying_with_imports(fix, qtbot)
    _upload(fix)
    w.resize(480, 1000)  # tall enough to list all five without scrolling
    _open_review(w)
    texts = refused._painted_text(w, monkeypatch)
    for ident in ("KSBA", "FLOUT", "VTU", "BIGBEA (BIGBEAR12)", "KPMD"):
        assert ident in texts
    assert flight_plan.OFFER_EFB_NOTE in texts
    assert "ALTITUDES AND SPEEDS" in flight_plan.OFFER_EFB_NOTE
    for label in ("Accept", "Reject", "Later"):
        assert label in texts


def test_offer_shown_at_construction_when_already_pending(fix, qtbot):
    """A display started (or restarted) after the upload still offers it."""
    refused._bus(fix)
    _define_import_keys(fix)
    _upload(fix)
    w = refused._widget(qtbot)
    assert w._offer is not None and w._offer["plan"].count == len(IMPORT)


# ---------------------------------------------------------------------------
# Accept and Reject
# ---------------------------------------------------------------------------
def test_accept_commits_the_import_through_the_normal_path(fix, qtbot):
    w = _flying_with_imports(fix, qtbot)
    seq_before = int(_value(fix, "FPLSEQ"))
    imp_seq = _upload(fix)
    _open_review(w)
    _tap(w, w._offer_accept)
    assert _value(fix, "FPLSEQ") == seq_before + 1
    assert _bus_route_ids(fix) == ["KSBA", "FLOUT", "VTU", "BIGBEA", "KPMD"]
    assert _value(fix, "FPL4TYPE") == fixbridge.TYPE_TO_FPLTYPE["user"]
    assert _value(fix, "FPLNAME") == "KSBA TO KPMD"
    assert _value(fix, "FPLIMPDONE") == imp_seq
    assert w._offer is None and not w._offer_open
    # The engine loads it like any commit, and the page lists it.
    refused._accept(fix)
    assert [wp.id for wp in w._plan.waypoints] == ["KSBA", "FLOUT", "VTU", "BIGBEA", "KPMD"]


def test_reject_drops_the_import_and_keeps_the_route(fix, qtbot):
    w = _flying_with_imports(fix, qtbot)
    seq_before = int(_value(fix, "FPLSEQ"))
    imp_seq = _upload(fix)
    _open_review(w)
    _tap(w, w._offer_reject)
    assert _value(fix, "FPLSEQ") == seq_before
    assert _bus_route_ids(fix) == ["ALPHA", "BRAVO", "CHARL"]
    assert _value(fix, "FPLIMPDONE") == imp_seq
    assert w._offer is None
    assert [wp.id for wp in w._plan.waypoints] == ["ALPHA", "BRAVO", "CHARL"]


def test_later_keeps_the_offer_and_the_route(fix, qtbot):
    w = _flying_with_imports(fix, qtbot)
    seq_before = int(_value(fix, "FPLSEQ"))
    _upload(fix)
    _open_review(w)
    _tap(w, w._close_offer)
    assert not w._offer_open and w._offer is not None
    assert _value(fix, "FPLSEQ") == seq_before
    assert _value(fix, "FPLIMPDONE") == 0


def test_a_tap_off_the_sheet_does_not_reach_the_soft_keys(fix, qtbot):
    w = _flying_with_imports(fix, qtbot)
    _upload(fix)
    _open_review(w)
    w.grab()
    # The bottom-left corner, outside the sheet, over the footer soft keys.
    QTest.mouseClick(w, Qt.MouseButton.LeftButton, pos=QPoint(2, w.height() - 2))
    assert not w._offer_open and w._offer is not None
    assert not w._menu_open and w._page == "fpl"


# ---------------------------------------------------------------------------
# what changes under the pilot
# ---------------------------------------------------------------------------
def test_accept_refuses_points_that_changed_under_the_review(fix, qtbot):
    """The plugin overwrites the points before it bumps FPLIMPSEQ: a list
    that changed after the pilot read it is not committed."""
    w = _flying_with_imports(fix, qtbot)
    seq_before = int(_value(fix, "FPLSEQ"))
    _upload(fix)
    _open_review(w)
    fix.db.set_value("FPLIMP2ID", "ZZZZZ")  # a newer upload, half written
    _tap(w, w._offer_accept)
    assert _value(fix, "FPLSEQ") == seq_before
    assert _value(fix, "FPLIMPDONE") == 0
    assert w._message == "PLAN CHANGED - REVIEW AGAIN"
    assert not w._offer_open


def test_a_newer_upload_replaces_the_offer_and_closes_the_sheet(fix, qtbot):
    w = _flying_with_imports(fix, qtbot)
    _upload(fix)
    _open_review(w)
    second = _upload(fix, points=IMPORT[:2], name="KSBA TO FLOUT")
    assert w._offer["key"] == second
    assert w._offer["plan"].count == 2
    assert not w._offer_open


def test_an_answer_on_another_display_withdraws_the_offer(fix, qtbot):
    w = _flying_with_imports(fix, qtbot)
    imp_seq = _upload(fix)
    _open_review(w)
    refused._other_display(fix).finish_import(imp_seq)
    assert w._offer is None and not w._offer_open


def test_read_only_page_offers_but_cannot_accept(fix, qtbot, monkeypatch):
    """A demo kiosk (DEMO4): the strip is drawn, its button is not a tap."""
    w = _flying_with_imports(fix, qtbot)
    _upload(fix)
    monkeypatch.setattr(flight_plan.kiosk, "locked", lambda: True)
    w.grab()
    assert w._open_offer not in [t[4] for t in w._tap_targets]
    assert w._offer_accept not in [t[4] for t in w._tap_targets]
