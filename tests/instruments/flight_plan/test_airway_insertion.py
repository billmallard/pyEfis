#  SPDX-License-Identifier: GPL-2.0-or-later
"""FPL page airway insertion (PA6, billmallard/pyEfis#237, AER-1605).

"With a fix selected, LOAD AIRWAY offers airways through that fix ... then an
exit fix from that airway's ordered points; the expansion is inserted
collapsed" (``makerplane/briefs/procedures_and_airways_plan.md`` section 3.5).
This exercises the exact "KSBA GVO V27 RZS KSMX" scenario the epic targets,
reusing the real GVO/RZS/POM coordinates and V27/A1 fixture already
established in ``tests/flightplan/test_airways.py`` (PA2).

Kept standalone (own ``_define_all_fp1_keys``/``_plan`` helpers) the same way
``test_row_geometry.py`` is -- see that file's docstring.
"""

import sqlite3

import pytest

from pyefis.flightplan import fixbridge
from pyefis.flightplan import model as fp_model
from pyefis.instruments import flight_plan

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
        id_key, lat_key, lon_key, type_key, flags_key = fixbridge._slot_keys(n)
        _define(fix, id_key, "str", "")
        _define(fix, lat_key, "float", 0.0)
        _define(fix, lon_key, "float", 0.0)
        _define(fix, type_key, "int", 0)
        _define(fix, flags_key, "int", 0)
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


def _plan(*waypoints):
    return fp_model.FlightPlan(name="TEST", waypoints=list(waypoints))


GVO = (34.53142, -120.09106)
POM = (34.06000, -117.75000)
RZS = (34.02000, -119.55000)
KSBA = (34.42621, -119.84037)
KSMX = (34.89892, -120.45758)

_SCHEMA = """
CREATE TABLE airways (
    id      INTEGER PRIMARY KEY,
    ident   TEXT NOT NULL,
    cycle   TEXT NOT NULL
);
CREATE TABLE airway_legs (
    airway_id   INTEGER NOT NULL REFERENCES airways(id),
    seq         INTEGER NOT NULL,
    fix_id      TEXT NOT NULL,
    fix_lat     REAL,
    fix_lon     REAL,
    fix_type    TEXT,
    min_alt_ft  INTEGER,
    max_alt_ft  INTEGER,
    direction   TEXT
);
CREATE INDEX idx_awy_ident ON airways(ident);
CREATE INDEX idx_awyleg_awy ON airway_legs(airway_id, seq);
CREATE INDEX idx_awyleg_fix ON airway_legs(fix_id);
"""


@pytest.fixture()
def pack_path(tmp_path):
    path = tmp_path / "procedures-conus.pack"
    con = sqlite3.connect(str(path))
    con.executescript(_SCHEMA)

    def insert_airway(ident, legs):
        cur = con.execute("INSERT INTO airways (ident, cycle) VALUES (?, ?)", (ident, "2609"))
        airway_id = cur.lastrowid
        for seq, fix_id, (lat, lon), fix_type, min_alt, max_alt, direction in legs:
            con.execute(
                "INSERT INTO airway_legs (airway_id, seq, fix_id, fix_lat, fix_lon, "
                "fix_type, min_alt_ft, max_alt_ft, direction) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (airway_id, seq, fix_id, lat, lon, fix_type, min_alt, max_alt, direction))

    # V27: GVO -> POM -> RZS, no direction restriction -- the epic's own
    # scenario, "KSBA GVO V27 RZS KSMX" flown by the engine as it stands.
    insert_airway("V27", [
        (100, "GVO", GVO, "vor", 5000, 18000, None),
        (110, "POM", POM, "ndb", 6000, 18000, None),
        (120, "RZS", RZS, "vor", 4000, 18000, None),
    ])
    # A1: a one-way (forward-only) restriction on the WOODY->WISKI leg.
    insert_airway("A1", [
        (100, "ALPHA", (35.0, -118.0), "waypoint", 3000, 17000, None),
        (110, "WOODY", (35.5, -118.2), "waypoint", 4000, 17000, None),
        (120, "WISKI", (36.0, -118.4), "waypoint", 5000, 17000, "F"),
        (130, "ZULUU", (36.5, -118.6), "waypoint", 5000, 17000, "B"),
    ])

    con.commit()
    con.close()
    return path


def _widget(qtbot, fix, pack_path):
    _define_all_fp1_keys(fix)
    w = flight_plan.FlightPlan(None)
    qtbot.addWidget(w)
    w.procedures_db_path = str(pack_path)
    return w


# ---------------------------------------------------------------------------
# row menu -> airway picker
# ---------------------------------------------------------------------------
def test_row_menu_load_airway_with_no_airways_at_fix_shows_message(fix, qtbot, pack_path):
    w = _widget(qtbot, fix, pack_path)
    w._plan = _plan(fp_model.Waypoint(id="KSBA", type="airport", lat=KSBA[0], lon=KSBA[1]))
    w._commit()

    w._row_menu_index = 0
    w._row_menu_load_airway()
    assert w._airway_picker is None
    assert "NO AIRWAYS" in w._message
    assert "KSBA" in w._message


def test_row_menu_load_airway_lists_airways_through_the_fix(fix, qtbot, pack_path):
    w = _widget(qtbot, fix, pack_path)
    w._plan = _plan(fp_model.Waypoint(id="GVO", type="vor", lat=GVO[0], lon=GVO[1]))
    w._commit()

    w._row_menu_index = 0
    w._row_menu_load_airway()
    assert w._airway_picker["stage"] == "airway"
    assert w._airway_picker["idents"] == ["V27"]
    w.grab()  # picker overlay paints without raising


def test_airway_picker_pick_ident_then_exit_lists_other_fixes_with_altitudes(fix, qtbot, pack_path):
    w = _widget(qtbot, fix, pack_path)
    w._plan = _plan(fp_model.Waypoint(id="GVO", type="vor", lat=GVO[0], lon=GVO[1]))
    w._commit()
    w._row_menu_index = 0
    w._row_menu_load_airway()

    w._airway_picker_pick_ident("V27")
    assert w._airway_picker["stage"] == "exit"
    exits = [leg.fix_id for leg in w._airway_picker["legs"]]
    assert exits == ["POM", "RZS"]  # entry fix (GVO) is never offered as an exit
    pom_leg = w._airway_picker["legs"][0]
    assert (pom_leg.min_alt_ft, pom_leg.max_alt_ft) == (6000, 18000)
    w.grab()


# ---------------------------------------------------------------------------
# full flow: KSBA GVO V27 RZS KSMX -- insertion, collapsing, persistence
# ---------------------------------------------------------------------------
def test_full_flow_inserts_expansion_collapsed_between_entry_and_exit(fix, qtbot, pack_path):
    w = _widget(qtbot, fix, pack_path)
    w._plan = _plan(
        fp_model.Waypoint(id="KSBA", type="airport", lat=KSBA[0], lon=KSBA[1]),
        fp_model.Waypoint(id="GVO", type="vor", lat=GVO[0], lon=GVO[1]),
        fp_model.Waypoint(id="KSMX", type="airport", lat=KSMX[0], lon=KSMX[1]),
    )
    w._commit()

    w._row_menu_index = 1  # GVO
    w._row_menu_load_airway()
    w._airway_picker_pick_ident("V27")
    w._airway_picker_pick_exit("RZS")

    assert w._airway_picker is None  # the flow closes itself on success
    ids = [wp.id for wp in w._plan.waypoints]
    assert ids == ["KSBA", "GVO", "POM", "RZS", "KSMX"]
    assert w._plan.waypoints[1].extra.get("airway") is None       # GVO: the entry, untagged
    assert w._plan.waypoints[2].extra["airway"] == "V27"          # POM: inserted
    assert w._plan.waypoints[3].extra["airway"] == "V27"          # RZS: inserted
    assert w._plan.waypoints[4].extra.get("airway") is None       # KSMX: untouched

    groups = w._row_groups()
    assert groups == [(0, 0, None), (1, 1, None), (2, 3, "V27"), (4, 4, None)]
    w.grab()  # renders the collapsed "V27 -> RZS" row without raising


def test_airway_tag_survives_the_fix_bus_round_trip(fix, qtbot, pack_path):
    """The FP1 bus contract carries id/lat/lon/type/role only (no per-slot
    "which airway" key) -- `_commit()` publishes and immediately reads back,
    so a naive re-read would silently un-collapse the row it had just drawn."""
    w = _widget(qtbot, fix, pack_path)
    w._plan = _plan(fp_model.Waypoint(id="GVO", type="vor", lat=GVO[0], lon=GVO[1]))
    w._commit()
    w._row_menu_index = 0
    w._row_menu_load_airway()
    w._airway_picker_pick_ident("V27")
    w._airway_picker_pick_exit("RZS")

    assert fix.db.get_item("FPLCOUNT").value == 3  # actually published, not just local
    assert w._plan.waypoints[1].extra.get("airway") == "V27"
    assert w._plan.waypoints[2].extra.get("airway") == "V27"

    # An unrelated commit (e.g. another edit) re-reads the route back off the
    # bus; the tag must still be there afterwards.
    w._commit()
    assert w._plan.waypoints[1].extra.get("airway") == "V27"
    assert w._plan.waypoints[2].extra.get("airway") == "V27"


def test_remove_on_a_collapsed_airway_row_takes_the_whole_group(fix, qtbot, pack_path):
    """PA16 (AER-2088): the collapsed row has no expand path any more, so
    Remove is the only way to take an airway segment back out -- and it must
    take the whole span (POM+RZS), not just the one fix the row menu happens
    to anchor to (the group's exit fix, RZS -- see `_paint_airway_summary_row`
    and `_row_menu_remove`'s `_group_containing`)."""
    w = _widget(qtbot, fix, pack_path)
    w._plan = _plan(
        fp_model.Waypoint(id="KSBA", type="airport", lat=KSBA[0], lon=KSBA[1]),
        fp_model.Waypoint(id="GVO", type="vor", lat=GVO[0], lon=GVO[1]),
        fp_model.Waypoint(id="KSMX", type="airport", lat=KSMX[0], lon=KSMX[1]),
    )
    w._commit()
    w._row_menu_index = 1  # GVO
    w._row_menu_load_airway()
    w._airway_picker_pick_ident("V27")
    w._airway_picker_pick_exit("RZS")
    assert [wp.id for wp in w._plan.waypoints] == ["KSBA", "GVO", "POM", "RZS", "KSMX"]

    group = next(g for g in w._row_groups() if g[2] == "V27")
    assert group == (2, 3, "V27")
    w._row_menu_index = group[1]  # RZS -- the anchor a collapsed-row tap opens
    w._row_menu_remove()

    assert [wp.id for wp in w._plan.waypoints] == ["KSBA", "GVO", "KSMX"]


# ---------------------------------------------------------------------------
# validation: enforced, not assumed (brief 3.4)
# ---------------------------------------------------------------------------
def test_direction_restriction_violation_is_shown_and_plan_is_unchanged(fix, qtbot, pack_path):
    w = _widget(qtbot, fix, pack_path)
    w._plan = _plan(fp_model.Waypoint(id="ZULUU", type="fix", lat=36.5, lon=-118.6))
    w._commit()
    w._row_menu_index = 0
    w._row_menu_load_airway()
    w._airway_picker_pick_ident("A1")
    # ZULUU -> ALPHA walks backward across WISKI's forward-only restriction.
    w._airway_picker_pick_exit("ALPHA")

    assert w._airway_picker is not None  # picker stays open so the pilot can retry
    assert "one-way" in w._airway_picker["message"]
    assert [wp.id for wp in w._plan.waypoints] == ["ZULUU"]


def test_route_full_refuses_the_whole_segment_atomically(fix, qtbot, pack_path):
    w = _widget(qtbot, fix, pack_path)
    near_cap = [fp_model.Waypoint(id="GVO", type="vor", lat=GVO[0], lon=GVO[1])]
    near_cap += [fp_model.Waypoint(id=f"WP{i:02d}", type="fix", lat=float(i), lon=float(i))
                 for i in range(fp_model.MAX_WAYPOINTS - 2)]
    w._plan = _plan(*near_cap)
    assert w._plan.count == fp_model.MAX_WAYPOINTS - 1
    w._commit()

    w._row_menu_index = 0  # GVO
    w._row_menu_load_airway()
    w._airway_picker_pick_ident("V27")
    w._airway_picker_pick_exit("RZS")  # needs 2 more slots (POM, RZS); only 1 free

    assert "ROUTE FULL" in w._message
    assert w._plan.count == fp_model.MAX_WAYPOINTS - 1  # untouched -- no partial insert
    assert all(wp.extra.get("airway") is None for wp in w._plan.waypoints)
