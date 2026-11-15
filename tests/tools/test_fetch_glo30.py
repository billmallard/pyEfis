#  SPDX-License-Identifier: GPL-2.0-or-later
"""Tests for tools/fetch_glo30.py tile selection (AER-4709).

A bounding box around the makerplane-data terrain regions also covers
land outside all of them: on 2026-11-03 it counted 185 tiles to fetch
when the tree lacked only 89 (AER-4710). --tiles-file fetches an exact
list, in the formats makerplane-data writes (glo30_tiles.txt and
make_glo30_tiles.py --check-tree output). There is no default selection,
so a run without one fails instead of fetching a box nobody chose.

No network: tileList.txt is seeded in --dest, and every run is --dry-run.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, _ROOT / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fg = _load("fetch_glo30")


def _name(tile):
    return f"Copernicus_DSM_COG_10_{tile[:3]}_00_{tile[3:]}_00_DEM"


INVENTORY = [_name(t) for t in (
    "N51W177", "N52W176", "N08W080", "N08W070", "N34W119", "S01W080")]


def _run(monkeypatch, tmp_path, capsys, *argv):
    (tmp_path / "tileList.txt").write_text("\n".join(INVENTORY) + "\n")
    monkeypatch.setattr(sys, "argv", [
        "fetch_glo30.py", "--dest", str(tmp_path), "--dry-run", *argv])
    fg.main()
    return capsys.readouterr().out


def test_tiles_file_takes_both_makerplane_data_formats(
        monkeypatch, tmp_path, capsys):
    listing = tmp_path / "list.txt"
    listing.write_text(
        "# Copernicus GLO-30 tiles inside the terrain regions\n"
        "N51W177\n"
        "\n"
        "N08W080  mexico-central-america\n"   # --check-tree line
        "N52W176  alaska\n")
    out = _run(monkeypatch, tmp_path, capsys, "--tiles-file", str(listing))
    assert "3 of 3 listed tiles exist" in out


def test_listed_selection_is_exact_not_a_box():
    # A box around N51W177 and N08W080 would also take N34W119 and N08W070.
    wanted, absent = fg.select_listed(INVENTORY, ["N51W177", "N08W080"])
    assert wanted == [_name("N51W177"), _name("N08W080")]
    assert absent == []


def test_listed_tile_without_inventory_entry_is_reported(
        monkeypatch, tmp_path, capsys):
    out = _run(monkeypatch, tmp_path, capsys,
               "--tiles", "N34W119", "N40W140", "bogus")
    assert "no GLO-30 tile for N40W140" in out
    assert "no GLO-30 tile for bogus" in out
    assert "1 of 3 listed tiles exist" in out


def test_duplicates_collapse():
    wanted, _ = fg.select_listed(INVENTORY, ["N34W119", "n34w119"])
    assert wanted == [_name("N34W119")]


def test_bbox_is_inclusive_sw_corners():
    got = fg.select_bbox(INVENTORY, 8, 52, -177, -80)
    assert set(got) == {_name(t) for t in (
        "N51W177", "N52W176", "N08W080", "N34W119")}


def test_no_selection_is_an_error(monkeypatch, tmp_path, capsys):
    with pytest.raises(SystemExit) as e:
        _run(monkeypatch, tmp_path, capsys)
    assert e.value.code == 2
    assert "there is no default" in capsys.readouterr().err


def test_partial_bbox_is_an_error(monkeypatch, tmp_path, capsys):
    with pytest.raises(SystemExit):
        _run(monkeypatch, tmp_path, capsys, "--min-lat", "7")


def test_list_and_bbox_together_is_an_error(monkeypatch, tmp_path, capsys):
    with pytest.raises(SystemExit):
        _run(monkeypatch, tmp_path, capsys, "--tiles", "N34W119",
             "--min-lat", "7", "--max-lat", "71",
             "--min-lon", "-177", "--max-lon", "-53")
