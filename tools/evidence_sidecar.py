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

``commit``, ``run`` and ``device`` are required. Producers may add their own keys
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


def build_sidecar(image, *, commit=None, run=None, device=None, extra=None):
    image = pathlib.Path(image)
    record = {
        "schema": SCHEMA,
        "commit": commit or resolve_pyefis_rev(),
        "run": run or describe_run(),
        "device": device or describe_device(),
        "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
        "created_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
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
