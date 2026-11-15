"""tools/bench_sweep.sh, section [2] (bench lock), against a real flock.

AER-2901: bench-deploy.sh opens the lock in its own shell (`exec 9>>`) and
takes it with a flock(1) child that exits at once. /proc/locks then names a
dead pid (or, inside a container's pid namespace, nobody), while the shell
that claimed the bench is alive and holds the fd. The sweep read that as the
AER-2663 orphan and failed every `bench-deploy.sh --check`.

Each case reproduces that lock shape for real and runs the sweep from inside
it, exactly as bench_sweep_check does (`9>&-`, so the sweep is not a holder).
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SWEEP = Path(__file__).resolve().parents[2] / "tools" / "bench_sweep.sh"

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux")
    or shutil.which("flock") is None
    or shutil.which("bash") is None,
    reason="bench_sweep.sh reads /proc and needs flock(1)",
)


def _run_locked(tmp_path, owner_pid_expr):
    """Take the lock bench-deploy's way, write a holder record whose pid= is
    `owner_pid_expr` (shell), then run the sweep. Returns (rc, output)."""
    lock = tmp_path / "bench.lock"
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    script = f"""
        exec 9>>"{lock}"
        flock 9 || exit 99
        sh -c 'exit 0' & dead=$!; wait "$dead"
        printf 'owner=TEST issue=AER-2901 pid=%s since=now\\n' {owner_pid_expr} > "{lock}.owner"
        "{SWEEP}" --lock "{lock}" --scratch "{scratch}" --fix-port 1 9>&-
    """
    p = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60)
    assert p.returncode != 99, p.stderr
    return p.returncode, p.stdout + p.stderr


def _lock_section(out):
    return out.split("[2] bench lock", 1)[1].split("[3]", 1)[0]


def test_live_claimant_with_exited_flock_child_is_clean(tmp_path):
    rc, out = _run_locked(tmp_path, "$$")
    assert "FINDING" not in _lock_section(out), out
    assert rc == 0, out
    assert "bench-sweep: clean." in out


def test_dead_claimant_is_still_a_finding(tmp_path):
    # The AER-2663 shape: the lock is held, but the pid that claimed the bench
    # is gone. The fix must not hide this.
    rc, out = _run_locked(tmp_path, '"$dead"')
    assert rc == 1, out
    assert "FINDING" in _lock_section(out), out


def test_sweep_is_executable():
    assert os.access(SWEEP, os.X_OK)


def _run_without_home(*args):
    # A root system unit with no User= line: systemd sets no HOME (AER-3036).
    env = {k: v for k, v in os.environ.items() if k != "HOME"}
    return subprocess.run(
        [str(SWEEP), "--fix-port", "1", *args],
        capture_output=True, text=True, timeout=60, env=env,
    )


def test_runs_with_home_unset_when_scratch_given(tmp_path):
    # The shipped unit passes --scratch. It must not trip `set -u` on HOME.
    p = _run_without_home("--lock", str(tmp_path / "bench.lock"),
                          "--scratch", str(tmp_path))
    assert "unbound variable" not in p.stderr, p.stderr
    assert p.returncode == 0, p.stdout + p.stderr
    assert "bench-sweep: clean." in p.stdout


def test_home_unset_without_scratch_is_a_usage_error(tmp_path):
    # Defaulting to "/bench-scratch" would report a clean [3] forever.
    p = _run_without_home("--lock", str(tmp_path / "bench.lock"))
    assert p.returncode == 2, p.stdout + p.stderr
    assert "HOME is unset" in p.stderr
