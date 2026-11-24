"""CERT20b (AER-6451) thermal sampler for the Pi 5: one JSON line every
--every seconds with SoC temperature, the real ARM clock, the firmware throttle
flags, load and per-process CPU. Reads only; changes nothing.

  soak_thermal.py --out thermal.jsonl --until <unix-seconds> [--every 2] [--pid N ...]

Sources: /sys/class/thermal/thermal_zone0/temp (cpu_thermal), the nvme hwmon
temp1_input when present (the nearest thing to an enclosure reading),
``vcgencmd measure_clock arm`` (the clock the firmware actually runs, which a
throttle lowers; sysfs scaling_cur_freq is only the kernel's request) and
``vcgencmd get_throttled``. The Pi 5 has no get_throttled sysfs file
(CERT20a). Flags: bits 0-3 are now (under-voltage, ARM frequency capped,
throttled, soft temperature limit), bits 16-19 the same since boot.
"""
import argparse
import glob
import json
import os
import subprocess
import time


def _read(p):
    try:
        with open(p) as f:
            return f.read().strip()
    except OSError:
        return None


def _vc(*argv):
    try:
        r = subprocess.run(["vcgencmd", *argv], capture_output=True, text=True, timeout=5)
        return r.stdout.strip() if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def _nvme_temp():
    for h in glob.glob("/sys/class/hwmon/hwmon*"):
        if _read(h + "/name") == "nvme":
            v = _read(h + "/temp1_input")
            return int(v) / 1000.0 if v else None
    return None


def _cpu_ticks(pid):
    s = _read("/proc/%d/stat" % pid)
    if not s:
        return None
    f = s.rsplit(")", 1)[1].split()
    return int(f[11]) + int(f[12])   # utime + stime


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--until", type=float, required=True)
    ap.add_argument("--every", type=float, default=2.0)
    ap.add_argument("--pid", type=int, action="append", default=[])
    a = ap.parse_args()
    hz = os.sysconf("SC_CLK_TCK")
    out = open(a.out, "a", buffering=1)
    while time.time() < a.until:
        stat = _read("/proc/stat").splitlines()[0].split()[1:]
        rec = {
            "wall": round(time.time(), 2), "mono_ns": time.monotonic_ns(),
            "soc_c": (int(_read("/sys/class/thermal/thermal_zone0/temp")) / 1000.0),
            "nvme_c": _nvme_temp(),
            "arm_hz": None, "throttled": _vc("get_throttled"),
            "kernel_cur_khz": _read("/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq"),
            "load": _read("/proc/loadavg"),
            "cpu_total": sum(int(x) for x in stat), "cpu_idle": int(stat[3]) + int(stat[4]),
            "pids": {str(p): _cpu_ticks(p) for p in a.pid}, "clk_tck": hz,
        }
        clk = _vc("measure_clock", "arm")
        if clk and "=" in clk:
            rec["arm_hz"] = int(clk.split("=", 1)[1])
        out.write(json.dumps(rec) + "\n")
        time.sleep(a.every)


if __name__ == "__main__":
    main()
