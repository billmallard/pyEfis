#  SPDX-License-Identifier: GPL-2.0-or-later
"""Tests for the `flight_plan` instrument (FP5a, billmallard/pyEfis#185).

Uses the repo's ``fix`` pytest fixture (``conftest.py``) and defines the
Appendix A flight-plan keys on it directly, the same pattern
``tests/flightplan/test_fixbridge.py`` uses (FP1 is a separate repo, its
``database/flightplan.yaml`` is not part of the shared fixture).
"""

import sqlite3
import time

import pytest

import pyefis.hmi as hmi
from pyefis.flightplan import catalog as fp_catalog
from pyefis.flightplan import fixbridge
from pyefis.flightplan import model as fp_model
from pyefis.flightplan import waypoints as fp_waypoints
from pyefis.instruments import flight_plan
from pyefis.screens import screenbuilder_factory as factory

_WIDE_BOUNDS = {"float": (-1e9, 1e9), "int": (-1_000_000, 1_000_000),
                "bool": (None, None), "str": (None, None)}

_ENGINE_DTYPES = {
    "FPLSTATE": "int", "FPLACTLEG": "int", "FPLPHASE": "str", "FPLAPR": "int",
    "FPLINTEG": "bool", "CDISCALE": "float", "FPLCRS": "float", "FPLXTK": "float",
    "FPLCDI": "float", "FPLTF": "int", "FPLFRLAT": "float", "FPLFRLON": "float",
    "WPNAME": "str", "WPLAT": "float", "WPLON": "float", "WPFROM": "str",
    "WPNEXT": "str", "WPDIS": "float", "WPETE": "int", "FPLREMDIS": "float",
    "FPLREMETE": "int", "FPLALERT": "bool", "GPSSRC": "int",
}
_ENGINE_DEFAULTS = {"int": 0, "float": 0.0, "bool": False, "str": ""}


def _define(fix, key, dtype, value):
    mn, mx = _WIDE_BOUNDS[dtype]
    fix.db.define_item(key, key, dtype, mn, mx, "", 0, "")
    fix.db.set_value(key, value)
    fix.db.get_item(key).bad = False
    fix.db.get_item(key).fail = False


def _define_all_fp1_keys(fix):
    for n in range(1, fixbridge.MAX_SLOTS + 1):
        id_key, lat_key, lon_key, type_key, role_key = fixbridge._slot_keys(n)
        _define(fix, id_key, "str", "")
        _define(fix, lat_key, "float", 0.0)
        _define(fix, lon_key, "float", 0.0)
        _define(fix, type_key, "int", 0)
        _define(fix, role_key, "int", 0)
    _define(fix, "FPLCOUNT", "int", 0)
    _define(fix, "FPLNAME", "str", "")
    _define(fix, "FPLSEQ", "int", 0)
    _define(fix, "DTOID", "str", "")
    _define(fix, "DTOLAT", "float", 0.0)
    _define(fix, "DTOLON", "float", 0.0)
    _define(fix, "DTOTYPE", "int", 0)
    _define(fix, "FPLCMD", "str", "")
    _define(fix, "FPLCMDACK", "int", 0)
    _define(fix, "FPLMSG", "str", "")
    for key, dtype in _ENGINE_DTYPES.items():
        _define(fix, key, dtype, _ENGINE_DEFAULTS[dtype])


AIRPORTS = [
    ("1", "KSBA", "Santa Barbara Muni", 34.42621, -119.84037, 10, 6000),
    ("2", "KSMX", "Santa Maria Pub", 34.89892, -120.45758, 257, 6304),
]
NAVAIDS = [("GVO", "VOR/DME", "Gaviota", "113.90", 2125, 34.53142, -120.09106)]


def _build_fixture_index(tmp_path):
    airports_path = tmp_path / "airports.sqlite"
    con = sqlite3.connect(str(airports_path))
    con.executescript(
        "CREATE TABLE airports (site_no TEXT PRIMARY KEY, icao TEXT, name TEXT, "
        "  lat REAL, lon REAL, elev_ft REAL);"
        "CREATE TABLE runways (site_no TEXT, rwy_id TEXT, length_ft REAL);")
    for site_no, icao, name, lat, lon, elev_ft, rwy_len in AIRPORTS:
        con.execute("INSERT INTO airports VALUES (?,?,?,?,?,?)",
                    (site_no, icao, name, lat, lon, elev_ft))
        con.execute("INSERT INTO runways VALUES (?,?,?)", (site_no, "1", rwy_len))
    con.commit()
    con.close()

    navaids_path = tmp_path / "navaids.sqlite"
    con = sqlite3.connect(str(navaids_path))
    con.executescript(
        "CREATE TABLE navaids (id TEXT, type TEXT, name TEXT, freq TEXT, "
        "  elev_ft REAL, lat REAL, lon REAL);"
        "CREATE TABLE fixes (id TEXT, use_code TEXT, lat REAL, lon REAL);")
    con.executemany("INSERT INTO navaids VALUES (?,?,?,?,?,?,?)", NAVAIDS)
    con.commit()
    con.close()

    idx = fp_waypoints.WaypointIndex(airports_db_path=airports_path,
                                      navaids_db_path=navaids_path)
    idx.wait_ready(5.0)
    return idx


def _install_index(w, idx):
    """Inject a fixture ``WaypointIndex``, also marking it "current" for the
    key check in ``_ensure_waypoint_index`` -- otherwise the next call (blank
    nasr/navaid/flightplan_dir Props) sees a key mismatch and silently
    rebuilds an empty index over the injected one."""
    w._waypoint_index = idx
    w._waypoint_index_key = (w.nasr_db_path, w.navaid_db_path, w.flightplan_dir)


def _install_catalog(w, cat):
    w._catalog = cat
    w._catalog_dir_used = w.flightplan_dir


def _plan(n):
    return fp_model.FlightPlan(name="TEST", waypoints=[
        fp_model.Waypoint(id=f"WP{i:02d}", type="fix", lat=float(i), lon=float(i))
        for i in range(n)
    ])


# ---------------------------------------------------------------------------
# construction / paint-never-raises
# ---------------------------------------------------------------------------
def test_construct_and_paint_with_no_gateway_keys(fix, qtbot):
    # `fix` initialises pyavtools.fix but defines none of the FP1 keys --
    # the "gateway keys missing" scenario FixBridge's own tests use.
    w = flight_plan.FlightPlan(None)
    qtbot.addWidget(w)
    w.resize(480, 320)
    assert w._bridge.available is False
    w.grab()  # forces paintEvent -- must not raise
    assert w._page == "fpl"


def test_construct_and_paint_empty_plan(fix, qtbot):
    _define_all_fp1_keys(fix)
    w = flight_plan.FlightPlan(None)
    qtbot.addWidget(w)
    w.resize(480, 320)
    assert w._bridge.available is True
    assert w._plan.count == 0
    w.grab()


def test_paint_fifty_slots_generous_perf_ceiling(fix, qtbot):
    _define_all_fp1_keys(fix)
    w = flight_plan.FlightPlan(None)
    qtbot.addWidget(w)
    w.resize(480, 320)
    w._plan = _plan(50)
    w._commit()
    assert w._plan.count == 50

    start = time.monotonic()
    for _ in range(5):
        w.grab()
    elapsed = (time.monotonic() - start) / 5
    assert elapsed < 0.5, f"paint took {elapsed * 1000:.1f} ms (generous CI ceiling)"


def test_build_via_factory(qtbot):
    w = factory.create_instrument(
        None, {"type": "flight_plan", "options": {}}, font_family="DejaVu Sans Condensed")
    qtbot.addWidget(w)
    assert isinstance(w, flight_plan.FlightPlan)


# ---------------------------------------------------------------------------
# keypad + FastFind + commit
# ---------------------------------------------------------------------------
def test_keypad_fastfind_and_commit_writes_seq_last(fix, qtbot, tmp_path):
    _define_all_fp1_keys(fix)
    w = flight_plan.FlightPlan(None)
    qtbot.addWidget(w)
    _install_index(w, _build_fixture_index(tmp_path))

    w._footer_add()
    assert w._page == "entry"
    for ch in "KS":
        w._entry_key(ch)
    assert w._entry_field == "KS"
    assert w._entry_suffix() == "BA"  # nearest match from the aircraft (0,0)

    order = []
    real_set_value = fix.db.set_value

    def tracking(key, value):
        order.append(key)
        real_set_value(key, value)

    fix.db.set_value = tracking
    try:
        w._entry_enter()
    finally:
        fix.db.set_value = real_set_value

    assert w._page == "fpl"
    assert w._plan.count == 1
    assert w._plan.waypoints[0].id == "KSBA"
    assert order[-1] == "FPLSEQ"
    assert order.index("FPL1ID") < order.index("FPLCOUNT") < order.index("FPLSEQ")


def test_fastfind_no_matches_and_duplicate(fix, qtbot, tmp_path):
    _define_all_fp1_keys(fix)
    w = flight_plan.FlightPlan(None)
    qtbot.addWidget(w)
    _install_index(w, _build_fixture_index(tmp_path))

    w._footer_add()
    for ch in "ZZ":
        w._entry_key(ch)
    w._entry_enter()
    assert w._entry_message == "NO MATCHES"

    w._waypoint_index.user.add(lat=34.531, lon=-120.091, id="GVO")
    w._entry_clear()
    for ch in "GVO":
        w._entry_key(ch)
    w._entry_enter()
    assert w._entry_message == "DUPLICATE FOUND"
    assert len(w._entry_dupe_choices) == 2


# ---------------------------------------------------------------------------
# insert / remove
# ---------------------------------------------------------------------------
def test_insert_before_after_remove_reorder(fix, qtbot, tmp_path):
    _define_all_fp1_keys(fix)
    w = flight_plan.FlightPlan(None)
    qtbot.addWidget(w)
    _install_index(w, _build_fixture_index(tmp_path))

    for ident in ("KSBA", "KSMX"):
        w._open_entry({"kind": "append", "index": None})
        for ch in ident:
            w._entry_key(ch)
        w._entry_enter()
    assert [wp.id for wp in w._plan.waypoints] == ["KSBA", "KSMX"]

    w._row_menu_index = 1
    w._row_menu_insert_before()
    for ch in "GVO":
        w._entry_key(ch)
    w._entry_enter()
    assert [wp.id for wp in w._plan.waypoints] == ["KSBA", "GVO", "KSMX"]

    w._row_menu_index = 0
    w._row_menu_remove()
    assert [wp.id for wp in w._plan.waypoints] == ["GVO", "KSMX"]


# ---------------------------------------------------------------------------
# set role + refusals
# ---------------------------------------------------------------------------
def test_set_role_writes_fplfrole_and_label(fix, qtbot):
    _define_all_fp1_keys(fix)
    w = flight_plan.FlightPlan(None)
    qtbot.addWidget(w)
    w._plan = _plan(3)
    w._commit()

    w._row_menu_index = 1
    w._row_menu_set_role("faf")
    assert w._plan.waypoints[1].role == "faf"
    assert int(fix.db.get_item("FPL2ROLE").value) == fixbridge.ROLE_TO_FPLROLE["faf"]
    assert flight_plan.ROLE_ABBREV["faf"] == "FAF"


def test_set_role_refuses_second_faf(fix, qtbot):
    _define_all_fp1_keys(fix)
    w = flight_plan.FlightPlan(None)
    qtbot.addWidget(w)
    w._plan = _plan(3)
    w._plan.set_role(0, "faf")
    w._commit()

    w._row_menu_index = 1
    w._row_menu_set_role("faf")
    assert "FAF" in w._message
    assert w._plan.waypoints[1].role == "none"


def test_set_role_refuses_map_before_faf(fix, qtbot):
    _define_all_fp1_keys(fix)
    w = flight_plan.FlightPlan(None)
    qtbot.addWidget(w)
    w._plan = _plan(3)
    w._plan.set_role(2, "faf")
    w._commit()

    w._row_menu_index = 0
    w._row_menu_set_role("map")
    assert "MAP" in w._message or "FAF" in w._message
    assert w._plan.waypoints[0].role == "none"


# ---------------------------------------------------------------------------
# header: LNAV / LOI, activate leg, row colours, state badge
# ---------------------------------------------------------------------------
def test_header_shows_lnav_and_loi(fix, qtbot):
    _define_all_fp1_keys(fix)
    fix.db.set_value("FPLAPR", 2)
    fix.db.set_value("FPLINTEG", False)
    w = flight_plan.FlightPlan(None)
    qtbot.addWidget(w)
    w.resize(480, 320)

    assert w._approach_text() == "LNAV"
    assert w._engine_value("FPLINTEG") is False
    w.grab()


def test_activate_leg_issues_act_command(fix, qtbot):
    _define_all_fp1_keys(fix)
    w = flight_plan.FlightPlan(None)
    qtbot.addWidget(w)
    w._plan = _plan(3)
    w._commit()

    w._row_menu_index = 1
    w._row_menu_activate_leg()
    assert fix.db.get_item("FPLCMD").value == "1 ACT 2"


def test_row_colors_active_past_future(fix, qtbot):
    _define_all_fp1_keys(fix)
    fix.db.set_value("FPLACTLEG", 2)
    w = flight_plan.FlightPlan(None)
    qtbot.addWidget(w)
    active_idx = int(w._engine_value("FPLACTLEG")) - 1
    assert active_idx == 1
    assert w._row_color(0, active_idx) == w.past_color
    assert w._row_color(1, active_idx) == w.active_color
    assert w._row_color(2, active_idx) == w.future_color


@pytest.mark.parametrize("state,badge", [(0, ""), (1, "LEG"), (2, "DIRECT"), (3, "SUSP")])
def test_state_badge_follows_fplstate(fix, qtbot, state, badge):
    _define_all_fp1_keys(fix)
    fix.db.set_value("FPLSTATE", state)
    w = flight_plan.FlightPlan(None)
    qtbot.addWidget(w)
    assert w._state_badge() == badge


@pytest.mark.parametrize("columns", ["DTK,DIS,CUM", "ETE,ETA", "DIS", "cum,dtk,ete,eta,dis"])
def test_columns_variants_render(fix, qtbot, columns):
    _define_all_fp1_keys(fix)
    w = flight_plan.FlightPlan(None)
    qtbot.addWidget(w)
    w.resize(480, 320)
    w.columns = columns
    w._plan = _plan(4)
    w._commit()
    w.grab()


# ---------------------------------------------------------------------------
# Menu: Store
# ---------------------------------------------------------------------------
def test_menu_store_writes_a_catalog_file(qtbot, tmp_path):
    w = flight_plan.FlightPlan(None)
    qtbot.addWidget(w)
    _install_catalog(w, fp_catalog.Catalog(tmp_path))
    w._plan = fp_model.FlightPlan(name="KSBA-KSMX", waypoints=[
        fp_model.Waypoint(id="KSBA", type="airport", lat=34.4, lon=-119.8),
        fp_model.Waypoint(id="KSMX", type="airport", lat=34.9, lon=-120.5),
    ])
    w._menu_store()
    assert w._message == "STORED"
    saved = list(tmp_path.glob("*.json"))
    assert len(saved) == 1


# ---------------------------------------------------------------------------
# HMI verbs (lockstep coverage is tests/editor; this covers wiring + dispatch)
# ---------------------------------------------------------------------------
def test_all_hmi_verbs_registered():
    hmi.initialize({})
    for verb in ("flightplan page", "flightplan direct to"):
        assert verb in hmi.actions.signalMap


def test_flightplan_page_verb_returns_to_fpl(fix, qtbot):
    _define_all_fp1_keys(fix)
    hmi.initialize({})
    w = flight_plan.FlightPlan(None)
    qtbot.addWidget(w)
    w._page = "entry"
    hmi.actions.trigger("flightplan page", "fpl")
    assert w._page == "fpl"


def test_flightplan_page_verb_respects_hmi_group(fix, qtbot):
    _define_all_fp1_keys(fix)
    hmi.initialize({})
    w = flight_plan.FlightPlan(None)
    qtbot.addWidget(w)
    w.hmi_group = "left"
    w._page = "entry"
    hmi.actions.trigger("flightplan page", "fpl right")
    assert w._page == "entry"
    hmi.actions.trigger("flightplan page", "fpl left")
    assert w._page == "fpl"
