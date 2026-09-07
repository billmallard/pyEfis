#  SPDX-License-Identifier: GPL-2.0-or-later
"""Tests for tools/bench_map_gestures.py (MP7, briefs/
map_gesture_perf_plan.md section 4; pyEfis #98).

Pure-function tests (dotted-path lookup, budget checking) run with no Qt
at all. The end-to-end tests build a real offscreen MovingMap with no
data files configured -- every layer stays trivially settled (brief:
"Layers with no async render... Default True"), so these stay fast while
still exercising the harness's own plumbing (event pump, gesture
bracket, JSON schema, --budget exit code) against the real widget."""

import importlib.util
import json
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, _ROOT / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def bmg():
    return _load("bench_map_gestures")


# --- _get_path / check_budgets: pure, no Qt --------------------------------

def test_get_path_resolves_nested(bmg):
    d = {"a": {"b": {"c": 5}}}
    assert bmg._get_path(d, "a.b.c") == (5, True)


def test_get_path_missing_key_not_found(bmg):
    d = {"a": {"b": {}}}
    assert bmg._get_path(d, "a.b.c") == (None, False)
    assert bmg._get_path(d, "a.x.c") == (None, False)


def _result(scenario, counters):
    return dict(scenario=scenario, counters=counters)


def test_check_budgets_passes_within_bound(bmg):
    results = [_result("pinch_out", {"frames_painted": 5})]
    budgets = {"pinch_out": [{"path": "frames_painted", "max": 10}]}
    assert bmg.check_budgets(results, budgets) == []


def test_check_budgets_flags_max_violation(bmg):
    results = [_result("pinch_out", {"frames_painted": 50})]
    budgets = {"pinch_out": [{"path": "frames_painted", "max": 1}]}
    violations = bmg.check_budgets(results, budgets)
    assert len(violations) == 1
    v = violations[0]
    assert v == dict(scenario="pinch_out", path="frames_painted",
                     value=50, bound="max", limit=1)


def test_check_budgets_flags_min_violation(bmg):
    results = [_result("pinch_out", {"settle_latency_ms": 5})]
    budgets = {"pinch_out": [{"path": "settle_latency_ms", "min": 10}]}
    violations = bmg.check_budgets(results, budgets)
    assert len(violations) == 1 and violations[0]["bound"] == "min"


def test_check_budgets_skips_missing_path_without_violating(bmg, capsys):
    results = [_result("pinch_out", {"frames_painted": 5})]
    budgets = {"pinch_out": [
        {"path": "layers.terrain.jobs_requested", "max": 1}]}
    assert bmg.check_budgets(results, budgets) == []
    assert "skipped" in capsys.readouterr().err


def test_check_budgets_ignores_scenario_absent_from_results(bmg):
    results = [_result("pinch_out", {"frames_painted": 5})]
    budgets = {"rotate": [{"path": "frames_painted", "max": 1}]}
    assert bmg.check_budgets(results, budgets) == []


# --- end-to-end: real MovingMap, offscreen, no data files ------------------

def test_ladder_scenario_end_to_end(bmg, qapp):
    bmg._bootstrap_fix_db(35.8, -78.8, 0.0, 1500.0)
    args = bmg._parse_args(
        ["--scenario", "ladder", "--w", "200", "--h", "200"])
    r = bmg.run_scenario(qapp, args, "ladder", "deadbeef", "test-host")
    assert r["scenario"] == "ladder"
    assert r["schema_version"] == 1
    assert r["counters"]["frames_painted"] > 0
    assert r["params"]["ladder"][0] == 2.0
    assert r["params"]["ladder"][-1] == 160.0
    assert "ladder:" in r["summary"]


def test_pinch_out_runs_full_gesture_and_settles(bmg, qapp):
    """No tile_path configured, so there's nothing for TerrainLayer to
    render -- this proves the scenario runs the full 90-event gesture
    bracket + hold without error, reaches the ladder's top range, and
    still measures a settle latency (every layer is trivially settled
    with no data, so settle should land quickly after the last event)."""
    bmg._bootstrap_fix_db(35.8, -78.8, 0.0, 1500.0)
    args = bmg._parse_args(
        ["--scenario", "pinch_out", "--w", "200", "--h", "200"])
    r = bmg.run_scenario(qapp, args, "pinch_out", "deadbeef", "test-host")
    assert r["params"]["range_actual_nm"] == pytest.approx(160.0, abs=1.0)
    assert r["counters"]["settle_latency_ms"] is not None
    assert r["counters"]["probe"]["count"] > 0   # map_perf_log started it


def test_main_writes_json_array_and_exits_zero(bmg, qapp, tmp_path):
    out = tmp_path / "out.json"
    rc = bmg.main(["--scenario", "ladder", "--w", "150", "--h", "150",
                  "--out", str(out)])
    assert rc == 0
    data = json.loads(out.read_text())
    assert isinstance(data, list) and len(data) == 1
    assert data[0]["scenario"] == "ladder"


def test_main_budget_violation_exits_nonzero(bmg, qapp, tmp_path):
    """DoD: --budget proven to exit non-zero on a budget it actually
    violates -- a gate that has never failed is not a gate."""
    budget = tmp_path / "budget.json"
    budget.write_text(json.dumps(
        {"ladder": [{"path": "frames_painted", "max": 0}]}))
    out = tmp_path / "out.json"
    rc = bmg.main(["--scenario", "ladder", "--w", "150", "--h", "150",
                  "--out", str(out), "--budget", str(budget)])
    assert rc != 0


def test_main_budget_satisfied_exits_zero(bmg, qapp, tmp_path):
    budget = tmp_path / "budget.json"
    budget.write_text(json.dumps(
        {"ladder": [{"path": "frames_painted", "max": 10000}]}))
    out = tmp_path / "out.json"
    rc = bmg.main(["--scenario", "ladder", "--w", "150", "--h", "150",
                  "--out", str(out), "--budget", str(budget)])
    assert rc == 0
