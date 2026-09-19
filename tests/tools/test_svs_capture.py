"""Tests for tools/svs_capture.py's mock-FIX fixture (AER-708) and its
rendering-identity metadata (AER-1675).

MAGVAR previously had no seat in the capture tool's mock FIX database, so
``head_true = HEAD - MAGVAR`` (src/pyefis/instruments/ai/__init__.py) always
subtracted a constant zero -- a variation-handling defect at any magnitude was
invisible to every capture the tool could produce. These tests exercise
``seed_mock_fix`` directly (pure ``fix.db`` calls, no Qt/GL) to prove:

* ``--magvar`` defaults to 0.0, so an unmodified invocation seeds MAGVAR=0.0
  and every other key exactly as before -- the fixture is byte-for-byte
  unchanged unless the flag is passed.
* A non-zero ``--magvar`` changes only the MAGVAR key.
"""
import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]


def _load_svs_capture():
    spec = importlib.util.spec_from_file_location(
        "svs_capture", _ROOT / "tools" / "svs_capture.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def svs_capture():
    # svs_capture.py inserts its own sys.path entries and swaps in the mock
    # FIX client at import time -- mirrors how it's invoked as a script.
    return _load_svs_capture()


def _args(**overrides):
    base = dict(
        lat=34.4275, lon=-119.8546, alt=500.0,
        heading=87.0, pitch=0.0, roll=0.0, magvar=0.0,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


def test_magvar_flag_defaults_to_zero(svs_capture):
    args = svs_capture.parse_args([
        "--out", "x.png", "--lat", "0", "--lon", "0", "--alt", "0",
    ])
    assert args.magvar == 0.0


def test_magvar_flag_parses_explicit_value(svs_capture):
    args = svs_capture.parse_args([
        "--out", "x.png", "--lat", "0", "--lon", "0", "--alt", "0",
        "--magvar", "12.5",
    ])
    assert args.magvar == 12.5


def test_default_magvar_seeds_zero_and_matches_prior_fixture(svs_capture):
    """At --magvar 0 (the default), MAGVAR seeds to 0.0 and every other key
    matches exactly what the tool wrote before MAGVAR existed."""
    values = svs_capture.seed_mock_fix(_args())

    assert values["MAGVAR"] == 0.0
    assert svs_capture.fix.db.get_item("MAGVAR").value == 0.0

    expected_unchanged = {
        "PITCH": 0.0, "ROLL": 0.0, "ALAT": 0.0, "TAS": 120.0,
        "HEAD": 87.0, "VS": 0.0, "GS": 120.0, "TRACK": 87.0,
        "LAT": 34.4275, "LONG": -119.8546, "ALT": 500.0,
    }
    for key, expected in expected_unchanged.items():
        assert values[key] == expected
        assert svs_capture.fix.db.get_item(key).value == expected


def test_nonzero_magvar_changes_only_magvar(svs_capture):
    """A non-zero --magvar changes MAGVAR and leaves every other seeded key
    identical to the --magvar 0 fixture."""
    baseline = svs_capture.seed_mock_fix(_args())
    shifted = svs_capture.seed_mock_fix(_args(magvar=10.0))

    assert shifted["MAGVAR"] == 10.0
    assert baseline["MAGVAR"] == 0.0
    for key in baseline:
        if key == "MAGVAR":
            continue
        assert shifted[key] == baseline[key]


def test_magvar_direction_matches_west_positive_convention(svs_capture):
    """West-positive MAGVAR (FAA "West is best": MAG = TRUE + W_VAR) means
    the AI widget's ``head_true = HEAD - MAGVAR`` must read LOWER than the
    seeded (magnetic) HEAD when MAGVAR is positive."""
    values = svs_capture.seed_mock_fix(_args(heading=87.0, magvar=10.0))
    head_true = values["HEAD"] - values["MAGVAR"]
    assert head_true == pytest.approx(77.0)
    assert head_true < values["HEAD"]


# ---------------------------------------------------------------------------
# --offscreen (AER-763): svs_capture needs a window today (a QMainWindow it
# shows so its QOpenGLWidget viewport can initialise), which eglfs refuses to
# hand out a second one of while pyEfis already holds the display. These
# tests only cover parse_args' validation -- the render path itself
# (make_offscreen_target / render_offscreen_frame) needs a real GL context
# and is not exercised by this suite; see the module docstring for what is
# and is not verified about it.
# ---------------------------------------------------------------------------

def test_offscreen_flag_defaults_to_false(svs_capture):
    args = svs_capture.parse_args([
        "--out", "x.png", "--lat", "0", "--lon", "0", "--alt", "0",
    ])
    assert args.offscreen is False


def test_offscreen_flag_parses(svs_capture):
    args = svs_capture.parse_args([
        "--out", "x.png", "--lat", "0", "--lon", "0", "--alt", "0",
        "--offscreen",
    ])
    assert args.offscreen is True


def test_offscreen_accepts_default_msaa(svs_capture):
    """--msaa's default (1) is compatible with --offscreen -- only an
    explicit, non-default sample count is rejected."""
    args = svs_capture.parse_args([
        "--out", "x.png", "--lat", "0", "--lon", "0", "--alt", "0",
        "--offscreen",
    ])
    assert args.msaa == 1


def test_offscreen_rejects_non_default_msaa(svs_capture, capsys):
    """The offscreen FBO is always allocated at 0 samples (glReadPixels on a
    multisample FBO is invalid, same constraint the windowed path has) -- a
    non-default --msaa would silently be ignored rather than failing at
    readback, so parse_args rejects the combination up front."""
    with pytest.raises(SystemExit):
        svs_capture.parse_args([
            "--out", "x.png", "--lat", "0", "--lon", "0", "--alt", "0",
            "--offscreen", "--msaa", "4",
        ])
    assert "--offscreen" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# pyefis_rev (AER-1675): a cross-renderer differential only localises a
# defect if a disagreement can be attributed to different code vs different
# GPU, which needs the rendering identity read from the live checkout --
# never a constant someone has to remember to bump.
# ---------------------------------------------------------------------------

def _git_repo(tmp_path, dirty=False):
    repo = tmp_path / "repo"
    repo.mkdir()
    run = lambda *cmd: subprocess.run(
        ["git", *cmd], cwd=repo, capture_output=True, text=True, check=True,
    )
    run("init", "-q")
    run("-c", "user.email=test@test", "-c", "user.name=test",
        "commit", "--allow-empty", "-q", "-m", "init")
    if dirty:
        (repo / "untracked.txt").write_text("scratch")
    return repo


def test_resolve_pyefis_rev_reports_clean_checkout(svs_capture, tmp_path):
    repo = _git_repo(tmp_path)
    rev = svs_capture.resolve_pyefis_rev(repo)
    assert rev != "unknown"
    assert not rev.endswith("-dirty")


def test_resolve_pyefis_rev_flags_dirty_checkout(svs_capture, tmp_path):
    repo = _git_repo(tmp_path, dirty=True)
    rev = svs_capture.resolve_pyefis_rev(repo)
    assert rev.endswith("-dirty")


def test_resolve_pyefis_rev_unknown_outside_a_git_checkout(svs_capture, tmp_path):
    not_a_repo = tmp_path / "not-a-repo"
    not_a_repo.mkdir()
    assert svs_capture.resolve_pyefis_rev(not_a_repo) == "unknown"


def test_write_manifest_writes_sidecar_json_beside_the_frame(svs_capture, tmp_path):
    out = tmp_path / "frame.png"
    svs_capture._write_manifest(out, "abc1234-dirty")

    manifest = tmp_path / "frame.png.json"
    assert manifest.is_file()
    assert json.loads(manifest.read_text()) == {"pyefis_rev": "abc1234-dirty"}
