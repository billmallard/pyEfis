#  SPDX-License-Identifier: GPL-2.0-or-later
"""Waypoint lookup service + user waypoints (FP3).

``WaypointIndex`` builds an in-memory identifier index over the on-device
``airports.sqlite`` / ``navaids.sqlite`` packs (both signed and read-only —
there is nowhere to persist an index on the pack itself) plus a small,
mutable JSON-backed store of user-created waypoints. See
``makerplane/briefs/flight_plan_plan.md`` section 3.4 and
billmallard/pyEfis#182.

Construction never raises: a missing or unreadable database path just
leaves that source out of the index and ``ready`` reflects what actually
loaded. The ident index itself is built on a background thread so
constructing a ``WaypointIndex`` never blocks its caller; every query
method waits for that build to finish before answering, so the first call
after construction may block briefly while later calls are instant.

Qt-free: nothing here may import PyQt6.
"""

from __future__ import annotations

import bisect
import csv
import json
import logging
import math
import os
import re
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import geo

log = logging.getLogger(__name__)

WAYPOINT_TYPES = frozenset({"airport", "vor", "ndb", "fix", "user", "map"})

DEFAULT_PREFIX_LIMIT = 5
DEFAULT_NEAREST_RADIUS_NM = 200.0
DEFAULT_NEAREST_LIMIT = 25

USER_ID_MAX_LEN = 6
USER_COMMENT_MAX_LEN = 25
USER_WAYPOINT_CAP = 1000
USER_DEDUPE_DEG = 0.0001
RECENT_CAP = 20

_USER_ID_RE = re.compile(r"^[A-Z0-9]+$")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class WaypointError(ValueError):
    """Base class for all user-waypoint refusals — always a caller mistake,
    never an internal fault, so callers can catch this one class and show
    ``str(exc)`` to the pilot."""


class InvalidWaypointError(WaypointError):
    pass


class DuplicateIdentError(WaypointError):
    pass


class WaypointNotFoundError(WaypointError):
    pass


class WaypointInUseError(WaypointError):
    pass


class WaypointCapacityError(WaypointError):
    pass


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class Waypoint:
    id: str
    type: str
    lat: float
    lon: float
    name: str = ""
    elev_ft: float | None = None
    freq: str | None = None
    comment: str = ""


@dataclass
class ImportResult:
    added: int = 0
    skipped_duplicate_position: int = 0
    skipped_duplicate_id: int = 0
    skipped_invalid: int = 0


@dataclass
class _IndexEntry:
    waypoint: Waypoint
    runway_len_ft: float | None = None


def _norm_ident(s) -> str:
    return (s or "").strip().upper()


def _airport_id_aliases(raw: str) -> tuple[str, list[str]]:
    """Canonical ICAO id + alias idents for an airport's raw NASR ``icao``
    column value, expanding the K+3-letter normalisation both directions
    (mirrors ``ai/airport_db.py`` NASRAirportDB.airports_in_range)."""
    norm = _norm_ident(raw)
    if len(norm) == 3 and norm.isalpha():
        return "K" + norm, [norm]
    if len(norm) == 4 and norm[0] == "K" and norm[1:].isalpha():
        return norm, [norm[1:]]
    return norm, []


# ---------------------------------------------------------------------------
# User waypoints
# ---------------------------------------------------------------------------
class UserWaypointStore:
    """``<userdir>/user_waypoints.json`` — ``{"schema": "mp-userwpt/1",
    "waypoints": [{"id", "comment", "lat", "lon", "created"}]}``. Construct-
    never-raises; atomic writes (tmp file + ``os.replace``)."""

    SCHEMA = "mp-userwpt/1"

    def __init__(self, path=None):
        self._path = Path(path) if path else None
        self._lock = threading.Lock()
        self._waypoints: dict[str, dict] = {}
        self._load()

    def _load(self):
        if self._path is None or not self._path.is_file():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            for rec in data.get("waypoints", []):
                ident = _norm_ident(rec.get("id", ""))
                if not ident:
                    continue
                self._waypoints[ident] = {
                    "id": ident,
                    "lat": float(rec["lat"]),
                    "lon": float(rec["lon"]),
                    "comment": rec.get("comment", "") or "",
                    "created": rec.get("created", "") or "",
                }
        except Exception as e:
            log.warning("UserWaypointStore: failed to load %s: %s", self._path, e)

    def _save(self):
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": self.SCHEMA,
            "waypoints": [self._waypoints[k] for k in sorted(self._waypoints)],
        }
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, self._path)

    @staticmethod
    def _to_waypoint(rec: dict) -> Waypoint:
        return Waypoint(id=rec["id"], type="user", lat=rec["lat"], lon=rec["lon"],
                         comment=rec.get("comment", ""))

    # -- validation ------------------------------------------------------
    def _validate_id(self, ident) -> str:
        norm = _norm_ident(ident)
        if not norm or len(norm) > USER_ID_MAX_LEN or not _USER_ID_RE.match(norm):
            raise InvalidWaypointError(
                f"ident must be 1-{USER_ID_MAX_LEN} characters, A-Z/0-9: {ident!r}")
        return norm

    def _validate_comment(self, comment) -> str:
        comment = comment or ""
        if len(comment) > USER_COMMENT_MAX_LEN:
            raise InvalidWaypointError(
                f"comment exceeds {USER_COMMENT_MAX_LEN} characters")
        return comment

    def _next_default_id(self) -> str:
        n = 1
        while n <= 999:
            candidate = "USR%03d" % n
            if candidate not in self._waypoints:
                return candidate
            n += 1
        raise WaypointCapacityError("no default USRnnn ident available")

    def _find_by_position(self, lat: float, lon: float):
        for rec in self._waypoints.values():
            if (abs(rec["lat"] - lat) <= USER_DEDUPE_DEG
                    and abs(rec["lon"] - lon) <= USER_DEDUPE_DEG):
                return rec
        return None

    # -- public API --------------------------------------------------------
    def list(self) -> list[Waypoint]:
        with self._lock:
            return [self._to_waypoint(r) for r in self._waypoints.values()]

    def lookup(self, ident: str) -> list[Waypoint]:
        norm = _norm_ident(ident)
        with self._lock:
            rec = self._waypoints.get(norm)
            return [self._to_waypoint(rec)] if rec else []

    def add(self, lat: float, lon: float, comment: str = "", id: str | None = None) -> Waypoint:
        with self._lock:
            if len(self._waypoints) >= USER_WAYPOINT_CAP:
                raise WaypointCapacityError(
                    f"user waypoint cap ({USER_WAYPOINT_CAP}) reached")
            comment = self._validate_comment(comment)
            ident = self._validate_id(id) if id else self._next_default_id()
            if ident in self._waypoints:
                raise DuplicateIdentError(f"user waypoint {ident!r} already exists")
            rec = {"id": ident, "lat": float(lat), "lon": float(lon),
                   "comment": comment,
                   "created": datetime.now(timezone.utc).isoformat()}
            self._waypoints[ident] = rec
            self._save()
            return self._to_waypoint(rec)

    def edit(self, id: str, *, lat=None, lon=None, comment=None, active_idents=None) -> Waypoint:
        with self._lock:
            norm = _norm_ident(id)
            self._check_not_active(norm, active_idents)
            rec = self._waypoints.get(norm)
            if rec is None:
                raise WaypointNotFoundError(f"user waypoint {norm!r} not found")
            if lat is not None:
                rec["lat"] = float(lat)
            if lon is not None:
                rec["lon"] = float(lon)
            if comment is not None:
                rec["comment"] = self._validate_comment(comment)
            self._save()
            return self._to_waypoint(rec)

    def delete(self, id: str, active_idents=None) -> None:
        with self._lock:
            norm = _norm_ident(id)
            self._check_not_active(norm, active_idents)
            if norm not in self._waypoints:
                raise WaypointNotFoundError(f"user waypoint {norm!r} not found")
            del self._waypoints[norm]
            self._save()

    @staticmethod
    def _check_not_active(norm, active_idents):
        if active_idents and norm in {_norm_ident(a) for a in active_idents}:
            raise WaypointInUseError(f"{norm} is in the active flight plan")

    def import_csv(self, path) -> ImportResult:
        """Import idents from a CSV with (case-insensitive) columns
        id/ident, lat/latitude, lon/longitude and an optional comment/name
        column. A row within ``USER_DEDUPE_DEG`` of an existing user
        waypoint is skipped (the existing one is kept); a row whose ident
        already exists is skipped; invalid rows are skipped. Import stops
        (rather than raising) once the 1,000 cap is reached."""
        result = ImportResult()
        with open(path, newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            fieldmap = {(k or "").strip().lower(): k for k in (reader.fieldnames or [])}
            id_key = fieldmap.get("id") or fieldmap.get("ident")
            lat_key = fieldmap.get("lat") or fieldmap.get("latitude")
            lon_key = fieldmap.get("lon") or fieldmap.get("longitude")
            comment_key = fieldmap.get("comment") or fieldmap.get("name")
            if not (id_key and lat_key and lon_key):
                raise InvalidWaypointError(
                    "CSV must have id/ident, lat[itude], lon[gitude] columns")

            with self._lock:
                for row in reader:
                    if len(self._waypoints) >= USER_WAYPOINT_CAP:
                        break
                    try:
                        lat = float(row[lat_key])
                        lon = float(row[lon_key])
                    except (KeyError, TypeError, ValueError):
                        result.skipped_invalid += 1
                        continue
                    if self._find_by_position(lat, lon) is not None:
                        result.skipped_duplicate_position += 1
                        continue
                    try:
                        ident = self._validate_id(row.get(id_key, ""))
                    except InvalidWaypointError:
                        result.skipped_invalid += 1
                        continue
                    if ident in self._waypoints:
                        result.skipped_duplicate_id += 1
                        continue
                    comment = (row.get(comment_key) or "") if comment_key else ""
                    comment = comment[:USER_COMMENT_MAX_LEN]
                    self._waypoints[ident] = {
                        "id": ident, "lat": lat, "lon": lon, "comment": comment,
                        "created": datetime.now(timezone.utc).isoformat()}
                    result.added += 1
                self._save()
        return result


class RecentList:
    """``<userdir>/recent.json`` — ``{"idents": [...]}``, most-recent first,
    capped at ``RECENT_CAP``."""

    def __init__(self, path=None):
        self._path = Path(path) if path else None
        self._lock = threading.Lock()
        self._idents: list[str] = []
        self._load()

    def _load(self):
        if self._path is None or not self._path.is_file():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self._idents = [_norm_ident(i) for i in data.get("idents", []) if i][:RECENT_CAP]
        except Exception as e:
            log.warning("RecentList: failed to load %s: %s", self._path, e)

    def _save(self):
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps({"idents": self._idents}, indent=2), encoding="utf-8")
        os.replace(tmp, self._path)

    def push(self, ident: str) -> None:
        norm = _norm_ident(ident)
        if not norm:
            return
        with self._lock:
            if norm in self._idents:
                self._idents.remove(norm)
            self._idents.insert(0, norm)
            del self._idents[RECENT_CAP:]
            self._save()

    def list(self) -> list[str]:
        with self._lock:
            return list(self._idents)


# ---------------------------------------------------------------------------
# WaypointIndex
# ---------------------------------------------------------------------------
class WaypointIndex:
    """In-memory ident index over ``airports.sqlite`` + ``navaids.sqlite``,
    plus user waypoints and a recent list. Construct-never-raises; ``ready``
    reflects whether at least one source loaded."""

    def __init__(self, airports_db_path=None, navaids_db_path=None,
                 user_file=None, recent_file=None):
        self._airports_db_path = Path(airports_db_path) if airports_db_path else None
        self._navaids_db_path = Path(navaids_db_path) if navaids_db_path else None

        self._entries: list[_IndexEntry] = []
        self._by_ident: dict[str, list[_IndexEntry]] = {}
        self._sorted_idents: list[str] = []
        self._build_ok = False
        self._built = threading.Event()

        self.user = UserWaypointStore(user_file)
        self.recent = RecentList(recent_file)

        self._build_thread = threading.Thread(
            target=self._build, name="WaypointIndexBuild", daemon=True)
        self._build_thread.start()

    # ------------------------------------------------------------------
    # Build (background thread)
    # ------------------------------------------------------------------
    def _build(self):
        entries: list[_IndexEntry] = []
        by_ident: dict[str, list[_IndexEntry]] = {}
        ok = False
        if self._airports_db_path and self._airports_db_path.is_file():
            try:
                self._load_airports(entries, by_ident)
                ok = True
            except Exception as e:
                log.warning("WaypointIndex: failed to load airports db %s: %s",
                            self._airports_db_path, e)
        if self._navaids_db_path and self._navaids_db_path.is_file():
            try:
                self._load_navaids(entries, by_ident)
                ok = True
            except Exception as e:
                log.warning("WaypointIndex: failed to load navaids db %s: %s",
                            self._navaids_db_path, e)

        self._entries = entries
        self._by_ident = by_ident
        self._sorted_idents = sorted(by_ident.keys())
        self._build_ok = ok
        self._built.set()

    def _load_airports(self, entries, by_ident):
        con = sqlite3.connect(str(self._airports_db_path))
        try:
            con.row_factory = sqlite3.Row
            runway_len = dict(con.execute(
                "SELECT site_no, MAX(length_ft) FROM runways GROUP BY site_no"))
            for row in con.execute(
                    "SELECT site_no, icao, name, lat, lon, elev_ft FROM airports"):
                raw_id = row["icao"] or ""
                if not raw_id:
                    continue
                canonical, aliases = _airport_id_aliases(raw_id)
                wp = Waypoint(id=canonical, type="airport",
                              lat=row["lat"], lon=row["lon"],
                              name=(row["name"] or "").strip(),
                              elev_ft=row["elev_ft"])
                entry = _IndexEntry(waypoint=wp,
                                     runway_len_ft=runway_len.get(row["site_no"]))
                entries.append(entry)
                for ident in (canonical, *aliases):
                    by_ident.setdefault(ident, []).append(entry)
        finally:
            con.close()

    def _load_navaids(self, entries, by_ident):
        con = sqlite3.connect(str(self._navaids_db_path))
        try:
            con.row_factory = sqlite3.Row
            for row in con.execute(
                    "SELECT id, type, name, freq, elev_ft, lat, lon FROM navaids"):
                ident = _norm_ident(row["id"])
                if not ident:
                    continue
                wtype = "ndb" if "NDB" in (row["type"] or "").upper() else "vor"
                wp = Waypoint(id=ident, type=wtype, lat=row["lat"], lon=row["lon"],
                              name=(row["name"] or "").strip(),
                              elev_ft=row["elev_ft"], freq=(row["freq"] or None))
                entry = _IndexEntry(waypoint=wp)
                entries.append(entry)
                by_ident.setdefault(ident, []).append(entry)

            for row in con.execute("SELECT id, use_code, lat, lon FROM fixes"):
                ident = _norm_ident(row["id"])
                if not ident:
                    continue
                wp = Waypoint(id=ident, type="fix", lat=row["lat"], lon=row["lon"])
                entry = _IndexEntry(waypoint=wp)
                entries.append(entry)
                by_ident.setdefault(ident, []).append(entry)
        finally:
            con.close()

    def _wait_built(self):
        self._built.wait()

    def wait_ready(self, timeout: float | None = None) -> bool:
        """Block until the background build finishes (or *timeout* elapses).
        Returns ``ready``. Optional — every query method waits internally;
        this is for a caller (e.g. the instrument) that wants to know
        without issuing a query."""
        self._built.wait(timeout)
        return self.ready

    @property
    def ready(self) -> bool:
        return self._built.is_set() and self._build_ok

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    def lookup(self, ident: str) -> list[Waypoint]:
        """Exact match across all types (duplicates are returned, caller
        disambiguates)."""
        self._wait_built()
        norm = _norm_ident(ident)
        out = [e.waypoint for e in self._by_ident.get(norm, [])]
        out.extend(self.user.lookup(norm))
        return out

    def prefix(self, text: str, ref_lat: float, ref_lon: float,
               limit: int = DEFAULT_PREFIX_LIMIT, types=None) -> list[Waypoint]:
        """FastFind: idents starting with *text*, sorted by distance from
        ``(ref_lat, ref_lon)`` — the caller picks the reference (near the
        aircraft, near the last waypoint when appending, between the
        previous/next waypoint when inserting)."""
        self._wait_built()
        norm = _norm_ident(text)
        if not norm:
            return []
        type_set = set(types) if types else None

        candidates: list[Waypoint] = []
        lo = bisect.bisect_left(self._sorted_idents, norm)
        for ident in self._sorted_idents[lo:]:
            if not ident.startswith(norm):
                break
            for entry in self._by_ident[ident]:
                if type_set and entry.waypoint.type not in type_set:
                    continue
                candidates.append(entry.waypoint)
        for wp in self.user.list():
            if wp.id.startswith(norm) and (not type_set or wp.type in type_set):
                candidates.append(wp)

        candidates.sort(key=lambda wp: geo.distance_nm(ref_lat, ref_lon, wp.lat, wp.lon))
        return candidates[:limit]

    def nearest(self, ref_lat: float, ref_lon: float,
                radius_nm: float = DEFAULT_NEAREST_RADIUS_NM,
                limit: int = DEFAULT_NEAREST_LIMIT, types=None):
        """Nearest waypoints within *radius_nm*, nearest first. Returns
        ``(Waypoint, dist_nm, brg_true, extra)`` — *extra* is the longest
        runway length in ft for an airport, else ``None``."""
        self._wait_built()
        type_set = set(types) if types else None
        lat_cos = math.cos(math.radians(ref_lat))
        deg_lat = radius_nm / 60.0
        deg_lon = deg_lat / max(lat_cos, 1e-6)
        lat_lo, lat_hi = ref_lat - deg_lat, ref_lat + deg_lat
        lon_lo, lon_hi = ref_lon - deg_lon, ref_lon + deg_lon

        results = []

        def consider(wp: Waypoint, extra):
            if type_set and wp.type not in type_set:
                return
            if not (lat_lo <= wp.lat <= lat_hi and lon_lo <= wp.lon <= lon_hi):
                return
            dist = geo.distance_nm(ref_lat, ref_lon, wp.lat, wp.lon)
            if dist > radius_nm:
                return
            brg = geo.initial_bearing(ref_lat, ref_lon, wp.lat, wp.lon)
            results.append((wp, dist, brg, extra))

        for entry in self._entries:
            consider(entry.waypoint, entry.runway_len_ft)
        for wp in self.user.list():
            consider(wp, None)

        results.sort(key=lambda r: r[1])
        return results[:limit]
