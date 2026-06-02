"""
Water-body polygon loader for the SVS renderer.

Wraps water.sqlite built by tools/build_water_db.py from OSM /
Natural Earth shapefiles. Range-queryable by bbox; returns
WaterPolygon records that the SVS renderer projects via
``_project_polygon_clipped`` and fills with the standard COLOR_WATER.

    db = WaterDB(path)
    for poly in db.polygons_in_range(ac_lat, ac_lon, range_nm):
        for lat, lon in poly.vertices:
            ...

Construction never raises; if the file is missing or unreadable,
``ready`` stays False and queries yield nothing.

Schema (built by tools/build_water_db.py):
    water_polygons(
        id        INTEGER PRIMARY KEY,
        min_lat   REAL NOT NULL,
        max_lat   REAL NOT NULL,
        min_lon   REAL NOT NULL,
        max_lon   REAL NOT NULL,
        kind      TEXT NOT NULL,   -- 'ocean' | 'lake' | 'river' | ...
        elev_ft   REAL,            -- known surface elev (lakes); NULL for ocean
        vertices  BLOB NOT NULL    -- struct-packed <dd>... = list of (lat, lon)
    )
    INDEX idx_bbox ON water_polygons(min_lat, max_lat, min_lon, max_lon)
"""

from __future__ import annotations

import logging
import math
import sqlite3
import struct
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

NM_PER_DEG_LAT = 60.0


@dataclass
class WaterPolygon:
    id        : int
    kind      : str          # 'ocean', 'lake', 'river', ...
    elev_ft   : float | None # known water-surface elev; None = sample SRTM
    vertices  : list = field(default_factory=list)  # [(lat, lon), ...]

    @property
    def is_ocean(self) -> bool:
        return self.kind == "ocean"


class WaterDB:
    def __init__(self, sqlite_path: str | Path | None):
        self._path = Path(sqlite_path) if sqlite_path else None
        self._con: sqlite3.Connection | None = None
        if self._path is None or not self._path.is_file():
            log.info("WaterDB: %s not found — water rendering disabled",
                     self._path)
            return
        try:
            self._con = sqlite3.connect(str(self._path),
                                        check_same_thread=False)
            self._con.row_factory = sqlite3.Row
            # Sanity-check the schema. If the table or column shape is
            # wrong we drop back to "not ready" rather than crashing
            # downstream.
            self._con.execute(
                "SELECT id, min_lat, max_lat, min_lon, max_lon, "
                "       kind, elev_ft, vertices "
                "FROM water_polygons LIMIT 0")
        except Exception as e:
            log.warning("WaterDB: cannot open %s: %s", self._path, e)
            self._con = None

    @property
    def ready(self) -> bool:
        return self._con is not None

    def polygons_in_range(self, ac_lat: float, ac_lon: float,
                          range_nm: float):
        """Yield ``WaterPolygon`` for each polygon whose bounding box
        overlaps the aircraft's ``range_nm`` square. The yielded
        polygons may extend well beyond the range — the SVS clipper
        handles geometric clipping in screen space."""
        if not self.ready:
            return
        lat_cos = math.cos(math.radians(ac_lat))
        range_deg_lat = range_nm / NM_PER_DEG_LAT
        range_deg_lon = range_deg_lat / max(lat_cos, 1e-6)
        lat_lo = ac_lat - range_deg_lat
        lat_hi = ac_lat + range_deg_lat
        lon_lo = ac_lon - range_deg_lon
        lon_hi = ac_lon + range_deg_lon

        cur = self._con.execute(
            "SELECT id, kind, elev_ft, vertices "
            "FROM water_polygons "
            "WHERE max_lat > ? AND min_lat < ? "
            "  AND max_lon > ? AND min_lon < ?",
            (lat_lo, lat_hi, lon_lo, lon_hi))
        for r in cur:
            yield WaterPolygon(
                id=r["id"],
                kind=(r["kind"] or "").strip().lower(),
                elev_ft=r["elev_ft"],
                vertices=_decode_vertices(r["vertices"]))


def _decode_vertices(blob: bytes) -> list:
    """Unpack a struct-packed <dd... bytes blob into [(lat, lon), ...]."""
    if not blob:
        return []
    n = len(blob) // 16   # 2 doubles per vertex, 8 bytes each
    return [struct.unpack_from("<dd", blob, i * 16) for i in range(n)]


def encode_vertices(vertices) -> bytes:
    """Pack [(lat, lon), ...] into a struct-packed <dd... bytes blob.
    Inverse of ``_decode_vertices``; used by the build tool."""
    buf = bytearray(len(vertices) * 16)
    for i, (lat, lon) in enumerate(vertices):
        struct.pack_into("<dd", buf, i * 16, float(lat), float(lon))
    return bytes(buf)
