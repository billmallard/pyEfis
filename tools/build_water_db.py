#!/usr/bin/env python3
"""
Build a water-polygon sqlite database for SVS rendering.

Reads polygons from shapefiles (Natural Earth, OSM water-polygons) or
from a simple text format and writes them to a sqlite database the
WaterDB class can query.

Usage:
    # From shapefiles (requires pyshp):
    python build_water_db.py water.sqlite \\
        --ocean  /path/to/ne_10m_ocean.shp \\
        --lake   /path/to/ne_10m_lakes.shp \\
        --osm-water /path/to/water_polygons.shp

    # From a simple text format (no dependencies — useful on the Pi
    # for hand-crafting a small test dataset):
    python build_water_db.py water.sqlite --text input.txt

Text format:
    # Each polygon starts with a 'P kind [elev_ft]' line, followed by
    # vertex lines 'lat lon', ended with a blank line or EOF.
    P ocean
    34.4  -120.0
    34.4  -119.5
    34.0  -119.5
    34.0  -120.0

    P lake 656
    35.78 -81.30
    35.79 -81.28
    ...
"""

import argparse
import sqlite3
import sys
from pathlib import Path

# Local import; let it fail loudly if the module is wrong.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from pyefis.instruments.ai.water_db import encode_vertices


SCHEMA = """
CREATE TABLE IF NOT EXISTS water_polygons (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    min_lat   REAL NOT NULL,
    max_lat   REAL NOT NULL,
    min_lon   REAL NOT NULL,
    max_lon   REAL NOT NULL,
    kind      TEXT NOT NULL,
    elev_ft   REAL,
    vertices  BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_bbox
    ON water_polygons(min_lat, max_lat, min_lon, max_lon);
CREATE INDEX IF NOT EXISTS idx_kind ON water_polygons(kind);
"""


def insert_polygon(con, kind, elev_ft, vertices):
    if len(vertices) < 3:
        return False
    lats = [v[0] for v in vertices]
    lons = [v[1] for v in vertices]
    con.execute(
        "INSERT INTO water_polygons "
        "(min_lat, max_lat, min_lon, max_lon, kind, elev_ft, vertices) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (min(lats), max(lats), min(lons), max(lons),
         kind, elev_ft, encode_vertices(vertices)))
    return True


def import_shapefile(con, path, kind, elev_ft=None):
    """Import every polygon (and every ring of every multi-polygon) from
    a shapefile into the water_polygons table."""
    try:
        import shapefile  # pyshp
    except ImportError:
        print("ERROR: shapefile import requires pyshp (`pip install pyshp`)",
              file=sys.stderr)
        sys.exit(2)

    sf = shapefile.Reader(str(path))
    n = 0
    for shape in sf.shapes():
        if not shape.points:
            continue
        # shape.parts marks the start of each ring; iterate ring by ring.
        parts = list(shape.parts) + [len(shape.points)]
        for k in range(len(parts) - 1):
            ring = shape.points[parts[k]:parts[k + 1]]
            # Shapefile stores (lon, lat); we want (lat, lon).
            vertices = [(p[1], p[0]) for p in ring]
            if insert_polygon(con, kind, elev_ft, vertices):
                n += 1
    print(f"  {Path(path).name}: imported {n} ring(s) as kind={kind}")
    return n


def import_text(con, path):
    """Import polygons from the documented text format."""
    cur_kind = None
    cur_elev = None
    cur_verts: list = []
    n = 0

    def flush():
        nonlocal cur_verts, n
        if cur_kind and len(cur_verts) >= 3:
            if insert_polygon(con, cur_kind, cur_elev, cur_verts):
                n += 1
        cur_verts = []

    with open(path, "r") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                if line == "":
                    flush()
                continue
            if line.startswith("P "):
                flush()
                parts = line.split()
                cur_kind = parts[1].lower()
                cur_elev = float(parts[2]) if len(parts) >= 3 else None
            else:
                lat_s, lon_s = line.split()
                cur_verts.append((float(lat_s), float(lon_s)))
    flush()
    print(f"  {Path(path).name}: imported {n} polygon(s)")
    return n


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("output", help="sqlite output path")
    p.add_argument("--ocean", action="append", default=[],
                   help="ocean shapefile (no surface elev; SRTM may be 0/void)")
    p.add_argument("--lake", action="append", default=[],
                   help="lake shapefile; elev sampled from SRTM at render time")
    p.add_argument("--river", action="append", default=[],
                   help="river polygon shapefile")
    p.add_argument("--osm-water", action="append", default=[],
                   help="generic OSM water shapefile (kind='water')")
    p.add_argument("--text", action="append", default=[],
                   help="text-format polygon file (see module docstring)")
    args = p.parse_args()

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    con = sqlite3.connect(str(out))
    con.executescript(SCHEMA)

    total = 0
    for path in args.ocean:
        total += import_shapefile(con, path, "ocean")
    for path in args.lake:
        total += import_shapefile(con, path, "lake")
    for path in args.river:
        total += import_shapefile(con, path, "river")
    for path in args.osm_water:
        total += import_shapefile(con, path, "water")
    for path in args.text:
        total += import_text(con, path)
    con.commit()
    con.close()
    print(f"-> {out} ({total} polygons)")


if __name__ == "__main__":
    main()
