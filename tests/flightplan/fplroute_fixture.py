#  SPDX-License-Identifier: GPL-2.0-or-later
"""Regenerates ``fixtures/fplroute_blocks.json``: the route block
fix-gateway's synthetic tier loads for each committed sim profile
(``fixgw/sim/fplroute.py``, SYN1), as the ordered ``(key, value)`` writes.

``test_fplroute_conformance.py`` diffs pyEfis's publisher against these.
fix-gateway is a separate repo, so the blocks are committed here rather
than imported; rerun this after ``fplroute.py`` or a profile changes::

    python tests/flightplan/fplroute_fixture.py /path/to/fix-gateway

The test also reruns it itself, and fails on a stale fixture, when
``FIX_GATEWAY_SRC`` names a fix-gateway checkout.
"""

import glob
import json
import os
import subprocess
import sys
from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures" / "fplroute_blocks.json"


def generate(fix_gateway: str) -> dict:
    """``{profile name: {procedure, magvar_deg, writes}}`` for every profile
    under ``src/fixgw/sim/profiles``, built the way ``fixgw.sim.generator``
    builds the block it loads."""
    sys.path.insert(0, os.path.join(fix_gateway, "src"))
    from fixgw.sim import fplroute
    from fixgw.sim.cifp import Cifp
    from fixgw.sim.profile import load_profile

    blocks = {}
    for path in sorted(glob.glob(os.path.join(fix_gateway, "src/fixgw/sim/profiles/*.yaml"))):
        prof = load_profile(path)
        cifp = Cifp(prof.cifp_file)
        proc = prof.procedure
        slots, segments = fplroute.procedure_slots(
            cifp, proc["airport"], proc["approach"], proc["transition"], prof.magvar_deg)
        name = f"{proc['airport']} {proc['approach']} {proc['transition']}"[:32]
        writes = fplroute.route_block_writes(slots, segments, name, "RNAV", cifp.cycle, 1)
        blocks[prof.name] = {
            "procedure": {k: proc[k] for k in ("airport", "approach", "transition")},
            "magvar_deg": prof.magvar_deg,
            "writes": [[k, v] for k, v in writes],
        }
    return blocks


def dumps(doc: dict) -> str:
    """JSON with one write per line, so a regenerated fixture diffs by key."""
    lines = ["{", f' "fix_gateway_sha": {json.dumps(doc["fix_gateway_sha"])},', ' "profiles": {']
    names = list(doc["profiles"])
    for n, name in enumerate(names):
        p = doc["profiles"][name]
        lines += [f"  {json.dumps(name)}: {{",
                  f'   "procedure": {json.dumps(p["procedure"])},',
                  f'   "magvar_deg": {json.dumps(p["magvar_deg"])},',
                  '   "writes": [']
        lines += [f"    {json.dumps(w)}" + ("," if i < len(p["writes"]) - 1 else "")
                  for i, w in enumerate(p["writes"])]
        lines += ["   ]", "  }" + ("," if n < len(names) - 1 else "")]
    lines += [" }", "}"]
    return "\n".join(lines) + "\n"


def source_sha(fix_gateway: str) -> str:
    return subprocess.run(["git", "-C", fix_gateway, "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()


def main(argv):
    if len(argv) != 2:
        sys.exit(f"usage: {argv[0]} /path/to/fix-gateway")
    doc = {"fix_gateway_sha": source_sha(argv[1]), "profiles": generate(argv[1])}
    FIXTURE.parent.mkdir(exist_ok=True)
    FIXTURE.write_text(dumps(doc))
    print(f"wrote {len(doc['profiles'])} profiles to {FIXTURE}")


if __name__ == "__main__":
    main(sys.argv)
