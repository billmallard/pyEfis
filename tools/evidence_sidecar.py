#!/usr/bin/env python3
#  SPDX-License-Identifier: GPL-2.0-or-later
"""The evidence sidecar: ``<image>.json`` beside every new evidence image (TV12).

An evidence image says what the screen looked like. Its sidecar says which code drew
it, in which run, on which device -- the three things a reviewer otherwise has to dig
out of a commit message or trust someone's prose for. ``docs/evidence.md`` is the
convention; ``tools/evidence_index.py`` reads these files and lists which images carry
one.

Shape (``evidence-sidecar/1``)::

    {
     "schema": "evidence-sidecar/1",
     "commit": "1e7db42",           # pyEfis checkout that drew it; "-dirty" if uncommitted
     "run": "https://github.com/billmallard/pyEfis/actions/runs/123",  # or "local: <command>"
     "device": "Raspberry Pi 5 Model B Rev 1.0 (eglfs)",
     "sha256": "...",               # of the image bytes, so a stale sidecar is detectable
     "created_utc": "2026-10-31T12:00:00Z"
    }

``commit``, ``run`` and ``device`` are required. ``platform`` is optional: the CPU state
the frame was drawn at (``describe_platform()``), written when the sidecar describes the
machine it is made on. Producers may add their own keys
(``svs_capture.py`` adds ``capture_mode``, ``requested_size``, ...). Standard library
only, and no Qt: ``svs_capture.py`` imports it, and so can any render script.

Usage (any script that writes an evidence image)::

    from evidence_sidecar import write_sidecar
    write_sidecar(out_png)                       # commit, run, device resolved live

or from a shell, after the fact, for an image made by hand (all three keys required,
because only the person who made it knows them)::

    python tools/evidence_sidecar.py docs/images/aer1234_x/shot.png --commit 1e7db42 \
        --device "Beelink (xcb), live bench" --run "local: SIGUSR1 screenshot, AER-1234"
"""

import argparse
import datetime
import hashlib
import json
import os
import pathlib
import platform
import subprocess
import sys

SCHEMA = "evidence-sidecar/1"
REQUIRED = ("commit", "run", "device")

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from pyefis_rev import resolve_pyefis_rev  # noqa: E402


def sidecar_path(image):
    return pathlib.Path(str(image) + ".json")


def _read_first(*paths):
    for p in paths:
        try:
            text = pathlib.Path(p).read_text(errors="replace").replace("\x00", "").strip()
        except OSError:
            continue
        if text and text.lower() not in ("default string", "to be filled by o.e.m."):
            return text
    return ""


def describe_device(environ=None):
    """What drew the frame, in words a reader can match to a bench: the board model
    (device tree on a Pi, DMI on a PC), the Qt platform plugin, or the CI runner. Never
    the hostname -- that is private and the index would strip it anyway."""
    env = os.environ if environ is None else environ
    if env.get("GITHUB_ACTIONS") == "true":
        base = f"GitHub Actions {env.get('RUNNER_OS', '')} runner".replace("  ", " ")
    else:
        model = _read_first("/proc/device-tree/model")
        if not model:
            vendor = _read_first("/sys/class/dmi/id/sys_vendor")
            product = _read_first("/sys/class/dmi/id/product_name")
            model = " ".join(x for x in (vendor, product) if x)
        base = model or f"{platform.system()} {platform.machine()}".strip()
    qpa = env.get("QT_QPA_PLATFORM", "").split(":")[0]
    return f"{base} ({qpa})" if qpa else base


#: ARM ``CPU part`` ids (implementer 0x41) seen on the boards we run on. A part not
#: listed here leaves ``cpu_model`` absent; ``cpu_part`` still carries the raw id.
_ARM_PARTS = {"0xd03": "Cortex-A53", "0xd08": "Cortex-A72", "0xd0b": "Cortex-A76"}

#: ``vcgencmd get_throttled`` bits (Raspberry Pi firmware). Bit n+16 is "bit n has
#: happened since boot".
_THROTTLE_BITS = {0: "under_voltage", 1: "arm_freq_capped", 2: "throttled", 3: "soft_temp_limit"}

#: Thermal zone types that name the SoC or CPU package, most specific first.
_SOC_ZONES = ("cpu-thermal", "x86_pkg_temp", "soc_thermal", "cpu_thermal")


def _cpu_list_count(text):
    """Number of CPUs in a kernel cpu list ("0-3,6" -> 5); None when it does not parse."""
    count = 0
    try:
        for part in text.split(","):
            lo, _, hi = part.strip().partition("-")
            count += (int(hi) if hi else int(lo)) - int(lo) + 1
    except ValueError:
        return None
    return count or None


def _read_int(path):
    text = _read_first(path)
    try:
        return int(text)
    except ValueError:
        return None


def _vcgencmd(argv):
    try:
        out = subprocess.run(["vcgencmd", *argv], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def describe_platform(root="/", *, pid="self", firmware=None):
    """The CPU state a timing was taken at: SoC or CPU model, online cores, cpufreq
    policy (driver, governor, min/max frequency), this process's affinity, throttle
    state and SoC temperature. Two timings from one board compare only when these
    match.

    Every key is optional: one the kernel does not expose, or this user cannot read,
    is absent -- never filled with a default. ``root`` is where ``/proc`` and ``/sys``
    are read from (tests pass a fake tree). ``firmware`` runs a ``vcgencmd`` query and
    returns its output; by default it is the real command, and only when reading the
    live root, so a fake tree never mixes in this machine's firmware state. Reads only;
    changes nothing."""
    r = pathlib.Path(root)
    live = r == pathlib.Path("/")
    if firmware is None:
        firmware = _vcgencmd if live else (lambda argv: "")
    out = {}

    # Board, SoC and CPU model.
    board = _read_first(r / "proc/device-tree/model")
    if not board:
        board = " ".join(x for x in (_read_first(r / "sys/class/dmi/id/sys_vendor"),
                                     _read_first(r / "sys/class/dmi/id/product_name")) if x)
    if board:
        out["board"] = board
    try:
        compatible = (r / "proc/device-tree/compatible").read_bytes().split(b"\x00")
        compatible = [c.decode("ascii", "replace") for c in compatible if c]
    except OSError:
        compatible = []
    if compatible:
        out["soc"] = compatible[-1]
    cpuinfo = {}
    try:
        for line in (r / "proc/cpuinfo").read_text(errors="replace").splitlines():
            key, sep, value = line.partition(":")
            if sep and key.strip() and value.strip():
                cpuinfo.setdefault(key.strip(), value.strip())
    except OSError:
        pass
    if "model name" in cpuinfo:
        out["cpu_model"] = cpuinfo["model name"]
    elif "CPU part" in cpuinfo:
        out["cpu_part"] = f"{cpuinfo.get('CPU implementer', '?')}:{cpuinfo['CPU part']}"
        if cpuinfo.get("CPU implementer") == "0x41" and cpuinfo["CPU part"] in _ARM_PARTS:
            out["cpu_model"] = _ARM_PARTS[cpuinfo["CPU part"]]
    for src, dst in (("Revision", "revision"), ("stepping", "cpu_stepping"),
                     ("microcode", "microcode")):
        if src in cpuinfo:
            out[dst] = cpuinfo[src]

    # Online cores.
    cpu = r / "sys/devices/system/cpu"
    online = _read_first(cpu / "online")
    if online and _cpu_list_count(online):
        out["cpus_online"] = online
        out["cpus_online_count"] = _cpu_list_count(online)

    # cpufreq policies: driver, governor, frequency limits.
    policies = []
    try:
        policy_dirs = sorted((cpu / "cpufreq").glob("policy*"),
                             key=lambda p: int(p.name[6:]) if p.name[6:].isdigit() else 0)
    except OSError:
        policy_dirs = []
    for pdir in policy_dirs:
        policy = {"policy": pdir.name}
        for src, dst in (("related_cpus", "cpus"), ("scaling_driver", "driver"),
                         ("scaling_governor", "governor")):
            text = _read_first(pdir / src)
            if text:
                policy[dst] = text
        for src, dst in (("scaling_min_freq", "min_khz"), ("scaling_max_freq", "max_khz"),
                         ("cpuinfo_min_freq", "hw_min_khz"), ("cpuinfo_max_freq", "hw_max_khz"),
                         ("scaling_cur_freq", "cur_khz")):
            value = _read_int(pdir / src)
            if value is not None:
                policy[dst] = value
        if len(policy) > 1:
            policies.append(policy)
    if policies:
        out["cpufreq"] = policies
        governors = {p.get("governor") for p in policies}
        if len(governors) == 1 and None not in governors:
            out["governor"] = governors.pop()
    pstate = {}
    for name in ("status", "no_turbo", "min_perf_pct", "max_perf_pct"):
        text = _read_first(cpu / "intel_pstate" / name)
        if text:
            pstate[name] = int(text) if text.isdigit() else text
    if pstate:
        out["intel_pstate"] = pstate

    # This process's affinity.
    try:
        for line in (r / "proc" / str(pid) / "status").read_text(errors="replace").splitlines():
            if line.startswith("Cpus_allowed_list:"):
                allowed = line.split(":", 1)[1].strip()
                if _cpu_list_count(allowed):
                    out["affinity"] = allowed
                    out["affinity_count"] = _cpu_list_count(allowed)
                break
    except OSError:
        pass

    # Throttle state: the Pi firmware's flags, the Pi under-voltage alarm, the x86
    # thermal-throttle counters.
    throttle = {}
    reply = firmware(["get_throttled"])
    if reply.startswith("throttled="):
        try:
            bits = int(reply.split("=", 1)[1], 16)
        except ValueError:
            bits = None
        if bits is not None:
            throttle["get_throttled"] = hex(bits)
            throttle["now"] = [n for b, n in _THROTTLE_BITS.items() if bits & (1 << b)]
            throttle["since_boot"] = [n for b, n in _THROTTLE_BITS.items() if bits & (1 << (b + 16))]
    try:
        hwmons = sorted((r / "sys/class/hwmon").glob("hwmon*"))
    except OSError:
        hwmons = []
    for hw in hwmons:
        if _read_first(hw / "name") == "rpi_volt":
            alarm = _read_int(hw / "in0_lcrit_alarm")
            if alarm is not None:
                throttle["under_voltage_alarm"] = bool(alarm)
    counts = []
    for n in range(out.get("cpus_online_count") or 0):
        value = _read_int(cpu / f"cpu{n}/thermal_throttle/core_throttle_count")
        if value is None:
            counts = []
            break
        counts.append(value)
    if counts:
        throttle["core_throttle_count"] = counts
    package = _read_int(cpu / "cpu0/thermal_throttle/package_throttle_count")
    if package is not None:
        throttle["package_throttle_count"] = package
    if throttle:
        out["throttle"] = throttle

    # Temperatures, in degrees C, by thermal zone type.
    temps = {}
    try:
        zones = sorted((r / "sys/class/thermal").glob("thermal_zone*"))
    except OSError:
        zones = []
    for zone in zones:
        kind = _read_first(zone / "type")
        milli = _read_int(zone / "temp")
        if kind and milli is not None:
            temps.setdefault(kind, round(milli / 1000.0, 2))
    if temps:
        out["temperature_c"] = temps
        for kind in _SOC_ZONES:
            if kind in temps:
                out["soc_temp_c"] = temps[kind]
                break
    return out


def describe_run(argv=None, environ=None):
    """The run that produced it: the CI run URL when in Actions, else ``EVIDENCE_RUN``
    if the caller set one (a bench session, an issue), else the local command line."""
    env = os.environ if environ is None else environ
    if env.get("GITHUB_RUN_ID") and env.get("GITHUB_REPOSITORY"):
        server = env.get("GITHUB_SERVER_URL", "https://github.com")
        return f"{server}/{env['GITHUB_REPOSITORY']}/actions/runs/{env['GITHUB_RUN_ID']}"
    if env.get("EVIDENCE_RUN"):
        return env["EVIDENCE_RUN"]
    return "local: " + " ".join(sys.argv if argv is None else argv)


def build_sidecar(image, *, commit=None, run=None, device=None, extra=None, platform_state=None):
    """``platform_state`` is ``describe_platform()`` of this machine unless given. It is left
    out when ``device`` is given and ``platform_state`` is not: a device named by hand is not
    necessarily this machine, and its CPU state at the time is unknown here."""
    image = pathlib.Path(image)
    if platform_state is None and device is None:
        platform_state = describe_platform()
    record = {
        "schema": SCHEMA,
        "commit": commit or resolve_pyefis_rev(),
        "run": run or describe_run(),
        "device": device or describe_device(),
        "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
        "created_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if platform_state:
        record["platform"] = platform_state
    for k, v in (extra or {}).items():
        record.setdefault(k, v)
    return record


def write_sidecar(image, **kw):
    """Write ``<image>.json``. Call it after the image is saved: it hashes the bytes."""
    record = build_sidecar(image, **kw)
    sidecar_path(image).write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8")
    return record


def check_sidecar(image):
    """(state, record). state is one of: ``ok``, ``none`` (no sidecar), ``legacy``
    (a sidecar from before this convention, no ``schema``), ``incomplete`` (a required
    key missing or empty), ``stale`` (its sha256 is not this image's), ``unreadable``."""
    path = sidecar_path(image)
    if not path.is_file():
        return "none", {}
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "unreadable", {}
    if not isinstance(record, dict):
        return "unreadable", {}
    if record.get("schema") != SCHEMA:
        return "legacy", record
    if any(not str(record.get(k) or "").strip() for k in REQUIRED):
        return "incomplete", record
    digest = record.get("sha256")
    if digest and digest != hashlib.sha256(pathlib.Path(image).read_bytes()).hexdigest():
        return "stale", record
    return "ok", record


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("images", nargs="+")
    # All three required here: after the fact, only the person who made the image knows
    # which checkout, run and device it came from -- this machine's guess would be wrong.
    ap.add_argument("--commit", required=True, help="pyEfis commit that drew it")
    ap.add_argument("--run", required=True, help="CI run URL, bench session, or the command")
    ap.add_argument("--device", required=True, help='e.g. "Raspberry Pi 5 (eglfs), live panel"')
    args = ap.parse_args(argv)
    for image in args.images:
        rec = write_sidecar(image, commit=args.commit, run=args.run, device=args.device)
        print(f"{sidecar_path(image)}: {rec['commit']} | {rec['device']} | {rec['run']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
