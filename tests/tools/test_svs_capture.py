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
import hashlib
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
# hand out a second one of while pyEfis already holds the display. Most of
# these tests only cover parse_args' validation -- the actual render path
# (make_offscreen_target / render_offscreen_frame) needs a real GL context
# and is not exercised by this suite; see the module docstring for what is
# and is not verified about it. resize_for_offscreen_capture() is the
# exception: it is pure widget/scene geometry with no GL dependency (see its
# own docstring), so the AER-1692 regression below exercises the actual
# function svs_capture.py's --offscreen path calls, not a hand-derived
# reimplementation of it.
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


def test_offscreen_resize_tracks_requested_size(svs_capture, fix, qtbot):
    """AER-1692 regression: resize_for_offscreen_capture() must leave the
    widget's internal viewport tracking the requested capture size, not
    stuck at whatever size it had when set_svs_config() installed it.

    Before the fix, AI.redraw()'s centerOn() call -- which reads
    viewport().width()/height(), not the outer widget's own (correctly
    resized) size -- always centred the scene on the same fixed point, so
    the AI overlay's centre row never moved with --width/--height.
    """
    from PyQt6.QtCore import QPointF
    from pyefis.instruments.ai import AI

    widget = AI(None, show_fpm=False)
    qtbot.addWidget(widget)
    widget.set_svs_config({"enabled": False})

    for width, height in [(800, 600), (1920, 1200)]:
        svs_capture.resize_for_offscreen_capture(widget, width, height)

        assert widget.viewport().width() == width
        assert widget.viewport().height() == height

        # At rest (zero pitch/roll, horizon_position=50) the scene's centre
        # point is the pitch=0 horizon -- it must land at the viewport's
        # own vertical centre, scaling with height rather than sitting at a
        # fixed absolute row.
        horizon_view_y = widget.mapFromScene(
            QPointF(widget.scene.width() / 2, widget.scene.height() / 2)
        ).y()
        assert horizon_view_y == pytest.approx(height / 2, abs=1)


def test_render_offscreen_frame_flushes_gl_every_call(svs_capture, fix, qtbot,
                                                       monkeypatch):
    """AER-1697 regression: render_offscreen_frame() must end every call
    with a GL flush (``glFinish()``).

    The offscreen FBO is never presented through ``eglSwapBuffers`` -- no
    window, no swap chain -- so without an explicit flush the V3D kernel
    driver never gets a frame boundary to reclaim the per-submission
    scratch/binning BOs each draw allocates. Measured on the Pi 5 (real
    terrain, ``pyefis.service`` holding the display concurrently): without
    this call, ``pump()``'s 16ms tick loop leaked ~100-120 new BOs (~1.9 MB)
    on *every* tick while waiting for ``settled()`` -- unbounded and linear
    in tick count (``/sys/kernel/debug/dri/*/bo_stats`` climbed the whole
    run) -- the mechanism behind the ``Failed to allocate device memory for
    BO`` crashes and one board reboot. With the call, the same counters go
    flat within the first couple of ticks and stay flat for 1000+
    subsequent ones. No real GPU exists in this sandbox (see the module
    docstring above), so ctx/fbo are mocked here and only the flush call
    count is asserted -- this pins "a flush happens every frame", not the
    render's pixel output, which the rest of this suite already can't
    exercise here either.
    """
    from unittest.mock import MagicMock
    from PyQt6.QtGui import QImage
    from pyefis.instruments.ai import AI

    widget = AI(None, show_fpm=False)
    qtbot.addWidget(widget)
    widget.set_svs_config({"enabled": False})
    svs_capture.resize_for_offscreen_capture(widget, 64, 64)

    ctx = MagicMock()
    ctx.makeCurrent.return_value = True
    surface = MagicMock()
    fbo = MagicMock()
    fbo.bind.return_value = True
    paint_device = QImage(64, 64, QImage.Format.Format_RGB32)

    finish = MagicMock()
    monkeypatch.setattr(svs_capture.gl, "glFinish", finish)

    for _ in range(3):
        svs_capture.render_offscreen_frame(
            widget, ctx, surface, fbo, paint_device)

    assert finish.call_count == 3


# ---------------------------------------------------------------------------
# --width/--height on the windowed path (AER-1810): eglfs (no window manager)
# forces a windowed top-level to the screen size regardless of what was
# requested, delivering the requested geometry as a first resizeEvent and the
# forced one as a second (the same two-resize sequence AER-1785 diagnosed).
# check_delivered_size() is the pure geometry check main() refuses a capture
# on; it needs no GL context, so it's exercised directly here the same way
# resize_for_offscreen_capture() is above -- the actual eglfs forcing behavior
# itself is a platform fact, not something this suite can or needs to
# reproduce, only the resulting mismatch this code must catch.
# ---------------------------------------------------------------------------

def test_check_delivered_size_matches_the_requested_geometry(svs_capture, fix, qtbot):
    widget = svs_capture.CapturingAI(None, show_fpm=False)
    qtbot.addWidget(widget)
    widget.set_svs_config({"enabled": False})

    widget.resize(800, 600)
    widget.viewport().resize(800, 600)

    assert svs_capture.check_delivered_size(widget.viewport(), 800, 600) is None


def test_check_delivered_size_flags_eglfs_forced_fullscreen(svs_capture, fix, qtbot):
    """Simulates the AER-1785 two-resize sequence: a first resize at the
    requested --width/--height, then a second (the platform forcing
    fullscreen) that leaves the viewport at a different size. A caller who
    asked for 800x600 must see this as a hard mismatch against 1920x1200,
    not have it silently pass."""
    widget = svs_capture.CapturingAI(None, show_fpm=False)
    qtbot.addWidget(widget)
    widget.set_svs_config({"enabled": False})

    widget.resize(800, 600)
    widget.viewport().resize(800, 600)
    widget.resize(1920, 1200)
    widget.viewport().resize(1920, 1200)

    mismatch = svs_capture.check_delivered_size(widget.viewport(), 800, 600)
    assert mismatch == (1920, 1200)


def test_check_delivered_size_offscreen_target_always_matches_by_construction(
    svs_capture, fix, qtbot
):
    """The offscreen FBO (make_offscreen_target) is allocated at exactly the
    requested size with no window manager involved -- unlike the windowed
    path, resize_for_offscreen_capture cannot be forced to a different
    geometry, so check_delivered_size must report no mismatch after it."""
    from pyefis.instruments.ai import AI

    widget = AI(None, show_fpm=False)
    qtbot.addWidget(widget)
    widget.set_svs_config({"enabled": False})

    svs_capture.resize_for_offscreen_capture(widget, 1920, 1200)

    assert svs_capture.check_delivered_size(widget.viewport(), 1920, 1200) is None


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
    out.write_bytes(b"not-really-a-png")
    svs_capture._write_manifest(
        out,
        pyefis_rev="abc1234-dirty",
        capture_mode="windowed",
        requested_size=(800, 600),
        actual_size=(800, 600),
    )

    manifest = tmp_path / "frame.png.json"
    assert manifest.is_file()
    written = json.loads(manifest.read_text())
    assert written == {
        "pyefis_rev": "abc1234-dirty",
        "capture_mode": "windowed",
        "requested_size": [800, 600],
        "actual_size": [800, 600],
        "argv": written["argv"],
        "sha256": hashlib.sha256(out.read_bytes()).hexdigest(),
    }
    assert written["argv"]  # non-empty; exact value is the pytest invocation


def test_write_manifest_sha256_matches_the_frame_bytes(svs_capture, tmp_path):
    out = tmp_path / "frame.png"
    out.write_bytes(b"some png bytes")
    svs_capture._write_manifest(
        out,
        pyefis_rev="abc1234",
        capture_mode="offscreen",
        requested_size=(1920, 1200),
        actual_size=(1920, 1200),
    )

    manifest = json.loads((tmp_path / "frame.png.json").read_text())
    assert manifest["sha256"] == hashlib.sha256(b"some png bytes").hexdigest()
    assert manifest["capture_mode"] == "offscreen"
    assert manifest["requested_size"] == [1920, 1200]
    assert manifest["actual_size"] == [1920, 1200]
