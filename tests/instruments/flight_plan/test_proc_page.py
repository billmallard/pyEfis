#  SPDX-License-Identifier: GPL-2.0-or-later
"""The PROC page (PA7, billmallard/pyEfis#238, AER-1606): departure, arrival
and approach selection, loaded into the flight plan as a named block.

Every flow is driven twice where the issue asks for it: by touch (a mouse
press at a tap target, through ``mousePressEvent``) and by the encoder
alone (``enc_*``). Both press the same control: the encoder helper turns the
knob until its focus sits on the rect a finger would have pressed.

The procedures are KSBA's, decoded from the golden CIFP fixture
(``tests/flightplan/ksba_procedures.py``).
"""

from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtTest import QTest

from pyefis.flightplan import fixbridge
from pyefis.flightplan import model as fp_model
from pyefis.flightplan import proc_load
from pyefis.instruments import flight_plan
from tests.flightplan import ksba_procedures
from tests.instruments.flight_plan.test_segment_rows import _BLANK, _ENGINE, BEELINK, _define

KSBA = fp_model.Waypoint("KSBA", "airport", *ksba_procedures.KSBA)
RZS = fp_model.Waypoint("RZS", "vor", 34.50953, -119.77099)


@pytest.fixture()
def page(fix, qtbot, tmp_path):
    for key, dtype, blank in fixbridge.route_key_specs():
        _define(fix, key, dtype, blank)
    for key, dtype in _ENGINE.items():
        _define(fix, key, dtype, _BLANK[dtype])
    _define(fix, "FPLLDSEQ", "int", 0)
    fix.db.set_value("MAGVAR", -12.0)
    w = flight_plan.FlightPlan(None)
    qtbot.addWidget(w)
    w.parent = SimpleNamespace(parent=BEELINK)
    w.resize(649, 993)
    w.procedures_db_path = str(ksba_procedures.build(tmp_path / "procedures.sqlite"))
    w._plan = fp_model.FlightPlan(waypoints=[RZS.copy(), KSBA.copy()])
    w._commit()
    _engine_loads(w, fix)
    return w


def _engine_loads(w, fix):
    """Play the engine accepting the commit on the bus."""
    fix.db.set_value("FPLLDSEQ", int(fix.db.get_item("FPLSEQ").value))
    w._on_bridge_change()


def _targets(w):
    w.grab()
    return list(zip(w._tap_targets, w._tap_kinds))


def _rect_of(w, pick):
    """The ``(x, y, w, h)`` of the tap target *pick* chooses from the
    topmost layer's targets, given as ``[(x, y, w, h, callback, kind)]``."""
    layer = [(*t, k) for t, k in _targets(w)][w._enc_layer_start:]
    found = pick(layer)
    assert found is not None, "no such control on screen"
    return found[:4]


def _touch(w, rect):
    x, y, rw, rh = rect
    QTest.mouseClick(w, Qt.MouseButton.LeftButton, pos=QPointF(x + rw / 2, y + rh / 2).toPoint())


def _encoder_press(w, rect):
    """Turn the knob until it focuses *rect*, then push."""
    if not w._enc_active:
        w.enc_select()
    for _ in range(200):
        ring = w._enc_ring()
        if w._enc_focus is not None and 0 <= w._enc_focus < len(ring):
            r = ring[w._enc_focus][1]
            if (round(r.x()), round(r.y()), round(r.width()), round(r.height())) == tuple(
                    round(v) for v in rect):
                w.enc_clicked()
                return
        w.enc_changed(1)
    raise AssertionError(f"the encoder never reached {rect}")


def _by_callback(cb):
    return lambda layer: next((t for t in layer if t[4] == cb), None)


def _nth_row(n):
    return lambda layer: ([t for t in layer if t[5] == "row"] + [None] * (n + 1))[n]


def _tab(label_index):
    """The PROC tab strip's *label_index*-th tab (Departure, Arrival,
    Approach), by position: the first three targets after the X."""
    return lambda layer: layer[1 + label_index]


def _field(w, field):
    return _nth_row(w._proc_fields().index(field))


PRESSES = {"touch": _touch, "encoder": _encoder_press}


def _press(w, how, pick):
    PRESSES[how](w, _rect_of(w, pick))


# ---------------------------------------------------------------------------
# Getting there
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("how", ["touch", "encoder"])
def test_the_fpl_footer_opens_the_proc_page(page, how):
    _press(page, how, _by_callback(page._footer_proc))
    assert page._page == "proc"
    # The destination is the airport offered for an approach.
    assert page._proc["kind"] == "approach" and page._proc["airport"] == "KSBA"


def test_the_hmi_page_verb_opens_it(page):
    page._act_page("proc")
    assert page._page == "proc"


# ---------------------------------------------------------------------------
# Every selection, by touch and by the knob
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("how", ["touch", "encoder"])
def test_an_approach_is_selected_and_loaded(page, how):
    page._open_proc_page("approach")
    _press(page, how, _field(page, "proc"))
    assert page._proc_picker == "proc"
    _press(page, how, _nth_row(0))                     # ILS07, the only one
    assert proc_load.procedure_name(page._proc["proc"]) == "ILS07"
    _press(page, how, _field(page, "transition"))
    _press(page, how, _nth_row(2))                     # GOLET, GVO, VECTORS
    assert page._proc["transition"] == "VECTORS"
    _press(page, how, _by_callback(page._proc_load))
    assert page._page == "fpl"
    assert [(s.kind, s.ident) for s in page._plan.segments] == [
        ("waypoint", ""), ("approach", "ILS07.VECTORS"), ("missed", "ILS07"),
        ("waypoint", "")]


@pytest.mark.parametrize("how", ["touch", "encoder"])
def test_a_departure_is_selected_tab_runway_and_transition(page, how):
    page._plan = fp_model.FlightPlan(waypoints=[KSBA.copy(), RZS.copy()])
    page._open_proc_page("approach")
    _press(page, how, _tab(0))
    assert page._proc["kind"] == "departure" and page._proc["airport"] == "KSBA"
    _press(page, how, _field(page, "proc"))
    _press(page, how, _nth_row(0))                     # FLOUT5
    _press(page, how, _field(page, "runway"))
    _press(page, how, _nth_row(0))                     # RW07
    _press(page, how, _field(page, "transition"))
    _press(page, how, _nth_row(2))                     # GVO, RZS, VTU, NONE
    assert (page._proc["runway"], page._proc["transition"]) == ("RW07", "VTU")
    _press(page, how, _by_callback(page._proc_load))
    assert [(s.kind, s.ident) for s in page._plan.segments][:2] == [
        ("waypoint", ""), ("departure", "FLOUT5.RW07.VTU")]


@pytest.mark.parametrize("how", ["touch", "encoder"])
def test_an_arrival_is_selected_transition_then_runway(page, how):
    page._open_proc_page("approach")
    _press(page, how, _tab(1))
    assert page._proc_fields() == ["airport", "proc", "transition", "runway"]
    _press(page, how, _field(page, "proc"))
    _press(page, how, _nth_row(0))                     # PITBL2
    _press(page, how, _field(page, "transition"))
    _press(page, how, _nth_row(0))                     # HEC
    _press(page, how, _field(page, "runway"))
    _press(page, how, _nth_row(1))                     # RW25
    _press(page, how, _by_callback(page._proc_load))
    assert ("arrival", "PITBL2.HEC.RW25") in [(s.kind, s.ident) for s in page._plan.segments]


@pytest.mark.parametrize("how", ["touch", "encoder"])
def test_the_airport_is_picked_on_the_entry_page_and_comes_back(page, how):
    page._open_proc_page("approach")
    _press(page, how, _field(page, "airport"))
    assert page._page == "entry" and page._entry_type_filter == "Apt"
    # The FPL tab lists the plan's airports; pick KSBA from it.
    page._select_entry_tab("FPL")
    page._select_waypoint(KSBA)
    assert page._page == "proc" and page._proc["airport"] == "KSBA"
    page._proc_open_field("airport")
    page._entry_cancel()
    assert page._page == "proc"


def test_the_knob_backs_out_of_a_picker_then_the_page(page):
    page._open_proc_page("approach")
    page._proc_open_field("proc")
    page.enc_select()
    assert page.enc_long_clicked() is True
    assert page._proc_picker is None and page._page == "proc"
    assert page.enc_long_clicked() is True
    assert page._page == "fpl"


# ---------------------------------------------------------------------------
# Replace, remove, and what reaches the bus
# ---------------------------------------------------------------------------
def _load(w, kind, ident, transition, runway=None):
    w._open_proc_page(kind)
    proc = w._ensure_procedure_index().find(w._proc["airport"], proc_load.PACK_KIND[kind], ident)
    w._proc_pick("proc", proc)
    w._proc_pick("transition", transition)
    if runway:
        w._proc_pick("runway", runway)
    w._proc_load()


def test_the_load_reaches_the_bus_as_approach_and_missed_segments(page, fix):
    _load(page, "approach", "I07", "VECTORS")
    kinds = [int(fix.db.get_item(f"FPLS{k}KIND").value)
             for k in range(1, int(fix.db.get_item("FPLSEGCNT").value) + 1)]
    assert kinds == [0, 4, 5, 0]
    assert fix.db.get_item("FPLS2ID").value == "ILS07.VECTORS"
    assert fix.db.get_item("FPLDBCYC").value == "2609"


def test_loading_again_replaces_the_approach(page, fix):
    _load(page, "approach", "I07", "VECTORS")
    _engine_loads(page, fix)
    _load(page, "approach", "I07", "GVO")
    assert [s.ident for s in page._plan.segments if s.kind == "approach"] == ["ILS07.GVO"]
    assert [s.kind for s in page._plan.segments].count("missed") == 1


@pytest.mark.parametrize("how", ["touch", "encoder"])
def test_remove_on_the_proc_page_takes_the_whole_block(page, fix, how):
    _load(page, "approach", "I07", "VECTORS")
    _engine_loads(page, fix)
    page._open_proc_page("approach")
    _press(page, how, _by_callback(page._proc_remove))
    assert [s.kind for s in page._plan.segments] == ["waypoint", "waypoint"]
    assert int(fix.db.get_item("FPLSEGCNT").value) == 2


def test_the_segment_menu_selects_and_removes_the_procedure(page, fix):
    _load(page, "approach", "I07", "VECTORS")
    _engine_loads(page, fix)
    missed = [k for k, s in enumerate(page._plan.segments) if s.kind == "missed"][0]
    page._open_seg_menu(missed)
    page._seg_menu_select_procedure()
    assert page._page == "proc" and page._proc["kind"] == "approach"
    page._close_proc()
    page._open_seg_menu(missed)
    page._seg_menu_remove_procedure()
    assert [s.kind for s in page._plan.segments] == ["waypoint", "waypoint"]


def test_the_procedure_is_one_collapsed_row_on_the_fpl_page(page, fix):
    _load(page, "approach", "I07", "VECTORS")
    _engine_loads(page, fix)
    assert page._display_rows(None) == [("wpt", 0), ("seg", 1), ("seg", 2), ("wpt", 8)]
    # Flying to NAPPS (slot 4): the approach opens around the active leg.
    assert page._display_rows(3) == [("wpt", 0), ("seg", 1), ("fix", 2, "from"),
                                     ("fix", 3, "to"), ("fix", 4, "next"), ("seg", 2),
                                     ("wpt", 8)]
    # Flying to its first fix is inside it: the leg into HABUT is the
    # procedure's.
    assert page._segment_active(1, 1)


def test_a_leg_without_a_fix_offers_no_direct_to(page, fix):
    _load(page, "approach", "I07", "VECTORS")
    _engine_loads(page, fix)
    ca = [i for i, wp in enumerate(page._plan.waypoints) if wp.pt == "CA"][0]
    page._open_seg_fix_menu(ca)
    w = page
    w.grab()
    callbacks = [t[4] for t in w._tap_targets[w._enc_layer_start:]]
    assert w._seg_fix_activate_leg in callbacks
    assert w._seg_fix_direct_to not in callbacks and w._seg_fix_wpt_info not in callbacks


# ---------------------------------------------------------------------------
# Refusals: from the engine, and before it
# ---------------------------------------------------------------------------
def test_an_engine_refusal_says_why_on_the_page(page, fix):
    # The GOLET transition codes an FC leg; the engine refuses the route
    # whole and says so on FPLMSG (guardrail 1).
    _load(page, "approach", "I07", "GOLET")
    fix.db.set_value("FPLMSG", "UNSUPP FC LOBER")
    page._on_fplmsg()
    assert page._plan_refused()
    assert page._refusal_text() == "EDIT REFUSED: CAN'T FLY FC LEG AT LOBER"
    # The flown plan is back on the page, and the PROC page says it too.
    assert [s.kind for s in page._plan.segments] == ["waypoint", "waypoint"]
    page._open_proc_page("approach")
    page.grab()
    assert page._plan_refused()


def test_an_incomplete_selection_says_what_is_missing(page):
    page._open_proc_page("approach")
    page._proc_load()
    assert page._proc["message"] == "SELECT APPROACH"
    assert page._page == "proc"


def test_a_pilot_faf_is_named_instead_of_silently_moved(page, fix):
    page._plan.set_role(0, "faf")
    _load(page, "approach", "I07", "VECTORS")
    assert page._page == "proc"
    assert page._proc["message"] == "CLEAR THE FAF/MAP ON RZS BEFORE LOADING AN APPROACH"


def test_no_pack_says_so_instead_of_an_empty_list(page):
    page.procedures_db_path = ""
    page._open_proc_page("approach")
    page._proc_open_field("proc")
    assert page._proc_picker is None
    assert page._proc["message"] == "NO PROCEDURES DATABASE"


def test_the_hold_speed_option_sizes_a_timed_hold(page, fix):
    # KSBA ILS 07's missed approach holds at GOLET for one minute.
    page.hold_speed_kt = 120
    _load(page, "approach", "I07", "VECTORS")
    hm = [n for n in range(1, int(fix.db.get_item("FPLCOUNT").value) + 1)
          if fix.db.get_item(f"FPL{n}PT").value == "HM"]
    assert [fix.db.get_item(f"FPL{n}DST").value for n in hm] == [2.0]


# ---------------------------------------------------------------------------
# PA9: the approach's type and cycle, and an expired cycle (AER-1608)
# ---------------------------------------------------------------------------
from datetime import date
from unittest.mock import MagicMock

from pyefis.flightplan import airac

# The fixture pack is AIRAC 2609: current 2026-09-03 until 2026-10-01.
DURING_2609 = date(2026, 9, 10)
AFTER_2609 = date(2026, 10, 1)


def _header_texts(w):
    p = MagicMock()
    w._paint_header(p, w.width(), 80, True)
    return [(c.args[-1], p.setPen.call_args_list[i].args[0].color().name())
            for i, c in enumerate(p.drawText.call_args_list)
            if i < len(p.setPen.call_args_list)]


@pytest.mark.parametrize("how", ["touch", "encoder"])
def test_an_expired_pack_loads_the_approach_and_says_so(page, fix, how, monkeypatch):
    """Guardrail 3 (Bill 2026-09-18): expired procedure data is annunciated,
    never refused. Driven through the page as a pilot would, the approach
    loads, reaches the bus, and the header names the expired cycle."""
    monkeypatch.setattr(airac, "utc_today", lambda: AFTER_2609)
    page._open_proc_page("approach")
    _press(page, how, _field(page, "proc"))
    _press(page, how, _nth_row(0))                     # ILS07
    _press(page, how, _field(page, "transition"))
    _press(page, how, _nth_row(0))                     # GOLET
    _press(page, how, _by_callback(page._proc_load))
    assert page._page == "fpl"
    assert page._proc is None or not page._proc.get("message")
    assert [(s.kind, s.ident) for s in page._plan.segments][1:3] == [
        ("approach", "ILS07.GOLET"), ("missed", "ILS07")]
    assert fix.db.get_item("FPLS2ID").value == "ILS07.GOLET"
    assert fix.db.get_item("FPLAPRTYPE").value == "ILS"
    assert fix.db.get_item("FPLDBCYC").value == "2609"
    assert page._procedure_text() == ("ILS  AIRAC 2609 EXPIRED", "#ffb000")
    assert ("ILS  AIRAC 2609 EXPIRED", "#ffb000") in _header_texts(page)


def test_a_current_pack_shows_type_and_cycle(page, fix, monkeypatch):
    monkeypatch.setattr(airac, "utc_today", lambda: DURING_2609)
    _load(page, "approach", "I07", "VECTORS")
    assert page._procedure_text() == ("ILS  AIRAC 2609", "#9a9a9a")
    assert ("ILS  AIRAC 2609", "#9a9a9a") in _header_texts(page)


def test_a_departure_alone_shows_its_cycle_and_no_approach_type(page, fix, monkeypatch):
    monkeypatch.setattr(airac, "utc_today", lambda: AFTER_2609)
    page._plan = fp_model.FlightPlan(waypoints=[KSBA.copy(), RZS.copy()])
    _load(page, "departure", "FLOUT5", "GVO", runway="RW07")
    assert [s.kind for s in page._plan.segments][1] == "departure"
    assert fix.db.get_item("FPLAPRTYPE").value == ""
    assert page._procedure_text() == ("AIRAC 2609 EXPIRED", "#ffb000")


def test_no_procedure_no_cycle_on_the_header(page):
    assert page._procedure_text() is None


def test_the_preview_and_the_fixes_sheet_name_an_expired_cycle(page, monkeypatch):
    monkeypatch.setattr(airac, "utc_today", lambda: AFTER_2609)
    assert page._cycle_text("2609") == ("AIRAC 2609 EXPIRED", "#ffb000")
    monkeypatch.setattr(airac, "utc_today", lambda: DURING_2609)
    assert page._cycle_text("2609") == ("AIRAC 2609", "#9a9a9a")
