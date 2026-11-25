#  SPDX-License-Identifier: GPL-2.0-or-later
"""Regenerate ``route_string_packs.json`` from real packs (RTE1, AER-6454).

    python3 tests/flightplan/fixtures/make_route_string_packs.py \\
        <airports.sqlite> <navaids.sqlite> <procedures.sqlite>

The committed file was made from the Beelink bench's packs, cycle 2611
(``/data/makerplane-data/{navdata,navaids,procedures}/current``). It keeps
the rows the route-string tests name, unedited: whole tables are not
copied, but every row of a kept airport, navaid, fix, airway or procedure
is. The tables keep the pack's own schema.
"""

import json
import sqlite3
import sys
from pathlib import Path

# The airports pack stores NASR ARPT_ID, so KSBA is "SBA" there.
AIRPORTS = ("SBA", "PMD", "PHX", "SMX", "LAX", "ABQ", "SAF")
NAVAIDS = ("VTU", "TTE", "LHS", "GVO", "HEC", "RZS", "ABQ", "AA", "MAZ", "PHX", "PMD")
FIXES = ("FLOUT", "HENER", "OHIGH", "WRING", "AMONT", "LOPES", "PAIDD", "JEFFY",
         "WAYVE", "DARTS", "MOVVE", "MIPTE", "DEANO", "KWANG", "GOLET")
AIRWAYS = ("V27", "V485", "V459")
PROCEDURES = (("KSBA", "sid", "FLOUT5"), ("KSBA", "star", "PITBL2"))


def _schema(con, tables):
    rows = con.execute("SELECT type, name, tbl_name, sql FROM sqlite_master "
                       "WHERE sql IS NOT NULL").fetchall()
    return [sql for _t, _n, tbl, sql in rows if tbl in tables]


def _rows(con, sql, args=()):
    cur = con.execute(sql, args)
    return [list(r) for r in cur.fetchall()]


def _marks(seq):
    return ",".join("?" * len(seq))


def main(airports, navaids, procedures):
    out = {}
    con = sqlite3.connect(airports)
    out["airports"] = {
        "schema": _schema(con, ("airports", "runways", "pack_meta")),
        "airports": _rows(con, f"SELECT * FROM airports WHERE icao IN ({_marks(AIRPORTS)})",
                          AIRPORTS),
        "runways": _rows(con, "SELECT r.* FROM runways r JOIN airports a USING (site_no) "
                              f"WHERE a.icao IN ({_marks(AIRPORTS)})", AIRPORTS),
        "pack_meta": _rows(con, "SELECT * FROM pack_meta"),
    }
    con = sqlite3.connect(navaids)
    out["navaids"] = {
        "schema": _schema(con, ("navaids", "fixes", "pack_meta")),
        "navaids": _rows(con, f"SELECT * FROM navaids WHERE id IN ({_marks(NAVAIDS)})", NAVAIDS),
        "fixes": _rows(con, f"SELECT * FROM fixes WHERE id IN ({_marks(FIXES)})", FIXES),
        "pack_meta": _rows(con, "SELECT * FROM pack_meta"),
    }
    con = sqlite3.connect(procedures)
    awy = [r[0] for r in con.execute(
        f"SELECT id FROM airways WHERE ident IN ({_marks(AIRWAYS)})", AIRWAYS)]
    proc = [con.execute("SELECT id FROM procedures WHERE airport=? AND kind=? AND ident=?",
                        p).fetchone()[0] for p in PROCEDURES]
    trans = [r[0] for r in con.execute(
        f"SELECT id FROM transitions WHERE proc_id IN ({_marks(proc)})", proc)]
    out["procedures"] = {
        "schema": _schema(con, ("airways", "airway_legs", "procedures", "transitions", "legs",
                                "pack_meta")),
        "airways": _rows(con, f"SELECT * FROM airways WHERE id IN ({_marks(awy)})", awy),
        "airway_legs": _rows(con, f"SELECT * FROM airway_legs WHERE airway_id IN "
                                  f"({_marks(awy)})", awy),
        "procedures": _rows(con, f"SELECT * FROM procedures WHERE id IN ({_marks(proc)})", proc),
        "transitions": _rows(con, f"SELECT * FROM transitions WHERE id IN ({_marks(trans)})",
                             trans),
        "legs": _rows(con, f"SELECT * FROM legs WHERE transition_id IN ({_marks(trans)})", trans),
        "pack_meta": _rows(con, "SELECT * FROM pack_meta"),
    }
    path = Path(__file__).with_name("route_string_packs.json")
    path.write_text(json.dumps(out, indent=0) + "\n", encoding="utf-8")
    print(path, path.stat().st_size, "bytes")


if __name__ == "__main__":
    main(*sys.argv[1:4])
