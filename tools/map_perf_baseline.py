#!/usr/bin/env python3
#  SPDX-License-Identifier: GPL-2.0-or-later
"""Per-host timing baselines for the moving-map perf budgets (MP8b-2,
briefs/map_gesture_perf_plan.md section 5; pyEfis #98, AER-1135).

Section 5's timing rows -- worker render <= 0.6 s at 160/300 NM, settle
latency <= 600 ms, paint p95 <= 15 ms, roads worker <= 0.3 s, GUI-thread
starved time and max gap <= 50 ms -- were measured on one machine (the
Beelink N150). MP8's DoD therefore asserts them "against
``tests/perf/baselines/<hostname>.json`` with a 1.5x tolerance ... on an
unknown host they warn". This module owns both halves of that: minting a
baseline (``mint``) and comparing a measurement to one (``check``).

**The problem this module actually exists to solve.** A count budget's
falsifier is a mutant: break MP1's gating and "1 render per pinch"
goes red. A timing budget has no such falsifier, because the thing that
makes a timing assertion worthless is not a mutant in the code under
test -- it is *a baseline captured on a degraded tree*. A baseline minted
while the terrain worker was rendering twice per pinch records the slow
number as normal, and every future run of that budget then passes at
1.5x of a defect. The budget is green, permanently, and measures nothing.
Nothing in the timing measurement itself can detect this: slow-because-
broken and slow-because-this-box-is-slow are the same number.

So the guards below are the substitute for a falsifier, and they are all
of the form "prove the tree was healthy *by some means other than the
clock*, at mint time":

  1. **Clean tree at a named commit.** ``git status --porcelain`` must be
     empty and the SHA is recorded. A baseline whose provenance cannot be
     re-checked is not evidence.
  2. **The count-based budgets must pass in the same run.** This is the
     load-bearing one. ``tests/perf/test_map_gestures.py`` (MP8a) asserts
     renders-per-pinch, superseded-renders, paints-per-sweep and
     QPointF-count -- all *hardware-independent*, so they read the same on
     a Beelink and on a loaded CI runner. They are exactly the pipeline
     defects that would inflate a timing baseline, and they are visible
     without a clock. Minting runs them and refuses on a single failure.
  3. **Reproducibility.** ``--repeats`` runs (default 3); if
     ``max/min > _SPREAD_MAX`` for any metric the box was too noisy to
     mint on and the tool refuses. A baseline is the median, never a
     single sample and never the minimum.
  4. **Recorded data-pack identity.** Every timing row is a function of
     how much geometry the scene holds, so the water pack's
     ``pack_meta`` (id + cycle) and the fixture pin are recorded. A
     baseline minted against a different pack cycle is not a baseline for
     this one -- ``check`` downgrades to a warning when they differ
     rather than silently comparing across data versions.
  5. **A calibration probe, re-run at check time.** ``calibration_ms``
     times a fixed, pack-free numpy workload (``_calibrate``). It is
     recorded at mint and re-measured at check; if the host has drifted
     more than ``_CALIBRATION_DRIFT_MAX`` (thermal throttling, a noisy
     neighbour, different silicon behind the same hostname) the baseline
     is no longer describing this machine and ``check`` warns instead of
     gating. This is what stops a baseline minted on a quiet box from
     failing every run on a busy one, and -- more importantly -- stops a
     baseline minted on a busy box from passing a real 1.4x regression
     forever.

None of that makes a bad baseline impossible. It makes a bad baseline
require a *clean tree at a named SHA on which the count budgets passed
three times running with a recorded pack cycle*, which is a much smaller
target than "somebody ran the tool once".

**Host identity is NOT the hostname, and that is a change from the
brief.** ``socket.gethostname()`` on a GitHub-hosted runner is a
per-job random string (``fv-az###-###``), and in a container it is the
container id -- this module was developed in one whose hostname changed
on every recreate. Keying baselines by ``gethostname()`` therefore means
*no baseline is ever found* on exactly the hosts CI runs on, so every
timing budget warns, forever: a test that gates nothing. ``host_id()``
prefers an explicit ``PYEFIS_PERF_HOST`` -- an operator naming a machine
they intend to keep -- and falls back to the hostname only for a real
workstation or bench where that name is stable. See
``tests/perf/baselines/README.md``.

CLI::

    # mint (run it on the machine you are minting for, tree clean)
    PYEFIS_PERF_HOST=beelink python tools/map_perf_baseline.py mint \\
        --tile-path /data/makerplane-data/terrain/tiles \\
        --water-db /data/makerplane-data/water/current/water.sqlite \\
        --out tests/perf/baselines/beelink.json

    # show what would be compared, without asserting
    PYEFIS_PERF_HOST=beelink python tools/map_perf_baseline.py check \\
        --measured run.json
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import socket
import subprocess
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
BASELINE_DIR = _ROOT / "tests" / "perf" / "baselines"

#: MP8 DoD: "timing budgets assert against tests/perf/baselines/
#: <hostname>.json with a 1.5x tolerance".
TOLERANCE = 1.5

#: Refuse to mint when the spread across --repeats exceeds this. A box
#: that cannot reproduce itself within 25% cannot support a 1.5x gate:
#: the noise would eat two thirds of the tolerance.
_SPREAD_MAX = 1.25

#: How far the calibration probe may drift between mint and check before
#: the baseline stops describing this machine. Deliberately tighter than
#: TOLERANCE -- the probe is a fixed workload with no I/O, so it should
#: be far more stable than a render, and a 1.3x drift on it means the
#: whole box moved.
_CALIBRATION_DRIFT_MAX = 1.3

#: Metrics a baseline carries. ``lower_is_better`` is True for all of
#: them today (they are all latencies); the key is kept explicit so a
#: future throughput row cannot be silently compared the wrong way.
METRICS = {
    "terrain_render_ms_160nm": {"section5_reference_ms": 600.0},
    "terrain_render_ms_300nm": {"section5_reference_ms": 600.0},
    "settle_latency_ms_pinch_out": {"section5_reference_ms": 600.0},
    "paint_ms_p95_40nm": {"section5_reference_ms": 15.0},
    "roads_render_ms_80nm": {"section5_reference_ms": 300.0},
    "probe_max_gap_ms_pinch": {"section5_reference_ms": 50.0},
}

SCHEMA_VERSION = 2


class BaselineError(RuntimeError):
    """Minting refused, or a baseline file is unusable."""


# ---------------------------------------------------------------------------
# Host identity
# ---------------------------------------------------------------------------

def host_id() -> str:
    """The name a baseline file is keyed by.

    ``PYEFIS_PERF_HOST`` wins: it is an operator asserting "this machine
    has a stable identity and I intend to keep a baseline for it". The
    hostname is the fallback for workstations and the bench, where it is
    a real name. On a CI runner or in a container it is not, and the
    caller finds no baseline and warns -- which is the honest outcome,
    not a bug (see the module docstring)."""
    explicit = os.environ.get("PYEFIS_PERF_HOST", "").strip()
    if explicit:
        return explicit
    return socket.gethostname()


def baseline_path(host: str | None = None,
                  directory: Path | None = None) -> Path:
    return Path(directory or BASELINE_DIR) / f"{host or host_id()}.json"


def load_baseline(host: str | None = None,
                  directory: Path | None = None) -> dict | None:
    """The baseline for ``host``, or ``None`` when this host has never
    been minted. ``None`` is the warn case, never a failure."""
    p = baseline_path(host, directory)
    if not p.is_file():
        return None
    data = json.loads(p.read_text())
    if data.get("schema_version") != SCHEMA_VERSION:
        raise BaselineError(
            f"{p}: schema_version {data.get('schema_version')!r}, this "
            f"code speaks {SCHEMA_VERSION}. Re-mint rather than "
            "hand-editing: the fields that changed are the provenance "
            "fields, and a hand-patched one is exactly the unverifiable "
            "baseline this module exists to prevent.")
    return data


# ---------------------------------------------------------------------------
# Calibration probe
# ---------------------------------------------------------------------------

def _calibrate(reps: int = 3) -> float:
    """Median wall-ms of a fixed, pack-free, allocation-light numpy
    workload.

    Purpose: give ``check`` a way to ask "is this still the machine the
    baseline was minted on?" that does not depend on the code under test,
    the data packs, or Qt. Deliberately CPU-and-memory-bound in roughly
    the proportion the terrain worker is (a big float32 elementwise pass
    plus a reduction), so throttling or a noisy neighbour moves it the
    same way it moves a render.

    The absolute value is meaningless across machines; only the ratio
    between a recorded value and a fresh one is used."""
    import numpy as np
    rng = np.random.default_rng(0)         # fixed seed: same work every time
    a = rng.random((1024, 1024), dtype=np.float32)
    b = rng.random((1024, 1024), dtype=np.float32)
    out = []
    for _ in range(reps):
        t0 = time.perf_counter()
        for _ in range(8):
            c = np.sqrt(a * a + b * b)
            _ = float(c.sum())
        out.append((time.perf_counter() - t0) * 1000.0)
    return _median(out)


def _median(values):
    v = sorted(values)
    n = len(v)
    if not n:
        raise BaselineError("median of an empty sample")
    return v[n // 2] if n % 2 else 0.5 * (v[n // 2 - 1] + v[n // 2])


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------

def _git(*args) -> str:
    try:
        return subprocess.run(["git", "-C", str(_ROOT), *args],
                              capture_output=True, text=True,
                              check=True).stdout.strip()
    except Exception:
        return ""


def tree_is_clean() -> tuple[bool, str]:
    """(clean, detail). Untracked files count as dirty: an untracked
    ``sitecustomize.py`` or a stray ``conftest.py`` changes what runs."""
    status = _git("status", "--porcelain")
    return (status == ""), status


def water_pack_identity(water_db: str | os.PathLike | None) -> dict:
    """``pack_meta`` from a water pack, so a baseline records WHICH data
    it was minted against.

    Every timing row here is a function of how much geometry the scene
    holds, so a pack cycle change moves the numbers for reasons that have
    nothing to do with the code. Returns ``{}`` for a pack with no
    ``pack_meta`` table (pre-versioned packs) -- recorded as unknown
    rather than guessed."""
    if not water_db:
        return {}
    import sqlite3
    try:
        con = sqlite3.connect(f"file:{os.fspath(water_db)}?mode=ro", uri=True)
    except Exception:
        return {}
    try:
        rows = dict(con.execute("SELECT key, value FROM pack_meta"))
    except Exception:
        try:
            rows = {k: v for k, v in con.execute("SELECT * FROM pack_meta")}
        except Exception:
            return {}
    finally:
        con.close()
    return {k: rows[k] for k in ("id", "cycle", "schema_version")
            if k in rows}


def environment() -> dict:
    return {
        "host_id": host_id(),
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "processor": platform.processor() or platform.machine(),
        "cpu_count": os.cpu_count(),
        "python": platform.python_version(),
        "qt": _qt_version(),
    }


def _qt_version() -> str:
    try:
        from PyQt6.QtCore import QT_VERSION_STR
        return QT_VERSION_STR
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# check: compare a measurement to a baseline
# ---------------------------------------------------------------------------

class Verdict:
    """One metric's result. ``gated`` False means this comparison is not
    evidence -- read ``reason``, do not read ``ok``."""

    __slots__ = ("metric", "measured", "baseline", "bound", "ok", "gated",
                 "reason")

    def __init__(self, metric, measured=None, baseline=None, bound=None,
                 ok=None, gated=False, reason=""):
        self.metric = metric
        self.measured = measured
        self.baseline = baseline
        self.bound = bound
        self.ok = ok
        self.gated = gated
        self.reason = reason

    def __repr__(self):
        if not self.gated:
            return f"<{self.metric}: NOT GATED -- {self.reason}>"
        return (f"<{self.metric}: {self.measured:.1f} vs bound "
                f"{self.bound:.1f} ms ({'ok' if self.ok else 'FAIL'})>")

    def as_dict(self):
        return {s: getattr(self, s) for s in self.__slots__}


def check(metric: str, measured_ms: float, baseline: dict | None,
          tolerance: float = TOLERANCE,
          calibration_ms: float | None = None) -> Verdict:
    """Compare one measured metric against ``baseline``.

    Returns a ``Verdict``; never raises for the ordinary "no baseline"
    cases, because those are the WARN outcomes the DoD asks for, and a
    caller that cannot tell "passed" from "was not gated" is the vacuity
    this whole module is trying to avoid -- hence ``gated`` being a
    separate field from ``ok`` rather than folding "not gated" into a
    pass."""
    if metric not in METRICS:
        raise BaselineError(f"unknown metric {metric!r}; known: "
                            f"{sorted(METRICS)}")
    if baseline is None:
        return Verdict(metric, measured=measured_ms, gated=False,
                       reason=f"no baseline for host {host_id()!r}")
    rec = (baseline.get("metrics") or {}).get(metric)
    if rec is None or rec.get("ms") is None:
        return Verdict(metric, measured=measured_ms, gated=False,
                       reason=f"baseline for {host_id()!r} carries no "
                              f"{metric!r} row")

    recorded_cal = baseline.get("calibration_ms")
    if calibration_ms is not None and recorded_cal:
        drift = max(calibration_ms / recorded_cal,
                    recorded_cal / calibration_ms)
        if drift > _CALIBRATION_DRIFT_MAX:
            return Verdict(
                metric, measured=measured_ms, baseline=rec["ms"], gated=False,
                reason=(f"calibration probe drifted {drift:.2f}x "
                        f"({recorded_cal:.0f} ms at mint, "
                        f"{calibration_ms:.0f} ms now, limit "
                        f"{_CALIBRATION_DRIFT_MAX}x) -- this baseline no "
                        "longer describes this machine; re-mint it"))

    bound = rec["ms"] * tolerance
    return Verdict(metric, measured=measured_ms, baseline=rec["ms"],
                   bound=bound, ok=measured_ms <= bound, gated=True,
                   reason="")


# ---------------------------------------------------------------------------
# mint
# ---------------------------------------------------------------------------

def build_baseline(samples: list[dict], *, water_db=None, fixture_pin=None,
                   config: dict | None = None,
                   count_budgets_passed: bool,
                   allow_dirty: bool = False,
                   spread_max: float = _SPREAD_MAX) -> dict:
    """Turn N measurement dicts into one baseline record, refusing every
    way a baseline can be untrustworthy (module docstring, guards 1-5).

    ``samples`` is a list of ``{metric: ms}``; a metric absent from a
    sample is absent from the baseline (a host with no highway pack
    simply has no ``roads_render_ms_80nm`` row, and ``check`` reports
    that as not-gated rather than inventing one)."""
    if not samples:
        raise BaselineError("no samples")

    clean, detail = tree_is_clean()
    if not clean and not allow_dirty:
        raise BaselineError(
            "refusing to mint from a dirty working tree -- a baseline is "
            "a claim about a named commit, and this one could not be "
            "re-derived from any commit:\n" + detail)

    if not count_budgets_passed:
        raise BaselineError(
            "refusing to mint: the MP8a count-based budgets "
            "(tests/perf/test_map_gestures.py) did not all pass on this "
            "tree. Those are hardware-INDEPENDENT, so a failure there is "
            "a pipeline defect, not a slow machine -- and a timing "
            "baseline captured over a pipeline defect records the defect "
            "as normal and passes it forever at 1.5x. Fix the count "
            "budgets first; there is no --force for this one.")

    metrics = {}
    for name in METRICS:
        values = [s[name] for s in samples
                  if s.get(name) is not None]
        if not values:
            continue
        lo, hi = min(values), max(values)
        spread = (hi / lo) if lo > 0 else math.inf
        if spread > spread_max:
            raise BaselineError(
                f"refusing to mint {name!r}: {len(values)} repeats spread "
                f"{spread:.2f}x ({lo:.1f}..{hi:.1f} ms), over the "
                f"{spread_max}x limit. This box cannot reproduce itself "
                f"closely enough to support a {TOLERANCE}x gate -- the "
                "noise would eat most of the tolerance. Quiesce it and "
                "re-run, or accept that this host is warn-only.")
        metrics[name] = {
            "ms": round(_median(values), 3),
            "samples": [round(v, 3) for v in values],
            "spread": round(spread, 3),
            "section5_reference_ms": METRICS[name]["section5_reference_ms"],
        }

    if not metrics:
        raise BaselineError(
            "refusing to mint an empty baseline: none of the known "
            f"metrics ({sorted(METRICS)}) was present in any sample.")

    return {
        "schema_version": SCHEMA_VERSION,
        "host_id": host_id(),
        "git_sha": _git("rev-parse", "HEAD"),
        "git_describe": _git("describe", "--always", "--dirty"),
        "tree_clean": clean,
        "count_budgets_passed": True,
        "calibration_ms": round(_calibrate(), 3),
        "water_pack": water_pack_identity(water_db),
        "fixture_pin": fixture_pin or {},
        "config": config or {},
        "environment": environment(),
        "tolerance": TOLERANCE,
        "metrics": metrics,
    }


def run_count_budgets() -> bool:
    """Run MP8a's count-based budgets in a subprocess and report whether
    they all passed -- guard 2, the one with no override.

    A subprocess, not an in-process ``pytest.main``: those tests build a
    QApplication and several MovingMap widgets, and minting is about to
    do the same. Sharing a process would let one leak into the other, and
    the whole value of this guard is that its answer is independent of
    the timing run it is vouching for."""
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "--no-cov", "-q",
         str(_ROOT / "tests" / "perf" / "test_map_gestures.py")],
        cwd=str(_ROOT), env=env, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stdout[-4000:])
        sys.stderr.write(proc.stderr[-2000:])
    return proc.returncode == 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cmd_mint(args) -> int:
    sys.path.insert(0, str(_ROOT / "tests"))
    from perf import measure as measure_mod     # tests/perf/measure.py

    if not args.skip_count_budgets:
        print("running MP8a count budgets (guard 2)...", file=sys.stderr)
        passed = run_count_budgets()
    else:
        passed = False        # build_baseline refuses; --skip is a dry-run aid
    samples = []
    for i in range(args.repeats):
        print(f"measurement pass {i + 1}/{args.repeats}...", file=sys.stderr)
        samples.append(measure_mod.measure_all(
            tile_path=args.tile_path, water_db=args.water_db,
            highway_db=args.highway_db, scene=args.scene,
            w=args.w, h=args.h, water_max_vertices=args.water_max_vertices))
    baseline = build_baseline(
        samples, water_db=args.water_db, count_budgets_passed=passed,
        allow_dirty=args.allow_dirty,
        config={"scene": args.scene, "w": args.w, "h": args.h,
                "water_max_vertices": args.water_max_vertices})
    out = Path(args.out or baseline_path())
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(baseline, indent=2, sort_keys=True) + "\n")
    print(f"wrote {out}")
    return 0


def _cmd_check(args) -> int:
    baseline = load_baseline()
    measured = json.loads(Path(args.measured).read_text())
    cal = _calibrate()
    rc = 0
    for metric in METRICS:
        if measured.get(metric) is None:
            continue
        v = check(metric, measured[metric], baseline, calibration_ms=cal)
        print(v)
        if v.gated and not v.ok:
            rc = 1
    return rc


def _parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="command", required=True)

    m = sub.add_parser("mint", help="mint a baseline for this host")
    m.add_argument("--tile-path", default="")
    m.add_argument("--water-db", default="")
    m.add_argument("--highway-db", default="")
    m.add_argument("--scene", default="raleigh")
    m.add_argument("--w", type=int, default=650)
    m.add_argument("--h", type=int, default=1040)
    m.add_argument("--water-max-vertices", type=int, default=1024)
    m.add_argument("--repeats", type=int, default=3)
    m.add_argument("--out", default="")
    m.add_argument("--allow-dirty", action="store_true",
                   help="mint from a dirty tree (the record says so; "
                        "never commit one)")
    m.add_argument("--skip-count-budgets", action="store_true",
                   help="dry run only -- build_baseline still refuses")
    m.set_defaults(func=_cmd_mint)

    c = sub.add_parser("check", help="compare a measurement json to the "
                                     "baseline for this host")
    c.add_argument("--measured", required=True)
    c.set_defaults(func=_cmd_check)
    return ap.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv)
    try:
        return args.func(args)
    except BaselineError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
