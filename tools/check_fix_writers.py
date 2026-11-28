#!/usr/bin/env python3
#  SPDX-License-Identifier: GPL-2.0-or-later
"""Every FIX key pyEfis writes is declared in fix-gateway's writer register, and
no new class takes a route-concept name (ARCHG2, AER-6403).  A CI ratchet.

The writer register lives in fix-gateway only (`src/fixgw/database/writers.yaml`,
ARCHG1).  pyEfis keeps no copy of it, and no copy of the scanner either: this
fetches both from fix-gateway at the commit pinned in `tests/arch/fix_gateway.pin`
(a sparse, shallow checkout of a few files), then

  - scans pyEfis with fix-gateway's own `tools/check_key_writers.py`
    (`scan_writes(..., repo="pyEfis")`, the scan ARCHG1's `--generate --pyefis`
    used to fill the register's `pyefis` field), and fails on any write by a
    module the register does not list under `pyefis` for that key;
  - checks `tests/arch/concept_names.yaml` with the same module's
    `check_concepts`.

A module the register lists that no longer writes the key is reported as a
notice, not a failure: the fix is in fix-gateway, and failing here would need
both repos to change in lockstep.  Whether a declared pyEfis write makes a key
multi-writer is fix-gateway's check (its baseline), so declaring a write there
first is what puts it in front of that ratchet.

Usage:
    python tools/check_fix_writers.py                # check; exit 1 on a failure
    python tools/check_fix_writers.py --fixgw DIR    # against a checkout already at the pin
    python tools/check_fix_writers.py pin            # print the pinned commit
    python tools/check_fix_writers.py fetch          # fetch the pinned files; print where

The fetched files are cached under ~/.cache/pyefis/ (or $XDG_CACHE_HOME); set
FIXGW_REMOTE to fetch from a mirror.  Needs git and network the first time.
docs/key_writers.md says how to declare a write and how to bump the pin.
"""

import argparse
import importlib.util
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PIN_FILE = "tests/arch/fix_gateway.pin"
CONCEPTS = "tests/arch/concept_names.yaml"
REMOTE = "https://github.com/billmallard/fix-gateway.git"

# What the scanner needs: itself, the catalog dump and the database loader it
# runs (so templated keys expand as the gateway expands them), and the register.
SPARSE = [
    "/tools/check_key_writers.py",
    "/tools/dump_fix_keys.py",
    "/src/fixgw/__init__.py",
    "/src/fixgw/cfg.py",
    "/src/fixgw/database.py",
    "/src/fixgw/config/database.yaml",
    "/src/fixgw/config/database/",
    "/src/fixgw/database/",
]

DECLARE = ("declare it in fix-gateway writers.yaml first, then bump %s "
           "(docs/key_writers.md)" % PIN_FILE)


class PinError(Exception):
    pass


def read_pin(root=ROOT):
    lines = [ln.strip() for ln in (pathlib.Path(root) / PIN_FILE).read_text().splitlines()]
    shas = [ln for ln in lines if ln and not ln.startswith("#")]
    if len(shas) != 1 or len(shas[0]) != 40 or any(c not in "0123456789abcdef" for c in shas[0]):
        raise PinError("%s must hold exactly one full 40-character commit SHA; found %r"
                       % (PIN_FILE, shas))
    return shas[0]


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                          text=True).stdout.strip()


def head_of(path):
    try:
        return git("rev-parse", "HEAD", cwd=path)
    except (subprocess.CalledProcessError, FileNotFoundError, NotADirectoryError):
        return None


def cache_dir(sha):
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return pathlib.Path(base) / "pyefis" / ("fix-gateway-" + sha[:12])


def fetch(sha, dest=None, paths=SPARSE):
    """A sparse, shallow checkout of `paths` of fix-gateway at `sha`; returns its path."""
    dest = pathlib.Path(dest or cache_dir(sha))
    if head_of(dest) == sha and all((dest / p.strip("/")).exists() for p in paths):
        return dest
    dest.mkdir(parents=True, exist_ok=True)
    if not (dest / ".git").exists():
        git("init", "-q", cwd=dest)
        git("remote", "add", "origin", os.environ.get("FIXGW_REMOTE") or REMOTE, cwd=dest)
    git("sparse-checkout", "set", "--no-cone", *paths, cwd=dest)
    git("fetch", "-q", "--depth", "1", "--filter=blob:none", "origin", sha, cwd=dest)
    git("checkout", "-q", "--detach", "FETCH_HEAD", cwd=dest)
    return dest


def pinned_checkout(fixgw=None, root=ROOT):
    """The fix-gateway files at the pin: `fixgw` if given (it must be at the
    pin), else the cache, fetched if needed."""
    sha = read_pin(root)
    if fixgw is None:
        return fetch(sha), sha
    have = head_of(fixgw)
    if have != sha:
        raise PinError("%s is at %s, and %s pins %s; check out the pinned commit, or "
                       "leave out --fixgw to fetch it" % (fixgw, have, PIN_FILE, sha))
    return pathlib.Path(fixgw), sha


def load_scanner(fixgw):
    """fix-gateway's tools/check_key_writers.py, imported from the checkout."""
    path = pathlib.Path(fixgw) / "tools" / "check_key_writers.py"
    spec = importlib.util.spec_from_file_location("fixgw_check_key_writers", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def check_declared(writes, register, sha):
    """Failures: a pyEfis write the register does not list under `pyefis`.
    Notices: a listed pyEfis writer the scan no longer finds."""
    fails, notices = [], []
    found = {}
    for w in writes:
        found.setdefault(w["key"], {}).setdefault(w["module"], "%s:%d" % (w["file"], w["line"]))
    for key in sorted(found):
        declared = (register.get(key) or {}).get("pyefis") or []
        for mod, where in sorted(found[key].items()):
            if mod not in declared:
                fails.append("%s: %s writes it (%s), and fix-gateway's writers.yaml at %s does not "
                             "list %s under `pyefis`; %s" % (key, mod, where, sha[:12], mod, DECLARE))
    for key, e in sorted(register.items()):
        for mod in (e or {}).get("pyefis") or []:
            if mod not in found.get(key, {}):
                notices.append("%s: fix-gateway's writers.yaml lists %s under `pyefis`, and the "
                               "scan finds no write from it; remove it there" % (key, mod))
    return fails, notices


def run_checks(root=ROOT, fixgw=None, catalog=None):
    """(failures, notices, sha) for the pyEfis tree at `root`."""
    fixgw, sha = pinned_checkout(fixgw, root)
    kw = load_scanner(fixgw)
    catalog = catalog if catalog is not None else kw.load_catalog(str(fixgw))
    writes = kw.scan_writes(str(root), catalog, repo="pyEfis")
    fails, notices = check_declared(writes, kw.load_yaml(str(fixgw), kw.REGISTER), sha)
    fails += kw.check_concepts(str(root), kw.load_yaml(str(root), CONCEPTS))
    return fails, notices, sha


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", nargs="?", default="check", choices=("check", "pin", "fetch"))
    ap.add_argument("--fixgw", help="a fix-gateway checkout already at the pinned commit")
    a = ap.parse_args(argv)
    try:
        if a.command == "pin":
            print(read_pin())
            return 0
        if a.command == "fetch":
            print(pinned_checkout(a.fixgw)[0])
            return 0
        fails, notices, sha = run_checks(fixgw=a.fixgw)
    except (PinError, subprocess.CalledProcessError) as e:
        print("error: %s" % (e.stderr.strip() if getattr(e, "stderr", None) else e))
        return 2
    print("fix-gateway writer register and scanner at %s (%s)" % (sha, PIN_FILE))
    for f in fails:
        print(f)
    for n in notices:
        print("notice: " + n)
    print("%d failure(s), %d notice(s)" % (len(fails), len(notices)))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
