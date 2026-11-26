#  SPDX-License-Identifier: GPL-2.0-or-later
"""Tests for tools/build_navaid_db.py -- the NASR NAV/FIX/AWY -> sqlite builder.

Focused on the NASR 26-01 DPN change (effective 03 Sep 2026): the SP special-
route filter, and the backward-safety guarantee that it is a no-op on every
pre-Sept cycle. See makerplane-data docs/nasr_2601_dpn_prep.md sections 4 and 5.
Plain pytest + tmp_path: synthetic CSVs, no network, no Qt.
"""

import csv
import importlib.util
import sqlite3
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]

_OPEN = []


@pytest.fixture(autouse=True)
def _close_connections():
    yield
    while _OPEN:
        _OPEN.pop().close()


def _load(name):
    spec = importlib.util.spec_from_file_location(name, _ROOT / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bn = _load("build_navaid_db")


def _write(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


# Three shared points; CCC is charted only as SPECIAL ENROUTE (a fix on the SP
# route), which the builder ingests unconditionally (it never reads CHARTS).
FIXES = [
    ("AAA", "RP", "34.0", "-119.0", "LOW ALTITUDE RNAV"),
    ("BBB", "RP", "35.0", "-118.0", "LOW ALTITUDE RNAV"),
    ("CCC", "RP", "36.0", "-117.0", "SPECIAL ENROUTE"),
]


def _build(tmp_path, *, airways, fixes=FIXES, navaids=()):
    d = tmp_path / "nasr"
    d.mkdir()
    _write(d / "NAV_BASE.csv",
           ["NAV_ID", "NAV_TYPE", "NAME", "FREQ", "ELEV", "LAT_DECIMAL", "LONG_DECIMAL"],
           navaids)
    _write(d / "FIX_BASE.csv",
           ["FIX_ID", "FIX_USE_CODE", "LAT_DECIMAL", "LONG_DECIMAL", "CHARTS"],
           fixes)
    _write(d / "AWY_BASE.csv",
           ["AWY_DESIGNATION", "AWY_ID", "AIRWAY_STRING"],
           airways)
    out = tmp_path / "navaids.sqlite"
    bn.main(["--nasr-dir", str(d), "-o", str(out)])
    con = sqlite3.connect(out)
    _OPEN.append(con)
    return con


def test_sp_route_filtered_out_others_kept(tmp_path):
    """A V route, a non-regulatory AT route, and an SP route: SP is absent from
    awy_segments; V and AT are present (we filter on the designation, never on
    REGULATORY, so legitimate non-reg oceanic routes stay)."""
    con = _build(tmp_path, airways=[
        ("V", "V27", "AAA BBB"),
        ("AT", "A1", "BBB CCC"),
        ("SP", "ZK9999", "AAA BBB CCC"),
    ])
    awys = {r[0] for r in con.execute("SELECT DISTINCT awy_id FROM awy_segments")}
    assert "V27" in awys and "A1" in awys
    assert "ZK9999" not in awys


def test_skip_count_reported(tmp_path, capsys):
    _build(tmp_path, airways=[
        ("V", "V27", "AAA BBB"),
        ("SP", "ZK1", "AAA BBB"),
        ("SP", "ZK2", "BBB CCC"),
    ])
    assert "skipped 2 special routes" in capsys.readouterr().out


def test_navaids_and_fixes_carry_their_region(tmp_path):
    """FPA5 (AER-6544): the pack keeps where each record is, so a resolver
    can tell two same-named places apart. Real cycle-2611 rows: two of the
    three ``BR`` NDBs (MN, TX), the Freeport VOR/DME in the Bahamas (no
    state), and GOLET, whose FIX_BASE row codes ICAO region K2."""
    d = tmp_path / "nasr"
    d.mkdir()
    _write(d / "NAV_BASE.csv",
           ["NAV_ID", "NAV_TYPE", "STATE_CODE", "COUNTRY_CODE", "REGION_CODE", "NAME",
            "FREQ", "ELEV", "LAT_DECIMAL", "LONG_DECIMAL"],
           [("BR", "NDB", "MN", "US", "AGL", "LAREW", "251", "1260", "46.4566203", "-94.02243002"),
            ("BR", "NDB", "TX", "US", "ASW", "DEPOO", "393", "28.5", "25.98366283", "-97.50909794"),
            ("ZFP", "VOR/DME", "", "BS", "", "FREEPORT", "113.2", "7", "26.55534722", "-78.69784722")])
    _write(d / "FIX_BASE.csv",
           ["FIX_ID", "ICAO_REGION_CODE", "STATE_CODE", "COUNTRY_CODE", "FIX_USE_CODE",
            "LAT_DECIMAL", "LONG_DECIMAL"],
           [("GOLET", "K2", "CA", "US", "RP", "34.28135", "-119.864375")])
    _write(d / "AWY_BASE.csv", ["AWY_DESIGNATION", "AWY_ID", "AIRWAY_STRING"], [])
    out = tmp_path / "navaids.sqlite"
    bn.main(["--nasr-dir", str(d), "-o", str(out)])
    con = sqlite3.connect(out)
    _OPEN.append(con)

    assert con.execute("SELECT name, state, country FROM navaids ORDER BY lat").fetchall() == [
        ("Depoo", "TX", "US"), ("Freeport", "", "BS"), ("Larew", "MN", "US")]
    # NAV_BASE's REGION_CODE is the FAA region, not an ICAO one: not stored.
    assert "icao_region" not in {r[1] for r in con.execute("PRAGMA table_info(navaids)")}
    assert con.execute("SELECT id, icao_region, state, country FROM fixes").fetchall() == [
        ("GOLET", "K2", "CA", "US")]


def test_no_sp_rows_is_a_noop(tmp_path, capsys):
    """Pre-DPN fixture (no SP rows): every airway is built and the skip count is
    zero -- the regression guard for backward safety (section 4.3)."""
    con = _build(tmp_path, airways=[
        ("V", "V27", "AAA BBB"),
        ("AT", "A1", "BBB CCC"),
    ])
    awys = {r[0] for r in con.execute("SELECT DISTINCT awy_id FROM awy_segments")}
    assert awys == {"V27", "A1"}
    assert "skipped 0 special routes" in capsys.readouterr().out


def test_special_enroute_fix_kept_and_usable(tmp_path):
    """A fix charted only as SPECIAL ENROUTE is still ingested (section 5) and
    still resolves geometry for a KEPT airway that shares it -- so filtering SP
    airways never leaves a kept route with a geometry gap."""
    con = _build(tmp_path, airways=[("V", "V27", "BBB CCC")])
    assert "CCC" in {r[0] for r in con.execute("SELECT id FROM fixes")}
    seg = con.execute(
        "SELECT COUNT(*) FROM awy_segments WHERE awy_id='V27' AND (p1='CCC' OR p2='CCC')"
    ).fetchone()[0]
    assert seg == 1


def test_exclude_set_is_exactly_sp():
    """Guard against an accidental over-broad exclusion set."""
    assert bn.EXCLUDE_AWY_DESIGNATIONS == frozenset({"SP"})
