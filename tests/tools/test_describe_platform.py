#  SPDX-License-Identifier: GPL-2.0-or-later
"""Tests for ``describe_platform()`` in tools/evidence_sidecar.py (CERT20a).

A timing taken on a board says little unless it also says the CPU state it was taken
at: online cores, governor and frequency limits, the process's affinity, throttling,
SoC temperature. Each layout below is a fake /proc + /sys tree copied from a real bench
read on 2026-11-22: the Pi 5 (cpufreq-dt, vcgencmd throttle flags, rpi_volt alarm) and
the Beelink N150 (intel_pstate, thermal_throttle counters, a thermal zone whose temp
read fails). The empty root pins the rule that an unreadable field is absent, never
guessed. The last tests pin where the record is written: the sidecar and the perf
baseline."""

import importlib.util
import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "tools"))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, _ROOT / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


es = _load("evidence_sidecar")


def _tree(root, files):
    for rel, data in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, bytes):
            path.write_bytes(data)
        else:
            path.write_text(data)
    return root


_POLICY = "sys/devices/system/cpu/cpufreq/policy{}/"

PI5 = {
    "proc/device-tree/model": b"Raspberry Pi 5 Model B Rev 1.1\x00",
    "proc/device-tree/compatible": b"raspberrypi,5-model-b\x00brcm,bcm2712\x00",
    "proc/cpuinfo": (
        "processor\t: 0\nBogoMIPS\t: 108.00\nCPU implementer\t: 0x41\nCPU architecture: 8\n"
        "CPU variant\t: 0x4\nCPU part\t: 0xd0b\nCPU revision\t: 1\n\n"
        "processor\t: 1\nCPU implementer\t: 0x41\nCPU part\t: 0xd0b\n\n"
        "Revision\t: d04171\nSerial\t\t: 1234567890abcdef\nModel\t\t: Raspberry Pi 5 Model B Rev 1.1\n"),
    "proc/self/status": "Name:\tpython3\nCpus_allowed:\tf\nCpus_allowed_list:\t0-3\n",
    "sys/devices/system/cpu/online": "0-3\n",
    _POLICY.format(0) + "related_cpus": "0 1 2 3\n",
    _POLICY.format(0) + "scaling_driver": "cpufreq-dt\n",
    _POLICY.format(0) + "scaling_governor": "ondemand\n",
    _POLICY.format(0) + "scaling_min_freq": "1500000\n",
    _POLICY.format(0) + "scaling_max_freq": "2400000\n",
    _POLICY.format(0) + "cpuinfo_min_freq": "1500000\n",
    _POLICY.format(0) + "cpuinfo_max_freq": "2400000\n",
    _POLICY.format(0) + "scaling_cur_freq": "1600000\n",
    "sys/class/hwmon/hwmon0/name": "cpu_thermal\n",
    "sys/class/hwmon/hwmon3/name": "rpi_volt\n",
    "sys/class/hwmon/hwmon3/in0_lcrit_alarm": "0\n",
    "sys/class/thermal/thermal_zone0/type": "cpu-thermal\n",
    "sys/class/thermal/thermal_zone0/temp": "50150\n",
}


def _pi_firmware(argv):
    # The bench Pi's reply on 2026-11-22: capped, throttled and soft-limited since boot.
    return "throttled=0xe0000" if argv == ["get_throttled"] else ""


def test_pi5_layout(tmp_path):
    got = es.describe_platform(_tree(tmp_path, PI5), firmware=_pi_firmware)
    assert got["board"] == "Raspberry Pi 5 Model B Rev 1.1"
    assert got["soc"] == "brcm,bcm2712"
    assert got["cpu_model"] == "Cortex-A76"
    assert got["cpu_part"] == "0x41:0xd0b"
    assert got["revision"] == "d04171"
    assert (got["cpus_online"], got["cpus_online_count"]) == ("0-3", 4)
    assert got["governor"] == "ondemand"
    assert got["cpufreq"] == [{
        "policy": "policy0", "cpus": "0 1 2 3", "driver": "cpufreq-dt", "governor": "ondemand",
        "min_khz": 1500000, "max_khz": 2400000, "hw_min_khz": 1500000, "hw_max_khz": 2400000,
        "cur_khz": 1600000}]
    assert (got["affinity"], got["affinity_count"]) == ("0-3", 4)
    assert got["throttle"] == {
        "get_throttled": "0xe0000", "now": [],
        "since_boot": ["arm_freq_capped", "throttled", "soft_temp_limit"],
        "under_voltage_alarm": False}
    assert got["temperature_c"] == {"cpu-thermal": 50.15}
    assert got["soc_temp_c"] == 50.15
    assert "intel_pstate" not in got
    # The board serial is in /proc/cpuinfo; it must not reach a committed record.
    assert "1234567890abcdef" not in json.dumps(got)


def test_pi5_throttling_now_is_reported_as_now(tmp_path):
    got = es.describe_platform(_tree(tmp_path, PI5), firmware=lambda argv: "throttled=0x50005")
    assert got["throttle"]["now"] == ["under_voltage", "throttled"]
    assert got["throttle"]["since_boot"] == ["under_voltage", "throttled"]


X86 = {
    "sys/class/dmi/id/sys_vendor": "AZW\n",
    "sys/class/dmi/id/product_name": "MINI S\n",
    "proc/cpuinfo": "".join(
        f"processor\t: {n}\nvendor_id\t: GenuineIntel\ncpu family\t: 6\nmodel\t\t: 190\n"
        f"model name\t: Intel(R) N150\nstepping\t: 0\nmicrocode\t: 0x21\n\n" for n in range(4)),
    "proc/self/status": "Name:\tpython3\nCpus_allowed_list:\t0-3\n",
    "sys/devices/system/cpu/online": "0-3\n",
    "sys/devices/system/cpu/intel_pstate/status": "active\n",
    "sys/devices/system/cpu/intel_pstate/no_turbo": "0\n",
    "sys/devices/system/cpu/intel_pstate/min_perf_pct": "19\n",
    "sys/devices/system/cpu/intel_pstate/max_perf_pct": "100\n",
    "sys/devices/system/cpu/cpu0/thermal_throttle/package_throttle_count": "5525\n",
    "sys/class/thermal/thermal_zone0/type": "acpitz\n",
    "sys/class/thermal/thermal_zone0/temp": "27800\n",
    # iwlwifi's zone exists but its temp read fails (ENODATA on the bench): a
    # directory stands in for the file so the read raises.
    "sys/class/thermal/thermal_zone1/type": "iwlwifi_1\n",
    "sys/class/thermal/thermal_zone1/temp/.unreadable": "",
    "sys/class/thermal/thermal_zone2/type": "x86_pkg_temp\n",
    "sys/class/thermal/thermal_zone2/temp": "41000\n",
}
for _n in range(4):
    X86.update({
        _POLICY.format(_n) + "related_cpus": f"{_n}\n",
        _POLICY.format(_n) + "scaling_driver": "intel_pstate\n",
        _POLICY.format(_n) + "scaling_governor": "powersave\n",
        _POLICY.format(_n) + "scaling_min_freq": "700000\n",
        _POLICY.format(_n) + "scaling_max_freq": "3600000\n",
        _POLICY.format(_n) + "cpuinfo_min_freq": "700000\n",
        _POLICY.format(_n) + "cpuinfo_max_freq": "3600000\n",
        f"sys/devices/system/cpu/cpu{_n}/thermal_throttle/core_throttle_count": "5525\n",
    })


def test_x86_intel_pstate_layout(tmp_path):
    got = es.describe_platform(_tree(tmp_path, X86), firmware=lambda argv: "")
    assert got["board"] == "AZW MINI S"
    assert got["cpu_model"] == "Intel(R) N150"
    assert (got["cpu_stepping"], got["microcode"]) == ("0", "0x21")
    assert "soc" not in got and "revision" not in got and "cpu_part" not in got
    assert got["cpus_online_count"] == 4
    assert [p["policy"] for p in got["cpufreq"]] == ["policy0", "policy1", "policy2", "policy3"]
    assert {p["driver"] for p in got["cpufreq"]} == {"intel_pstate"}
    assert got["governor"] == "powersave"
    assert (got["cpufreq"][0]["min_khz"], got["cpufreq"][0]["max_khz"]) == (700000, 3600000)
    assert "cur_khz" not in got["cpufreq"][0]  # not in the fixture: absent, not zero
    assert got["intel_pstate"] == {"status": "active", "no_turbo": 0,
                                   "min_perf_pct": 19, "max_perf_pct": 100}
    assert got["throttle"] == {"core_throttle_count": [5525] * 4, "package_throttle_count": 5525}
    assert got["temperature_c"] == {"acpitz": 27.8, "x86_pkg_temp": 41.0}
    assert got["soc_temp_c"] == 41.0


def test_mixed_governors_leave_the_summary_absent(tmp_path):
    files = dict(X86)
    files[_POLICY.format(2) + "scaling_governor"] = "performance\n"
    got = es.describe_platform(_tree(tmp_path, files), firmware=lambda argv: "")
    assert "governor" not in got
    assert [p["governor"] for p in got["cpufreq"]] == ["powersave", "powersave", "performance", "powersave"]


def test_policies_sort_numerically(tmp_path):
    files = {}
    for n in (0, 2, 10):
        files[_POLICY.format(n) + "scaling_governor"] = "schedutil\n"
    got = es.describe_platform(_tree(tmp_path, files), firmware=lambda argv: "")
    assert [p["policy"] for p in got["cpufreq"]] == ["policy0", "policy2", "policy10"]


def test_nothing_readable_gives_an_empty_record(tmp_path):
    assert es.describe_platform(tmp_path, firmware=lambda argv: "") == {}
    assert es.describe_platform(tmp_path / "does-not-exist", firmware=lambda argv: "") == {}


def test_garbage_values_are_absent_not_guessed(tmp_path):
    files = {
        "sys/devices/system/cpu/online": "\n",
        "proc/self/status": "Cpus_allowed_list:\tbogus\n",
        _POLICY.format(0) + "scaling_max_freq": "<unsupported>\n",
        "sys/class/thermal/thermal_zone0/type": "cpu-thermal\n",
        "sys/class/thermal/thermal_zone0/temp": "\n",
    }
    got = es.describe_platform(_tree(tmp_path, files), firmware=lambda argv: "throttled=zz")
    assert got == {}


def test_a_fake_root_never_asks_this_machines_firmware(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(es, "_vcgencmd", lambda argv: called.append(argv) or "throttled=0x1")
    got = es.describe_platform(_tree(tmp_path, PI5))
    assert called == [] and "get_throttled" not in got.get("throttle", {})


def test_describe_platform_on_this_machine_is_json_and_reads_only():
    got = es.describe_platform()
    json.dumps(got)
    if hasattr(os, "sched_getaffinity") and "affinity_count" in got:
        assert got["affinity_count"] == len(os.sched_getaffinity(0))


# --------------------------------------------------------------------------- writers

def _png(path):
    path.write_bytes(b"\x89PNG not really")
    return path


def test_sidecar_carries_platform_and_keeps_its_schema(tmp_path, monkeypatch):
    monkeypatch.setattr(es, "describe_platform", lambda: {"governor": "ondemand"})
    img = _png(tmp_path / "shot.png")
    rec = es.write_sidecar(img, commit="abc1234", run="local: test")
    assert rec["schema"] == "evidence-sidecar/1"
    assert es.REQUIRED == ("commit", "run", "device")
    assert rec["platform"] == {"governor": "ondemand"}
    assert es.check_sidecar(img)[0] == "ok"


def test_sidecar_for_a_hand_named_device_omits_this_machines_platform(tmp_path, monkeypatch):
    monkeypatch.setattr(es, "describe_platform", lambda: {"governor": "ondemand"})
    rec = es.write_sidecar(_png(tmp_path / "shot.png"), commit="a", run="r", device="Pi 5 (eglfs)")
    assert "platform" not in rec


def test_sidecar_omits_an_empty_platform(tmp_path, monkeypatch):
    monkeypatch.setattr(es, "describe_platform", lambda: {})
    rec = es.write_sidecar(_png(tmp_path / "shot.png"), commit="a", run="r")
    assert "platform" not in rec


def test_perf_baseline_record_carries_platform(monkeypatch):
    mpb = _load("map_perf_baseline")
    monkeypatch.setattr(mpb, "describe_platform", lambda: {"governor": "performance"})
    monkeypatch.setattr(mpb, "_calibrate", lambda reps=3: 1.0)
    b = mpb.build_baseline([{"terrain_render_ms_160nm": 100.0}],
                           count_budgets_passed=True, allow_dirty=True)
    assert b["platform"] == {"governor": "performance"}
    assert b["schema_version"] == mpb.SCHEMA_VERSION

