#  SPDX-License-Identifier: GPL-2.0-or-later
"""G61 (pyEfis #380): the FPL page never lists a route the engine refused
as the loaded plan.

After a refused commit the slots on the bus still hold the refused route;
the engine keeps flying the one it had, leaves ``FPLLDSEQ`` at that
route's ``FPLSEQ`` and writes the reason to ``FPLMSG`` (fix-gateway
flightplan plugin, PA8). Bill's ruling (2026-11-07): the page shows the
plan the engine is flying, with the reason shown prominently, and keeps the
refused edit as a draft the pilot can reopen and correct.

The engine is played by hand here: ``FPLLDSEQ`` written to the new seq is
an accept, ``FPLMSG`` with ``FPLLDSEQ`` left alone is a refusal.
"""

import pytest
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtTest import QTest

from pyefis.flightplan import fixbridge
from pyefis.flightplan import model as fp_model
from pyefis.instruments import flight_plan
from tests.instruments.flight_plan import test_flight_plan as base


def _flown():
    return fp_model.FlightPlan(name="FLOWN", waypoints=[
        fp_model.Waypoint(id=ident, type="fix", lat=34.0 + n * 0.1, lon=-119.0)
        for n, ident in enumerate(("ALPHA", "BRAVO", "CHARL"))])


def _refused():
    """The issue's repro: a route with an RF leg and no turn direction,
    which the engine answers with BADTURN."""
    return fp_model.FlightPlan(name="REFUSED", waypoints=[
        fp_model.Waypoint(id="XRAYA", type="fix", lat=35.0, lon=-118.0),
        fp_model.Waypoint(id="XRAYB", type="fix", lat=35.1, lon=-118.0, pt="RF",
                          ctr_lat=35.05, ctr_lon=-118.05, turn=""),
    ])


def _append(w, ident, lat, lon):
    w._plan.insert_after(w._plan.count - 1,
                         fp_model.Waypoint(id=ident, type="fix", lat=lat, lon=lon))


def _ids(plan):
    return [wp.id for wp in plan.waypoints]


def _bus(fix, loaded=True):
    """The FP1 keys plus FPLLDSEQ (*loaded*; False leaves it undefined, a
    gateway that predates the key)."""
    base._define_all_fp1_keys(fix)
    if loaded:
        base._define(fix, "FPLLDSEQ", "int", 0)


def _accept(fix):
    fix.db.set_value("FPLLDSEQ", int(fix.db.get_item("FPLSEQ").value))


def _refuse(fix, reason="BADTURN"):
    fix.db.set_value("FPLMSG", reason)


def _other_display(fix):
    """A second writer of the route block (another display, or the moving
    map's banner): its commit reaches this widget through the bus."""
    return fixbridge.FixBridge(fix)


def _widget(qtbot):
    w = flight_plan.FlightPlan(None)
    qtbot.addWidget(w)
    w.resize(480, 480)
    return w


def _flying(fix, qtbot):
    """A widget whose bus holds _flown(), loaded by the engine."""
    _bus(fix)
    _other_display(fix).publish(_flown())
    _accept(fix)
    return _widget(qtbot)


class _TextRecorder(QPainter):
    texts = []

    def drawText(self, *args):
        _TextRecorder.texts.append(args[-1])
        return super().drawText(*args)


def _painted_text(w, monkeypatch):
    _TextRecorder.texts = []
    monkeypatch.setattr(flight_plan, "QPainter", _TextRecorder)
    img = QImage(w.width(), w.height(), QImage.Format.Format_RGB32)
    w._paint(img)
    return list(_TextRecorder.texts)


def _tap_on(w, action):
    w.grab()
    for (x, y, tw, th, cb) in w._tap_targets:
        if cb == action:
            QTest.mouseClick(w, Qt.MouseButton.LeftButton, pos=QPoint(int(x + tw / 2),
                                                                     int(y + th / 2)))
            return
    raise AssertionError("no tap target for %r" % action)


# ---------------------------------------------------------------------------
# the defect
# ---------------------------------------------------------------------------
def test_refused_commit_is_not_listed_as_the_loaded_plan(fix, qtbot, monkeypatch):
    """The issue's repro: FPLLDSEQ 1, then FPLSEQ 2 with an RF and no turn
    direction, refused with BADTURN. The page keeps listing the flown plan
    and says the edit was refused, with the engine's reason."""
    w = _flying(fix, qtbot)
    assert _ids(w._plan) == ["ALPHA", "BRAVO", "CHARL"]

    _other_display(fix).publish(_refused())
    _refuse(fix, "BADTURN")
    assert int(fix.db.get_item("FPLSEQ").value) == 2
    assert int(fix.db.get_item("FPLLDSEQ").value) == 1

    assert _ids(w._plan) == ["ALPHA", "BRAVO", "CHARL"]
    texts = _painted_text(w, monkeypatch)
    assert "EDIT REFUSED: BADTURN" in texts
    assert not any(t.startswith("XRAY") for t in texts)
    assert any(t.startswith("ALPHA") for t in texts)


def test_a_refused_route_already_on_the_bus_at_start_is_never_listed(fix, qtbot,
                                                                     monkeypatch):
    """The widget comes up after the refusal (a restart, a second screen):
    it has never seen the flown plan, so it lists nothing rather than the
    refused slots -- and still says why."""
    _bus(fix)
    other = _other_display(fix)
    other.publish(_flown())
    _accept(fix)
    other.publish(_refused())
    _refuse(fix, "BADTURN")

    w = _widget(qtbot)
    assert _ids(w._plan) == []
    assert _ids(w._draft) == ["XRAYA", "XRAYB"]
    texts = _painted_text(w, monkeypatch)
    assert "EDIT REFUSED: BADTURN" in texts
    assert not any(t.startswith("XRAY") for t in texts)


# ---------------------------------------------------------------------------
# the pilot's own edit
# ---------------------------------------------------------------------------
def test_own_edit_stays_on_screen_until_the_engine_answers(fix, qtbot):
    """No flicker on every edit: an edit the engine has not answered yet is
    neither reverted nor flagged."""
    w = _flying(fix, qtbot)
    _append(w, "DELTA", 34.5, -119.0)
    w._commit()
    assert _ids(w._plan) == ["ALPHA", "BRAVO", "CHARL", "DELTA"]
    assert w._refusal is None
    _accept(fix)
    assert _ids(w._plan) == ["ALPHA", "BRAVO", "CHARL", "DELTA"]
    assert w._refusal is None
    assert _ids(w._flown_plan) == ["ALPHA", "BRAVO", "CHARL", "DELTA"]


def test_own_refused_edit_reverts_and_is_kept_as_a_draft(fix, qtbot, monkeypatch):
    w = _flying(fix, qtbot)
    _append(w, "DELTA", 34.5, -119.0)
    w._commit()
    _refuse(fix, "BADLEG 4")

    assert _ids(w._plan) == ["ALPHA", "BRAVO", "CHARL"]
    assert _ids(w._draft) == ["ALPHA", "BRAVO", "CHARL", "DELTA"]
    assert "EDIT REFUSED: BADLEG 4" in _painted_text(w, monkeypatch)


def test_draft_reopens_for_correction_and_a_load_ends_it(fix, qtbot, monkeypatch):
    w = _flying(fix, qtbot)
    _other_display(fix).publish(_refused())
    _refuse(fix, "BADTURN")

    _tap_on(w, w._reopen_draft)
    assert w._draft_open
    assert _ids(w._plan) == ["XRAYA", "XRAYB"]
    texts = _painted_text(w, monkeypatch)
    assert "DRAFT - NOT LOADED: BADTURN" in texts
    assert "Flown plan" in texts
    monkeypatch.undo()

    # A correction the engine refuses again keeps the pilot in the draft.
    _append(w, "XRAYC", 35.2, -118.0)
    w._commit()
    _refuse(fix, "BADTURN")
    assert w._draft_open
    assert _ids(w._plan) == ["XRAYA", "XRAYB", "XRAYC"]

    # One it loads is the flight plan: the strip and the draft are gone.
    w._plan.remove(1)
    w._commit()
    _accept(fix)
    assert not w._draft_open and w._refusal is None and w._draft is None
    assert _ids(w._plan) == ["XRAYA", "XRAYC"]
    texts = _painted_text(w, monkeypatch)
    assert not any(t.startswith(("EDIT REFUSED", "DRAFT")) for t in texts)


def test_flown_plan_button_leaves_the_draft_and_keeps_it(fix, qtbot):
    w = _flying(fix, qtbot)
    _other_display(fix).publish(_refused())
    _refuse(fix, "BADTURN")
    _tap_on(w, w._reopen_draft)
    _tap_on(w, w._show_flown_plan)
    assert not w._draft_open
    assert _ids(w._plan) == ["ALPHA", "BRAVO", "CHARL"]
    assert _ids(w._draft) == ["XRAYA", "XRAYB"]


def test_draft_has_no_active_leg(fix, qtbot):
    """FPLACTLEG counts legs of the flown plan; on the draft it would
    highlight a row the engine is not flying."""
    w = _flying(fix, qtbot)
    fix.db.set_value("FPLACTLEG", 2)
    assert w._active_index() == 1
    _other_display(fix).publish(_refused())
    _refuse(fix, "BADTURN")
    assert w._active_index() == 1
    w._reopen_draft()
    assert w._active_index() is None


# ---------------------------------------------------------------------------
# edges
# ---------------------------------------------------------------------------
def test_an_unanswered_commit_is_treated_as_refused(fix, qtbot):
    w = _flying(fix, qtbot)
    w.commit_answer_ms = 50
    _append(w, "DELTA", 34.5, -119.0)
    w._commit()
    qtbot.waitUntil(lambda: w._refusal is not None, timeout=2000)
    assert w._refusal[1] == "NO ENGINE ANSWER"
    assert _ids(w._plan) == ["ALPHA", "BRAVO", "CHARL"]
    # A late load still wins.
    _accept(fix)
    assert w._refusal is None
    assert _ids(w._plan) == ["ALPHA", "BRAVO", "CHARL", "DELTA"]


def test_fplmsg_with_no_commit_waiting_changes_nothing(fix, qtbot):
    """FPLMSG also answers commands (a rejected DTO); with the route loaded
    it is not a refusal of the route."""
    w = _flying(fix, qtbot)
    _refuse(fix, "NOWPT")
    assert w._refusal is None
    assert _ids(w._plan) == ["ALPHA", "BRAVO", "CHARL"]


def test_gateway_without_fplldseq_keeps_the_pre_key_behaviour(fix, qtbot):
    _bus(fix, loaded=False)
    w = _widget(qtbot)
    _other_display(fix).publish(_refused())
    _refuse(fix, "BADTURN")
    assert _ids(w._plan) == ["XRAYA", "XRAYB"]
    assert w._refusal is None
