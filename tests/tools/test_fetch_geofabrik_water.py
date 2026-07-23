#  SPDX-License-Identifier: GPL-2.0-or-later
"""Tests for tools/fetch_geofabrik_water.py -- issue #106 double-append.

The post-loop cache sweep (meant to serve --build-only, whose skipped
download loop leaves ``shp_paths`` empty) also ran on the normal path,
where the loop had already appended every requested area. Every
shapefile then reached build_water_db.py twice, and its plain INSERTs
doubled each inland polygon in the output (the 2026q2r6 candidate:
128 args for 64 areas, 18.9 GB vs the canonical 4 GB). These tests pin
the input-assembly contract: each --osm-water arg exactly once, on
every assembly path.

Plain pytest + tmp_path + monkeypatch; the builder subprocess is
captured, never run, so there are no build-time deps to skip on.
"""

import importlib.util
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, _ROOT / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fw = _load("fetch_geofabrik_water")

LAYER = fw.WATER_LAYER_FILES[0]


def _seed_cache(cache_dir, areas):
    """Pre-extract the given areas so the download loop resume path
    (and the --build-only sweep) sees them as done."""
    for area in areas:
        d = cache_dir / "extracted" / area.replace("/", "-")
        d.mkdir(parents=True)
        (d / LAYER).write_bytes(b"stub")


def _run_main(monkeypatch, tmp_path, states, extra_args=()):
    """Run main() against a tmp cache with the builder call captured.
    Returns the list of --osm-water argument values it would pass."""
    cache = tmp_path / "cache"
    out = tmp_path / "out.sqlite"
    calls = []

    def _fake_builder(cmd):
        # main() stats the output after the builder returns.
        calls.append(cmd)
        out.write_bytes(b"stub")

    monkeypatch.setattr(fw.subprocess, "check_call", _fake_builder)
    monkeypatch.setattr(sys, "argv", [
        "fetch_geofabrik_water.py",
        "--states", states,
        "--cache-dir", str(cache),
        "--output", str(out),
        "--ocean-shp", "", "--ne-lakes", "",
        *extra_args,
    ])
    fw.main()
    assert len(calls) == 1
    cmd = calls[0]
    return [cmd[i + 1] for i, a in enumerate(cmd) if a == "--osm-water"]


def test_resume_path_passes_each_shapefile_once(monkeypatch, tmp_path):
    # Fully-cached normal run (the 2026q2r6 scenario): the sweep must
    # not re-append what the resume loop already added.
    (tmp_path / "cache").mkdir()
    _seed_cache(tmp_path / "cache", ["texas", "oklahoma"])
    paths = _run_main(monkeypatch, tmp_path, "texas,oklahoma")
    assert len(paths) == 2
    assert len(set(paths)) == 2


def test_build_only_passes_each_shapefile_once(monkeypatch, tmp_path):
    (tmp_path / "cache").mkdir()
    _seed_cache(tmp_path / "cache", ["texas", "oklahoma"])
    paths = _run_main(monkeypatch, tmp_path, "texas,oklahoma",
                      extra_args=("--build-only",))
    assert len(paths) == 2
    assert len(set(paths)) == 2


def test_normal_path_excludes_unrequested_cached_areas(monkeypatch,
                                                       tmp_path):
    # A single-state run over a well-stocked cache must build that
    # state only -- the old sweep silently included every cached area.
    (tmp_path / "cache").mkdir()
    _seed_cache(tmp_path / "cache", ["texas", "oklahoma", "kansas"])
    paths = _run_main(monkeypatch, tmp_path, "texas")
    assert len(paths) == 1
    assert paths[0].endswith(str(Path("texas") / LAYER)) or \
        "texas" in paths[0]


def test_duplicate_states_arg_collapses(monkeypatch, tmp_path):
    (tmp_path / "cache").mkdir()
    _seed_cache(tmp_path / "cache", ["texas"])
    paths = _run_main(monkeypatch, tmp_path, "texas,texas")
    assert len(paths) == 1
