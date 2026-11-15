"""
Airport / runway database for the SVS renderer.

One backend, merged across provider packs, exposing a range-based query API:

    db = make_airport_db(svs_config)
    for ap in db.airports_in_range(ac_lat, ac_lon, range_nm):
        ap.icao, ap.name, ap.ref_lat, ap.ref_lon, ap.elev_ft
        for rwy in ap.runways:
            rwy.thr1_lat, rwy.thr1_lon, rwy.thr1_elev_ft, ...

* ``NASRAirportDB`` — reads ``airports.sqlite`` built from FAA NASR CSVs
  (see ``tools/build_airport_db.py``). Carries real runway widths,
  displaced-threshold offsets, marking type, TDZ elevation, approach
  lighting — everything needed to render Tier C surface markings.

The ``CIFPAirportDB`` backend (``pyavtools.CIFPObjects``, the data path of
the legacy Virtual VFR overlay) was retired with that overlay (VVFR1,
AER-5417): the NASR pack is the only airport source. A config that still sets
``cifp_path`` gets a warning naming ``nasr_db_path`` and no airports.

``make_airport_db(svs_config)`` merges whatever NASR-format packs resolve.
"""

from __future__ import annotations

import logging
import math
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

NM_PER_DEG_LAT = 60.0           # 1° of latitude ≈ 60 NM
DEFAULT_RWY_WIDTH_FT = 100.0    # used when source data lacks width

# RWY_MARKING_TYPE_CODE values from FAA NASR (APT_RWY_END):
#   "PIR" — precision instrument runway (full TDZ, side stripes, aim point)
#   "NPI" — non-precision instrument (threshold bars, aim point, no TDZ)
#   "BSC" — basic / visual (designator, centerline only)
#   "NSTD", "" — non-standard or unknown
MARKING_PRECISION = "PIR"
MARKING_NONPRECISION = "NPI"
MARKING_BASIC = "BSC"


def _row_get(row, key, default=None):
    """Read an optional sqlite column, tolerating older airport packs built
    before the column existed. ``sqlite3.Row`` raises IndexError for an unknown
    key; construct-never-raises means a pre-VG1 pack must still read cleanly."""
    try:
        return row[key]
    except (IndexError, KeyError):
        return default


@dataclass
class RunwayRecord:
    airport_id : str
    name       : str             # e.g. "07" or "25L"
    thr1_lat   : float
    thr1_lon   : float
    thr1_elev_ft : float
    thr2_lat   : float
    thr2_lon   : float
    thr2_elev_ft : float
    length_ft  : float
    bearing_deg: float           # true bearing thr1 → thr2
    width_ft   : float = DEFAULT_RWY_WIDTH_FT
    surface    : str = ""        # NASR surface code ("ASPH", "TURF-GRVL", ...)
    # Optional Tier C fields — populated by the NASR backend; empty/zero when the pack lacks them.
    thr1_designator : str = ""   # e.g. "07" or "25L"
    thr2_designator : str = ""
    thr1_marking    : str = ""   # PIR / NPI / BSC / ""
    thr2_marking    : str = ""
    thr1_displaced_ft : float = 0.0
    thr2_displaced_ft : float = 0.0
    thr1_tdz_elev_ft  : float = 0.0
    thr2_tdz_elev_ft  : float = 0.0
    thr1_apch_lgt   : str = ""   # "MALSR", "ALSF1", "P2L", ...
    thr2_apch_lgt   : str = ""
    # VGSI (visual glidepath) — NASR-only, NULL where none is installed/published.
    # None (not 0.0/"") distinguishes "no VGSI here" from a real value; no
    # consumer reads these yet (VG1 tier 1 lands the data only).
    thr1_vgsi_type  : str | None = None    # "P4L", "V2R", ... (type + boxes + side)
    thr2_vgsi_type  : str | None = None
    thr1_visual_gpa : float | None = None  # published visual glide path angle (deg)
    thr2_visual_gpa : float | None = None


@dataclass
class AirportRecord:
    icao    : str
    name    : str
    ref_lat : float
    ref_lon : float
    elev_ft : float
    runways : list[RunwayRecord] = field(default_factory=list)


# ---------------------------------------------------------------------------
# NASR sqlite backend
# ---------------------------------------------------------------------------
class NASRAirportDB:
    """SVS airport/runway data source backed by ``airports.sqlite`` —
    built once by ``tools/build_airport_db.py`` from the FAA NASR CSVs."""

    def __init__(self, sqlite_path: str | Path | None, paved_only=True):
        # Filter to paved runways (ASPH/CONC/PEM
        # substrings); airports left with no
        # runways drop entirely — flight-tested
        # declutter (DFW turf strips).
        self._paved_only = bool(paved_only)
        self._path = Path(sqlite_path) if sqlite_path else None
        self._con: sqlite3.Connection | None = None
        if self._path is None or not self._path.is_file():
            log.info("NASRAirportDB: %s not found — falling back", self._path)
            return
        try:
            self._con = sqlite3.connect(str(self._path),
                                        check_same_thread=False)
            self._con.row_factory = sqlite3.Row
        except Exception as e:
            log.warning("NASRAirportDB: cannot open %s: %s", self._path, e)
            self._con = None

    @property
    def ready(self) -> bool:
        return self._con is not None

    def airports_in_range(self, ac_lat: float, ac_lon: float,
                          range_nm: float):
        if not self.ready:
            return
        lat_cos = math.cos(math.radians(ac_lat))
        range_deg_lat = range_nm / NM_PER_DEG_LAT
        range_deg_lon = range_deg_lat / max(lat_cos, 1e-6)
        lat_lo = ac_lat - range_deg_lat
        lat_hi = ac_lat + range_deg_lat
        lon_lo = ac_lon - range_deg_lon
        lon_hi = ac_lon + range_deg_lon

        # First pass: airports within the bounding box.
        cur = self._con.execute(
            "SELECT site_no, icao, name, lat, lon, elev_ft "
            "FROM airports "
            "WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?",
            (lat_lo, lat_hi, lon_lo, lon_hi))
        airport_rows = cur.fetchall()
        if not airport_rows:
            return

        range_nm_sq = range_nm * range_nm
        for ar in airport_rows:
            d_lat = (ar["lat"] - ac_lat) * NM_PER_DEG_LAT
            d_lon = (ar["lon"] - ac_lon) * NM_PER_DEG_LAT * lat_cos
            if d_lat * d_lat + d_lon * d_lon > range_nm_sq:
                continue
            runways = list(self._runways_for(ar["site_no"]))
            if not runways:
                continue
            icao = ar["icao"]
            # NASR's ARPT_ID is FAA-style (no leading K for CONUS); add it
            # so labels and lookup keys match how pilots refer to airports.
            if icao and len(icao) == 3 and icao.isalpha():
                icao = "K" + icao
            yield AirportRecord(
                icao=icao,
                name=(ar["name"] or "").title(),
                ref_lat=ar["lat"], ref_lon=ar["lon"],
                elev_ft=ar["elev_ft"] or 0.0,
                runways=runways)

    def _runways_for(self, site_no: str):
        # Fetch all runways and ends for this site, then pair each end pair
        # into a single RunwayRecord.
        rwys = self._con.execute(
            "SELECT rwy_id, length_ft, width_ft, surface FROM runways "
            "WHERE site_no = ?", (site_no,)).fetchall()
        if self._paved_only:
            rwys = [r for r in rwys
                    if any(t in (r["surface"] or "").upper()
                           for t in ("ASPH", "CONC", "PEM"))]
        ends_by_rwy: dict[str, list] = {}
        for e in self._con.execute(
            "SELECT * FROM runway_ends WHERE site_no = ?", (site_no,)):
            ends_by_rwy.setdefault(e["rwy_id"], []).append(e)

        for r in rwys:
            ends = ends_by_rwy.get(r["rwy_id"], [])
            if len(ends) < 2:
                continue   # need both ends to draw a quad
            # Sort by numeric designator so "07/25" yields end "07" first.
            ends.sort(key=lambda x: _designator_sort_key(x["end_id"]))
            a, b = ends[0], ends[1]
            if a["lat"] is None or b["lat"] is None:
                continue
            yield RunwayRecord(
                airport_id=site_no, name=r["rwy_id"],
                thr1_lat=a["lat"], thr1_lon=a["lon"],
                thr1_elev_ft=a["elev_ft"] or 0.0,
                thr2_lat=b["lat"], thr2_lon=b["lon"],
                thr2_elev_ft=b["elev_ft"] or 0.0,
                length_ft=r["length_ft"] or 0.0,
                bearing_deg=a["true_alignment_deg"] or 0.0,
                width_ft=r["width_ft"] or DEFAULT_RWY_WIDTH_FT,
                surface=(r["surface"] or "").strip(),
                thr1_designator=a["end_id"] or "",
                thr2_designator=b["end_id"] or "",
                thr1_marking=(a["marking_type"] or "").strip(),
                thr2_marking=(b["marking_type"] or "").strip(),
                thr1_displaced_ft=a["displaced_thr_len_ft"] or 0.0,
                thr2_displaced_ft=b["displaced_thr_len_ft"] or 0.0,
                thr1_tdz_elev_ft=a["tdz_elev_ft"] or 0.0,
                thr2_tdz_elev_ft=b["tdz_elev_ft"] or 0.0,
                thr1_apch_lgt=(a["apch_lgt_code"] or "").strip(),
                thr2_apch_lgt=(b["apch_lgt_code"] or "").strip(),
                thr1_vgsi_type=_row_get(a, "vgsi_code"),
                thr2_vgsi_type=_row_get(b, "vgsi_code"),
                thr1_visual_gpa=_row_get(a, "visual_gpa"),
                thr2_visual_gpa=_row_get(b, "visual_gpa"),
            )


def _designator_sort_key(end_id: str):
    """Sort key so '07' < '25' and 'L'/'C'/'R' suffixes stay grouped."""
    s = (end_id or "").strip()
    digits = "".join(c for c in s if c.isdigit())
    suffix = "".join(c for c in s if not c.isdigit())
    try:
        n = int(digits) if digits else 99
    except ValueError:
        n = 99
    return (n, suffix)


# ---------------------------------------------------------------------------
# Backend selector
# ---------------------------------------------------------------------------
class _MultiAirportDB:
    """Merge several airport providers into one queryable DB.

    Airport data comes from independent provider packs on their own update
    cadences — the US FAA NASR pack (primary, rich Tier-C data) plus optional
    supplemental packs (e.g. Canada from OurAirports). Each provider is a
    ``NASRAirportDB`` over its own sqlite. ``airports_in_range`` chains them and
    de-dups by ICAO so an airport that two providers both carry appears once
    (earlier providers — NASR first — win)."""

    def __init__(self, dbs):
        self._dbs = [d for d in dbs if getattr(d, "ready", False)]

    @property
    def ready(self) -> bool:
        return bool(self._dbs)

    def airports_in_range(self, ac_lat, ac_lon, range_nm):
        seen = set()
        for db in self._dbs:
            for ap in db.airports_in_range(ac_lat, ac_lon, range_nm):
                key = (ap.icao or "").upper() or (round(ap.ref_lat, 4),
                                                  round(ap.ref_lon, 4))
                if key in seen:
                    continue
                seen.add(key)
                yield ap


def make_airport_db(config: dict):
    """Pick the best available airport DB backend for an SVS config.

    Preference order:
      1. NASR primary (``nasr_db_path``) + any provider packs discovered under
         ``airport_provider_dir`` (``<dir>/*/current/airports.sqlite``), merged.
      2. A no-op stub (``ready == False``).

    Provider packs auto-discover: dropping a new airports-<x> pack into the
    provider dir makes its airports appear with no config change.
    """
    paved = bool(config.get("paved_only", True))
    dbs = []
    nasr_path = config.get("nasr_db_path", "")
    if nasr_path:
        dbs.append(NASRAirportDB(nasr_path, paved_only=paved))

    provider_dir = config.get("airport_provider_dir", "")
    if provider_dir:
        import glob
        pat = str(Path(provider_dir) / "*" / "current" / "airports.sqlite")
        for p in sorted(glob.glob(pat)):
            dbs.append(NASRAirportDB(p, paved_only=paved))

    dbs = [d for d in dbs if getattr(d, "ready", False)]
    if len(dbs) == 1:
        return dbs[0]
    if dbs:
        return _MultiAirportDB(dbs)

    if config.get("cifp_path"):
        # VVFR1: the CIFP airport backend is gone. Say so rather than draw
        # no runways silently for a config written before the retirement.
        log.warning("AirportDB: cifp_path is no longer read (the CIFP "
                    "airport backend was retired); set nasr_db_path to the "
                    "airports.sqlite NASR pack")

    # No data — return an empty stub so callers can rely on .ready.
    class _Empty:
        ready = False
        def airports_in_range(self, *a, **kw):
            return iter(())
    return _Empty()
