#  SPDX-License-Identifier: GPL-2.0-or-later
"""Airport idents from NASR ``ICAO_ID`` (FPA4, AER-6543).

NASR's ``ARPT_ID`` is the FAA ident (SBA, ANC). The readers used to make any
three-letter ident K plus the ident, which is right in the contiguous US and
wrong in Alaska and Hawaii: Anchorage read as KANC, so ``PANC`` from a route
string, a ``.fpl`` or the procedures pack found no airport. The pack now
carries ``icao_id``; packs built before it keep the K rule.

The end-to-end tests run the real builder (``tools/build_airport_db.py``) on
NASR-shaped CSVs, then read the pack through both readers: ``WaypointIndex``
and the SVS ``NASRAirportDB``. The rows are real cycle 2026-10-29 NASR values.
"""

import csv
import importlib.util
import sqlite3
from pathlib import Path

import pytest

from pyefis.flightplan.waypoints import WaypointIndex, airport_idents
from pyefis.instruments.ai.airport_db import NASRAirportDB

_ROOT = Path(__file__).resolve().parents[2]


def _load_builder():
    spec = importlib.util.spec_from_file_location(
        "build_airport_db", _ROOT / "tools" / "build_airport_db.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ba = _load_builder()

BASE_HEADER = ["SITE_NO", "ARPT_ID", "ARPT_NAME", "LAT_DECIMAL", "LONG_DECIMAL",
               "ELEV", "MAG_VARN", "MAG_HEMIS", "STATE_CODE", "CITY", "ICAO_ID"]
# (site_no, ARPT_ID, name, lat, lon, elev, state, ICAO_ID)
BASE_ROWS = [
    ("50017.*A", "ANC", "TED STEVENS ANCHORAGE INTL", "61.17432", "-149.99814", "151.5", "AK", "PANC"),
    ("50061.*A", "MRI", "MERRILL FLD", "61.21354", "-149.84439", "137.4", "AK", "PAMR"),
    # An Alaska strip with no ICAO ident: it must not become K + ident.
    ("50015.*A", "AKK", "AKHIOK", "56.93868", "-154.18257", "44", "AK", ""),
    ("02220.*A", "SBA", "SANTA BARBARA MUNI", "34.42621", "-119.84037", "13.4", "CA", "KSBA"),
    ("01818.*A", "HNL", "DANIEL K INOUYE INTL", "21.31787", "-157.92023", "13", "HI", "PHNL"),
]
RWY_HEADER = ["SITE_NO", "RWY_ID", "RWY_LEN", "RWY_WIDTH",
              "SURFACE_TYPE_CODE", "RWY_LGT_CODE"]
END_HEADER = ["SITE_NO", "RWY_ID", "RWY_END_ID", "TRUE_ALIGNMENT",
              "LAT_DECIMAL", "LONG_DECIMAL", "RWY_END_ELEV",
              "LAT_DISPLACED_THR_DECIMAL", "LONG_DISPLACED_THR_DECIMAL",
              "DISPLACED_THR_LEN", "TDZ_ELEV", "RWY_MARKING_TYPE_CODE",
              "APCH_LGT_SYSTEM_CODE", "RWY_END_LGTS_FLAG",
              "CNTRLN_LGTS_AVBL_FLAG", "TDZ_LGT_AVBL_FLAG",
              "VGSI_CODE", "VISUAL_GLIDE_PATH_ANGLE"]


def _write(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


def _build_pack(dir_, *, with_icao_column=True):
    """Run the real builder. Every airport gets one paved runway with two
    ends, so the SVS reader (which skips runway-less airports) yields it."""
    dir_.mkdir(parents=True)
    header = BASE_HEADER if with_icao_column else BASE_HEADER[:-1]
    base, rwys, ends = [], [], []
    for site, arpt, name, lat, lon, elev, state, icao in BASE_ROWS:
        row = [site, arpt, name, lat, lon, elev, "15", "E", state, name]
        base.append(row + [icao] if with_icao_column else row)
        rwys.append((site, "09/27", "5000", "100", "ASPH", "HIGH"))
        for end, dlon in (("09", -0.005), ("27", 0.005)):
            ends.append((site, "09/27", end, "90", lat, str(float(lon) + dlon),
                         elev, "", "", "", "", "PIR", "", "Y", "N", "N", "", ""))
    _write(dir_ / "APT_BASE.csv", header, base)
    _write(dir_ / "APT_RWY.csv", RWY_HEADER, rwys)
    _write(dir_ / "APT_RWY_END.csv", END_HEADER, ends)
    out = dir_ / "airports.sqlite"
    ba.build(dir_, out)
    return out


def _navaids(tmp_path):
    p = tmp_path / "navaids.sqlite"
    con = sqlite3.connect(str(p))
    con.executescript(
        "CREATE TABLE navaids (id TEXT, type TEXT, name TEXT, freq TEXT, "
        "  elev_ft REAL, lat REAL, lon REAL);"
        "CREATE TABLE fixes (id TEXT, use_code TEXT, lat REAL, lon REAL);")
    con.close()
    return p


def _index(tmp_path, pack):
    idx = WaypointIndex(str(pack), str(_navaids(tmp_path)),
                        user_file=str(tmp_path / "user_waypoints.json"),
                        recent_file=str(tmp_path / "recent.json"))
    assert idx.wait_ready(timeout=5) is True
    return idx


def _svs_idents(pack):
    db = NASRAirportDB(pack)
    found = {}
    for lat, lon in ((61.19, -149.9), (56.94, -154.18), (34.43, -119.84),
                     (21.32, -157.92)):
        for ap in db.airports_in_range(lat, lon, 20):
            found[ap.name] = ap.icao
    db._con.close()
    return found


# ---------------------------------------------------------------------------
# The rebuilt pack
# ---------------------------------------------------------------------------
def test_builder_stores_the_icao_ident_beside_the_faa_ident(tmp_path):
    pack = _build_pack(tmp_path / "pack")
    con = sqlite3.connect(str(pack))
    rows = dict(((icao, icao_id) for icao, icao_id in con.execute(
        "SELECT icao, icao_id FROM airports")))
    con.close()
    assert rows == {"ANC": "PANC", "MRI": "PAMR", "AKK": None,
                    "SBA": "KSBA", "HNL": "PHNL"}


def test_nasr_file_without_icao_id_falls_back_to_the_k_rule(tmp_path):
    """A NASR cycle without ICAO_ID still builds, and the empty column reads
    as an old pack: KSBA stays KSBA, it does not become plain SBA."""
    pack = _build_pack(tmp_path / "pack", with_icao_column=False)
    con = sqlite3.connect(str(pack))
    assert {r[0] for r in con.execute("SELECT icao_id FROM airports")} == {None}
    con.close()
    idx = _index(tmp_path, pack)
    assert [w.id for w in idx.lookup("SBA")] == ["KSBA"]
    assert [w.id for w in idx.lookup("KSBA")] == ["KSBA"]
    assert _svs_idents(pack)["Santa Barbara Muni"] == "KSBA"


def test_rebuilt_pack_resolves_alaska_by_icao_and_faa_ident(tmp_path):
    """The definition of done: PANC and ANC both find Anchorage, and KSBA and
    SBA still find Santa Barbara. On a pack without the column this failed:
    PANC found nothing and Anchorage was KANC."""
    idx = _index(tmp_path, _build_pack(tmp_path / "pack"))
    for ident, want in (("PANC", "PANC"), ("ANC", "PANC"),
                        ("PAMR", "PAMR"), ("MRI", "PAMR"),
                        ("PHNL", "PHNL"), ("HNL", "PHNL"),
                        ("KSBA", "KSBA"), ("SBA", "KSBA")):
        assert [w.id for w in idx.lookup(ident)] == [want], ident
    assert idx.lookup("KANC") == []
    assert idx.lookup("KHNL") == []


def test_airport_without_an_icao_ident_keeps_its_faa_ident(tmp_path):
    idx = _index(tmp_path, _build_pack(tmp_path / "pack"))
    assert [w.id for w in idx.lookup("AKK")] == ["AKK"]
    assert idx.lookup("KAKK") == []


def test_svs_labels_use_the_icao_ident(tmp_path):
    found = _svs_idents(_build_pack(tmp_path / "pack"))
    assert found == {"Ted Stevens Anchorage Intl": "PANC",
                     "Merrill Fld": "PAMR", "Akhiok": "AKK",
                     "Santa Barbara Muni": "KSBA",
                     "Daniel K Inouye Intl": "PHNL"}


# ---------------------------------------------------------------------------
# Packs built before the column keep working, with the old K rule
# ---------------------------------------------------------------------------
def _strip_icao_id_column(pack):
    """The pack exactly as the builder wrote it before FPA4."""
    con = sqlite3.connect(str(pack))
    con.execute("ALTER TABLE airports DROP COLUMN icao_id")
    con.commit()
    con.close()
    return pack


def test_old_pack_still_resolves_with_the_k_rule(tmp_path):
    pack = _strip_icao_id_column(_build_pack(tmp_path / "pack"))
    idx = _index(tmp_path, pack)
    assert [w.id for w in idx.lookup("SBA")] == ["KSBA"]
    assert [w.id for w in idx.lookup("KSBA")] == ["KSBA"]
    # The known wrong case of the fallback, which a rebuilt pack fixes.
    assert [w.id for w in idx.lookup("ANC")] == ["KANC"]
    assert idx.lookup("PANC") == []


def test_old_pack_still_loads_in_the_svs(tmp_path):
    found = _svs_idents(_strip_icao_id_column(_build_pack(tmp_path / "pack")))
    assert found["Santa Barbara Muni"] == "KSBA"
    assert found["Ted Stevens Anchorage Intl"] == "KANC"


# ---------------------------------------------------------------------------
# The shared rule
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("raw, icao_id, legacy, want", [
    ("ANC", "PANC", False, ("PANC", ["ANC"])),
    ("SBA", "KSBA", False, ("KSBA", ["SBA"])),
    ("Z13", "PFZK", False, ("PFZK", ["Z13"])),    # digit FAA ident
    ("AKK", None, False, ("AKK", [])),
    ("KDEN", "KDEN", False, ("KDEN", [])),        # FAA ident already ICAO
    (" anc ", " panc ", False, ("PANC", ["ANC"])),
    ("ANC", None, True, ("KANC", ["ANC"])),
    ("KSBA", None, True, ("KSBA", ["SBA"])),
    ("CYQG", None, True, ("CYQG", [])),
])
def test_airport_idents(raw, icao_id, legacy, want):
    assert airport_idents(raw, icao_id, legacy=legacy) == want
