#  SPDX-License-Identifier: GPL-2.0-or-later
"""Hold... on any fix (HOLDFIX1, AER-6210): the row and segment-fix menus
open a hold editor in clearance form, Insert puts an ``HM`` slot after the
fix on the bus, and the FPL menu's suspend item reads "Exit hold" and sends
RESUME while an ``HM`` hold is flown.

The inserted route is also loaded on the fix-gateway engine itself, from
the checkout CI fetches (``FIXGW_FLIGHTPLAN_ENGINE``; locally
``FIX_GATEWAY_SRC``), and flown into the hold.

Route: AAA (34N 120W), BBB (a VOR 50 nm east), CCC. The hold is at BBB.
"""

from types import SimpleNamespace

import pytest

from pyefis.flightplan import fixbridge, geo, hold
from pyefis.flightplan import model as fp_model
from pyefis.instruments import flight_plan
from tests.instruments.test_map_hold_entry import engine_mod  # noqa: F401 (fixture)

BEELINK = SimpleNamespace(screenWidth=1920, screenHeight=1080, screenDiagonalInches=21.5)
MAGVAR = 12.0

_BOUNDS = {"float": (-1e9, 1e9), "int": (-1_000_000, 1_000_000),
           "bool": (None, None), "str": (None, None)}
_ENGINE = {
    "FPLSTATE": "int", "FPLACTLEG": "int", "FPLPHASE": "str", "FPLAPR": "int",
    "FPLINTEG": "bool", "CDISCALE": "float", "FPLCRS": "float", "FPLXTK": "float",
    "FPLCDI": "float", "FPLTF": "int", "FPLFRLAT": "float", "FPLFRLON": "float",
    "WPNAME": "str", "WPLAT": "float", "WPLON": "float", "WPFROM": "str",
    "WPNEXT": "str", "WPDIS": "float", "WPETE": "int", "FPLREMDIS": "float",
    "FPLREMETE": "int", "FPLALERT": "bool", "GPSSRC": "int",
    "FPLACTSEG": "int", "FPLSEGREM": "float", "MAGVAR": "float",
}
_BLANK = {"int": 0, "float": 0.0, "bool": False, "str": ""}

A = fp_model.Waypoint(id="AAA", type="fix", lat=34.0, lon=-120.0)
B = fp_model.Waypoint(id="BBB", type="vor", lat=34.0, lon=-119.0)
C = fp_model.Waypoint(id="CCC", type="fix", lat=34.5, lon=-118.5)
D = fp_model.Waypoint(id="DDD", type="fix", lat=35.0, lon=-118.0)


def _define(fix, key, dtype, value):
    mn, mx = _BOUNDS[dtype]
    fix.db.define_item(key, key, dtype, mn, mx, "", 0, "")
    fix.db.set_value(key, value)
    item = fix.db.get_item(key)
    item.bad = item.fail = False


def _set(fix, key, value):
    fix.db.set_value(key, value)
    item = fix.db.get_item(key)
    item.fail = item.old = item.bad = False


@pytest.fixture()
def page(fix, qtbot, monkeypatch):
    for key, dtype, blank in fixbridge.route_key_specs():
        _define(fix, key, dtype, blank)
    for key, dtype in _ENGINE.items():
        _define(fix, key, dtype, _BLANK[dtype])
    for key in ("LAT", "LONG", "ALT"):
        _define(fix, key, "float", 0.0)
    _set(fix, "MAGVAR", MAGVAR)
    _set(fix, "LAT", 34.0)
    _set(fix, "LONG", -120.3)
    _set(fix, "ALT", 6000.0)
    w = flight_plan.FlightPlan(None)
    qtbot.addWidget(w)
    w.parent = SimpleNamespace(parent=BEELINK)
    w.resize(649, 993)
    w._plan = fp_model.FlightPlan(name="TEST", segments=[
        fp_model.waypoint_segment(A), fp_model.waypoint_segment(B),
        fp_model.waypoint_segment(C)])
    w._commit()
    sent = []
    monkeypatch.setattr(w._bridge, "command",
                        lambda verb, arg=None, on_ack=None: sent.append((verb, arg)))
    w.sent = sent
    w.fixdb = fix
    return w


def _menu_labels(w):
    """The labels a menu paints, read off its tap targets' callbacks."""
    w._tap_targets, w._tap_kinds = [], []
    captured = []
    real = w._paint_menu_list

    def spy(p, ww, hh, items, *a, **k):
        captured.extend(label for label, _ in items)
        return real(p, ww, hh, items, *a, **k)
    w._paint_menu_list = spy
    try:
        w.grab()
    finally:
        del w._paint_menu_list
    return captured


def _slot(fix, n, name):
    return fix.db.get_item(fixbridge._slot_key(n, name)).value


# -- the menus --------------------------------------------------------------

def test_row_menu_offers_hold_on_a_fix_but_not_on_a_hold(page):
    page._open_row_menu(1)
    assert "Hold..." in _menu_labels(page)
    page._row_menu_hold()
    page._hold_insert()
    page._open_row_menu(1)
    assert "Hold..." not in _menu_labels(page)   # BBB already holds
    page._open_row_menu(2)
    assert "Hold..." not in _menu_labels(page)   # the hold row itself
    page._close_row_menu()


def test_segment_fix_menu_offers_hold_and_remove_hold(page):
    page._plan = fp_model.FlightPlan(name="T", segments=[
        fp_model.Segment(kind="airway", ident="V27", legs=[A, B, C, D])])
    page._commit()
    page._open_seg_fix_menu(1)
    labels = _menu_labels(page)
    assert "Hold..." in labels and "Remove Hold" not in labels
    page._seg_fix_hold()
    assert page._hold_edit["fix"] == "BBB"
    page._hold_insert()
    assert [w.id for w in page._plan.segments[0].legs] == ["AAA", "BBB", "BBB", "CCC", "DDD"]
    page._open_seg_fix_menu(2)
    labels = _menu_labels(page)
    assert "Remove Hold" in labels and "Hold..." not in labels
    page._seg_fix_remove_hold()
    assert [w.id for w in page._plan.segments[0].legs] == ["AAA", "BBB", "CCC", "DDD"]
    assert page.fixdb.db.get_item("FPLCOUNT").value == 4


# -- the editor's defaults --------------------------------------------------

def test_editor_defaults_to_holding_as_you_arrive(page):
    page._open_row_menu(1)
    page._row_menu_hold()
    e = page._hold_edit
    back = geo.initial_bearing(B.lat, B.lon, A.lat, A.lon)
    arrive_mag = (back + 180.0 + MAGVAR) % 360.0
    assert e["ref"] == "inbound" and e["course"] == pytest.approx(arrive_mag)
    # Arriving eastbound (about 102 mag), the pattern lies to the west.
    assert e["direction"] == hold.nearest_direction(arrive_mag + 180.0) == "W"
    assert (e["turn"], e["leg"], e["unit"]) == ("R", 1.0, "MIN")
    page.grab()


def test_leg_time_default_follows_the_altitude(page):
    _set(page.fixdb, "ALT", 14000.0)
    page._open_hold_editor(1)
    assert page._hold_edit["leg"] == 1.0
    _set(page.fixdb, "ALT", 16500.0)
    page._open_hold_editor(1)
    assert page._hold_edit["leg"] == 1.5
    page.fixdb.db.get_item("ALT").fail = True
    page._open_hold_editor(1)
    assert page._hold_edit["leg"] == 1.0


def test_no_leg_into_the_first_fix_and_no_position_holds_north(page):
    page.fixdb.db.get_item("LAT").fail = True
    page._open_hold_editor(0)
    e = page._hold_edit
    assert (e["direction"], e["ref"], e["course"]) == ("N", "radial", 0.0)


# -- entering the clearance ---------------------------------------------------

def test_the_briefs_clearance_inserts_its_hm_slot(page):
    # "Hold southeast of BBB on the 130 radial, left turns, 10-mile legs."
    page._open_hold_editor(1)
    page._hold_set_direction("SE")
    page._hold_toggle_ref()                       # inbound -> radial
    assert page._hold_edit["ref"] == "radial"
    page._hold_edit_course()
    assert page._modal["title"] == "RADIAL"
    page._modal["value"] = "130"
    page._modal_enter()
    page._hold_set_turn("L")
    page._hold_toggle_unit()                      # MIN -> NM
    page._hold_edit_leg()
    page._modal["value"] = "10"
    page._modal_enter()
    text, _ = page._hold_summary()
    assert text == "INBOUND 310°  L TURNS  10 NM"
    page.grab()
    page._hold_insert()
    fix = page.fixdb
    assert page._hold_edit is None
    assert fix.db.get_item("FPLCOUNT").value == 4
    assert [_slot(fix, n, "ID") for n in range(1, 5)] == ["AAA", "BBB", "BBB", "CCC"]
    assert (_slot(fix, 3, "PT"), _slot(fix, 3, "CRS"), _slot(fix, 3, "TURN"),
            _slot(fix, 3, "DST")) == ("HM", 310.0, "L", 10.0)
    assert (_slot(fix, 3, "LAT"), _slot(fix, 3, "LON")) == (B.lat, B.lon)
    assert _slot(fix, 3, "FLAGS") == 0
    assert _slot(fix, 3, "SGI") == 3     # its own waypoint row


def test_minutes_go_on_the_bus_as_distance_at_the_hold_speed(page):
    page.hold_speed_kt = 120.0
    _set(page.fixdb, "ALT", 16000.0)
    page._open_hold_editor(1)
    page._hold_insert()
    assert _slot(page.fixdb, 3, "DST") == hold.minutes_to_nm(1.5, 120.0) == 3.0


def test_the_inbound_course_on_the_bus_is_magnetic(page):
    page._open_hold_editor(1)
    arrive_mag = page._hold_edit["course"]
    page._hold_insert()
    assert _slot(page.fixdb, 3, "CRS") == pytest.approx(round(arrive_mag, 1))


def test_unit_and_reference_toggles_keep_the_hold(page):
    page._open_hold_editor(1)
    page._hold_toggle_unit()
    assert (page._hold_edit["unit"], page._hold_edit["leg"]) == ("NM", 1.5)
    page._hold_toggle_unit()
    assert (page._hold_edit["unit"], page._hold_edit["leg"]) == ("MIN", 1.0)
    before = page._hold_resolve()[0].crs
    page._hold_toggle_ref()
    assert page._hold_resolve()[0].crs == pytest.approx(before)


def test_a_new_direction_moves_an_untyped_course_but_not_a_typed_one(page):
    page._open_hold_editor(1)
    page._hold_set_direction("N")
    assert page._hold_resolve()[0].crs == pytest.approx(180.0)
    page._hold_edit_course()
    page._modal["value"] = "170"
    page._modal_enter()                            # inbound 170: north side
    page._hold_set_direction("E")
    wp, error = page._hold_resolve()
    assert wp is None and error == "INBOUND 170° IS NOT E OF THE FIX"


def test_a_wrong_side_or_bad_entry_inserts_nothing(page):
    page._open_hold_editor(1)
    page._hold_set_direction("N")
    page._hold_edit_course()
    page._modal["value"] = "090"
    page._modal_enter()
    page._hold_insert()
    assert page._hold_edit["message"] == "INBOUND 090° IS NOT N OF THE FIX"
    assert page.fixdb.db.get_item("FPLCOUNT").value == 3
    page._hold_edit_course()
    page._modal["value"] = "400"
    page._modal_enter()
    assert page._hold_edit["message"] == "BAD COURSE"
    page._hold_edit_leg()
    page._modal["value"] = "0"
    page._modal_enter()
    assert page._hold_edit["message"] == "BAD LEG"
    page.grab()
    page._close_hold_editor()
    assert page._hold_edit is None
    assert page.fixdb.db.get_item("FPLCOUNT").value == 3


def test_editor_paints_and_its_taps_reach_the_fields(page):
    page._open_hold_editor(1)
    page.grab()
    calls = {t[4] for t in page._tap_targets[page._enc_layer_start:]}
    names = {getattr(c, "__name__", "") for c in calls}
    assert {"_hold_insert", "_close_hold_editor", "_hold_edit_course",
            "_hold_toggle_ref", "_hold_edit_leg", "_hold_toggle_unit"} <= names
    # Eight compass points, two turn buttons.
    lambdas = [c for c in calls if getattr(c, "__name__", "") == "<lambda>"]
    assert len(lambdas) == 10
    page._enc_back()
    assert page._hold_edit is None


# -- Exit hold ------------------------------------------------------------------

def _flying(page, phase, act):
    _set(page.fixdb, "FPLPHASE", phase)
    _set(page.fixdb, "FPLACTLEG", act)
    page._sync_engine_from_bridge()


def test_exit_hold_reads_and_sends_resume_in_an_hm_hold(page):
    page._open_hold_editor(1)
    page._hold_insert()
    _flying(page, "HOLD", 3)
    assert page._suspend_label() == "Exit hold"
    page._menu_open = True
    page.grab()
    page._menu_suspend_resume()
    assert page.sent == [("RESUME", None)]


def test_outside_the_hold_the_item_is_suspend_again(page):
    page._open_hold_editor(1)
    page._hold_insert()
    _flying(page, "ENR", 3)            # flying to the hold, not in it yet
    assert page._suspend_label() == "Suspend"
    _flying(page, "HOLD", 2)           # an engine HOLD on a non-HM slot
    assert page._suspend_label() == "Suspend"
    page._menu_suspend_resume()
    assert page.sent == [("SUSP", None)]


def test_hf_hold_offers_no_exit(page):
    page._plan.insert_hold(1, hold.hold_waypoint(B, 270.0, "R", 1.5).copy(pt="HF"))
    page._commit()
    _flying(page, "HOLD", 3)
    assert page._suspend_label() == "Suspend"


# -- the engine flies it --------------------------------------------------------

def _engine_route(mod, fix):
    n = fix.db.get_item("FPLCOUNT").value
    wps = []
    for i in range(1, n + 1):
        v = {name: _slot(fix, i, name) for name, _, _ in fixbridge.SLOT_FIELDS}
        wps.append(mod.Waypoint(v["ID"], v["LAT"], v["LON"], v["TYPE"], v["PT"], v["CRS"],
                                v["DST"], v["ALT"], v["SPD"], v["SGI"], v["FLAGS"],
                                v["CTRLAT"], v["CTRLON"], v["TURN"]))
    segs = []
    for k in range(1, fix.db.get_item("FPLSEGCNT").value + 1):
        g = {name: fix.db.get_item(fixbridge._seg_key(k, name)).value
             for name, _, _ in fixbridge.SEGMENT_FIELDS}
        segs.append(mod.Segment(g["KIND"], g["ID"], g["ENT"], g["EXT"], g["FIRST"], g["LAST"]))
    return wps, segs


def test_the_inserted_slot_loads_on_the_engine_and_is_flown(page, engine_mod):
    page._open_hold_editor(1)            # hold as you arrive at BBB
    page._hold_insert()
    wps, segs = _engine_route(engine_mod, page.fixdb)
    e = engine_mod.Engine()
    e.load_route(wps, "TEST", 1, segs)
    start = geo.destination_point(A.lat, A.lon, 90.0, 1.0)
    e.handle_command("1 ACT 2", (start[0], start[1], True))
    crs = geo.initial_bearing(A.lat, A.lon, B.lat, B.lon)
    total = geo.distance_nm(A.lat, A.lon, B.lat, B.lon)
    out, t = {}, 1000.0
    for step in range(1, 200):
        d = min(total + 0.3, step * 0.5)
        lat, lon = geo.destination_point(A.lat, A.lon, crs, d)
        out = e.update(lat, lon, 120.0, MAGVAR, True, None, None, t)
        t += 15.0
        if out.get("phase") == "HOLD":
            break
    assert out.get("phase") == "HOLD"
    assert out["act_leg"] == 3
    # Arriving on the inbound course: a direct entry.
    assert e._hold_entry == engine_mod.HOLD_ENTRY_DIRECT
    ack, msg = e.handle_command("3 RESUME", (lat, lon, True))
    assert (ack, msg) == (3, "HOLD EXIT ARMED")
