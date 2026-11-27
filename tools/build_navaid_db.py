#!/usr/bin/env python3
#  SPDX-License-Identifier: GPL-2.0-or-later
"""Build navaids.sqlite from FAA NASR NAV / FIX / AWY / HPF CSVs.

Feeds the moving map's navaid, fix and airway layers
(docs/moving_map_spec.md 5.3) and the published holds (HOLDFIX3).
Mirrors tools/build_airport_db.py: plain stdlib, produces a
self-contained sqlite consumed on-device.

    python tools/build_navaid_db.py \
        --nav NAV_BASE.csv --fix FIX_BASE.csv --awy AWY_BASE.csv \
        --hpf HPF_CSV_DIR/ -o navaids.sqlite

    # or point at a directory holding the extracted NAV/FIX/AWY/HPF CSV
    # zips (the makerplane-data pack pipeline calls it this way):
    python tools/build_navaid_db.py --nasr-dir extracted/ -o navaids.sqlite

Tables:
  navaids(id, type, name, freq, elev_ft, lat, lon, state, country)
  fixes(id, use_code, lat, lon, icao_region, state, country)
  awy_segments(awy_id, seq, p1, lat1, lon1, p2, lat2, lon2)
  holds(hp_name, hp_no, point_id, point_icao, point_type, lat, lon,
        nav_id, nav_type, hold_dir, hold_ref_deg, azimuth,
        inbound_crs, turn, leg_nm, charts)
  hold_limits(hp_name, hp_no, speed_range, alt_raw,
              alt_min_ft, alt_max_ft)

Airway geometry comes from AWY_BASE.AIRWAY_STRING (ordered point
names) joined against the fix/navaid coordinates. Points whose name
is ambiguous (duplicate id with different coordinates) or unknown are
skipped; the polyline connects across the gap.

Holds come from the NASR holding-pattern file, one row per (HP_NAME,
HP_NO); the contract is makerplane-data docs/hpf_holds.md. The hold
point is FIX_ID + ICAO_REGION_CODE, or the navaid NAV_ID + NAV_TYPE
when FIX_ID is empty, and its lat/lon is joined from FIX_BASE /
NAV_BASE of the same build. leg_nm NULL means a timed hold: NASR never
publishes the time. A hold whose point does not resolve is dropped and
counted.
"""

import argparse
import csv
import re
import sqlite3
from pathlib import Path

# SP = SPECIAL ROUTE (NASR 26-01 DPN, effective 03 Sep 2026): non-regulatory
# ZK helicopter-air-ambulance RNAV routes. Per the FAA they are "not included
# on public charts" and may not be filed or flown without Flight Standards
# approval -- so they must never be drawn on the moving map. Filter them out at
# build time by their AWY_DESIGNATION. See makerplane-data
# docs/nasr_2601_dpn_prep.md section 4. No SP rows exist before the 03 Sep
# cycle, so this is a no-op on every current pack.
EXCLUDE_AWY_DESIGNATIONS = frozenset({"SP"})

# The three HPF members the holds tables need. All are required: a navaids pack
# built for holds that silently has none is the failure to avoid
# (makerplane-data docs/hpf_holds.md, "Proposed pack contract").
HPF_FILES = ("HPF_BASE.csv", "HPF_SPD_ALT.csv", "HPF_CHRT.csv")

# HPF_SPD_ALT.ALTITUDE is MIN/MAX in hundreds of feet ("30/60"). Anything else
# (318 Gulf "20-100" rows, single numbers, speed and altitude swapped, a
# minimum above the maximum) keeps its raw text and no parsed altitudes.
_ALT_MIN_MAX = re.compile(r"(\d+)/(\d+)")


def _find_csv(root, name):
    hits = sorted(Path(root).rglob(name))
    if not hits:
        raise SystemExit(f"{name} not found under {root}")
    return str(hits[0])


def _f(row, key):
    v = (row.get(key) or "").strip()
    try:
        return float(v)
    except ValueError:
        return None


# Where a record is (FPA5, AER-6544): ``state`` and ``country`` are NASR's
# STATE_CODE and COUNTRY_CODE, and ``icao_region`` is FIX_BASE's
# ICAO_REGION_CODE (``K2``, ``PA``). NAV_BASE carries no ICAO region (its
# REGION_CODE is the FAA administrative region, ``AWP``), so navaids have
# none. The state is what tells the pilot which of two same-named places is
# meant: in cycle 2611, 37 idents name more than one place, almost all of them
# NDBs in different states (``BR``: MN, TX, IA), and FIX_BASE repeats no ident
# at all. The columns come last, so a reader that selects by name is
# unaffected, and a pack built before them simply lacks them.
def load_navaids(path):
    out = []
    with open(path, encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            lat, lon = _f(r, "LAT_DECIMAL"), _f(r, "LONG_DECIMAL")
            if lat is None or lon is None:
                continue
            out.append(((r.get("NAV_ID") or "").strip(),
                        (r.get("NAV_TYPE") or "").strip(),
                        (r.get("NAME") or "").strip().title(),
                        (r.get("FREQ") or "").strip(),
                        _f(r, "ELEV"), lat, lon,
                        (r.get("STATE_CODE") or "").strip(),
                        (r.get("COUNTRY_CODE") or "").strip()))
    return out


def load_fixes(path):
    out = []
    with open(path, encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            lat, lon = _f(r, "LAT_DECIMAL"), _f(r, "LONG_DECIMAL")
            if lat is None or lon is None:
                continue
            out.append(((r.get("FIX_ID") or "").strip(),
                        (r.get("FIX_USE_CODE") or "").strip(), lat, lon,
                        (r.get("ICAO_REGION_CODE") or "").strip(),
                        (r.get("STATE_CODE") or "").strip(),
                        (r.get("COUNTRY_CODE") or "").strip()))
    return out


def point_lookup(navaids, fixes):
    """name -> (lat, lon); ambiguous names (conflicting coords beyond
    ~1 NM) are dropped so airways never jump continents."""
    pts, dead = {}, set()
    for name, _t, _n, _f2, _e, lat, lon, *_where in navaids:
        _add(pts, dead, name, lat, lon)
    for name, _u, lat, lon, *_where in fixes:
        _add(pts, dead, name, lat, lon)
    for name in dead:
        pts.pop(name, None)
    return pts


def _add(pts, dead, name, lat, lon):
    if not name or name in dead:
        return
    old = pts.get(name)
    if old is None:
        pts[name] = (lat, lon)
    elif abs(old[0] - lat) + abs(old[1] - lon) > 0.02:
        dead.add(name)


def _s(row, key):
    return (row.get(key) or "").strip()


def _i(row, key):
    v = _s(row, key)
    return int(v) if v.isdigit() else None


def hold_point_index(nav_path, fix_path):
    """Hold-point key -> (lat, lon), with ambiguous keys dropped.

    A fix is keyed by (FIX_ID, ICAO_REGION_CODE). A navaid is keyed by
    (NAV_ID, NAV_TYPE, STATE_CODE, COUNTRY_CODE): NAV_ID + NAV_TYPE alone is
    not unique (33 NDB idents repeat across states in 2611, six of them with a
    hold), and the wrong one is hundreds of miles away."""
    pts, dead = {}, set()
    with open(fix_path, encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            lat, lon = _f(r, "LAT_DECIMAL"), _f(r, "LONG_DECIMAL")
            if lat is not None and lon is not None and _s(r, "FIX_ID"):
                _add(pts, dead, ("FIX", _s(r, "FIX_ID"),
                                 _s(r, "ICAO_REGION_CODE")), lat, lon)
    with open(nav_path, encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            lat, lon = _f(r, "LAT_DECIMAL"), _f(r, "LONG_DECIMAL")
            if lat is not None and lon is not None and _s(r, "NAV_ID"):
                _add(pts, dead, ("NAV", _s(r, "NAV_ID"), _s(r, "NAV_TYPE"),
                                 _s(r, "STATE_CODE"), _s(r, "COUNTRY_CODE")),
                     lat, lon)
    for k in dead:
        pts.pop(k, None)
    return pts


def parse_altitude(raw):
    """'30/60' -> (3000, 6000); None, None for every other shape."""
    m = _ALT_MIN_MAX.fullmatch(raw)
    if not m:
        return None, None
    lo, hi = int(m.group(1)) * 100, int(m.group(2)) * 100
    if lo > hi:
        return None, None
    return lo, hi


def load_holds(base_path, spd_alt_path, chrt_path, pts):
    """-> (holds rows, hold_limits rows, dropped hold count,
    limits rows whose altitude did not parse)."""
    charts = {}
    with open(chrt_path, encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            charts.setdefault((_s(r, "HP_NAME"), _i(r, "HP_NO")), []).append(
                _s(r, "CHARTING_TYPE_DESC"))
    holds, kept, dropped = [], set(), 0
    with open(base_path, encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            key = (_s(r, "HP_NAME"), _i(r, "HP_NO"))
            fix_id, nav_id = _s(r, "FIX_ID"), _s(r, "NAV_ID")
            nav_type = _s(r, "NAV_TYPE")
            if fix_id:
                icao = _s(r, "ICAO_REGION_CODE")
                point = (fix_id, icao or None, "FIX")
                ll = pts.get(("FIX", fix_id, icao))
            else:
                point = (nav_id, None, nav_type)
                ll = pts.get(("NAV", nav_id, nav_type, _s(r, "STATE_CODE"),
                              _s(r, "COUNTRY_CODE")))
            if ll is None:
                dropped += 1
                continue
            kept.add(key)
            holds.append(key + point + ll + (
                nav_id or None, nav_type or None,
                _s(r, "HOLD_DIRECTION") or None,
                _i(r, "HOLD_DEG_OR_CRS"),          # NULL when not numeric
                _s(r, "AZIMUTH") or None,
                _i(r, "COURSE_INBOUND_DEG"),
                _s(r, "TURN_DIRECTION") or None,
                _i(r, "LEG_LENGTH_DIST"),
                "|".join(charts.get(key, ())) or None))
    limits, unparsed = [], 0
    with open(spd_alt_path, encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            key = (_s(r, "HP_NAME"), _i(r, "HP_NO"))
            if key not in kept:
                continue
            raw = _s(r, "ALTITUDE")
            lo, hi = parse_altitude(raw)
            unparsed += lo is None
            limits.append(key + (_s(r, "SPEED_RANGE") or None, raw or None,
                                 lo, hi))
    return holds, limits, dropped, unparsed


def load_airways(path, pts):
    segs = []
    skipped = 0
    with open(path, encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            if (r.get("AWY_DESIGNATION") or "").strip() in EXCLUDE_AWY_DESIGNATIONS:
                skipped += 1          # SP special routes -- never charted
                continue
            awy = (r.get("AWY_ID") or "").strip()
            chain = [(n, pts[n]) for n in
                     (r.get("AIRWAY_STRING") or "").split()
                     if n in pts]
            for i, ((n1, c1), (n2, c2)) in enumerate(
                    zip(chain, chain[1:])):
                segs.append((awy, i, n1, c1[0], c1[1], n2, c2[0], c2[1]))
    return segs, skipped


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--nav")
    ap.add_argument("--fix")
    ap.add_argument("--awy")
    ap.add_argument("--nasr-dir",
                    help="directory holding extracted NAV/FIX/AWY CSVs; "
                         "stands in for any of --nav/--fix/--awy/--hpf")
    ap.add_argument("--hpf",
                    help="directory holding the extracted HPF CSVs "
                         "(HPF_BASE, HPF_SPD_ALT, HPF_CHRT); required")
    ap.add_argument("-o", "--output", default="navaids.sqlite")
    args = ap.parse_args(argv)

    if args.nasr_dir:
        args.nav = args.nav or _find_csv(args.nasr_dir, "NAV_BASE.csv")
        args.fix = args.fix or _find_csv(args.nasr_dir, "FIX_BASE.csv")
        args.awy = args.awy or _find_csv(args.nasr_dir, "AWY_BASE.csv")
        args.hpf = args.hpf or args.nasr_dir
    if not (args.nav and args.fix and args.awy and args.hpf):
        ap.error("provide --nav/--fix/--awy/--hpf or --nasr-dir")
    hpf = [_find_csv(args.hpf, name) for name in HPF_FILES]

    navaids = load_navaids(args.nav)
    fixes = load_fixes(args.fix)
    pts = point_lookup(navaids, fixes)
    segs, skipped_awy = load_airways(args.awy, pts)
    holds, limits, dropped_holds, unparsed_alt = load_holds(
        *hpf, hold_point_index(args.nav, args.fix))

    con = sqlite3.connect(args.output)
    cur = con.cursor()
    cur.executescript("""
        DROP TABLE IF EXISTS navaids;
        DROP TABLE IF EXISTS fixes;
        DROP TABLE IF EXISTS awy_segments;
        DROP TABLE IF EXISTS holds;
        DROP TABLE IF EXISTS hold_limits;
        CREATE TABLE navaids (id TEXT, type TEXT, name TEXT, freq TEXT,
                              elev_ft REAL, lat REAL, lon REAL,
                              state TEXT, country TEXT);
        CREATE TABLE fixes (id TEXT, use_code TEXT, lat REAL, lon REAL,
                            icao_region TEXT, state TEXT, country TEXT);
        CREATE TABLE awy_segments (awy_id TEXT, seq INTEGER,
                                   p1 TEXT, lat1 REAL, lon1 REAL,
                                   p2 TEXT, lat2 REAL, lon2 REAL);
        CREATE TABLE holds (hp_name TEXT, hp_no INTEGER,
                            point_id TEXT, point_icao TEXT, point_type TEXT,
                            lat REAL, lon REAL, nav_id TEXT, nav_type TEXT,
                            hold_dir TEXT, hold_ref_deg INTEGER, azimuth TEXT,
                            inbound_crs INTEGER, turn TEXT, leg_nm INTEGER,
                            charts TEXT);
        CREATE TABLE hold_limits (hp_name TEXT, hp_no INTEGER,
                                  speed_range TEXT, alt_raw TEXT,
                                  alt_min_ft INTEGER, alt_max_ft INTEGER);
    """)
    cur.executemany("INSERT INTO navaids VALUES (?,?,?,?,?,?,?,?,?)", navaids)
    cur.executemany("INSERT INTO fixes VALUES (?,?,?,?,?,?,?)", fixes)
    cur.executemany("INSERT INTO awy_segments VALUES (?,?,?,?,?,?,?,?)",
                    segs)
    cur.executemany("INSERT INTO holds VALUES "
                    "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", holds)
    cur.executemany("INSERT INTO hold_limits VALUES (?,?,?,?,?,?)", limits)
    cur.executescript("""
        CREATE INDEX idx_nav_ll ON navaids(lat, lon);
        CREATE INDEX idx_fix_ll ON fixes(lat, lon);
        CREATE INDEX idx_seg_ll ON awy_segments(lat1, lon1);
        CREATE INDEX idx_hold_pt ON holds(point_id);
        CREATE INDEX idx_hold_limits ON hold_limits(hp_name, hp_no);
    """)
    con.commit()
    con.close()
    # The "skipped N special routes" count always prints (even at 0) so a CI log
    # reader can see the SP filter ran, per docs/nasr_2601_dpn_prep.md section 4.
    print("wrote %s: %d navaids, %d fixes, %d airway segments "
          "(skipped %d special routes)"
          % (args.output, len(navaids), len(fixes), len(segs), skipped_awy))
    # The dropped-hold and unparsed-altitude counts always print too: about 138
    # holds (ILS locators not in NAV_BASE) and 343 altitudes in 2611.
    print("holds: %d holds, %d speed/altitude rows "
          "(dropped %d holds at unresolved points, "
          "%d altitudes not MIN/MAX)"
          % (len(holds), len(limits), dropped_holds, unparsed_alt))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
