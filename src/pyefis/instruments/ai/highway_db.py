"""
Major-highway polyline database for the SVS (issue #35).

Mirror of water_db.py: an R-tree-indexed sqlite of decimated OSM road
polylines (motorway/trunk classes from the Geofabrik state extracts),
built by tools/build_highway_db.py. Construct-never-raises: a missing
or unreadable file leaves ``ready`` False and queries yield nothing.

RD3a (AER-640): the builder also carries OSM ``tunnel``/``bridge``/``ref``
per way, packed as a ``flags`` bitmask (``FLAG_TUNNEL``/``FLAG_BRIDGE``)
plus a ``ref`` text column. Both columns are read **when present** --
a published pack built before AER-623 lands has neither, and
``HighwayLine.flags``/``.ref`` fall back to ``0``/``None`` rather than
raising, so an old pack in the field keeps working unchanged.

Attribution: OpenStreetMap contributors, ODbL.
"""

import logging
import sqlite3
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

NM_TO_DEG = 1.0 / 60.0

# Bits of HighwayLine.flags (also the bit assignment tools/build_highway_db.py
# writes) -- brief svs_roads_visual_plan.md section 3.3 / AER-640.
FLAG_TUNNEL = 1 << 0
FLAG_BRIDGE = 1 << 1


def encode_vertices(vertices) -> bytes:
    """(lat, lon) float pairs -> little-endian float32 blob."""
    return np.asarray(vertices, dtype="<f4").tobytes()


def decode_vertices(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype="<f4").reshape(-1, 2)


class HighwayLine:
    __slots__ = ("vertices", "fclass", "flags", "ref")

    def __init__(self, vertices, fclass, flags=0, ref=None):
        self.vertices = vertices
        self.fclass = fclass
        self.flags = flags
        self.ref = ref


class HighwayDB:
    SCHEMA_VERSION = 1

    def __init__(self, path):
        self.ready = False
        self._con = None
        self._has_flags_ref = False
        if not path:
            return
        p = Path(path)
        if not p.is_file():
            log.warning("HighwayDB: %s not found — highways disabled", p)
            return
        try:
            self._con = sqlite3.connect(str(p), check_same_thread=False)
            cur = self._con.execute(
                "SELECT count(*) FROM highway_lines")
            n = cur.fetchone()[0]
            cols = {row[1] for row in
                    self._con.execute("PRAGMA table_info(highway_lines)")}
            self._has_flags_ref = "flags" in cols and "ref" in cols
            self.ready = True
            log.info("HighwayDB: %d polylines from %s%s", n, p.name,
                      "" if self._has_flags_ref
                      else " (no tunnel/bridge/ref columns -- old pack)")
        except Exception as e:
            log.warning("HighwayDB: failed to open %s: %s", path, e)
            self._con = None

    def polylines_in_range(self, lat: float, lon: float, range_nm: float,
                           classes=None):
        """Yield HighwayLine objects whose bbox intersects the range box
        around (lat, lon).

        ``classes`` optionally restricts to an ``fclass`` set, filtered in
        SQL so the moving-map LOD only fetches the classes it will draw at
        the current range (map/layers/roads.py). ``None`` = every class.

        ``flags``/``ref`` are read when the pack carries those columns
        (AER-640); a pack built before AER-623 lands has neither, and every
        yielded ``HighwayLine`` falls back to ``flags=0, ref=None`` rather
        than raising -- the published pack in the field predates this."""
        if not self.ready:
            return
        d = range_nm * NM_TO_DEG
        select_cols = ("l.fclass, l.verts, l.flags, l.ref"
                       if self._has_flags_ref else "l.fclass, l.verts")
        sql = (f"SELECT {select_cols} FROM highway_lines l "
               "JOIN highway_rtree r ON r.id = l.id "
               "WHERE r.max_lat >= ? AND r.min_lat <= ? "
               "  AND r.max_lon >= ? AND r.min_lon <= ?")
        params = [lat - d, lat + d, lon - d * 2.0, lon + d * 2.0]
        classes = list(classes) if classes is not None else None
        if classes is not None:
            if not classes:
                return                       # empty set -> draw nothing
            sql += " AND l.fclass IN (%s)" % ",".join("?" * len(classes))
            params.extend(classes)
        if self._has_flags_ref:
            for fclass, blob, flags, ref in self._con.execute(sql, params):
                yield HighwayLine(decode_vertices(blob), fclass,
                                  flags or 0, ref)
        else:
            for fclass, blob in self._con.execute(sql, params):
                yield HighwayLine(decode_vertices(blob), fclass)
