#  SPDX-License-Identifier: GPL-2.0-or-later
"""Hold at present position (HOLDFIX2, AER-6322): the FPL menu's "Hold at
PPOS" opens the HOLDFIX1 hold editor on a user waypoint ``PPOS`` at the
aircraft, inbound on the present track. Insert puts ``PPOS`` and its
``HM`` slot in front of the active leg's TO fix and, once the engine has
loaded that route, sends ``ACT`` for the hold slot. No usable GPS position
is refused with a message.

The inserted pair is also loaded on the fix-gateway engine itself and the
hold slot activated, as in the spike's scenario S3
(``makerplane/briefs/hold_at_any_fix_spike.md``): a direct entry at once.

Route: AAA (34N 120W), BBB (a VOR 50 nm east), CCC. The aircraft is at
``AC``, between AAA and BBB, tracking ``TRACK_MAG``.
"""

from types import SimpleNamespace

import pytest

from pyefis.flightplan import fixbridge, geo, hold
from pyefis.flightplan import model as fp_model
from pyefis.instruments import flight_plan
from tests.instruments.flight_plan.test_hold_editor import (
    A, B, C, BEELINK, MAGVAR, _BLANK, _ENGINE, _define, _engine_route, _flying,
    _menu_labels, _set, _slot)
from tests.instruments.test_map_hold_entry import engine_mod  # noqa: F401 (fixture)

# The aircraft: between AAA and BBB, a little north of the leg.
AC = (34.05, -119.6)
TRACK_MAG = 95.0


def _page(fix, qtbot, monkeypatch, loaded_seq):
    """The FPL page on AAA, BBB, CCC with the aircraft at ``AC`` tracking
    ``TRACK_MAG``. *loaded_seq*: the gateway publishes ``FPLLDSEQ`` (the
    engine's answer to a commit, played by hand here); False is a gateway
    from before the key."""
    for key, dtype, blank in fixbridge.route_key_specs():
        _define(fix, key, dtype, blank)
    for key, dtype in _ENGINE.items():
        _define(fix, key, dtype, _BLANK[dtype])
    if loaded_seq:
        _define(fix, "FPLLDSEQ", "int", 0)
    for key in ("LAT", "LONG", "ALT", "TRACK", "TRACKM"):
        _define(fix, key, "float", 0.0)
    _set(fix, "MAGVAR", MAGVAR)
    _set(fix, "LAT", AC[0])
    _set(fix, "LONG", AC[1])
    _set(fix, "ALT", 6000.0)
    _set(fix, "TRACKM", TRACK_MAG)
    _set(fix, "TRACK", TRACK_MAG - MAGVAR)
    w = flight_plan.FlightPlan(None)
    qtbot.addWidget(w)
    w.parent = SimpleNamespace(parent=BEELINK)
    w.resize(649, 993)
    w._plan = fp_model.FlightPlan(name="TEST", segments=[
        fp_model.waypoint_segment(A), fp_model.waypoint_segment(B),
        fp_model.waypoint_segment(C)])
    w._commit()
    if loaded_seq:
        _accept(fix)
    sent = []
    monkeypatch.setattr(w._bridge, "command",
                        lambda verb, arg=None, on_ack=None: sent.append((verb, arg)))
    w.sent = sent
    w.fixdb = fix
    return w


def _accept(fix):
    fix.db.set_value("FPLLDSEQ", int(fix.db.get_item("FPLSEQ").value))


@pytest.fixture()
def page(fix, qtbot, monkeypatch):
    return _page(fix, qtbot, monkeypatch, loaded_seq=False)


@pytest.fixture()
def page_ldseq(fix, qtbot, monkeypatch):
    return _page(fix, qtbot, monkeypatch, loaded_seq=True)


def _ids(fix):
    return [_slot(fix, n, "ID") for n in range(1, fix.db.get_item("FPLCOUNT").value + 1)]


# -- the pure parts ---------------------------------------------------------------

def test_the_ppos_fix_is_a_user_waypoint_at_the_aircraft():
    wp = hold.present_position_waypoint(*AC)
    assert (wp.id, wp.type, wp.lat, wp.lon, wp.pt) == ("PPOS", "user", AC[0], AC[1], "TF")


def test_the_pair_goes_in_front_of_the_active_to_fix():
    plan = fp_model.FlightPlan(name="T", waypoints=[A, B, C])
    assert hold.ppos_insert_index(plan, None) == 0     # nothing active
    assert hold.ppos_insert_index(plan, 0) == 0        # off-route direct-to
    assert hold.ppos_insert_index(plan, 1) == 0        # to AAA from the aircraft
    assert hold.ppos_insert_index(plan, 2) == 1        # AAA -> BBB
    assert hold.ppos_insert_index(plan, 3) == 2
    assert hold.ppos_insert_index(plan, 4) == 0        # past the end: nothing active


def test_in_a_hold_the_pair_goes_after_the_hold_slot():
    plan = fp_model.FlightPlan(name="T", waypoints=[A, B, C])
    plan.insert_hold(1, hold.hold_waypoint(B, 270.0, "R", 4.0))
    assert hold.ppos_insert_index(plan, 3) == 3        # flying the HM at BBB


def test_is_ppos_pair_wants_this_fix_and_its_hold():
    at = hold.present_position_waypoint(*AC)
    plan = fp_model.FlightPlan(name="T", waypoints=[A, at, B])
    plan.insert_hold(1, hold.hold_waypoint(at, 95.0, "R", 2.0))
    assert hold.is_ppos_pair(plan, 1, at)
    assert not hold.is_ppos_pair(plan, 0, at)
    assert not hold.is_ppos_pair(plan, 2, at)
    assert not hold.is_ppos_pair(plan, 3, at)          # no slot after it
    moved = hold.present_position_waypoint(AC[0] + 0.01, AC[1])
    assert not hold.is_ppos_pair(plan, 1, moved)       # an older PPOS elsewhere


# -- the menu and the editor's defaults ----------------------------------------------

def test_the_fpl_menu_offers_hold_at_ppos(page):
    page._menu_open = True
    assert "Hold at PPOS" in _menu_labels(page)
    page._menu_hold_ppos()
    assert page._menu_open is False
    assert page._hold_edit["fix"] == "PPOS" and page._hold_edit["ppos"] is True
    page.grab()


def test_no_gps_position_is_refused_with_a_message(page):
    page.fixdb.db.get_item("LAT").old = True
    page._menu_open = True
    page._menu_hold_ppos()
    assert page._hold_edit is None
    assert page._message == "NO GPS POSITION"
    assert page.fixdb.db.get_item("FPLCOUNT").value == 3
    assert page.sent == []
    page.grab()


def test_the_editor_defaults_to_holding_on_the_present_track(page):
    page._open_ppos_hold_editor()
    e = page._hold_edit
    assert (e["ref"], e["course"]) == ("inbound", TRACK_MAG)
    assert e["direction"] == "W"                       # the pattern behind the aircraft
    assert (e["turn"], e["leg"], e["unit"]) == ("R", 1.0, "MIN")
    text, _ = page._hold_summary()
    assert text == "INBOUND 095°  R TURNS  1 MIN = 1.5 NM"


def test_the_track_is_true_track_plus_magvar_without_trackm(page):
    page.fixdb.db.get_item("TRACKM").fail = True
    page._open_ppos_hold_editor()
    assert page._hold_edit["course"] == pytest.approx(TRACK_MAG)


def test_no_track_holds_north(page):
    page.fixdb.db.get_item("TRACKM").fail = True
    page.fixdb.db.get_item("TRACK").old = True
    page._open_ppos_hold_editor()
    e = page._hold_edit
    assert (e["direction"], e["ref"], e["course"]) == ("N", "radial", 0.0)


def test_leg_time_follows_the_altitude(page):
    _set(page.fixdb, "ALT", 16000.0)
    page._open_ppos_hold_editor()
    assert page._hold_edit["leg"] == 1.5


# -- Insert -------------------------------------------------------------------------

def test_with_nothing_active_the_pair_starts_the_plan_and_is_activated(page):
    page._open_ppos_hold_editor()
    page._hold_insert()
    fix = page.fixdb
    assert page._hold_edit is None and page._message == "HOLD AT PPOS"
    assert _ids(fix) == ["PPOS", "PPOS", "AAA", "BBB", "CCC"]
    assert (_slot(fix, 1, "LAT"), _slot(fix, 1, "LON")) == AC
    assert _slot(fix, 1, "TYPE") == fixbridge.TYPE_TO_FPLTYPE["user"]
    assert (_slot(fix, 2, "PT"), _slot(fix, 2, "CRS"), _slot(fix, 2, "TURN"),
            _slot(fix, 2, "DST")) == ("HM", TRACK_MAG, "R", 1.5)
    assert (_slot(fix, 2, "LAT"), _slot(fix, 2, "LON")) == AC
    assert page.sent == [("ACT", 2)]


def test_in_flight_the_pair_goes_before_the_to_fix(page):
    _flying(page, "ENR", 2)                            # AAA -> BBB
    page._open_ppos_hold_editor()
    page._hold_insert()
    assert _ids(page.fixdb) == ["AAA", "PPOS", "PPOS", "BBB", "CCC"]
    assert _slot(page.fixdb, 3, "PT") == "HM"
    assert page.sent == [("ACT", 3)]


def test_a_new_hold_while_holding_goes_after_the_hold_flown(page):
    page._open_hold_editor(1)                          # HOLDFIX1 hold at BBB
    page._hold_insert()
    _flying(page, "HOLD", 3)
    page._open_ppos_hold_editor()
    page._hold_insert()
    assert _ids(page.fixdb) == ["AAA", "BBB", "BBB", "PPOS", "PPOS", "CCC"]
    assert page.sent == [("ACT", 5)]


def test_the_fix_is_where_the_aircraft_is_at_insert(page):
    page._open_ppos_hold_editor()
    _set(page.fixdb, "LAT", AC[0] + 0.02)              # a mile on, editing
    page._hold_insert()
    assert _slot(page.fixdb, 1, "LAT") == AC[0] + 0.02
    assert _slot(page.fixdb, 2, "LAT") == AC[0] + 0.02


def test_position_lost_before_insert_inserts_nothing(page):
    page._open_ppos_hold_editor()
    page.fixdb.db.get_item("LONG").fail = True
    assert page._hold_summary() == ("NO GPS POSITION", "#ff4040")
    page.grab()
    page._hold_insert()
    assert page._hold_edit["message"] == "NO GPS POSITION"
    assert page.fixdb.db.get_item("FPLCOUNT").value == 3
    assert page.sent == []


def test_a_wrong_side_entry_inserts_nothing(page):
    page._open_ppos_hold_editor()
    page._hold_set_direction("E")                      # typed course stays 095
    page._hold_edit_course()
    page._modal["value"] = "095"
    page._modal_enter()
    page._hold_insert()
    assert page._hold_edit["message"] == "INBOUND 095° IS NOT E OF THE FIX"
    assert page.fixdb.db.get_item("FPLCOUNT").value == 3
    assert page.sent == []


def test_a_draft_gives_way_to_the_flown_plan(page):
    page._draft = fp_model.FlightPlan(name="DRAFT", waypoints=[C])
    page._flown_plan = fp_model.FlightPlan(name="TEST", waypoints=[A, B, C])
    page._draft_open = True
    page._plan = fp_model.FlightPlan(name="DRAFT", waypoints=[C])
    page._open_ppos_hold_editor()
    assert page._draft_open is False
    page._hold_insert()
    assert _ids(page.fixdb) == ["PPOS", "PPOS", "AAA", "BBB", "CCC"]


# -- ACT waits for the engine to load the route ---------------------------------------

def test_act_waits_for_the_engine_to_load_the_route(page_ldseq):
    page = page_ldseq
    page._open_ppos_hold_editor()
    page._hold_insert()
    assert _ids(page.fixdb) == ["PPOS", "PPOS", "AAA", "BBB", "CCC"]
    assert page.sent == []                             # FPLLDSEQ still the old route
    _accept(page.fixdb)
    assert page.sent == [("ACT", 2)]
    _accept(page.fixdb)                                # a repeat answer sends nothing more
    page._on_bridge_change("FPLLDSEQ")
    assert page.sent == [("ACT", 2)]


def test_an_engine_write_during_the_commit_keeps_the_act_waiting(page_ldseq, monkeypatch):
    # The engine writes its outputs every cycle, from the gateway's thread.
    # One landing while the commit is half on the bus, with the route
    # check due, reads the old route as loaded. That must not use up the ACT.
    page = page_ldseq
    real = page._bridge._set

    def _set_key(key, value):
        real(key, value)
        if key == "FPLCOUNT":                          # the slots are in, FPLSEQ is not
            page._route_checked_at = float("-inf")
            page._on_bridge_change("WPDIS")
    monkeypatch.setattr(page._bridge, "_set", _set_key)
    page._open_ppos_hold_editor()
    page._hold_insert()
    assert page.sent == []
    _accept(page.fixdb)
    assert page.sent == [("ACT", 2)]


def test_a_refused_route_is_never_activated(page_ldseq):
    page = page_ldseq
    page._open_ppos_hold_editor()
    page._hold_insert()
    page.fixdb.db.set_value("FPLMSG", "ROUTECAP")      # the engine refuses it
    assert page._plan_refused() and page._pending_hold_act is None
    # The pilot fixes the draft and commits again: no stale ACT 2 on it.
    fixbridge.FixBridge(page.fixdb).publish(fp_model.FlightPlan(name="X", waypoints=[A, B]))
    _accept(page.fixdb)
    assert page.sent == []


def test_another_route_loaded_first_is_not_activated(page_ldseq):
    page = page_ldseq
    page._open_ppos_hold_editor()
    page._hold_insert()
    # Another display's commit lands and is loaded instead of this one.
    fixbridge.FixBridge(page.fixdb).publish(fp_model.FlightPlan(name="X", waypoints=[A, B, C]))
    _accept(page.fixdb)
    assert page.sent == []
    assert page._pending_hold_act is None


def test_an_act_refusal_is_shown(page):
    page._on_hold_act_ack(7, False, "")
    assert page._message == "HOLD NOT ACTIVATED"


# -- the engine flies it (spike S3) ---------------------------------------------------

def test_the_inserted_pair_loads_on_the_engine_and_activates_into_the_hold(page, engine_mod):
    _flying(page, "ENR", 2)
    page._open_ppos_hold_editor()
    page._hold_insert()
    assert page.sent == [("ACT", 3)]
    wps, segs = _engine_route(engine_mod, page.fixdb)
    e = engine_mod.Engine()
    e.load_route(wps, "TEST", 1, segs)
    ack, _ = e.handle_command("1 ACT 3", (AC[0], AC[1], True))
    assert ack == 1
    trk_true = TRACK_MAG - MAGVAR
    out, t = {}, 1000.0
    for step in range(3):
        lat, lon = geo.destination_point(AC[0], AC[1], trk_true, 0.05 * step)
        out = e.update(lat, lon, 120.0, MAGVAR, True, None, None, t)
        t += 1.5
    assert out["act_leg"] == 3
    assert out.get("phase") == "HOLD"
    # On the inbound course, at the fix: a direct entry, turning outbound.
    assert e._hold_entry == engine_mod.HOLD_ENTRY_DIRECT
    assert e._leg_phase == engine_mod.LEGPHASE_TURN_OUT
