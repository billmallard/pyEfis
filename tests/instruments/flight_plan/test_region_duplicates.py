#  SPDX-License-Identifier: GPL-2.0-or-later
"""FPL page resolvers on an ident that names two places (FPA5, AER-6544).

RTE1's rule, "ambiguous idents are shown, never guessed", needs each place
to say where it is. Before FPA5 the packs carried no region and every
resolver after the build matched the ident alone: Direct-To by ident did
nothing on a duplicate, the Recent tab showed the first match whichever
place was picked, the duplicate chooser listed two rows a pilot could not
tell apart, and LOAD AIRWAY offered an airway through the other place of
the same name.

Two synthetic fixes ``DUPEE`` in two ICAO regions (FIX_BASE repeats no
ident in cycle 2611, so no real pair exists), one of them on airway T999.

Kept standalone (own ``_define_all_fp1_keys`` helper) the same way
``test_airway_insertion.py`` is.
"""

import sqlite3

import pytest

from pyefis.flightplan import fixbridge
from pyefis.flightplan import model as fp_model
from pyefis.flightplan import waypoints as fp_waypoints
from pyefis.instruments import flight_plan

_WIDE_BOUNDS = {"float": (-1e9, 1e9), "int": (-1_000_000, 1_000_000),
                "bool": (None, None), "str": (None, None)}

DUPEE_CA = (34.30, -119.80)
DUPEE_CO = (39.90, -105.10)
KWANG = (34.30911, -119.51415)


def _define(fix, key, dtype, value):
    mn, mx = _WIDE_BOUNDS[dtype]
    fix.db.define_item(key, key, dtype, mn, mx, "", 0, "")
    fix.db.set_value(key, value)
    fix.db.get_item(key).bad = False
    fix.db.get_item(key).fail = False


_ENGINE_DTYPES = {
    "FPLSTATE": "int", "FPLACTLEG": "int", "FPLPHASE": "str", "FPLAPR": "int",
    "FPLINTEG": "bool", "CDISCALE": "float", "FPLCRS": "float", "FPLXTK": "float",
    "FPLCDI": "float", "FPLTF": "int", "FPLFRLAT": "float", "FPLFRLON": "float",
    "WPNAME": "str", "WPLAT": "float", "WPLON": "float", "WPFROM": "str",
    "WPNEXT": "str", "WPDIS": "float", "WPETE": "int", "FPLREMDIS": "float",
    "FPLREMETE": "int", "FPLALERT": "bool", "GPSSRC": "int",
    "FPLACTSEG": "int", "FPLSEGREM": "float",
}
_ENGINE_DEFAULTS = {"int": 0, "float": 0.0, "bool": False, "str": ""}


def _define_all_fp1_keys(fix):
    for key, dtype, blank in fixbridge.route_key_specs():
        _define(fix, key, dtype, blank)
    for key, dtype in _ENGINE_DTYPES.items():
        _define(fix, key, dtype, _ENGINE_DEFAULTS[dtype])


@pytest.fixture()
def packs(tmp_path):
    navaids = tmp_path / "navaids.sqlite"
    con = sqlite3.connect(str(navaids))
    con.executescript(
        "CREATE TABLE navaids (id TEXT, type TEXT, name TEXT, freq TEXT, "
        "  elev_ft REAL, lat REAL, lon REAL, state TEXT, country TEXT);"
        "CREATE TABLE fixes (id TEXT, use_code TEXT, lat REAL, lon REAL, "
        "  icao_region TEXT, state TEXT, country TEXT);")
    con.executemany("INSERT INTO fixes VALUES (?,?,?,?,?,?,?)", [
        ("DUPEE", "RP", *DUPEE_CA, "K2", "CA", "US"),
        ("DUPEE", "RP", *DUPEE_CO, "K7", "CO", "US"),
        ("KWANG", "RP", *KWANG, "K2", "CA", "US"),
    ])
    con.commit()
    con.close()

    procedures = tmp_path / "procedures.pack"
    con = sqlite3.connect(str(procedures))
    con.executescript(
        "CREATE TABLE airways (id INTEGER PRIMARY KEY, ident TEXT NOT NULL, "
        "  cycle TEXT NOT NULL);"
        "CREATE TABLE airway_legs (airway_id INTEGER NOT NULL, seq INTEGER NOT NULL, "
        "  fix_id TEXT NOT NULL, fix_lat REAL, fix_lon REAL, fix_type TEXT, "
        "  min_alt_ft INTEGER, max_alt_ft INTEGER, direction TEXT, fix_region TEXT);")
    con.execute("INSERT INTO airways (id, ident, cycle) VALUES (1, 'T999', '2611')")
    con.executemany("INSERT INTO airway_legs VALUES (1,?,?,?,?,'waypoint',?,17500,NULL,'K2')", [
        (100, "DUPEE", *DUPEE_CA, 5000), (110, "KWANG", *KWANG, 4000)])
    con.commit()
    con.close()
    return tmp_path, navaids, procedures


def _widget(qtbot, fix, packs):
    tmp_path, navaids, procedures = packs
    _define_all_fp1_keys(fix)
    w = flight_plan.FlightPlan(None)
    qtbot.addWidget(w)
    w.procedures_db_path = str(procedures)
    idx = fp_waypoints.WaypointIndex(None, str(navaids),
                                      recent_file=str(tmp_path / "recent.json"))
    assert idx.wait_ready(5.0)
    w._waypoint_index = idx
    w._waypoint_index_key = (w.nasr_db_path, w.navaid_db_path, w.flightplan_dir)
    return w


def _colorado(choices):
    return next(c for c in choices if c.lat == DUPEE_CO[0])


def test_direct_to_by_ident_on_a_duplicate_opens_the_chooser(fix, qtbot, packs):
    """Before FPA5 this did nothing at all: no direct-to, no page, no word."""
    w = _widget(qtbot, fix, packs)
    w._act_direct_to("DUPEE")
    assert w._page == "dto"
    assert w._entry_message == "DUPLICATE FOUND"
    assert sorted(c.lat for c in w._entry_dupe_choices) == [DUPEE_CA[0], DUPEE_CO[0]]
    assert fix.db.get_item("DTOID").value == ""

    w._choose_duplicate(_colorado(w._entry_dupe_choices))
    assert fix.db.get_item("DTOID").value == "DUPEE"
    assert fix.db.get_item("DTOLAT").value == pytest.approx(DUPEE_CO[0])
    assert fix.db.get_item("FPLCMD").value.endswith("DTO")


def test_direct_to_by_a_unique_ident_still_goes_direct(fix, qtbot, packs):
    w = _widget(qtbot, fix, packs)
    w._act_direct_to("KWANG")
    assert fix.db.get_item("DTOID").value == "KWANG"
    assert w._page == "fpl"
    assert w._entry_dupe_choices is None


def test_duplicate_chooser_rows_name_the_region(fix, qtbot, packs, monkeypatch):
    w = _widget(qtbot, fix, packs)
    w._entry_dupe_choices = w._waypoint_index.lookup("DUPEE")
    rows = []
    monkeypatch.setattr(w, "_paint_menu_list",
                        lambda p, w_, h, items, *a, **k: rows.extend(t for t, _cb in items))
    w._paint_dupe_chooser(_NullPainter(), 800, 480)
    assert sorted(rows) == ["DUPEE fix CA", "DUPEE fix CO"]


class _NullPainter:
    """Stands in for the QPainter the backdrop draws with; the rows are what
    is under test."""

    def __getattr__(self, name):
        return lambda *a, **k: None


def test_recent_tab_shows_the_place_that_was_picked(fix, qtbot, packs):
    """Before FPA5 the Recent tab showed the first DUPEE in the database (the
    California one) after the pilot had picked the Colorado one."""
    w = _widget(qtbot, fix, packs)
    w._open_entry({"kind": "append", "index": None})
    for ch in "DUPEE":
        w._entry_key(ch)
    w._entry_enter()
    assert w._entry_message == "DUPLICATE FOUND"
    w._choose_duplicate(_colorado(w._entry_dupe_choices))
    assert w._plan.waypoints[-1].lat == pytest.approx(DUPEE_CO[0])

    w._open_entry({"kind": "append", "index": None})
    w._select_entry_tab("Recent")
    assert [(r.id, r.lat) for r in w._entry_tab_rows()] == [("DUPEE", DUPEE_CO[0])]


def test_load_airway_offers_no_airway_through_the_other_place(fix, qtbot, packs):
    """T999 passes through the California DUPEE. Before FPA5 LOAD AIRWAY on the
    Colorado DUPEE offered it, and the expansion jumped 870 nm."""
    w = _widget(qtbot, fix, packs)
    w._plan = fp_model.FlightPlan(name="T", waypoints=[
        fp_model.Waypoint(id="DUPEE", type="fix", lat=DUPEE_CO[0], lon=DUPEE_CO[1])])
    w._commit()
    w._row_menu_index = 0
    w._row_menu_load_airway()
    assert w._airway_picker is None
    assert w._message == "NO AIRWAYS AT DUPEE"

    w._plan = fp_model.FlightPlan(name="T", waypoints=[
        fp_model.Waypoint(id="DUPEE", type="fix", lat=DUPEE_CA[0], lon=DUPEE_CA[1])])
    w._commit()
    w._row_menu_index = 0
    w._row_menu_load_airway()
    assert w._airway_picker["idents"] == ["T999"]
