#  SPDX-License-Identifier: GPL-2.0-or-later
"""RTE1b (AER-6785): a route string typed or pasted on the FPL page's menu is
expanded from the panel's own navdata (``route_string.expand``) and offered
on EFB4b's Accept/Reject sheet; only Accept makes it the route.

The packs are the real cycle-2611 rows ``tests/flightplan/test_route_string.py``
uses, and the two routes are Bill's bench plans from there.
"""

import pytest
from PyQt6.QtCore import QEvent, QPoint, QRectF, Qt
from PyQt6.QtGui import QGuiApplication, QImage, QKeyEvent, QKeySequence, QPainter
from PyQt6.QtTest import QTest

from pyefis.instruments import flight_plan
from tests.flightplan import test_route_string as rs_tests
from tests.instruments.flight_plan import test_efb_import as efb
from tests.instruments.flight_plan import test_refused_commit as refused


@pytest.fixture(scope="module")
def packs(tmp_path_factory):
    return rs_tests._build_all(tmp_path_factory.mktemp("rte1b_packs"))


def _with_packs(w, packs, tmp_path):
    w.nasr_db_path = str(packs["airports"])
    w.navaid_db_path = str(packs["navaids"])
    w.procedures_db_path = str(packs["procedures"])
    w.flightplan_dir = str(tmp_path)
    assert w._ensure_waypoint_index().wait_ready(timeout=5)
    return w


@pytest.fixture
def page(fix, qtbot, packs, tmp_path):
    """A page flying refused._flown(), with the route-string packs."""
    w = _with_packs(refused._flying(fix, qtbot), packs, tmp_path)
    w.resize(480, 800)
    yield w
    w._ensure_airway_graph().close()


def _value(fix, key):
    return fix.db.get_item(key).value


def _bus_ids(fix):
    return efb._bus_route_ids(fix)


def _ids(plan):
    return [wp.id for wp in plan.waypoints]


class _Recorder(QPainter):
    """Every drawText's rect and text, so a test can press what it reads."""
    drawn = []

    def drawText(self, *args):
        if isinstance(args[0], QRectF):
            _Recorder.drawn.append((args[0], args[-1]))
        return super().drawText(*args)


def _painted(w, monkeypatch):
    _Recorder.drawn = []
    monkeypatch.setattr(flight_plan, "QPainter", _Recorder)
    w._tap_targets = []
    w._paint(QImage(w.width(), w.height(), QImage.Format.Format_RGB32))
    monkeypatch.undo()
    return list(_Recorder.drawn)


def _texts(w, monkeypatch):
    return [t for _r, t in _painted(w, monkeypatch)]


def _press(w, label, monkeypatch):
    """Tap the label as the pilot reads it: the topmost tap target under
    the centre of where it was painted."""
    drawn = _painted(w, monkeypatch)
    hits = [r for r, t in drawn if t == label]
    assert hits, f"{label!r} is not on the page: {[t for _r, t in drawn]}"
    c = hits[-1].center()
    w.grab()
    for (x, y, tw, th, _cb) in reversed(w._tap_targets):
        if x <= c.x() <= x + tw and y <= c.y() <= y + th:
            QTest.mouseClick(w, Qt.MouseButton.LeftButton, pos=QPoint(int(c.x()), int(c.y())))
            return
    raise AssertionError(f"{label!r} is painted but takes no press")


def _type_on_keypad(w, text, monkeypatch):
    for ch in text:
        _press(w, "SPACE" if ch == " " else ch, monkeypatch)


def _enter_route(w, text, monkeypatch):
    """Menu, Route, the route on the on-screen keypad, ENT."""
    _press(w, "MENU", monkeypatch)
    _press(w, "Route", monkeypatch)
    assert w._modal is not None and w._modal["title"] == "ENTER ROUTE"
    _type_on_keypad(w, text, monkeypatch)
    _press(w, "ENT", monkeypatch)


# ---------------------------------------------------------------------------
# entry
# ---------------------------------------------------------------------------
def test_menu_route_opens_an_entry_with_space_and_dot(page, monkeypatch):
    _press(page, "MENU", monkeypatch)
    _press(page, "Route", monkeypatch)
    texts = _texts(page, monkeypatch)
    assert "ENTER ROUTE" in texts
    assert "SPACE" in texts and "." in texts


@pytest.mark.parametrize("text, fpl", [(rs_tests.KSBA_KPMD, rs_tests.KSBA_KPMD_FPL),
                                       (rs_tests.KSBA_KPHX, rs_tests.KSBA_KPHX_FPL)],
                         ids=["KSBA-KPMD", "KSBA-KPHX"])
def test_typed_route_is_offered_and_does_not_replace_the_route(page, fix, monkeypatch,
                                                                text, fpl):
    seq_before = int(_value(fix, "FPLSEQ"))
    _enter_route(page, text, monkeypatch)
    assert page._offer is not None and page._offer_open
    assert _ids(page._offer["plan"]) == [i for i, _t, _la, _lo in fpl]
    # Pending, never the active route.
    assert _value(fix, "FPLSEQ") == seq_before
    assert _bus_ids(fix) == ["ALPHA", "BRAVO", "CHARL"]
    assert _ids(page._plan) == ["ALPHA", "BRAVO", "CHARL"]
    texts = _texts(page, monkeypatch)
    assert f"ROUTE: {fpl[0][0]}-{fpl[-1][0]}" in texts
    assert flight_plan.ROUTE_NOTE in texts
    for label in ("Accept", "Reject", "Later"):
        assert label in texts


def test_physical_keyboard_types_spaces_and_pastes(page, monkeypatch):
    page.keyboard = True
    page._menu_route()
    QTest.keyClicks(page, "ksba vtu")
    assert page._modal["value"] == "KSBA VTU"
    QGuiApplication.clipboard().setText(" v485 ohigh\nkpmd ")
    QTest.keySequence(page, QKeySequence(QKeySequence.StandardKey.Paste))
    assert page._modal["value"] == "KSBA VTU V485 OHIGH KPMD"
    QTest.keyClick(page, Qt.Key.Key_Return)
    assert _ids(page._offer["plan"])[:3] == ["KSBA", "VTU", "HENER"]


def test_space_is_not_taken_by_an_ident_modal(page):
    """Only the route's entry takes a space: an ident or name modal does
    not, as before."""
    page.keyboard = True
    page._modal_open("NAME", "", False, 10, lambda v: None)
    page.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Space,
                                 Qt.KeyboardModifier.NoModifier, " "))
    assert page._modal["value"] == ""


def test_refusal_reopens_the_entry_with_the_text_and_the_reason(page, fix, monkeypatch):
    _enter_route(page, "KSBA XYZZY KPMD", monkeypatch)
    assert page._offer is None
    assert page._modal["value"] == "KSBA XYZZY KPMD"
    assert "NOT FOUND: XYZZY" in _texts(page, monkeypatch)
    # Fixing the one token is enough.
    for _ in "XYZZY KPMD":
        _press(page, "BKSP", monkeypatch)
    _type_on_keypad(page, "VTU KPMD", monkeypatch)
    _press(page, "ENT", monkeypatch)
    assert _ids(page._offer["plan"]) == ["KSBA", "VTU", "KPMD"]


# ---------------------------------------------------------------------------
# runway prompt
# ---------------------------------------------------------------------------
def test_sid_needing_a_runway_asks_and_expands_again(page, monkeypatch):
    page._menu_route()
    page._modal["value"] = "KSBA FLOUT5 VTU V27 GVO KSMX"
    _press(page, "ENT", monkeypatch)
    assert page._offer is None
    texts = _texts(page, monkeypatch)
    assert "KSBA FLOUT5 RUNWAY" in texts
    for rw in ("RW07", "RW15B", "RW25"):
        assert rw in texts
    _press(page, "RW25", monkeypatch)
    plan = page._offer["plan"]
    assert ("departure", "FLOUT5.RW25.VTU") in [(s.kind, s.ident) for s in plan.segments]


def test_runway_prompt_cancel_goes_back_to_the_entry(page, monkeypatch):
    page._menu_route()
    page._modal["value"] = "KSBA FLOUT5 VTU V27 GVO KSMX"
    _press(page, "ENT", monkeypatch)
    _press(page, "Cancel", monkeypatch)
    assert page._route_runway is None and page._offer is None
    assert page._modal["value"] == "KSBA FLOUT5 VTU V27 GVO KSMX"


# ---------------------------------------------------------------------------
# duplicate chooser
# ---------------------------------------------------------------------------
def test_ident_with_two_places_uses_the_duplicate_chooser(page, monkeypatch):
    # AA is two real NDBs, Kenie (Minnesota) and Cedar (Georgia).
    page._menu_route()
    page._modal["value"] = "KSBA AA KPMD"
    _press(page, "ENT", monkeypatch)
    assert page._offer is None
    assert page._entry_message == "DUPLICATE FOUND"
    assert sorted(w.name for w in page._entry_dupe_choices) == ["Cedar", "Kenie"]
    labels = [t for t in _texts(page, monkeypatch) if t.startswith("AA ")]
    assert len(labels) == 2
    kenie = next(t for t in labels if "Kenie" in t)
    _press(page, kenie, monkeypatch)
    plan = page._offer["plan"]
    assert _ids(plan) == ["KSBA", "AA", "KPMD"]
    assert plan.waypoints[1].name == "Kenie"


def test_duplicate_chooser_cancel_goes_back_to_the_entry(page, monkeypatch):
    page._menu_route()
    page._modal["value"] = "KSBA AA KPMD"
    _press(page, "ENT", monkeypatch)
    _press(page, "Cancel", monkeypatch)
    assert page._entry_dupe_choices is None and page._offer is None
    assert page._modal["value"] == "KSBA AA KPMD"
    assert "TWO PLACES NAMED: AA" in _texts(page, monkeypatch)


# ---------------------------------------------------------------------------
# Accept and Reject
# ---------------------------------------------------------------------------
def test_accept_commits_through_publish_and_the_engine_loads_it(page, fix, monkeypatch):
    seq_before = int(_value(fix, "FPLSEQ"))
    _enter_route(page, rs_tests.KSBA_KPMD, monkeypatch)
    expected = _ids(page._offer["plan"])
    _press(page, "Accept", monkeypatch)
    assert _value(fix, "FPLSEQ") == seq_before + 1
    assert _bus_ids(fix) == expected
    assert page._offer is None and not page._offer_open
    # The airways go across as segments, not as loose fixes.
    assert int(_value(fix, "FPLSEGCNT")) > 1
    refused._accept(fix)
    assert _ids(page._plan) == expected


def test_reject_drops_the_route_and_keeps_the_flown_one(page, fix, monkeypatch):
    seq_before = int(_value(fix, "FPLSEQ"))
    _enter_route(page, rs_tests.KSBA_KPMD, monkeypatch)
    _press(page, "Reject", monkeypatch)
    assert page._offer is None
    assert _value(fix, "FPLSEQ") == seq_before
    assert _bus_ids(fix) == ["ALPHA", "BRAVO", "CHARL"]
    assert _ids(page._plan) == ["ALPHA", "BRAVO", "CHARL"]


def test_an_efb_upload_waits_behind_a_typed_route(fix, qtbot, packs, tmp_path, monkeypatch):
    """One sheet, one offer at a time: a plan staged on the bus while the
    pilot reviews a typed route waits, and is offered once it is answered."""
    w = _with_packs(efb._flying_with_imports(fix, qtbot), packs, tmp_path)
    w.resize(480, 800)
    try:
        _enter_route(w, "KSBA VTU KPMD", monkeypatch)
        efb._upload(fix)
        assert w._offer["key"][0] == "route"
        _press(w, "Reject", monkeypatch)
        assert w._offer is not None and w._offer["staged"]
    finally:
        w._ensure_airway_graph().close()
