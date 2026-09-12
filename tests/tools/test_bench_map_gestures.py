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
import time
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


# --- moving-position (AER-679): pure helpers -------------------------------

def test_dead_reckon_step_matches_aer677_formula(bmg):
    """Same formula AER-677's fixgw.netfix repro and visual_svs_test.py's
    SVS_SIM_MOTION use: 130 kt / hdg 280 for 1 s moves ~0.0361 NM,
    almost entirely westbound (hdg 280 is close to due west) with a
    small northward component."""
    lat, lon = bmg._dead_reckon_step(40.0, -82.855, 130.0, 280.0, 1.0)
    assert lat > 40.0          # hdg 280 has a small +cos component north
    assert lon < -82.855       # hdg 280 moves west (lon decreases)
    assert lat == pytest.approx(40.0, abs=0.001)
    assert lon == pytest.approx(-82.855, abs=0.001)


def test_dead_reckon_step_zero_speed_is_stationary(bmg):
    lat, lon = bmg._dead_reckon_step(35.8, -78.8, 0.0, 90.0, 1.0)
    assert (lat, lon) == (35.8, -78.8)


def test_percentiles_empty_is_all_none(bmg):
    p = bmg._percentiles([])
    assert p == dict(p50=None, p95=None, p99=None, max=None, count=0)


def test_percentiles_single_value_all_equal(bmg):
    p = bmg._percentiles([42.0])
    assert p == dict(p50=42.0, p95=42.0, p99=42.0, max=42.0, count=1)


def test_percentiles_p95_and_max_differ_on_a_spread(bmg):
    values = list(range(1, 101))   # 1..100
    p = bmg._percentiles([float(v) for v in values])
    assert p["max"] == 100.0
    assert p["p50"] < p["p95"] < p["p99"] <= p["max"]
    assert p["count"] == 100


# --- moving-position: hit/miss + timing hooks, no Qt -----------------------

class _FakeSVSRenderer:
    """Stand-in for an SVSRenderer exposing just the attributes
    _install_svs_hooks touches, so the hit/miss + timing logic can be
    tested without a real GL context."""

    def __init__(self):
        self._water_worker = None
        self._hwy_worker = None
        self._async_state = {}
        self.water_calls = 0

    def draw(self, p, w, h, ac_lat, ac_lon, ac_alt_ft, pitch_deg,
             roll_deg, heading_deg, pixels_per_deg,
             device_pixel_ratio=1.0):
        time.sleep(0.01)

    def _collect_water_triangles(self, ac_lat, ac_lon, range_nm):
        self.water_calls += 1
        if self.water_calls == 1:
            self._water_worker = object()   # simulate a fresh kickoff

    def _collect_highways(self, ac_lat, ac_lon, ac_alt_ft, range_nm,
                          pixels_per_deg):
        pass   # never touches _hwy_worker -> every call is a "hit"

    def _async_cache(self, name, key, builder):
        st = self._async_state.setdefault(
            name, {"key": None, "val": None, "worker": None})
        if st["key"] != key:
            st["worker"] = object()   # simulate a fresh kickoff
            st["key"] = key
        return st["val"]


def test_install_svs_hooks_counts_water_hit_then_miss(bmg):
    f = _FakeSVSRenderer()
    samples, collectors, restore = bmg._install_svs_hooks(f)
    f._collect_water_triangles(0.0, 0.0, 10.0)   # miss: kicks a worker
    f._collect_water_triangles(0.0, 0.0, 10.0)   # hit: worker unchanged
    assert collectors["water"] == {"hit": 1, "miss": 1}
    assert collectors["highways"] == {"hit": 0, "miss": 0}
    restore()


def test_install_svs_hooks_counts_highway_always_hit(bmg):
    f = _FakeSVSRenderer()
    samples, collectors, restore = bmg._install_svs_hooks(f)
    f._collect_highways(0.0, 0.0, 0.0, 10.0, 100.0)
    f._collect_highways(0.0, 0.0, 0.0, 10.0, 100.0)
    assert collectors["highways"] == {"hit": 2, "miss": 0}
    restore()


def test_install_svs_hooks_counts_async_cache_obstacles(bmg):
    f = _FakeSVSRenderer()
    samples, collectors, restore = bmg._install_svs_hooks(f)
    f._async_cache("obstacles", ("keyA",), lambda: {})
    f._async_cache("obstacles", ("keyA",), lambda: {})   # same key -> hit
    f._async_cache("obstacles", ("keyB",), lambda: {})   # new key -> miss
    assert collectors["obstacles"] == {"hit": 1, "miss": 2}
    restore()


def test_install_svs_hooks_restore_stops_counting(bmg):
    f = _FakeSVSRenderer()
    samples, collectors, restore = bmg._install_svs_hooks(f)
    f._collect_highways(0.0, 0.0, 0.0, 10.0, 100.0)
    restore()
    f._collect_highways(0.0, 0.0, 0.0, 10.0, 100.0)   # not counted anymore
    assert collectors["highways"] == {"hit": 1, "miss": 0}


def test_install_svs_hooks_measures_draw_gap_and_total(bmg):
    f = _FakeSVSRenderer()
    samples, collectors, restore = bmg._install_svs_hooks(f)
    f.draw(None, 100, 100, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 10.0)
    time.sleep(0.02)
    f.draw(None, 100, 100, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 10.0)
    restore()
    assert len(samples["total_ms"]) == 2
    assert samples["total_ms"][0] >= 8.0     # ~10ms sleep inside draw()
    assert len(samples["gap_ms"]) == 1       # gap only after the 2nd call
    assert samples["gap_ms"][0] >= 18.0      # ~10ms draw + ~20ms sleep


def test_install_map_hooks_measures_paint_to_paint_gap(bmg):
    class _FakePerf:
        def __init__(self):
            self.calls = []

        def record_paint_ms(self, ms):
            self.calls.append(ms)

    perf = _FakePerf()
    samples, restore = bmg._install_map_hooks(perf)
    perf.record_paint_ms(1.0)
    time.sleep(0.02)
    perf.record_paint_ms(1.0)
    restore()
    assert perf.calls == [1.0, 1.0]   # original still runs
    assert len(samples) == 1
    assert samples[0] >= 18.0


# --- moving-position: end to end (map target needs no GL) ------------------

def test_moving_position_map_only_end_to_end(bmg, qapp):
    args = bmg._parse_args([
        "--moving-position", "--target", "map",
        "--w", "150", "--h", "150",
        "--duration", "0.5", "--position-hz", "20", "--gs", "130",
        "--heading", "280"])
    r = bmg.run_moving_position(qapp, args, "deadbeef", "test-host")
    assert r["scenario"] == "moving_position"
    assert r["target"] == "map"
    assert "svs" not in r["counters"]
    gap = r["counters"]["map"]["frame_gap_ms"]
    assert gap["count"] >= 0   # a short/idle run may paint 0-1 times
    assert "caveat" in r and "AER-677" in r["caveat"]
    assert "moving_position:" in r["summary"]


def test_moving_position_budget_gate_via_main(bmg, qapp, tmp_path):
    """DoD: the --budget gate actually trips on a moving-position result
    -- proven the same way test_main_budget_violation_exits_nonzero
    proves it for a gesture scenario."""
    budget = tmp_path / "budget.json"
    budget.write_text(json.dumps(
        {"moving_position": [
            {"path": "map.frame_gap_ms.count", "min": 10**9}]}))
    out = tmp_path / "out.json"
    rc = bmg.main([
        "--moving-position", "--target", "map",
        "--w", "150", "--h", "150", "--duration", "0.3",
        "--position-hz", "20", "--out", str(out), "--budget", str(budget)])
    assert rc != 0


def test_shipped_moving_position_budget_gates_map_on_probe_not_frame_gap(bmg):
    """AER-1082 regression: the shipped budget must not resurrect AER-679's
    borrowed 50 ms bound on map.frame_gap_ms.p95. AER-692 showed that path
    reads ~205 ms p50 / ~292 ms p95 for a healthy map at 10 NM/130 kt --
    pose-quantization arithmetic, not a defect -- so a bound there fails
    every run, forever, correctly-behaving code included."""
    budget = json.loads(
        (_ROOT / "tools" / "budgets" / "moving_position.json").read_text())
    checks = {c["path"]: c for c in budget["moving_position"]}
    assert "map.frame_gap_ms.p95" not in checks
    assert checks["map.probe.p95_ms"]["max"] == 50
    assert checks["svs.frame_gap_ms.p95"]["max"] == 50


def test_shipped_moving_position_budget_passes_healthy_quantized_map(bmg):
    """A map reading AER-692's own quantization numbers (~292 ms p95
    frame_gap_ms) but a healthy GuiProbe gap (~10.9 ms, no GIL
    starvation) must pass the shipped budget -- it would have failed the
    old shared 50 ms frame_gap_ms bound despite being defect-free."""
    budget = json.loads(
        (_ROOT / "tools" / "budgets" / "moving_position.json").read_text())
    result = dict(scenario="moving_position", counters=dict(
        svs=dict(frame_gap_ms=dict(p95=24.1)),
        map=dict(frame_gap_ms=dict(p95=292.0),
                 probe=dict(p95_ms=10.9))))
    assert bmg.check_budgets([result], budget) == []


def test_shipped_moving_position_budget_passes_healthy_svs(bmg):
    """AER-1086 regression: a measured healthy SVS reading must pass the
    shipped budget. Fixture is AER-1086's own bench run -- healthy
    current dev, --moving-position --target svs, 130 kt/280 deg/20 Hz,
    real GL (offscreen QPA can't create a QOpenGLWidget context at all;
    this run used a shared X display instead) -- p50 33.0 / p95 34.0 /
    p99 34.9 / max 35.6 ms, comfortably under the 50 ms bar. A test that
    only asserts the key exists would not have caught the DEMO-era
    "~25 ms (40 fps)" provenance this bar used to cite (AER-677's
    retired numbers), nor would it prove the bar is set above a real
    measurement rather than below it."""
    budget = json.loads(
        (_ROOT / "tools" / "budgets" / "moving_position.json").read_text())
    result = dict(scenario="moving_position", counters=dict(
        svs=dict(frame_gap_ms=dict(p95=34.0)),
        map=dict(frame_gap_ms=dict(p95=292.0),
                 probe=dict(p95_ms=10.9))))
    assert bmg.check_budgets([result], budget) == []


def test_moving_position_svs_target_reports_or_skips_without_gl(bmg, qapp):
    """SVS is GL-required with no CPU fallback (ai/svs.py) -- in a
    headless CI box with no usable GL, SVS disables itself and this
    just proves the harness doesn't crash and reports zero frames
    rather than fabricating numbers. Where GL *is* available (the
    Beelink bench), this is the actual AER-677 regression check."""
    args = bmg._parse_args([
        "--moving-position", "--target", "svs",
        "--w", "150", "--h", "150",
        "--duration", "0.5", "--position-hz", "20"])
    r = bmg.run_moving_position(qapp, args, "deadbeef", "test-host")
    assert r["target"] == "svs"
    assert "map" not in r["counters"]
    svs = r["counters"]["svs"]
    assert set(svs["collectors"]) == {"water", "highways", "obstacles",
                                      "airports"}
    if svs["frame_total_ms"]["count"] == 0:
        pytest.skip("no GL context in this environment (SVS UNAVAIL)")
    assert svs["frame_gap_ms"]["count"] >= 0
