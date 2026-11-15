#  SPDX-License-Identifier: GPL-2.0-or-later
"""Tests for pyefis.flightplan.catalog -- FP4 (billmallard/pyEfis#183)."""

import time

import pytest

from pyefis.flightplan.catalog import (
    Catalog,
    ManagedRouteError,
    MANAGED_PREFIX,
    slugify,
)
from pyefis.flightplan.model import FlightPlan, MAX_WAYPOINTS, Waypoint

KSBA = Waypoint(id="KSBA", type="airport", lat=34.42621, lon=-119.84037)
KSMX = Waypoint(id="KSMX", type="airport", lat=34.89892, lon=-120.45758)


def _plan(name="KSBA-KSMX"):
    return FlightPlan(name=name, waypoints=[
        Waypoint(id=KSBA.id, type=KSBA.type, lat=KSBA.lat, lon=KSBA.lon),
        Waypoint(id=KSMX.id, type=KSMX.type, lat=KSMX.lat, lon=KSMX.lon),
    ])


# ---------------------------------------------------------------------------
# slugify
# ---------------------------------------------------------------------------
def test_slugify_strips_unsafe_characters():
    assert slugify("KSBA -> KSMX") == "KSBA_-_KSMX"
    assert slugify("KSBA / KSMX") == "KSBA_KSMX"
    assert slugify("") == "route"


# ---------------------------------------------------------------------------
# Construct-never-raises / missing directory
# ---------------------------------------------------------------------------
def test_missing_directory_list_is_empty(tmp_path):
    cat = Catalog(tmp_path / "does" / "not" / "exist")
    assert cat.list() == []


def test_directory_created_on_first_save(tmp_path):
    routes_dir = tmp_path / "routes"
    assert not routes_dir.exists()
    cat = Catalog(routes_dir)
    cat.save(_plan())
    assert routes_dir.is_dir()


# ---------------------------------------------------------------------------
# save / load / list / delete
# ---------------------------------------------------------------------------
def test_save_derives_slug_from_name(tmp_path):
    cat = Catalog(tmp_path)
    slug = cat.save(_plan("KSBA-KSMX"))
    assert slug == "KSBA-KSMX"
    assert (tmp_path / "KSBA-KSMX.json").is_file()


def test_save_load_round_trip(tmp_path):
    cat = Catalog(tmp_path)
    slug = cat.save(_plan())
    loaded = cat.load(slug)
    assert [w.id for w in loaded.waypoints] == ["KSBA", "KSMX"]
    assert loaded.created and loaded.modified


def test_load_missing_route_raises():
    cat = Catalog("/nonexistent")
    with pytest.raises(Exception):
        cat.load("nope")


def test_list_reports_name_distance_count_comment_mtime(tmp_path):
    cat = Catalog(tmp_path)
    plan = _plan()
    plan.comment = "the bench route"
    cat.save(plan)
    entries = cat.list()
    assert len(entries) == 1
    entry = entries[0]
    assert entry.slug == "KSBA-KSMX"
    assert entry.name == "KSBA-KSMX"
    assert entry.count == 2
    assert entry.comment == "the bench route"
    assert entry.total_nm == pytest.approx(41.648, abs=1e-3)
    assert entry.mtime > 0


def test_list_skips_unreadable_files(tmp_path):
    cat = Catalog(tmp_path)
    cat.save(_plan())
    (tmp_path / "garbage.json").write_text("not json", encoding="utf-8")
    entries = cat.list()
    assert len(entries) == 1


def test_delete_removes_file(tmp_path):
    cat = Catalog(tmp_path)
    slug = cat.save(_plan())
    cat.delete(slug)
    assert cat.list() == []


def test_delete_missing_file_is_a_noop(tmp_path):
    cat = Catalog(tmp_path)
    cat.delete("never-existed")  # must not raise


# ---------------------------------------------------------------------------
# copy / invert
# ---------------------------------------------------------------------------
def test_copy_persists_a_new_entry_and_leaves_original(tmp_path):
    cat = Catalog(tmp_path)
    slug = cat.save(_plan())
    new_slug = cat.copy(slug, "KSBA-KSMX copy")
    assert new_slug != slug
    assert [w.id for w in cat.load(slug).waypoints] == ["KSBA", "KSMX"]
    assert [w.id for w in cat.load(new_slug).waypoints] == ["KSBA", "KSMX"]
    assert cat.load(new_slug).name == "KSBA-KSMX copy"


def test_invert_does_not_persist(tmp_path):
    cat = Catalog(tmp_path)
    slug = cat.save(_plan())
    inverted = cat.invert(slug)
    assert [w.id for w in inverted.waypoints] == ["KSMX", "KSBA"]
    # the stored plan is unchanged (guide 3-36)
    assert [w.id for w in cat.load(slug).waypoints] == ["KSBA", "KSMX"]
    assert set(p.stem for p in tmp_path.glob("*.json")) == {slug}


# ---------------------------------------------------------------------------
# managed_ refusal
# ---------------------------------------------------------------------------
def test_save_refuses_managed_slug(tmp_path):
    cat = Catalog(tmp_path)
    plan = _plan(f"{MANAGED_PREFIX}from_configurator")
    with pytest.raises(ManagedRouteError):
        cat.save(plan)
    assert cat.list() == []


def test_save_refuses_explicit_managed_slug(tmp_path):
    cat = Catalog(tmp_path)
    with pytest.raises(ManagedRouteError):
        cat.save(_plan(), slug=f"{MANAGED_PREFIX}foo")


def test_delete_refuses_managed_slug(tmp_path):
    import json

    cat = Catalog(tmp_path)
    # Simulate a configurator-delivered file already on disk.
    tmp_path.mkdir(parents=True, exist_ok=True)
    managed_path = tmp_path / f"{MANAGED_PREFIX}kfoo.json"
    managed_path.write_text(json.dumps(_plan().to_json()), encoding="utf-8")
    with pytest.raises(ManagedRouteError):
        cat.delete(f"{MANAGED_PREFIX}kfoo")
    assert managed_path.is_file()


def test_copy_into_managed_slug_refused(tmp_path):
    cat = Catalog(tmp_path)
    slug = cat.save(_plan())
    with pytest.raises(ManagedRouteError):
        cat.copy(slug, f"{MANAGED_PREFIX}hijack")


# ---------------------------------------------------------------------------
# Atomicity
# ---------------------------------------------------------------------------
def test_save_atomic_failure_leaves_original_intact(tmp_path, monkeypatch):
    cat = Catalog(tmp_path)
    slug = cat.save(_plan())
    original_bytes = (tmp_path / f"{slug}.json").read_bytes()

    def _boom(*_a, **_k):
        raise OSError("simulated crash between tmp write and replace")

    monkeypatch.setattr("pyefis.flightplan.catalog.os.replace", _boom)
    other = _plan("changed name that would overwrite")
    with pytest.raises(OSError):
        cat.save(other, slug=slug)

    assert (tmp_path / f"{slug}.json").read_bytes() == original_bytes


# ---------------------------------------------------------------------------
# Budget: save/load of a 50-waypoint route <= 20 ms
# ---------------------------------------------------------------------------
def test_save_load_50_waypoint_budget_ms(tmp_path):
    cat = Catalog(tmp_path)
    plan = FlightPlan(name="BIG", waypoints=[
        Waypoint(id=f"WP{i:02d}", type="fix", lat=float(i), lon=float(i))
        for i in range(MAX_WAYPOINTS)
    ])
    t0 = time.perf_counter()
    slug = cat.save(plan)
    cat.load(slug)
    dt_ms = (time.perf_counter() - t0) * 1000
    assert dt_ms < 100, f"50-waypoint save+load took {dt_ms:.1f} ms (budget 20 ms; generous margin here)"


# ---------------------------------------------------------------------------
# Qt-free
# ---------------------------------------------------------------------------
def test_no_qt_import():
    import subprocess
    import sys
    from pathlib import Path

    src_root = str(Path(__file__).resolve().parents[2] / "src")
    code = (
        "import sys\n"
        "import pyefis.flightplan.catalog\n"
        "assert 'PyQt6' not in sys.modules, sorted(m for m in sys.modules if 'PyQt' in m)\n"
    )
    result = subprocess.run([sys.executable, "-c", code], cwd=src_root,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
