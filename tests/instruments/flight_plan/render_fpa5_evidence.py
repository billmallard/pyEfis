#  SPDX-License-Identifier: GPL-2.0-or-later
"""Renders docs/images/fpa5/*.png (FPA5, AER-6544): ``flightplan direct to
BR`` on a navaids pack holding the three real cycle-2611 ``BR`` NDBs, once
from a pack built before FPA5 (no region columns) and once from one built
with them, at the Beelink's Flight Plan pane size, 649 x 993. Not collected
by pytest (no test_ prefix); run it explicitly:

    QT_QPA_PLATFORM=offscreen PYTHONPATH=src python -m pytest \\
        tests/instruments/flight_plan/render_fpa5_evidence.py --no-cov -q
"""

import os
import sqlite3

from pyefis.flightplan import waypoints as fp_waypoints
from pyefis.instruments import flight_plan
from tests.instruments.flight_plan.test_region_duplicates import _define_all_fp1_keys

OUT = os.path.join(os.path.dirname(__file__), "..", "..", "..", "docs", "images", "fpa5")

# Real cycle-2611 NAV_BASE rows (NASR 2026-10-29).
BR = [
    ("BR", "NDB", "Larew", "251", 1260, 46.4566203, -94.02243002, "MN", "US"),
    ("BR", "NDB", "Depoo", "393", 28.5, 25.98366283, -97.50909794, "TX", "US"),
    ("BR", "NDB", "Burns", "390", 574.1, 40.65435738, -91.12322608, "IA", "US"),
]


def _pack(path, with_region):
    con = sqlite3.connect(str(path))
    cols = ", state TEXT, country TEXT" if with_region else ""
    con.executescript(
        "CREATE TABLE navaids (id TEXT, type TEXT, name TEXT, freq TEXT, "
        f"  elev_ft REAL, lat REAL, lon REAL{cols});"
        "CREATE TABLE fixes (id TEXT, use_code TEXT, lat REAL, lon REAL);")
    rows = BR if with_region else [r[:7] for r in BR]
    con.executemany(f"INSERT INTO navaids VALUES ({','.join('?' * len(rows[0]))})", rows)
    con.commit()
    con.close()


def test_render(fix, qtbot, tmp_path):
    os.makedirs(OUT, exist_ok=True)
    _define_all_fp1_keys(fix)
    for name, with_region in (("1_chooser_pack_before_fpa5.png", False),
                              ("2_chooser_pack_with_region.png", True)):
        pack = tmp_path / f"{with_region}.sqlite"
        _pack(pack, with_region)
        w = flight_plan.FlightPlan(None)
        qtbot.addWidget(w)
        w.resize(649, 993)
        idx = fp_waypoints.WaypointIndex(None, str(pack), recent_file=str(tmp_path / "r.json"))
        assert idx.wait_ready(5.0)
        w._waypoint_index = idx
        w._waypoint_index_key = (w.nasr_db_path, w.navaid_db_path, w.flightplan_dir)
        w._act_direct_to("BR")
        assert w._page == "dto" and len(w._entry_dupe_choices) == 3
        w.grab().save(os.path.join(OUT, name))
