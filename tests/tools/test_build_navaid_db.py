#  SPDX-License-Identifier: GPL-2.0-or-later
"""Tests for tools/build_navaid_db.py -- the NASR NAV/FIX/AWY/HPF -> sqlite builder.

Covers the NASR 26-01 DPN change (effective 03 Sep 2026): the SP special-
route filter, and the backward-safety guarantee that it is a no-op on every
pre-Sept cycle. See makerplane-data docs/nasr_2601_dpn_prep.md sections 4 and 5.
And the published holds from HPF (HOLDFIX3, makerplane-data docs/hpf_holds.md).
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


HPF_BASE_HDR = ["HP_NAME", "HP_NO", "STATE_CODE", "COUNTRY_CODE", "FIX_ID",
                "ICAO_REGION_CODE", "NAV_ID", "NAV_TYPE", "HOLD_DIRECTION",
                "HOLD_DEG_OR_CRS", "AZIMUTH", "COURSE_INBOUND_DEG",
                "TURN_DIRECTION", "LEG_LENGTH_DIST"]


def _fixes(rows):
    """FIX_BASE rows with the ICAO region the hold join needs ('K2')."""
    return [r if len(r) == 6 else r + ("K2",) for r in rows]


def _write_nasr(d, *, airways=(), fixes=FIXES, navaids=(), holds=(),
                spd_alt=(), charts=(), omit=()):
    d.mkdir()
    _write(d / "NAV_BASE.csv",
           ["NAV_ID", "NAV_TYPE", "NAME", "FREQ", "ELEV", "LAT_DECIMAL", "LONG_DECIMAL",
            "STATE_CODE", "COUNTRY_CODE"],
           navaids)
    _write(d / "FIX_BASE.csv",
           ["FIX_ID", "FIX_USE_CODE", "LAT_DECIMAL", "LONG_DECIMAL", "CHARTS",
            "ICAO_REGION_CODE"],
           _fixes(fixes))
    _write(d / "AWY_BASE.csv",
           ["AWY_DESIGNATION", "AWY_ID", "AIRWAY_STRING"],
           airways)
    files = {"HPF_BASE.csv": (HPF_BASE_HDR, holds),
             "HPF_SPD_ALT.csv": (["HP_NAME", "HP_NO", "SPEED_RANGE", "ALTITUDE"], spd_alt),
             "HPF_CHRT.csv": (["HP_NAME", "HP_NO", "CHARTING_TYPE_DESC"], charts)}
    for name, (hdr, rows) in files.items():
        if name not in omit:
            _write(d / name, hdr, rows)


def _build(tmp_path, *, airways=(), fixes=FIXES, navaids=(), holds=(),
           spd_alt=(), charts=()):
    d = tmp_path / "nasr"
    _write_nasr(d, airways=airways, fixes=fixes, navaids=navaids, holds=holds,
                spd_alt=spd_alt, charts=charts)
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


# --- Published holds (HOLDFIX3, makerplane-data docs/hpf_holds.md) ---------

# Two NDBs share the ident "AA" in different states, as 33 NDB idents do in
# 2611; the hold names the state, and only that one is the right point.
NAVAIDS = [
    ("ABC", "VORTAC", "ABC", "112.0", "100", "34.5", "-118.5", "CA", "US"),
    ("AA", "NDB", "CEDAR", "350", "500", "33.53", "-82.61", "GA", "US"),
    ("AA", "NDB", "HECTOR", "400", "900", "47.01", "-96.82", "ND", "US"),
]


def _hold(name, no, *, fix="", icao="", nav="", nav_type="", state="CA",
          country="US", hold_dir="NE", ref="26", azimuth="RAD", inbound="206",
          turn="R", leg="4"):
    return (name, no, state, country, fix, icao, nav, nav_type, hold_dir, ref,
            azimuth, inbound, turn, leg)


def _holds(con):
    con.row_factory = sqlite3.Row
    return {(r["hp_name"], r["hp_no"]): dict(r)
            for r in con.execute("SELECT * FROM holds")}


def _limits(con):
    con.row_factory = sqlite3.Row
    return [dict(r) for r in con.execute(
        "SELECT * FROM hold_limits ORDER BY hp_name, hp_no, alt_raw")]


def test_two_holds_at_one_fix(tmp_path):
    """Two published holds at AAA (an ILS hold and an RNAV one, as at AABEE in
    2611): two rows, each with its own geometry and the fix's coordinates."""
    con = _build(tmp_path, navaids=NAVAIDS, holds=[
        _hold("AAA INT*CA*K2", "1", fix="AAA", icao="K2", nav="ABC",
              nav_type="VORTAC", ref="26", azimuth="RAD", inbound="206",
              turn="L", leg="4"),
        _hold("AAA WP*CA*K2", "2", fix="AAA", icao="K2", ref="80",
              azimuth="RNAV", inbound="260", turn="R", leg="10"),
    ], charts=[("AAA INT*CA*K2", "1", "ENROUTE LOW"),
               ("AAA INT*CA*K2", "1", "STAR"),
               ("AAA WP*CA*K2", "2", "IAP")])
    h = _holds(con)
    assert set(h) == {("AAA INT*CA*K2", 1), ("AAA WP*CA*K2", 2)}
    one, two = h[("AAA INT*CA*K2", 1)], h[("AAA WP*CA*K2", 2)]
    assert (one["point_id"], one["point_icao"], one["point_type"]) == ("AAA", "K2", "FIX")
    assert (one["lat"], one["lon"]) == (two["lat"], two["lon"]) == (34.0, -119.0)
    assert (one["nav_id"], one["nav_type"], one["hold_ref_deg"], one["azimuth"]) == (
        "ABC", "VORTAC", 26, "RAD")
    assert (one["inbound_crs"], one["turn"], one["leg_nm"]) == (206, "L", 4)
    assert one["charts"] == "ENROUTE LOW|STAR"
    assert (two["nav_id"], two["nav_type"], two["azimuth"]) == (None, None, "RNAV")
    assert (two["inbound_crs"], two["turn"], two["leg_nm"], two["charts"]) == (
        260, "R", 10, "IAP")


def test_hold_at_a_navaid(tmp_path):
    """FIX_ID empty: the point is the navaid, keyed by id, type and state."""
    con = _build(tmp_path, navaids=NAVAIDS, holds=[
        _hold("ABC VORTAC*CA", "1", nav="ABC", nav_type="VORTAC", ref="90",
              azimuth="RAD", inbound="270")])
    h = _holds(con)[("ABC VORTAC*CA", 1)]
    assert (h["point_id"], h["point_icao"], h["point_type"]) == ("ABC", None, "VORTAC")
    assert (h["lat"], h["lon"]) == (34.5, -118.5)
    assert (h["nav_id"], h["inbound_crs"]) == ("ABC", 270)


def test_navaid_hold_takes_the_ident_in_its_own_state(tmp_path):
    """NAV_ID + NAV_TYPE is not unique: the GA hold must land on the GA NDB,
    not the ND one 1,000 miles away."""
    con = _build(tmp_path, navaids=NAVAIDS, holds=[
        _hold("CEDAR NDB*GA", "1", nav="AA", nav_type="NDB", state="GA"),
        _hold("HECTOR NDB*ND", "1", nav="AA", nav_type="NDB", state="ND")])
    h = _holds(con)
    assert (h[("CEDAR NDB*GA", 1)]["lat"], h[("CEDAR NDB*GA", 1)]["lon"]) == (33.53, -82.61)
    assert (h[("HECTOR NDB*ND", 1)]["lat"], h[("HECTOR NDB*ND", 1)]["lon"]) == (47.01, -96.82)


def test_navaid_key_still_ambiguous_is_dropped(tmp_path, capsys):
    """Two NDBs with the same ident, type and state but far apart (MB in MI,
    2611): the hold cannot be placed, so it is dropped, never guessed."""
    navaids = NAVAIDS + [
        ("MB", "NDB", "ONE", "200", "0", "44.27", "-86.14", "MI", "US"),
        ("MB", "NDB", "TWO", "201", "0", "43.46", "-84.18", "MI", "US")]
    con = _build(tmp_path, navaids=navaids, holds=[
        _hold("ONE NDB*MI", "1", nav="MB", nav_type="NDB", state="MI")])
    assert _holds(con) == {}
    assert "dropped 1 holds at unresolved points" in capsys.readouterr().out


def test_timed_hold_has_no_leg(tmp_path):
    """LEG_LENGTH_DIST empty = a timed hold; NASR never publishes the time,
    so leg_nm is NULL, not 0 and not a guessed minute."""
    con = _build(tmp_path, holds=[_hold("BBB INT*CA*K2", "1", fix="BBB",
                                        icao="K2", leg="")])
    assert _holds(con)[("BBB INT*CA*K2", 1)]["leg_nm"] is None


def test_non_numeric_reference_and_empty_direction(tmp_path):
    """32 rows in 2611 carry a direction letter in HOLD_DEG_OR_CRS, and 8 have
    no HOLD_DIRECTION: both become NULL rather than a bogus number."""
    con = _build(tmp_path, holds=[_hold("BBB INT*CA*K2", "1", fix="BBB",
                                        icao="K2", ref="SW", hold_dir="")])
    h = _holds(con)[("BBB INT*CA*K2", 1)]
    assert (h["hold_ref_deg"], h["hold_dir"]) == (None, None)


ALT_SHAPES = [
    ("30/60", 3000, 6000),     # MIN/MAX, hundreds of feet
    ("180/450", 18000, 45000),
    ("20-100", None, None),    # 318 Gulf offshore rows, a dash
    ("200", None, None),       # single number (speed and altitude swapped)
    ("085140", None, None),    # one six-digit run
    ("60/10", None, None),     # minimum above the maximum
    ("", None, None),
]


@pytest.mark.parametrize("raw,lo,hi", ALT_SHAPES)
def test_parse_altitude_shapes(raw, lo, hi):
    assert bn.parse_altitude(raw) == (lo, hi)


def test_hold_limits_keep_raw_text_for_every_shape(tmp_path, capsys):
    """Every altitude shape is carried with its raw text; only MIN/MAX gets
    parsed feet. Speed is a class label kept as text."""
    name = "CCC INT*CA*K2"
    con = _build(tmp_path, holds=[_hold(name, "1", fix="CCC", icao="K2")],
                 spd_alt=[(name, "1", "170/175" if raw == "20-100" else "200", raw)
                          for raw, _lo, _hi in ALT_SHAPES])
    got = {r["alt_raw"]: (r["alt_min_ft"], r["alt_max_ft"], r["speed_range"])
           for r in _limits(con)}
    for raw, lo, hi in ALT_SHAPES:
        assert got[raw or None][:2] == (lo, hi)
    assert got["20-100"][2] == "170/175" and got["30/60"][2] == "200"
    assert "5 altitudes not MIN/MAX" in capsys.readouterr().out


def test_unresolved_point_dropped_with_its_limits(tmp_path, capsys):
    """A hold at an ILS compass locator that NAV_BASE does not list (132 of
    the 138 misses in 2611): dropped, counted, and its speed/altitude rows go
    with it so hold_limits never names a missing hold."""
    con = _build(tmp_path, navaids=NAVAIDS, holds=[
        _hold("TUNGG LOM*IL", "1", nav="PI", nav_type="LO", state="IL"),
        _hold("ZZZZZ INT*CA*K2", "1", fix="ZZZZZ", icao="K2"),
        _hold("AAA INT*CA*K2", "1", fix="AAA", icao="K2")],
        spd_alt=[("TUNGG LOM*IL", "1", "200", "30/60"),
                 ("ZZZZZ INT*CA*K2", "1", "200", "30/60"),
                 ("AAA INT*CA*K2", "1", "200", "40/60")])
    assert set(_holds(con)) == {("AAA INT*CA*K2", 1)}
    assert [(r["hp_name"], r["alt_min_ft"]) for r in _limits(con)] == [
        ("AAA INT*CA*K2", 4000)]
    assert "dropped 2 holds at unresolved points" in capsys.readouterr().out


def test_fix_region_is_part_of_the_key(tmp_path):
    """A fix id is unique only within its ICAO region."""
    con = _build(tmp_path, holds=[_hold("AAA INT*CA*K1", "1", fix="AAA", icao="K1")])
    assert _holds(con) == {}


@pytest.mark.parametrize("missing", bn.HPF_FILES)
def test_refuses_to_run_without_an_hpf_csv(tmp_path, missing):
    """A navaids pack built for holds that silently has none is the failure to
    avoid: a missing HPF CSV stops the build before any output is written."""
    d = tmp_path / "nasr"
    _write_nasr(d, omit=(missing,))
    out = tmp_path / "navaids.sqlite"
    with pytest.raises(SystemExit, match=missing):
        bn.main(["--nasr-dir", str(d), "-o", str(out)])
    assert not out.exists()


def test_explicit_paths_need_hpf(tmp_path):
    d = tmp_path / "nasr"
    _write_nasr(d)
    base = ["--nav", str(d / "NAV_BASE.csv"), "--fix", str(d / "FIX_BASE.csv"),
            "--awy", str(d / "AWY_BASE.csv"), "-o", str(tmp_path / "o.sqlite")]
    with pytest.raises(SystemExit):
        bn.main(base)
    assert bn.main(base + ["--hpf", str(d)]) == 0


def test_existing_tables_unchanged_by_holds(tmp_path):
    """The holds tables are additive: navaids/fixes/awy_segments keep their
    columns, so a device whose pyEfis does not read holds is unaffected."""
    con = _build(tmp_path, airways=[("V", "V27", "AAA BBB")], navaids=NAVAIDS)
    cols = {t: [r[1] for r in con.execute(f"PRAGMA table_info({t})")]
            for t in ("navaids", "fixes", "awy_segments")}
    assert cols == {
        "navaids": ["id", "type", "name", "freq", "elev_ft", "lat", "lon"],
        "fixes": ["id", "use_code", "lat", "lon"],
        "awy_segments": ["awy_id", "seq", "p1", "lat1", "lon1",
                         "p2", "lat2", "lon2"]}
