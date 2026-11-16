#  SPDX-License-Identifier: GPL-2.0-or-later
"""Starting an airway at a SID's exit fix (G87, billmallard/pyEfis#474).

Found on the Beelink in PA14 bench validation (AER-1613,
``docs/images/pa14_bench/README.md`` frame ``d04``): KSBA, FLOUT5 from
runway 15B with the VTU transition, then V485 from VTU. The procedure row
had no Load Airway, so VTU went in as a plain waypoint after the SID to
start V485 from, and the bus carried VTU in slots 4 and 5: a zero-length
leg the engine flies on course 000 until it sequences.

V485 here is decoder output, not typed by hand: makerplane-data
``packtools.arinc424.iter_airway_legs`` (commit cb6607b) over FAA CIFP
``FAACIFP18`` cycle 2611, the four ``V485`` records VTU, HENER, OHIGH and
FLW. The plain VTU is the waypoint-database position the bench put in
slot 5 (``docs/images/pa14_bench/data/route_ksba_ksmo.json``), a few feet
from the pack's.
"""

import sqlite3

import pytest

from pyefis.flightplan import model as fp_model
from tests.instruments.flight_plan.test_proc_page import _engine_loads, _load, page  # noqa: F401

V485 = [
    (100, "VTU", 34.11506389, -119.0495, "vor", 5000, 17500),
    (110, "HENER", 34.33106389, -119.22768889, "waypoint", 9000, 17500),
    (120, "OHIGH", 34.43135278, -119.31081944, "waypoint", 9000, 17500),
    (130, "FLW", 35.09308333, -119.86557778, "vor", None, None),
]
VTU_WAYPOINT_DB = fp_model.Waypoint("VTU", "vor", 34.11506461, -119.04949866)

_AIRWAY_SCHEMA = """
CREATE TABLE airways (id INTEGER PRIMARY KEY, ident TEXT NOT NULL, cycle TEXT NOT NULL);
CREATE TABLE airway_legs (airway_id INTEGER NOT NULL, seq INTEGER NOT NULL, fix_id TEXT NOT NULL,
    fix_lat REAL, fix_lon REAL, fix_type TEXT, min_alt_ft INTEGER, max_alt_ft INTEGER,
    direction TEXT);
"""


@pytest.fixture()
def sid(page, fix):  # noqa: F811
    """The bench's route so far: KSBA, then FLOUT5.RW15B.VTU, on the bus."""
    con = sqlite3.connect(page.procedures_db_path)
    con.executescript(_AIRWAY_SCHEMA)
    con.execute("INSERT INTO airways VALUES (1, 'V485', '2611')")
    con.executemany("INSERT INTO airway_legs VALUES (1, ?, ?, ?, ?, ?, ?, ?, NULL)", V485)
    con.commit()
    con.close()
    page._plan = fp_model.FlightPlan(waypoints=[page._plan.waypoints[1].copy()])  # KSBA
    page._commit()
    _engine_loads(page, fix)
    _load(page, "departure", "FLOUT5", "VTU", "RW15B")
    _engine_loads(page, fix)
    assert [(s.kind, s.ident) for s in page._plan.segments] == [
        ("waypoint", ""), ("departure", "FLOUT5.RW15B.VTU")]
    assert page._plan.waypoints[-1].id == "VTU"
    return page


def _bus_ids(fix):
    return [fix.db.get_item(f"FPL{n}ID").value
            for n in range(1, int(fix.db.get_item("FPLCOUNT").value) + 1)]


def _menu_callbacks(w):
    w.grab()
    return [t[4] for t in w._tap_targets[w._enc_layer_start:]]


def test_the_departure_row_loads_v485_from_vtu_with_one_vtu_slot(sid, fix):
    k = 1
    sid._open_seg_menu(k)
    assert sid._seg_menu_load_airway in _menu_callbacks(sid)
    sid._seg_menu_load_airway()
    assert sid._airway_picker["entry_wp"].id == "VTU"
    assert "V485" in sid._airway_picker["idents"]
    sid._airway_picker_pick_ident("V485")
    sid._airway_picker_pick_exit("OHIGH")
    assert sid._message == ""
    assert [(s.kind, s.ident, [w.id for w in s.legs]) for s in sid._plan.segments] == [
        ("waypoint", "", ["KSBA"]),
        ("departure", "FLOUT5.RW15B.VTU", ["", "FLOUT", "VTU"]),
        ("airway", "V485", ["HENER", "OHIGH"])]
    # The MEAs are V485's: 5000 on VTU->HENER, 9000 on HENER->OHIGH.
    assert [w.alt for w in sid._plan.segments[2].legs] == ["+5000", "+9000"]
    _engine_loads(sid, fix)
    assert _bus_ids(fix) == ["KSBA", "", "FLOUT", "VTU", "HENER", "OHIGH"]
    # No leg on the published route is zero-length.
    plan = sid._plan
    assert all(plan.leg(i)[1] > 0.1 for i in range(2, plan.count - 1))


def test_entering_vtu_again_after_the_sid_is_refused(sid, fix):
    """The bench workaround: insert VTU after the SID's VTU."""
    before = sid._plan.to_json()
    with pytest.raises(fp_model.FlightPlanError, match="VTU IS ALREADY THE PREVIOUS FIX"):
        sid._plan.insert_after(sid._plan.count - 1, VTU_WAYPOINT_DB.copy())
    assert sid._plan.to_json() == before
    # Through the page: the entry page says why and keeps the plan.
    sid._open_entry({"kind": "insert_after", "index": sid._plan.count - 1})
    sid._select_waypoint(VTU_WAYPOINT_DB)
    assert sid._entry_message == "VTU IS ALREADY THE PREVIOUS FIX"
    assert sid._plan.to_json() == before


def test_a_fix_before_its_own_slot_is_refused_too(sid):
    with pytest.raises(fp_model.FlightPlanError, match="KSBA IS ALREADY THE NEXT FIX"):
        sid._plan.insert_before(0, sid._plan.waypoints[0].copy())


def test_a_different_fix_still_goes_in_after_the_sid(sid):
    hener = fp_model.Waypoint("HENER", "fix", *V485[1][2:4])
    sid._plan.insert_after(sid._plan.count - 1, hener)
    assert [w.id for w in sid._plan.waypoints][-2:] == ["VTU", "HENER"]


def test_an_airway_row_chains_the_next_airway_from_its_exit(sid, fix):
    sid._open_seg_menu(1)
    sid._seg_menu_load_airway()
    sid._airway_picker_pick_ident("V485")
    sid._airway_picker_pick_exit("HENER")
    # VTU -> HENER alone is one leg: the airway refuses it, as before.
    assert "single leg" in sid._message
    sid._message = ""
    sid._open_seg_menu(1)
    sid._seg_menu_load_airway()
    sid._airway_picker_pick_ident("V485")
    sid._airway_picker_pick_exit("OHIGH")
    sid._open_seg_menu(2)
    assert sid._seg_menu_load_airway in _menu_callbacks(sid)
    sid._seg_menu_load_airway()
    assert sid._airway_picker["entry_wp"].id == "OHIGH"
    # OHIGH -> FLW is one leg too; back the way it came is two.
    sid._airway_picker_pick_ident("V485")
    sid._airway_picker_pick_exit("VTU")
    assert [w.id for w in sid._plan.waypoints] == ["KSBA", "", "FLOUT", "VTU", "HENER",
                                                    "OHIGH", "HENER", "VTU"]
    assert [s.kind for s in sid._plan.segments] == ["waypoint", "departure", "airway",
                                                     "airway"]


def test_approach_and_missed_rows_offer_no_load_airway(sid, fix):
    _load(sid, "approach", "I07", "VECTORS")
    _engine_loads(sid, fix)
    for k, seg in enumerate(sid._plan.segments):
        if seg.kind in ("approach", "missed"):
            sid._open_seg_menu(k)
            assert sid._seg_menu_load_airway not in _menu_callbacks(sid)
            sid._close_seg_menu()
