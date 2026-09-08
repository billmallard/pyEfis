#  SPDX-License-Identifier: GPL-2.0-or-later
"""Tests for pyefis.flightplan.model -- FP4 (billmallard/pyEfis#183)."""

import pytest

from pyefis.flightplan.model import (
    FlightPlan,
    FlightPlanError,
    MAX_WAYPOINTS,
    SCHEMA,
    Waypoint,
)

KSBA = Waypoint(id="KSBA", type="airport", lat=34.42621, lon=-119.84037, name="Santa Barbara Muni")
GVO = Waypoint(id="GVO", type="vor", lat=34.53142, lon=-120.09106)
USR001 = Waypoint(id="USR001", type="user", lat=34.7, lon=-120.3, comment="RIDGE")
ZUMAB = Waypoint(id="ZUMAB", type="fix", lat=34.95, lon=-120.30)
RW30 = Waypoint(id="RW30", type="map", lat=34.90, lon=-120.44)
KSMX = Waypoint(id="KSMX", type="airport", lat=34.89892, lon=-120.45758)


def _route(*wps):
    # Fresh Waypoint copies -- the module-level fixtures above are shared
    # across tests, and set_role()/invert() mutate/consume in place.
    fresh = [Waypoint(id=w.id, type=w.type, lat=w.lat, lon=w.lon, name=w.name,
                       alt_ft=w.alt_ft, comment=w.comment) for w in wps]
    return FlightPlan(name="", comment="", waypoints=fresh)


# ---------------------------------------------------------------------------
# Waypoint
# ---------------------------------------------------------------------------
def test_waypoint_rejects_unknown_type():
    with pytest.raises(FlightPlanError):
        Waypoint(id="X", type="blimp", lat=0, lon=0)


def test_waypoint_rejects_unknown_role():
    with pytest.raises(FlightPlanError):
        Waypoint(id="X", type="fix", lat=0, lon=0, role="bogus")


# ---------------------------------------------------------------------------
# Editing
# ---------------------------------------------------------------------------
def test_insert_before_and_after():
    plan = _route(KSBA, KSMX)
    plan.insert_before(1, GVO)
    assert [w.id for w in plan.waypoints] == ["KSBA", "GVO", "KSMX"]
    plan.insert_after(1, USR001)
    assert [w.id for w in plan.waypoints] == ["KSBA", "GVO", "USR001", "KSMX"]


def test_insert_rejects_out_of_range_index():
    plan = _route(KSBA)
    with pytest.raises(FlightPlanError):
        plan.insert_before(5, GVO)
    with pytest.raises(FlightPlanError):
        plan.insert_after(5, GVO)


def test_remove_returns_waypoint():
    plan = _route(KSBA, GVO, KSMX)
    removed = plan.remove(1)
    assert removed.id == "GVO"
    assert [w.id for w in plan.waypoints] == ["KSBA", "KSMX"]


def test_remove_rejects_out_of_range_index():
    plan = _route(KSBA)
    with pytest.raises(FlightPlanError):
        plan.remove(3)


def test_insert_and_remove_respect_50_waypoint_cap():
    plan = FlightPlan(waypoints=[
        Waypoint(id=f"WP{i}", type="fix", lat=0.0, lon=float(i)) for i in range(MAX_WAYPOINTS)
    ])
    with pytest.raises(FlightPlanError):
        plan.insert_after(0, GVO)
    plan.remove(0)
    plan.insert_after(0, GVO)  # room for one now
    assert plan.count == MAX_WAYPOINTS


def test_constructing_over_cap_raises():
    with pytest.raises(FlightPlanError):
        FlightPlan(waypoints=[
            Waypoint(id=f"WP{i}", type="fix", lat=0.0, lon=float(i))
            for i in range(MAX_WAYPOINTS + 1)
        ])


# ---------------------------------------------------------------------------
# invert()
# ---------------------------------------------------------------------------
def test_invert_reverses_waypoints():
    plan = _route(KSBA, GVO, KSMX)
    inverted = plan.invert()
    assert [w.id for w in inverted.waypoints] == ["KSMX", "GVO", "KSBA"]
    # original untouched
    assert [w.id for w in plan.waypoints] == ["KSBA", "GVO", "KSMX"]


def test_invert_clears_roles():
    plan = _route(KSBA, ZUMAB, RW30, KSMX)
    plan.set_role(1, "faf")
    plan.set_role(2, "map")
    inverted = plan.invert()
    assert all(w.role == "none" for w in inverted.waypoints)
    assert plan.approach() == (1, 2)  # original plan's roles survive


def test_invert_default_name():
    plan = _route(KSBA, KSMX)
    inverted = plan.invert()
    assert inverted.name == "KSMX-KSBA"


# ---------------------------------------------------------------------------
# set_role / approach
# ---------------------------------------------------------------------------
def test_set_role_faf_then_map():
    plan = _route(KSBA, ZUMAB, RW30, KSMX)
    plan.set_role(1, "faf")
    plan.set_role(2, "map")
    assert plan.approach() == (1, 2)
    assert plan.waypoints[1].role == "faf"
    assert plan.waypoints[2].role == "map"


def test_set_role_refuses_second_faf():
    plan = _route(KSBA, ZUMAB, RW30, KSMX)
    plan.set_role(1, "faf")
    with pytest.raises(FlightPlanError):
        plan.set_role(2, "faf")


def test_set_role_refuses_second_map():
    plan = _route(KSBA, ZUMAB, RW30, KSMX)
    plan.set_role(2, "map")
    with pytest.raises(FlightPlanError):
        plan.set_role(3, "map")


def test_set_role_refuses_map_before_faf():
    plan = _route(KSBA, ZUMAB, RW30, KSMX)
    plan.set_role(2, "faf")
    with pytest.raises(FlightPlanError):
        plan.set_role(1, "map")


def test_set_role_refuses_faf_after_existing_map():
    plan = _route(KSBA, ZUMAB, RW30, KSMX)
    plan.set_role(1, "map")
    with pytest.raises(FlightPlanError):
        plan.set_role(2, "faf")


def test_set_role_can_reassign_same_slot():
    plan = _route(KSBA, ZUMAB, RW30, KSMX)
    plan.set_role(1, "faf")
    plan.set_role(1, "iaf")  # replacing the FAF at the same slot is fine
    assert plan.waypoints[1].role == "iaf"
    assert plan.approach() is None


def test_set_role_none_always_allowed():
    plan = _route(KSBA, ZUMAB, RW30, KSMX)
    plan.set_role(1, "faf")
    plan.set_role(2, "map")
    plan.set_role(1, "none")
    assert plan.approach() is None


def test_set_role_iaf_and_mahp_unconstrained():
    plan = _route(KSBA, GVO, ZUMAB, RW30, KSMX)
    plan.set_role(0, "iaf")
    plan.set_role(4, "mahp")
    assert plan.waypoints[0].role == "iaf"
    assert plan.waypoints[4].role == "mahp"


def test_set_role_rejects_bad_index_and_role():
    plan = _route(KSBA)
    with pytest.raises(FlightPlanError):
        plan.set_role(5, "faf")
    with pytest.raises(FlightPlanError):
        plan.set_role(0, "bogus")


def test_approach_none_without_both_roles():
    plan = _route(KSBA, ZUMAB, KSMX)
    assert plan.approach() is None
    plan.set_role(1, "faf")
    assert plan.approach() is None


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------
def test_leg_and_total_and_cumulative_ksba_ksmx():
    plan = _route(KSBA, KSMX)
    dtk, dist = plan.leg(0)
    assert dist == pytest.approx(41.648, abs=1e-3)
    assert dtk == pytest.approx(313.13, abs=0.01)
    assert plan.total_nm == pytest.approx(41.648, abs=1e-3)
    assert plan.cumulative(0) == 0.0
    assert plan.cumulative(1) == pytest.approx(41.648, abs=1e-3)


def test_total_nm_zero_for_single_or_empty_plan():
    assert _route(KSBA).total_nm == 0.0
    assert _route().total_nm == 0.0


def test_leg_rejects_out_of_range():
    plan = _route(KSBA)
    with pytest.raises(FlightPlanError):
        plan.leg(0)


def test_default_name():
    assert _route(KSBA, GVO, KSMX).default_name() == "KSBA-KSMX"
    assert _route().default_name() == ""


# ---------------------------------------------------------------------------
# JSON round-trip (Appendix B, "mp-route/1")
# ---------------------------------------------------------------------------
def test_json_round_trip_basic():
    plan = FlightPlan(name="KSBA-KSMX", comment="test route",
                       waypoints=[KSBA, GVO, USR001, KSMX], source="device")
    data = plan.to_json()
    assert data["schema"] == SCHEMA
    assert data["name"] == "KSBA-KSMX"
    assert [w["id"] for w in data["waypoints"]] == ["KSBA", "GVO", "USR001", "KSMX"]

    back = FlightPlan.from_json(data)
    assert back.name == plan.name
    assert [w.id for w in back.waypoints] == [w.id for w in plan.waypoints]
    assert back.waypoints[0].name == "Santa Barbara Muni"
    assert back.waypoints[2].comment == "RIDGE"


def test_json_round_trip_preserves_roles():
    plan = _route(KSBA, ZUMAB, RW30, KSMX)
    plan.set_role(1, "faf")
    plan.set_role(2, "map")
    back = FlightPlan.from_json(plan.to_json())
    assert back.approach() == (1, 2)
    assert back.waypoints[1].role == "faf"
    assert back.waypoints[2].role == "map"


def test_json_round_trip_preserves_unknown_plan_fields():
    data = {
        "schema": SCHEMA, "name": "X", "comment": "", "created": "", "modified": "",
        "source": "device", "waypoints": [], "future_field": {"nested": True},
    }
    plan = FlightPlan.from_json(data)
    assert plan.extra == {"future_field": {"nested": True}}
    round_tripped = plan.to_json()
    assert round_tripped["future_field"] == {"nested": True}


def test_json_round_trip_preserves_unknown_waypoint_fields():
    data = {
        "schema": SCHEMA, "name": "X", "comment": "", "created": "", "modified": "",
        "source": "device",
        "waypoints": [{"id": "KSBA", "type": "airport", "lat": 1.0, "lon": 2.0,
                       "future_field": "kept"}],
    }
    plan = FlightPlan.from_json(data)
    assert plan.waypoints[0].extra == {"future_field": "kept"}
    assert plan.to_json()["waypoints"][0]["future_field"] == "kept"


def test_from_json_rejects_unknown_schema():
    with pytest.raises(FlightPlanError):
        FlightPlan.from_json({"schema": "mp-route/2", "waypoints": []})


def test_to_json_falls_back_to_default_name():
    plan = _route(KSBA, KSMX)
    assert plan.to_json()["name"] == "KSBA-KSMX"


def test_appendix_b_example_round_trips():
    data = {
        "schema": "mp-route/1",
        "name": "KSBA-KSMX",
        "comment": "",
        "created": "2026-09-07T20:00:00Z",
        "modified": "2026-09-07T20:05:00Z",
        "source": "device",
        "waypoints": [
            {"id": "KSBA", "type": "airport", "lat": 34.42621, "lon": -119.84037,
             "name": "Santa Barbara Muni", "alt_ft": None},
            {"id": "GVO", "type": "vor", "lat": 34.53142, "lon": -120.09106},
            {"id": "USR001", "type": "user", "lat": 34.7, "lon": -120.3,
             "comment": "RIDGE"},
            {"id": "ZUMAB", "type": "fix", "lat": 34.95, "lon": -120.30, "role": "faf"},
            {"id": "RW30", "type": "map", "lat": 34.90, "lon": -120.44, "role": "map"},
            {"id": "KSMX", "type": "airport", "lat": 34.89892, "lon": -120.45758},
        ],
    }
    plan = FlightPlan.from_json(data)
    assert plan.count == 6
    assert plan.approach() == (3, 4)
    back = plan.to_json()
    assert back["waypoints"][3]["role"] == "faf"
    assert back["waypoints"][4]["role"] == "map"
    assert "role" not in back["waypoints"][0]  # default role omitted


# ---------------------------------------------------------------------------
# Qt-free
# ---------------------------------------------------------------------------
def test_no_qt_import():
    import subprocess
    import sys
    from pathlib import Path

    src_root = str(Path(__file__).resolve().parents[2] / "src")
    code = (
        "import sys\n"
        "import pyefis.flightplan.model\n"
        "assert 'PyQt6' not in sys.modules, sorted(m for m in sys.modules if 'PyQt' in m)\n"
    )
    result = subprocess.run([sys.executable, "-c", code], cwd=src_root,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
