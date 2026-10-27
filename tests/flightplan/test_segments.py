#  SPDX-License-Identifier: GPL-2.0-or-later
"""Route segments (RS2, billmallard/pyEfis#305, AER-3791): the segment model
and its edits, invert with the one-way re-check, ``mp-route/2`` store/load
with the AIRAC re-expansion, and the bus round trip through ``FixBridge``.
See ``makerplane/briefs/route_segments_plan.md`` sections 4 and 9, and the
segment table contract in fix-gateway ``doc/flightplan_keys.md``.

The pack is a hand-built three-airway fixture, not real CIFP data: what is
under test is how the model treats an airway (its boundaries, direction
codes and cycle), not the airway's geography.
"""

import json
import sqlite3

import pytest

from pyefis.flightplan import airways, catalog, fixbridge, model
from pyefis.flightplan.model import FlightPlan, FlightPlanError, Segment, Waypoint
from tests.flightplan.test_fixbridge import _define, _define_all_fp1_keys

_SCHEMA = """
CREATE TABLE airways (id INTEGER PRIMARY KEY, ident TEXT NOT NULL, cycle TEXT NOT NULL);
CREATE TABLE airway_legs (
    airway_id INTEGER NOT NULL, seq INTEGER NOT NULL, fix_id TEXT NOT NULL,
    fix_lat REAL, fix_lon REAL, fix_type TEXT, min_alt_ft INTEGER, max_alt_ft INTEGER,
    direction TEXT);
CREATE INDEX idx_awy_ident ON airways(ident);
CREATE INDEX idx_awyleg_awy ON airway_legs(airway_id, seq);
CREATE INDEX idx_awyleg_fix ON airway_legs(fix_id);
"""

# V27: GVO .. AVOLS, two-way. MEA is coded on the row that ends the leg.
V27 = [(10, "GVO", 34.53, -120.09, 5000, None), (20, "AFOXY", 34.61, -120.16, 6000, None),
       (30, "ORCUT", 34.85, -120.39, 7000, None), (40, "AVOLS", 35.10, -120.60, 8000, None)]
# A1: the ALPHA -> ZULUU direction only from WOODY on ("F" on the legs that
# end at WISKI and ZULUU), so it cannot be inverted across those legs.
A1 = [(10, "ALPHA", 35.0, -118.0, 3000, None), (20, "WOODY", 35.5, -118.2, 4000, None),
      (30, "WISKI", 36.0, -118.4, 5000, "F"), (40, "ZULUU", 36.5, -118.6, 5000, "F")]


def _build_pack(path, cycle="2610", v27=V27):
    if path.exists():
        path.unlink()
    con = sqlite3.connect(str(path))
    con.executescript(_SCHEMA)
    for ident, legs in (("V27", v27), ("A1", A1)):
        awy = con.execute("INSERT INTO airways (ident, cycle) VALUES (?, ?)",
                          (ident, cycle)).lastrowid
        for seq, fix_id, lat, lon, mea, direction in legs:
            con.execute("INSERT INTO airway_legs VALUES (?, ?, ?, ?, ?, 'waypoint', ?, 18000, ?)",
                        (awy, seq, fix_id, lat, lon, mea, direction))
    con.commit()
    con.close()
    return path


@pytest.fixture()
def graph(tmp_path):
    g = airways.AirwayGraph(_build_pack(tmp_path / "procedures.pack"))
    yield g
    g.close()


KSBA = Waypoint(id="KSBA", type="airport", lat=34.43, lon=-119.84)
GVO = Waypoint(id="GVO", type="vor", lat=34.53, lon=-120.09)
KSMX = Waypoint(id="KSMX", type="airport", lat=34.90, lon=-120.46)
ALPHA = Waypoint(id="ALPHA", type="fix", lat=35.0, lon=-118.0)


def _golden(graph):
    """KSBA GVO V27 AVOLS KSMX -- the PA6/PA16 bench route (brief 9)."""
    plan = FlightPlan(name="GOLD", waypoints=[KSBA.copy(), GVO.copy(), KSMX.copy()])
    plan.insert_airway(1, "V27", "AVOLS", graph)
    return plan


def _shape(plan):
    return [(s.kind, s.ident, [w.id for w in s.legs]) for s in plan.segments]


# ---------------------------------------------------------------------------
# the model
# ---------------------------------------------------------------------------
def test_insert_airway_makes_one_segment_entered_at_its_own_first_leg(graph):
    plan = _golden(graph)
    assert _shape(plan) == [
        ("waypoint", "", ["KSBA"]),
        ("airway", "V27", ["GVO", "AFOXY", "ORCUT", "AVOLS"]),
        ("waypoint", "", ["KSMX"])]
    v27 = plan.segments[1]
    assert (v27.entry, v27.exit, v27.cycle) == ("GVO", "AVOLS", "2610")
    # waypoints is the flat view every pre-RS2 reader uses
    assert [w.id for w in plan.waypoints] == ["KSBA", "GVO", "AFOXY", "ORCUT", "AVOLS", "KSMX"]
    assert [w.alt for w in v27.legs] == ["", "+6000", "+7000", "+8000"]
    assert plan.segment_span(1) == (1, 4)


def test_insert_airway_errors_are_flight_plan_errors(graph):
    plan = FlightPlan(waypoints=[GVO.copy()])
    with pytest.raises(FlightPlanError, match="not on airway"):
        plan.insert_airway(0, "V27", "NOPE", graph)
    with pytest.raises(FlightPlanError, match="unknown airway"):
        plan.insert_airway(0, "V99", "AVOLS", graph)
    assert _shape(plan) == [("waypoint", "", ["GVO"])]


def test_insert_airway_is_all_or_nothing_at_the_slot_cap(graph):
    plan = FlightPlan(waypoints=[Waypoint(id=f"W{i}", type="fix", lat=0, lon=0)
                                 for i in range(model.MAX_WAYPOINTS - 2)] + [GVO.copy()])
    with pytest.raises(FlightPlanError, match="route full"):
        plan.insert_airway(plan.count - 1, "V27", "AVOLS", graph)
    assert plan.count == model.MAX_WAYPOINTS - 1


def test_chained_airway_starts_after_the_shared_fix(graph, tmp_path):
    """V27 exits at ORCUT; a second airway loaded from ORCUT cannot own it
    too (one segment per slot), so it starts at the next fix."""
    plan = FlightPlan(waypoints=[GVO.copy()])
    plan.insert_airway(0, "V27", "ORCUT", graph)
    plan.insert_airway(2, "V27", "GVO", graph)  # back the way it came
    assert _shape(plan) == [("airway", "V27", ["GVO", "AFOXY", "ORCUT"]),
                            ("airway", "V27", ["AFOXY", "GVO"])]


def test_load_airway_from_inside_another_airway_is_refused(graph):
    plan = _golden(graph)
    with pytest.raises(FlightPlanError, match="inside V27"):
        plan.insert_airway(2, "V27", "GVO", graph)


def test_remove_segment_undoes_insert_airway(graph):
    plan = _golden(graph)
    plan.remove_segment(1)
    assert _shape(plan) == [("waypoint", "", ["KSBA"]), ("waypoint", "", ["GVO"]),
                            ("waypoint", "", ["KSMX"])]
    assert plan.waypoints[1].alt == ""


def test_change_exit_and_change_entry_re_expand(graph):
    plan = _golden(graph)
    plan.change_exit(1, "ORCUT", graph)
    assert _shape(plan)[1] == ("airway", "V27", ["GVO", "AFOXY", "ORCUT"])
    plan.change_entry(1, "AFOXY", graph)
    assert _shape(plan)[1] == ("airway", "V27", ["AFOXY", "ORCUT"])
    with pytest.raises(FlightPlanError):
        plan.change_exit(0, "AVOLS", graph)  # segment 0 is not an airway
    with pytest.raises(FlightPlanError):
        plan.change_exit(1, "AFOXY", graph)  # entry == exit


def test_split_at_keeps_the_remainder_an_airway(graph):
    plan = _golden(graph)
    head, tail = plan.split_at(1, "ORCUT")
    assert (head.kind, [w.id for w in head.legs]) == ("airway", ["GVO", "AFOXY"])
    assert (tail.kind, tail.entry, tail.exit) == ("airway", "ORCUT", "AVOLS")
    assert plan.count == 6


def test_split_at_leaves_a_one_fix_piece_as_a_waypoint(graph):
    plan = _golden(graph)
    plan.split_at(1, "AFOXY")
    assert _shape(plan)[1:3] == [("waypoint", "", ["GVO"]),
                                 ("airway", "V27", ["AFOXY", "ORCUT", "AVOLS"])]


def test_insert_or_remove_inside_an_airway_never_orphans_a_leg(graph):
    plan = _golden(graph)
    plan.insert_after(2, Waypoint(id="USR1", type="user", lat=34.7, lon=-120.3))
    assert _shape(plan)[1:4] == [("airway", "V27", ["GVO", "AFOXY"]),
                                 ("waypoint", "", ["USR1"]),
                                 ("airway", "V27", ["ORCUT", "AVOLS"])]
    plan.remove(4)  # ORCUT: what is left of that piece is one fix
    assert _shape(plan)[3:] == [("waypoint", "", ["AVOLS"]), ("waypoint", "", ["KSMX"])]
    assert [w.id for w in plan.waypoints] == ["KSBA", "GVO", "AFOXY", "USR1", "AVOLS", "KSMX"]


def test_segment_validation_mirrors_the_engine_rules():
    with pytest.raises(FlightPlanError):
        Segment(kind="airway", ident="V27", legs=[GVO.copy()])          # SEGLEN
    with pytest.raises(FlightPlanError):
        Segment(kind="airway", ident="", legs=[GVO.copy(), KSMX.copy()])  # SEGID
    with pytest.raises(FlightPlanError):
        Segment(kind="waypoint", ident="X", legs=[GVO.copy()])          # SEGID
    with pytest.raises(FlightPlanError):
        Segment(kind="waypoint", legs=[GVO.copy(), KSMX.copy()])        # SEGLEN
    with pytest.raises(FlightPlanError):
        Segment(kind="airway", ident="X" * 25, legs=[GVO.copy(), KSMX.copy()])
    with pytest.raises(FlightPlanError):
        Segment(kind="direct", legs=[GVO.copy()])                       # SEGKIND


# ---------------------------------------------------------------------------
# invert
# ---------------------------------------------------------------------------
def test_invert_reverses_segments_and_swaps_airway_entry_and_exit(graph):
    inverted = _golden(graph).invert(graph)
    assert _shape(inverted) == [
        ("waypoint", "", ["KSMX"]),
        ("airway", "V27", ["AVOLS", "ORCUT", "AFOXY", "GVO"]),
        ("waypoint", "", ["KSBA"])]
    v27 = inverted.segments[1]
    assert (v27.entry, v27.exit) == ("AVOLS", "GVO")
    # Flying it backward, the leg into each fix is the published leg that
    # ends at the fix before it: ORCUT <- AVOLS is coded on AVOLS (8000).
    assert [w.alt for w in v27.legs] == ["", "+8000", "+7000", "+6000"]
    assert inverted.name == "KSMX-KSBA"


def test_invert_across_a_one_way_airway_is_refused_with_the_reason(graph):
    plan = FlightPlan(waypoints=[ALPHA.copy()])
    plan.insert_airway(0, "A1", "ZULUU", graph)
    with pytest.raises(FlightPlanError, match=r"cannot invert: A1 is one-way"):
        plan.invert(graph)
    assert _shape(plan) == [("airway", "A1", ["ALPHA", "WOODY", "WISKI", "ZULUU"])]


def test_invert_with_airways_and_no_pack_is_refused(graph, tmp_path):
    plan = _golden(graph)
    with pytest.raises(FlightPlanError, match="no airway data"):
        plan.invert(None)
    with pytest.raises(FlightPlanError, match="no airway data"):
        plan.invert(airways.AirwayGraph(tmp_path / "missing.pack"))


def test_invert_without_airways_needs_no_pack():
    plan = FlightPlan(waypoints=[KSBA.copy(), KSMX.copy()])
    assert [w.id for w in plan.invert().waypoints] == ["KSMX", "KSBA"]


def test_invert_turns_a_procedure_back_into_plain_waypoints():
    plan = FlightPlan(segments=[
        model.waypoint_segment(KSBA.copy()),
        Segment(kind="approach", ident="R25.SBA", legs=[GVO.copy(role="faf"), KSMX.copy(
            role="map", pt="TF", alt="@1200")])])
    assert _shape(plan.invert()) == [("waypoint", "", ["KSMX"]), ("waypoint", "", ["GVO"]),
                                     ("waypoint", "", ["KSBA"])]
    assert all(w.role == "none" and w.alt == "" for w in plan.invert().waypoints)


# ---------------------------------------------------------------------------
# store / load (mp-route/2) and the AIRAC check
# ---------------------------------------------------------------------------
def test_store_and_load_keeps_the_airway(graph, tmp_path):
    cat = catalog.Catalog(tmp_path / "routes")
    slug = cat.save(_golden(graph))
    stored = json.loads((tmp_path / "routes" / f"{slug}.json").read_text())
    assert stored["schema"] == "mp-route/2"
    assert stored["segments"][1] | {"legs": None} == {
        "kind": "airway", "ident": "V27", "entry": "GVO", "exit": "AVOLS", "cycle": "2610",
        "legs": None}

    for loaded in (cat.load(slug), cat.load(slug, graph)):
        assert _shape(loaded) == _shape(_golden(graph))
        assert loaded.segments[1].cycle == "2610"
        assert loaded.notices == []


def test_v1_route_loads_as_waypoints_and_saves_as_v2(tmp_path):
    routes = tmp_path / "routes"
    routes.mkdir()
    (routes / "old.json").write_text(json.dumps({
        "schema": "mp-route/1", "name": "OLD", "waypoints": [
            {"id": "GVO", "type": "vor", "lat": 34.53, "lon": -120.09},
            {"id": "AFOXY", "type": "fix", "lat": 34.61, "lon": -120.16, "airway": "V27"}]}))
    cat = catalog.Catalog(routes)
    plan = cat.load("old")
    assert _shape(plan) == [("waypoint", "", ["GVO"]), ("waypoint", "", ["AFOXY"])]
    assert plan.waypoints[1].extra == {}  # PA6's display tag is not carried forward
    cat.save(plan, "old")
    assert json.loads((routes / "old.json").read_text())["schema"] == "mp-route/2"


def test_airac_change_re_expands_and_surfaces_the_change(graph, tmp_path):
    cat = catalog.Catalog(tmp_path / "routes")
    slug = cat.save(_golden(graph))
    # The next cycle withdraws ORCUT from V27.
    new_v27 = [leg for leg in V27 if leg[1] != "ORCUT"]
    newer = airways.AirwayGraph(_build_pack(tmp_path / "next.pack", "2611", new_v27))
    try:
        plan = cat.load(slug, newer)
    finally:
        newer.close()
    assert _shape(plan)[1] == ("airway", "V27", ["GVO", "AFOXY", "AVOLS"])
    assert plan.segments[1].cycle == "2611"
    assert plan.notices == [
        "V27 changed since this plan was saved (GVO AFOXY ORCUT AVOLS -> GVO AFOXY AVOLS)"]


def test_airac_change_with_the_same_fixes_is_silent(graph, tmp_path):
    cat = catalog.Catalog(tmp_path / "routes")
    slug = cat.save(_golden(graph))
    newer = airways.AirwayGraph(_build_pack(tmp_path / "next.pack", "2611"))
    try:
        plan = cat.load(slug, newer)
    finally:
        newer.close()
    assert plan.segments[1].cycle == "2611"
    assert plan.notices == []


def test_airac_change_that_breaks_the_airway_still_loads_and_says_so(graph, tmp_path):
    cat = catalog.Catalog(tmp_path / "routes")
    slug = cat.save(_golden(graph))
    gone = [leg for leg in V27 if leg[1] != "AVOLS"]
    newer = airways.AirwayGraph(_build_pack(tmp_path / "next.pack", "2611", gone))
    try:
        plan = cat.load(slug, newer)
    finally:
        newer.close()
    assert _shape(plan)[1] == ("airway", "V27", ["GVO", "AFOXY", "ORCUT", "AVOLS"])
    assert plan.segments[1].cycle == "2610"
    assert len(plan.notices) == 1
    assert plan.notices[0].startswith("V27 could not be checked against the current data")
    assert "AVOLS" in plan.notices[0]


def test_catalog_invert_runs_the_direction_check(graph, tmp_path):
    cat = catalog.Catalog(tmp_path / "routes")
    plan = FlightPlan(name="ONEWAY", waypoints=[ALPHA.copy()])
    plan.insert_airway(0, "A1", "ZULUU", graph)
    cat.save(plan, "oneway")
    with pytest.raises(FlightPlanError, match="one-way"):
        cat.invert("oneway", graph)
    slug = cat.save(_golden(graph))
    assert _shape(cat.invert(slug, graph))[1][2] == ["AVOLS", "ORCUT", "AFOXY", "GVO"]


# ---------------------------------------------------------------------------
# the bus
# ---------------------------------------------------------------------------
def _published(fix, plan):
    _define_all_fp1_keys(fix)
    bridge = fixbridge.FixBridge(fix)
    bridge.publish(plan)
    return bridge


def test_golden_route_table_matches_the_contract_example(fix, graph):
    """fix-gateway doc/flightplan_keys.md's worked example, with V27
    expanded to this fixture's four fixes."""
    _published(fix, _golden(graph))
    db = fix.db
    rows = [[db.get_item(f"FPLS{k}{f}").value for f in ("KIND", "ID", "ENT", "EXT", "FIRST", "LAST")]
            for k in range(1, db.get_item("FPLSEGCNT").value + 1)]
    assert rows == [[0, "", "KSBA", "KSBA", 1, 1], [1, "V27", "GVO", "AVOLS", 2, 5],
                    [0, "", "KSMX", "KSMX", 6, 6]]
    assert [db.get_item(f"FPL{n}SGI").value for n in range(1, 7)] == [1, 2, 2, 2, 2, 3]
    assert db.get_item("FPLDBCYC").value == "2610"


def test_a_restarted_bridge_reads_the_airway_back(fix, graph):
    plan = _golden(graph)
    _published(fix, plan)
    restarted = fixbridge.FixBridge(fix)
    back = restarted.read_plan()
    assert _shape(back) == _shape(plan)
    assert back.segments[1].cycle == "2610"
    assert [w.alt for w in back.waypoints] == [w.alt for w in plan.waypoints]


def test_published_course_is_magnetic(fix):
    """FPLfCRS is magnetic (MAG = TRUE + VAR, positive west), the convention
    the engine converts FPLCRS with -- not the true bearing the page drew."""
    _define_all_fp1_keys(fix)
    _define(fix, "MAGVAR", "float", 12.0)
    bridge = fixbridge.FixBridge(fix)
    a = Waypoint(id="A", type="fix", lat=0.0, lon=0.0)
    b = Waypoint(id="B", type="fix", lat=0.0, lon=1.0)  # due east, true 090
    bridge.publish(FlightPlan(waypoints=[a, b]))
    assert fix.db.get_item("FPL1CRS").value == 0.0
    assert fix.db.get_item("FPL2CRS").value == pytest.approx(102.0)
    # A derived course is not read back as a coded one: it would freeze
    # today's variation into the plan.
    assert bridge.read_plan().waypoints[1].crs is None


def test_every_slot_field_round_trips(fix):
    leg = Waypoint(id="SBA25", type="fix", lat=34.4, lon=-119.8, pt="RF", crs=250.0,
                   dst=2.5, alt="B2900,4000", spd=180, flags=0x01, role="faf",
                   ctr_lat=34.3, ctr_lon=-119.7, turn="L")
    first = Waypoint(id="IAF", type="fix", lat=34.5, lon=-119.6, pt="IF", role="iaf")
    plan = FlightPlan(segments=[Segment(kind="approach", ident="R25.SBA", legs=[first, leg])])
    _published(fix, plan)
    back = fixbridge.FixBridge(fix).read_plan()
    got = back.waypoints[1]
    assert (got.pt, got.dst, got.alt, got.spd, got.flags, got.role, got.ctr_lat, got.ctr_lon,
            got.turn) == ("RF", 2.5, "B2900,4000", 180, 0x01, "faf", 34.3, -119.7, "L")
    assert fix.db.get_item("FPL2FLAGS").value == 0x01 | fixbridge.ROLE_TO_FLAG["faf"]
    assert _shape(back) == [("approach", "R25.SBA", ["IAF", "SBA25"])]


def test_a_table_that_does_not_describe_the_slots_reads_as_waypoints(fix, graph):
    _published(fix, _golden(graph))
    fix.db.set_value("FPLS2LAST", 4)  # SEGRANGE: the engine would refuse this
    back = fixbridge.FixBridge(fix).read_plan()
    assert [s.kind for s in back.segments] == ["waypoint"] * 6
    assert [w.id for w in back.waypoints] == ["KSBA", "GVO", "AFOXY", "ORCUT", "AVOLS", "KSMX"]


def test_shrinking_the_route_blanks_the_old_segment_rows(fix, graph):
    bridge = _published(fix, _golden(graph))
    bridge.publish(FlightPlan(waypoints=[KSBA.copy()]))
    assert fix.db.get_item("FPLSEGCNT").value == 1
    assert fix.db.get_item("FPLS2KIND").value == 0
    assert fix.db.get_item("FPLS2ID").value == ""
    assert fix.db.get_item("FPLS3FIRST").value == 0
    assert fix.db.get_item("FPLDBCYC").value == ""
