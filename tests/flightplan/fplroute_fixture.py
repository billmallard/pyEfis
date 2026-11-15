#  SPDX-License-Identifier: GPL-2.0-or-later
"""Regenerates ``fixtures/fplroute_blocks.json``: the route block
fix-gateway's synthetic tier loads for each committed sim profile
(``fixgw/sim/fplroute.py``, SYN1), as the ordered ``(key, value)`` writes,
and for a profile that flies a procedure, that procedure's rows in a
``procedures`` pack.

``test_fplroute_conformance.py`` assembles each procedure from those rows
with ``proc_load`` and diffs pyEfis's publisher against the writes. The pack
rows are makerplane-data's decoder (``packtools.build.procedures``) run over
the same CIFP file the profile pins, so both sides start from one record
set. fix-gateway and makerplane-data are separate repos, so the output is
committed here rather than imported; rerun this after ``fplroute.py``, a
profile or the decoder changes::

    python tests/flightplan/fplroute_fixture.py /path/to/fix-gateway /path/to/makerplane-data

The test also reruns it itself, and fails on a stale fixture, when
``FIX_GATEWAY_SRC`` and ``MAKERPLANE_DATA_SRC`` name the two checkouts.
"""

import glob
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tests.flightplan import ksba_procedures  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "fplroute_blocks.json"


def _columns(table: str) -> list[str]:
    """*table*'s columns, in the order ``ksba_procedures.SCHEMA`` (makerplane-data's
    schema) declares them -- the order the fixture's rows are in."""
    con = sqlite3.connect(":memory:")
    con.executescript(ksba_procedures.SCHEMA)
    return [row[1] for row in con.execute(f"PRAGMA table_info({table})")]


def pack_rows(makerplane_data: str, cifp_file: str, cycle: str, airport: str, ident: str) -> dict:
    """The ``procedures`` / ``transitions`` / ``legs`` rows makerplane-data's
    decoder writes for one approach in *cifp_file*. A profile's file is a
    subset with no ``VOLUME`` header, so *cycle* is the profile's pinned one."""
    sys.path.insert(0, makerplane_data)
    from packtools import arinc424
    from packtools.build import procedures as build

    with tempfile.TemporaryDirectory() as tmp:
        con = sqlite3.connect(os.path.join(tmp, "procedures.db"))
        con.executescript(build._SCHEMA)
        build._build_procedures(con, Path(cifp_file), arinc424.build_fix_index(Path(cifp_file)), cycle)
        con.commit()
        procs = con.execute(f"SELECT {', '.join(_columns('procedures'))} FROM procedures "
                            "WHERE airport = ? AND kind = 'approach' AND ident = ?",
                            (airport, ident)).fetchall()
        if len(procs) != 1:
            raise SystemExit(f"{cifp_file}: {len(procs)} approaches {airport} {ident}")
        trans = con.execute(f"SELECT {', '.join(_columns('transitions'))} FROM transitions "
                            "WHERE proc_id = ? ORDER BY id", (procs[0][0],)).fetchall()
        legs = con.execute(f"SELECT {', '.join(_columns('legs'))} FROM legs WHERE transition_id IN "
                           f"({', '.join('?' * len(trans))}) ORDER BY transition_id, seq",
                           [t[0] for t in trans]).fetchall()
        con.close()
    return {"procedures": [list(r) for r in procs], "transitions": [list(r) for r in trans],
            "legs": [list(r) for r in legs]}


def generate(fix_gateway: str, makerplane_data: str) -> dict:
    """``{profile name: {procedure, magvar_deg, writes, pack}}`` for every
    profile under ``src/fixgw/sim/profiles``, built the way
    ``fixgw.sim.generator`` builds the block it loads. ``procedure`` and
    ``pack`` are None for a route that flies none."""
    sys.path.insert(0, os.path.join(fix_gateway, "src"))
    from fixgw.sim import fplroute
    from fixgw.sim.cifp import Cifp
    from fixgw.sim.profile import load_profile

    blocks = {}
    for path in sorted(glob.glob(os.path.join(fix_gateway, "src/fixgw/sim/profiles/*.yaml"))):
        prof = load_profile(path)
        cifp = Cifp(prof.cifp_file)
        slots, segments, name, aprtype = fplroute.route_slots(cifp, prof)
        writes = fplroute.route_block_writes(slots, segments, name, aprtype, cifp.cycle, 1)
        proc = prof.procedure
        blocks[prof.name] = {
            "procedure": proc and {k: proc[k] for k in ("airport", "approach", "transition")},
            "magvar_deg": prof.magvar_deg,
            "writes": [[k, v] for k, v in writes],
            "pack": proc and pack_rows(makerplane_data, prof.cifp_file, cifp.cycle,
                                       proc["airport"], proc["approach"]),
        }
    return blocks


def dumps(doc: dict) -> str:
    """JSON with one write per line, so a regenerated fixture diffs by key."""
    lines = ["{", f' "fix_gateway_sha": {json.dumps(doc["fix_gateway_sha"])},',
             f' "makerplane_data_sha": {json.dumps(doc["makerplane_data_sha"])},', ' "profiles": {']
    names = list(doc["profiles"])
    for n, name in enumerate(names):
        p = doc["profiles"][name]
        lines += [f"  {json.dumps(name)}: {{",
                  f'   "procedure": {json.dumps(p["procedure"])},',
                  f'   "magvar_deg": {json.dumps(p["magvar_deg"])},',
                  '   "writes": [']
        lines += [f"    {json.dumps(w)}" + ("," if i < len(p["writes"]) - 1 else "")
                  for i, w in enumerate(p["writes"])]
        lines += ["   ],"]
        pack = p["pack"]
        if pack is None:
            lines += ['   "pack": null']
        else:
            lines += ['   "pack": {']
            for t, table in enumerate(("procedures", "transitions", "legs")):
                rows = pack[table]
                lines += [f'    "{table}": [']
                lines += [f"     {json.dumps(r)}" + ("," if i < len(rows) - 1 else "")
                          for i, r in enumerate(rows)]
                lines += ["    ]" + ("," if t < 2 else "")]
            lines += ["   }"]
        lines += ["  }" + ("," if n < len(names) - 1 else "")]
    lines += [" }", "}"]
    return "\n".join(lines) + "\n"


def source_sha(checkout: str) -> str:
    return subprocess.run(["git", "-C", checkout, "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()


def main(argv):
    if len(argv) != 3:
        sys.exit(f"usage: {argv[0]} /path/to/fix-gateway /path/to/makerplane-data")
    doc = {"fix_gateway_sha": source_sha(argv[1]), "makerplane_data_sha": source_sha(argv[2]),
           "profiles": generate(argv[1], argv[2])}
    FIXTURE.parent.mkdir(exist_ok=True)
    FIXTURE.write_text(dumps(doc))
    print(f"wrote {len(doc['profiles'])} profiles to {FIXTURE}")


if __name__ == "__main__":
    main(sys.argv)
