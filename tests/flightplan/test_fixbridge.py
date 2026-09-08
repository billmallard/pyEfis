#  SPDX-License-Identifier: GPL-2.0-or-later
"""Tests for pyefis.flightplan.fixbridge -- FP4 (billmallard/pyEfis#183).

Uses the repo's ``fix`` pytest fixture (``conftest.py``, the mock FIX
database also used by ``tests/instruments/hsi/test_hsi.py``) and defines the
Appendix A flight-plan keys on it directly, since FP1 (fix-gateway) is a
separate repo and its ``database/flightplan.yaml`` is not part of this
fixture.
"""

import subprocess
import sys
from pathlib import Path

import pytest

from pyefis.flightplan import fixbridge, model


# DB_Item's min/max setters do `self.dtype(x)` with no ValueError guard for
# None on int/float (str(None) and bool(None) are harmless; int(None) and
# float(None) raise TypeError) -- so int/float keys need real numeric bounds,
# unlike the bool/str `None, None` convention conftest.py uses elsewhere.
_WIDE_BOUNDS = {"float": (-1e9, 1e9), "int": (-1_000_000, 1_000_000),
                "bool": (None, None), "str": (None, None)}


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
}
_ENGINE_DEFAULTS = {"int": 0, "float": 0.0, "bool": False, "str": ""}


def _define_all_fp1_keys(fix):
    """Defines the full Appendix A route block (all 50 slots), staging,
    command and engine-output keys on the fixture's mock FIX database."""
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


def _plan(n):
    return model.FlightPlan(name="TEST", waypoints=[
        model.Waypoint(id=f"WP{i:02d}", type="fix", lat=float(i), lon=float(i))
        for i in range(n)
    ])


# ---------------------------------------------------------------------------
# available
# ---------------------------------------------------------------------------
def test_available_false_with_no_keys_and_nothing_raises(fix):
    bridge = fixbridge.FixBridge(fix)
    assert bridge.available is False
    # every method must be a safe no-op, never raise
    bridge.publish(_plan(3))
    bridge.stage_direct_to(model.Waypoint(id="X", type="fix", lat=0, lon=0))
    assert bridge.command("ACT", 1) is None
    assert bridge.read_route() is None
    assert bridge.read_engine() is None


def test_available_true_with_all_fp1_keys_defined(fix):
    _define_all_fp1_keys(fix)
    bridge = fixbridge.FixBridge(fix)
    assert bridge.available is True


# ---------------------------------------------------------------------------
# publish
# ---------------------------------------------------------------------------
def test_publish_writes_slots_in_order_and_seq_last(fix):
    _define_all_fp1_keys(fix)
    bridge = fixbridge.FixBridge(fix)

    order = []
    real_set_value = fix.db.set_value

    def tracking_set_value(key, value):
        order.append(key)
        real_set_value(key, value)

    fix.db.set_value = tracking_set_value
    try:
        bridge.publish(_plan(2))
    finally:
        fix.db.set_value = real_set_value

    # slot 1 fields, then slot 2 fields, then count/name, then seq last
    assert order == [
        "FPL1ID", "FPL1LAT", "FPL1LON", "FPL1TYPE", "FPL1ROLE",
        "FPL2ID", "FPL2LAT", "FPL2LON", "FPL2TYPE", "FPL2ROLE",
        "FPLCOUNT", "FPLNAME", "FPLSEQ",
    ]
    assert fix.db.get_item("FPL1ID").value == "WP00"
    assert fix.db.get_item("FPL2ID").value == "WP01"
    assert fix.db.get_item("FPLCOUNT").value == 2
    assert fix.db.get_item("FPLNAME").value == "TEST"
    assert fix.db.get_item("FPLSEQ").value == 1


def test_publish_bumps_seq_by_one_each_time(fix):
    _define_all_fp1_keys(fix)
    bridge = fixbridge.FixBridge(fix)
    bridge.publish(_plan(1))
    bridge.publish(_plan(1))
    assert fix.db.get_item("FPLSEQ").value == 2


def test_publish_blanks_trailing_slots_on_shrink(fix):
    _define_all_fp1_keys(fix)
    bridge = fixbridge.FixBridge(fix)
    bridge.publish(_plan(20))
    assert fix.db.get_item("FPL20ID").value == "WP19"

    bridge.publish(_plan(3))
    assert fix.db.get_item("FPLCOUNT").value == 3
    for n in range(4, 21):
        id_key, lat_key, lon_key, type_key, role_key = fixbridge._slot_keys(n)
        assert fix.db.get_item(id_key).value == "", f"slot {n} id not blanked"
        assert fix.db.get_item(lat_key).value == 0.0, f"slot {n} lat not blanked"
        assert fix.db.get_item(type_key).value == 0, f"slot {n} type not blanked"
    # untouched, in-use slots survive
    assert fix.db.get_item("FPL1ID").value == "WP00"
    assert fix.db.get_item("FPL3ID").value == "WP02"


def test_publish_writes_role_and_type_codes(fix):
    _define_all_fp1_keys(fix)
    bridge = fixbridge.FixBridge(fix)
    plan = model.FlightPlan(name="APR", waypoints=[
        model.Waypoint(id="ZUMAB", type="fix", lat=1.0, lon=2.0, role="faf"),
        model.Waypoint(id="RW30", type="map", lat=3.0, lon=4.0, role="map"),
    ])
    bridge.publish(plan)
    assert fix.db.get_item("FPL1TYPE").value == 4  # fix
    assert fix.db.get_item("FPL1ROLE").value == 2  # faf
    assert fix.db.get_item("FPL2TYPE").value == 6  # map
    assert fix.db.get_item("FPL2ROLE").value == 3  # map


# ---------------------------------------------------------------------------
# stage_direct_to
# ---------------------------------------------------------------------------
def test_stage_direct_to_writes_dto_keys(fix):
    _define_all_fp1_keys(fix)
    bridge = fixbridge.FixBridge(fix)
    bridge.stage_direct_to(model.Waypoint(id="RZS", type="vor", lat=34.02, lon=-119.55))
    assert fix.db.get_item("DTOID").value == "RZS"
    assert fix.db.get_item("DTOLAT").value == pytest.approx(34.02)
    assert fix.db.get_item("DTOLON").value == pytest.approx(-119.55)
    assert fix.db.get_item("DTOTYPE").value == 2  # vor


# ---------------------------------------------------------------------------
# command / ack
# ---------------------------------------------------------------------------
def test_command_seq_increments_and_writes_fplcmd(fix):
    _define_all_fp1_keys(fix)
    bridge = fixbridge.FixBridge(fix)
    seq1 = bridge.command("ACT", 3)
    assert seq1 == 1
    assert fix.db.get_item("FPLCMD").value == "1 ACT 3"
    seq2 = bridge.command("SUSP")
    assert seq2 == 2
    assert fix.db.get_item("FPLCMD").value == "2 SUSP"


def test_command_ack_callback_fires_ok_true_on_positive_ack(fix):
    _define_all_fp1_keys(fix)
    bridge = fixbridge.FixBridge(fix)
    results = []
    seq = bridge.command("ACT", 1, on_ack=lambda s, ok, msg: results.append((s, ok, msg)))
    fix.db.get_item("FPLMSG").value = ""
    fix.db.set_value("FPLCMDACK", seq)
    assert results == [(seq, True, "")]


def test_command_ack_callback_fires_ok_false_on_negative_ack(fix):
    _define_all_fp1_keys(fix)
    bridge = fixbridge.FixBridge(fix)
    results = []
    seq = bridge.command("ACT", 99, on_ack=lambda s, ok, msg: results.append((s, ok, msg)))
    fix.db.get_item("FPLMSG").value = "BAD SLOT"
    fix.db.set_value("FPLCMDACK", -seq)
    assert results == [(seq, False, "BAD SLOT")]


def test_command_returns_none_and_no_ack_when_unavailable(fix):
    bridge = fixbridge.FixBridge(fix)
    assert bridge.available is False
    called = []
    seq = bridge.command("ACT", 1, on_ack=lambda *a: called.append(a))
    assert seq is None
    assert called == []


# ---------------------------------------------------------------------------
# ActivePlan read-back
# ---------------------------------------------------------------------------
def test_listener_fires_on_fplseq_change(fix):
    _define_all_fp1_keys(fix)
    bridge = fixbridge.FixBridge(fix)
    calls = []
    bridge.add_listener(lambda: calls.append(1))
    bridge.publish(_plan(1))
    assert len(calls) >= 1


def test_listener_fires_on_engine_output_change(fix):
    _define_all_fp1_keys(fix)
    bridge = fixbridge.FixBridge(fix)
    calls = []
    bridge.add_listener(lambda: calls.append(1))
    fix.db.set_value("FPLSTATE", 1)
    assert len(calls) >= 1


def test_read_route_reflects_published_plan(fix):
    _define_all_fp1_keys(fix)
    bridge = fixbridge.FixBridge(fix)
    bridge.publish(_plan(2))
    route = bridge.read_route()
    assert route.name == "TEST"
    assert route.seq == 1
    assert [s.id for s in route.waypoints] == ["WP00", "WP01"]
    assert route.waypoints[0].type == "fix"


def test_read_engine_reports_values_and_quality(fix):
    _define_all_fp1_keys(fix)
    bridge = fixbridge.FixBridge(fix)
    fix.db.set_value("FPLCRS", 313.13)
    fix.db.get_item("FPLCRS").bad = True
    engine = bridge.read_engine()
    assert engine["FPLCRS"].value == pytest.approx(313.13)
    assert engine["FPLCRS"].bad is True


# ---------------------------------------------------------------------------
# Qt-free (static -- fixbridge legitimately depends on pyavtools.fix, which
# is itself Qt-based, so the sys.modules check test_model.py/test_catalog.py
# use would fail for the wrong reason; this checks fixbridge.py's own source
# never imports PyQt6/PyQt5 directly).
# ---------------------------------------------------------------------------
def test_package_source_never_imports_qt_directly():
    pkg_dir = Path(__file__).resolve().parents[2] / "src" / "pyefis" / "flightplan"
    offenders = []
    for path in pkg_dir.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("import PyQt") or stripped.startswith("from PyQt"):
                offenders.append(f"{path.name}:{lineno}: {stripped}")
    assert offenders == [], "flightplan package must not import Qt directly:\n" + "\n".join(offenders)
