#  SPDX-License-Identifier: GPL-2.0-or-later
"""Shared pieces of the primary-flight core checks (docs/safety/core_modules.yaml).

The rules are judged here, on data: a list of module names for the runtime import check
(R4), a list of recorded writes for the write audit (R5). The data comes from
boot_probe.py, run as a child process so that its sys.modules is its own.
"""

import importlib.util
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
PROBE = pathlib.Path(__file__).resolve().parent / "boot_probe.py"
SHIPPED_CONFIG = ROOT / "src" / "pyefis" / "config"
CORE_ONLY = pathlib.Path(__file__).resolve().parent / "data" / "core_only" / "default.yaml"

_spec = importlib.util.spec_from_file_location("core_imports", ROOT / "tools" / "core_imports.py")
core_imports = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(core_imports)


def load():
    return core_imports.load_core_list()


def module_is_core(name, doc, root=ROOT):
    path = core_imports.module_file(name, root)
    return path is not None and core_imports.core_group(path, doc) is not None


# --------------------------------------------------------------------------- staging

def stage_config(dest, default_yaml=None):
    """A config directory: the shipped tree, with default.yaml replaced if asked."""
    dest = pathlib.Path(dest)
    shutil.copytree(SHIPPED_CONFIG, dest, dirs_exist_ok=True)
    if default_yaml is not None:
        shutil.copyfile(default_yaml, dest / "default.yaml")
    return dest


def stage_source(dest):
    """A copy of src/pyefis under dest/src, for planting a violation. Returns dest/src."""
    src = pathlib.Path(dest) / "src"
    shutil.copytree(ROOT / "src" / "pyefis", src / "pyefis",
                    ignore=shutil.ignore_patterns("__pycache__", "config"))
    return src


def plant(src, relpath, text):
    """Append text to one module of a staged source copy."""
    path = pathlib.Path(src).parent / relpath
    path.write_text(path.read_text(encoding="utf-8") + "\n" + text + "\n", encoding="utf-8")


def run_probe(config, out, writes=False, drive=False, src=None, timeout=600):
    cmd = [sys.executable, str(PROBE), "--config", str(config), "--out", str(out)]
    if writes:
        cmd.append("--writes")
    if drive:
        cmd.append("--drive")
    if src is not None:
        cmd += ["--src", str(src)]
    out = pathlib.Path(out)
    env = dict(os.environ)
    env.pop("INVOCATION_ID", None)  # main() exits early under systemd unless auto start
    env["MAKERPLANE_ACK_LOG"] = str(out.with_suffix(".acks.jsonl"))  # not the user's home
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout, env=env)
    assert out.is_file(), "boot probe wrote no result:\n%s" % proc.stderr[-4000:]
    result = json.loads(out.read_text(encoding="utf-8"))
    assert result["status"] == "ok", "%s\n%s" % (result["status"], proc.stderr[-4000:])
    expect = pathlib.Path(src if src is not None else ROOT / "src").resolve()
    assert pathlib.Path(result["pyefis"]).is_relative_to(expect), (
        "the probe loaded pyefis from %s, not from %s" % (result["pyefis"], expect))
    return result


# --------------------------------------------------------------------------- R4

def runtime_allowlist(doc):
    """{module name: [edge, ...]} from ratchet: runtime."""
    out = {}
    for entry in (doc.get("ratchet") or {}).get("runtime") or []:
        for name in entry.get("modules") or []:
            out.setdefault(name, []).append("%s (%s)" % (entry["edge"], entry["removed_by"]))
    return out


def runtime_offenders(doc, modules, root=ROOT):
    """Non-core pyefis modules and watched packages present in a module list."""
    watch = set(doc.get("runtime_watch") or [])
    out = []
    for name in modules:
        if name.split(".")[0] == "pyefis":
            if not module_is_core(name, doc, root):
                out.append(name)
        elif name in watch:
            out.append(name)
    return sorted(out)


def runtime_check(doc, modules, root=ROOT):
    """(new offenders, stale allowlisted names). Both empty means the ratchet holds."""
    found = runtime_offenders(doc, modules, root)
    allowed = runtime_allowlist(doc)
    new = [m for m in found if m not in allowed]
    stale = sorted(m for m in allowed if m not in found)
    return new, stale


# --------------------------------------------------------------------------- R5

def key_class(key, doc):
    """'sensed_computed', 'pilot_set' or None."""
    keys = (doc.get("primary_keys") or {})
    sc = keys.get("sensed_computed") or {}
    if key in (sc.get("keys") or []) or any(re.match(p, key) for p in sc.get("patterns") or []):
        return "sensed_computed"
    if key in (keys.get("pilot_set") or {}):
        return "pilot_set"
    return None


def _under(path, prefixes):
    return any(path == p or (p.endswith("/") and path.startswith(p)) for p in prefixes)


def write_violations(doc, writes):
    """{(key, writer): reason} for every recorded write rule R5 forbids."""
    allowed = (doc.get("primary_keys") or {}).get("pilot_set") or {}
    out = {}
    for w in writes:
        cls = key_class(w["key"], doc)
        if cls == "sensed_computed":
            out[(w["key"], w["writer"])] = (
                "%s is a sensed or computed primary key; no pyEfis code may write it "
                "(%s:%d)" % (w["key"], w["writer"], w["line"]))
        elif cls == "pilot_set":
            non_core = [p for p in w["stack"] if core_imports.core_group(p, doc) is None]
            if not _under(w["writer"], allowed[w["key"]]):
                out[(w["key"], w["writer"])] = (
                    "%s is pilot-set; %s:%d is not one of its core write paths"
                    % (w["key"], w["writer"], w["line"]))
            elif non_core:
                out[(w["key"], w["writer"])] = (
                    "%s written by %s:%d with non-core code on the call stack (%s)"
                    % (w["key"], w["writer"], w["line"], ", ".join(non_core)))
    return out


def write_allowlist(doc):
    return {(e["key"], e["writer"]): e for e in (doc.get("ratchet") or {}).get("writes") or []}


def write_check(doc, writes):
    """(new violations as reasons, stale allowlist keys)."""
    found = write_violations(doc, writes)
    allowed = write_allowlist(doc)
    new = [reason for k, reason in sorted(found.items()) if k not in allowed]
    stale = sorted(k for k in allowed if k not in found)
    return new, stale
