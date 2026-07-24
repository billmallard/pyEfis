#!/usr/bin/env python3
"""
Download Geofabrik per-state OSM shapefile extracts and build the SVS
water sqlite database from the inland-water layer (gis_osm_water_a_free_1).

Each Geofabrik state extract is a single zip containing every OSM layer
for the state. We only need ``gis_osm_water_a_free_1.shp`` (polygon
inland water — lakes, reservoirs, ponds, wide rivers) so the script
extracts just that layer and deletes the zip afterwards to keep disk
usage bounded (each state zip is 50 MB–1.5 GB).

The ocean coastline layer is sourced separately from the existing
``water-polygons-split-4326`` extract that ships with this checkout.

Regions that outgrow Geofabrik's free-shapefile size cap stop getting
daily shp builds (BC + Nunavut as of 2026-07; their ``-latest`` pointers
dangle at purged dated files and 404). When a region's shp.zip 404s the
script falls back to the region's ``-latest.osm.pbf`` extract — always
current, never size-capped — and extracts the same water layer from it
with pyosmium (issue #104). The fallback writes a shapefile twin of
``gis_osm_water_a_free_1`` into the cache, so the rest of the pipeline
(resume, filters, build) is unchanged. pyosmium is a tool-side optional
dependency (``pip install osmium``), never required by the pyEfis
runtime.

Usage:
    # Single state — fast path for verifying the pipeline
    python tools/fetch_geofabrik_water.py --states texas

    # Full lower-48 CONUS coverage (multi-hour download)
    python tools/fetch_geofabrik_water.py --states conus

    # Custom subset
    python tools/fetch_geofabrik_water.py \\
        --states oklahoma,arkansas,louisiana,texas
"""

import argparse
import json
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path


CONUS_STATES = [
    # Geofabrik ships no combined California shapefile extract (the
    # -latest-free.shp.zip URL 302s to the homepage); it is split into
    # norcal/socal subregion files. State entries may contain a "/" for
    # such subregion paths; filenames flatten it to "-".
    "alabama", "arizona", "arkansas",
    "california/norcal", "california/socal", "colorado",
    "connecticut", "delaware", "district-of-columbia", "florida",
    "georgia", "idaho", "illinois", "indiana", "iowa", "kansas",
    "kentucky", "louisiana", "maine", "maryland", "massachusetts",
    "michigan", "minnesota", "mississippi", "missouri", "montana",
    "nebraska", "nevada", "new-hampshire", "new-jersey", "new-mexico",
    "new-york", "north-carolina", "north-dakota", "ohio", "oklahoma",
    "oregon", "pennsylvania", "rhode-island", "south-carolina",
    "south-dakota", "tennessee", "texas", "utah", "vermont", "virginia",
    "washington", "west-virginia", "wisconsin", "wyoming",
]

BASE_URL = "https://download.geofabrik.de/north-america/us"
NA_BASE_URL = "https://download.geofabrik.de/north-america"

# Canada provinces + territories, prefixed with their Geofabrik area so
# download_state can route them under north-america/canada/. The canonical
# water-na pack includes them: 1.03M of its 1.27M inland rows sit north of
# 49.5N (617k north of 60N — the territories are in), measured 2026-07-21.
CANADA_PROVINCES = [
    "canada/alberta", "canada/british-columbia", "canada/manitoba",
    "canada/new-brunswick", "canada/newfoundland-and-labrador",
    "canada/northwest-territories", "canada/nova-scotia", "canada/nunavut",
    "canada/ontario", "canada/prince-edward-island", "canada/quebec",
    "canada/saskatchewan", "canada/yukon",
]

# Files we keep from the per-state zip. gis_osm_water_a is polygons
# (lakes/reservoirs/ponds/wide rivers); the linestring waterways layer
# is dropped because the SVS renderer only paints polygons.
WATER_LAYER_FILES = (
    "gis_osm_water_a_free_1.shp",
    "gis_osm_water_a_free_1.shx",
    "gis_osm_water_a_free_1.dbf",
    "gis_osm_water_a_free_1.prj",
    "gis_osm_water_a_free_1.cpg",
)

OCEAN_SHP_DEFAULT = (
    "openstreetmapsdata/water-polygons-split-4326/water_polygons.shp"
)

# WGS84 projection string as shipped in Geofabrik's .prj files, emitted
# alongside the pbf-extracted shapefile twin so the layer is a drop-in.
_WGS84_PRJ = (
    'GEOGCS["GCS_WGS_1984",DATUM["D_WGS_1984",SPHEROID["WGS_1984",'
    '6378137,298.257223563]],PRIMEM["Greenwich",0],UNIT["Degree",'
    '0.017453292519943295]]'
)

# natural=wetland subtypes that get their own fclass (wetland_<sub>) and
# dbf code in the Geofabrik layer; any other subtype folds into plain
# "wetland". Codes read from real dbf records, not documentation.
_WETLAND_SUBTYPES = {
    "marsh": 8221, "reedbed": 8222, "saltmarsh": 8223, "bog": 8224,
    "fen": 8225, "swamp": 8226, "tidalflat": 8229,
}


def water_fclass(tags):
    """Map OSM tags to Geofabrik's gis_osm_water_a ``(fclass, code)``,
    or None when the feature is not part of that layer.

    Derived empirically, not from documentation: a 100% osm_id join
    between Geofabrik's prince-edward-island daily shapefile and the
    same-day pbf (3,064/3,064 records matched, 2026-07-23). The join
    proves the precedence: natural=water wins over its water=/wetland=
    subtags except water=river -> riverbank and water=reservoir ->
    reservoir; bare landuse=basin and bare water=* (without
    natural=water) are NOT in the layer. glacier/dock follow Geofabrik's
    documented code scheme (no instances on PEI to verify empirically).

    ``tags`` is anything with dict-style ``.get`` (an osmium TagList or
    a plain dict).
    """
    nat = tags.get("natural")
    if nat == "water":
        w = tags.get("water")
        if w == "river":
            return ("riverbank", 8202)
        if w == "reservoir":
            return ("reservoir", 8201)
        return ("water", 8200)
    if nat == "wetland":
        sub = tags.get("wetland")
        if sub in _WETLAND_SUBTYPES:
            return ("wetland_" + sub, _WETLAND_SUBTYPES[sub])
        return ("wetland", 8220)
    if nat == "glacier":
        return ("glacier", 8211)
    if tags.get("landuse") == "reservoir":
        return ("reservoir", 8201)
    ww = tags.get("waterway")
    if ww == "riverbank":
        return ("riverbank", 8202)
    if ww == "dock":
        return ("dock", 8203)
    return None


def _ring_signed_area_xy(pts):
    """Shoelace signed area of an (x, y) ring; positive = CCW."""
    s = 0.0
    for i in range(len(pts) - 1):
        s += pts[i][0] * pts[i + 1][1] - pts[i + 1][0] * pts[i][1]
    return s / 2.0


def _fmt_bytes(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _download_url(url, out):
    """Stream ``url`` to ``out`` with progress, via a .partial temp so
    an interrupted download never leaves a truncated file under the
    final name."""
    print(f"  downloading {url}")
    t0 = time.time()
    tmp = out.with_suffix(out.suffix + ".partial")
    with urllib.request.urlopen(url) as resp, open(tmp, "wb") as fh:
        total = int(resp.headers.get("Content-Length", 0))
        copied = 0
        chunk = 1 << 20  # 1 MB
        while True:
            data = resp.read(chunk)
            if not data:
                break
            fh.write(data)
            copied += len(data)
            if total:
                pct = 100.0 * copied / total
                print(f"    {pct:5.1f}%  ({_fmt_bytes(copied)} / "
                      f"{_fmt_bytes(total)})", end="\r")
        print()
    tmp.replace(out)
    print(f"    done in {time.time() - t0:.1f}s "
          f"({_fmt_bytes(out.stat().st_size)})")
    return out


def _state_url_base(state):
    if state.startswith("canada/"):
        return f"{NA_BASE_URL}/{state}"
    return f"{BASE_URL}/{state}"


def download_state(state, cache_dir):
    """Download a single state's shp.zip from Geofabrik. Idempotent:
    if the file already exists with non-zero size, skip the download.
    Validates the result is actually a zip — Geofabrik answers unknown
    URLs with a 302 to its homepage, which otherwise lands here as a
    small HTML file and explodes later in ZipFile (California burned us:
    it only exists as norcal/socal subregion extracts)."""
    url = f"{_state_url_base(state)}-latest-free.shp.zip"
    out = cache_dir / (state.replace("/", "-") + "-latest-free.shp.zip")
    if out.exists() and out.stat().st_size > 0:
        print(f"  [cached] {out.name} ({_fmt_bytes(out.stat().st_size)})")
        return out
    _download_url(url, out)
    with open(out, "rb") as fh:
        magic = fh.read(4)
    if not magic.startswith(b"PK"):
        size = out.stat().st_size
        out.unlink()
        raise RuntimeError(
            f"{url} returned a non-zip ({_fmt_bytes(size)}; magic "
            f"{magic!r}) — Geofabrik redirects unknown URLs to its "
            "homepage. Wrong state name, or a split state (see "
            "california/norcal + california/socal)?")
    return out


def download_state_pbf(state, cache_dir):
    """Download a region's .osm.pbf extract (the shp-less fallback
    source). Idempotent like download_state. A pbf starts with a
    4-byte big-endian BlobHeader length — small, so the leading bytes
    are zero; an HTML redirect page is not, which catches Geofabrik's
    redirect-to-homepage answer for unknown regions."""
    url = f"{_state_url_base(state)}-latest.osm.pbf"
    out = cache_dir / (state.replace("/", "-") + "-latest.osm.pbf")
    if out.exists() and out.stat().st_size > 0:
        print(f"  [cached] {out.name} ({_fmt_bytes(out.stat().st_size)})")
        return out
    _download_url(url, out)
    with open(out, "rb") as fh:
        magic = fh.read(2)
    if magic != b"\x00\x00":
        size = out.stat().st_size
        out.unlink()
        raise RuntimeError(
            f"{url} returned a non-pbf ({_fmt_bytes(size)}; leading "
            f"bytes {magic!r}) — likely Geofabrik's redirect-to-"
            "homepage for an unknown region name")
    return out


def iter_pbf_water_areas(pbf_path):
    """Assemble water areas from a Geofabrik pbf extract and yield
    ``(osm_id, name, fclass, code, polygons)`` per feature, where
    ``polygons`` is GeoJSON MultiPolygon coordinates (list of polygons,
    each a list of [lon, lat] rings, first ring the outer).

    Requires pyosmium — a tool-side optional dependency only; the
    KeyFilter pre-assembly cut keeps the area assembler off the ~97% of
    ways that carry no water-adjacent key. Degenerate geometries osmium
    cannot build are counted and reported, not silently eaten."""
    try:
        import osmium
    except ImportError as e:
        raise RuntimeError(
            "pbf fallback requires pyosmium (`pip install osmium`) — a "
            "tool-side optional dependency, never a pyEfis runtime "
            "requirement") from e
    fac = osmium.geom.GeoJSONFactory()
    fp = (osmium.FileProcessor(str(pbf_path))
          .with_areas(osmium.filter.KeyFilter("natural", "landuse",
                                              "waterway"))
          .with_filter(osmium.filter.EntityFilter(osmium.osm.AREA)))
    geom_fail = 0
    for area in fp:
        hit = water_fclass(area.tags)
        if hit is None:
            continue
        fclass, code = hit
        try:
            coords = json.loads(fac.create_multipolygon(area))
        except (RuntimeError, ValueError):
            geom_fail += 1
            continue
        yield (str(area.orig_id()), area.tags.get("name", ""),
               fclass, code, coords["coordinates"])
    if geom_fail:
        print(f"    WARNING: {geom_fail} water area(s) had degenerate "
              "geometry osmium could not assemble; dropped")


def extract_water_from_pbf(pbf_path, out_dir):
    """Write a shapefile twin of gis_osm_water_a_free_1 from a pbf
    extract, under the canonical layer filenames in ``out_dir``, so
    the rest of the pipeline consumes it unchanged (resume, fclass
    filters, build_water_db.py — which reads it with the same pyshp).

    Writes via temp names and renames only on completion, so a killed
    extraction never leaves a truncated layer the resume path would
    trust. Zero extracted polygons is a hard error: a region with no
    water is a broken extract, not a real geography."""
    import shapefile  # pyshp — build_water_db.py already requires it
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = WATER_LAYER_FILES[0][:-len(".shp")]
    tmp_base = out_dir / (stem + "_partial")
    w = shapefile.Writer(str(tmp_base), shapeType=shapefile.POLYGON)
    # Field spec mirrors the real layer's dbf exactly (read from a
    # Geofabrik file, not invented).
    w.field("osm_id", "C", size=12)
    w.field("code", "N", size=4, decimal=0)
    w.field("fclass", "C", size=28)
    w.field("name", "C", size=100)
    t0 = time.time()
    n = 0
    for osm_id, name, fclass, code, polygons in \
            iter_pbf_water_areas(pbf_path):
        parts = []
        for rings in polygons:
            for k, ring in enumerate(rings):
                pts = [(float(x), float(y)) for x, y in ring]
                if len(pts) < 4:  # closed ring needs 3 distinct points
                    continue
                # Shapefile winding: outer rings CW, holes CCW. Ring
                # role comes from GeoJSON position (first = outer),
                # which is structural — don't infer role from winding.
                cw = _ring_signed_area_xy(pts) < 0
                if (k == 0) != cw:
                    pts.reverse()
                parts.append(pts)
        if not parts:
            continue
        w.poly(parts)
        name = name.encode("utf-8")[:100].decode("utf-8", "ignore")
        w.record(osm_id, code, fclass, name)
        n += 1
        if n % 20000 == 0:
            print(f"    {n} water polygons...")
    w.close()
    if n == 0:
        for ext in (".shp", ".shx", ".dbf"):
            tmp_base.with_suffix(ext).unlink(missing_ok=True)
        raise RuntimeError(
            f"{pbf_path.name}: pbf extraction produced 0 water "
            "polygons — refusing to emit an empty layer")
    for ext in (".shp", ".shx", ".dbf"):
        tmp_base.with_suffix(ext).replace(out_dir / (stem + ext))
    (out_dir / (stem + ".prj")).write_text(_WGS84_PRJ)
    (out_dir / (stem + ".cpg")).write_text("UTF-8")
    print(f"    extracted {n} water polygon(s) from {pbf_path.name} "
          f"in {time.time() - t0:.1f}s")
    return out_dir / WATER_LAYER_FILES[0]


def extract_water_layer(zip_path, dest_dir):
    """Extract just the water polygon layer from a state zip. Returns
    the path to the extracted .shp, or None if the zip doesn't contain
    the expected layer."""
    state = zip_path.name.replace("-latest-free.shp.zip", "")
    out_dir = dest_dir / state
    out_dir.mkdir(parents=True, exist_ok=True)
    shp_out = out_dir / WATER_LAYER_FILES[0]
    if shp_out.exists() and shp_out.stat().st_size > 0:
        return shp_out
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        want = []
        for layer in WATER_LAYER_FILES:
            for n in names:
                if n.endswith(layer):
                    want.append((n, layer))
                    break
        if not any(layer == WATER_LAYER_FILES[0]
                   for _, layer in want):
            print(f"  WARNING: {zip_path.name} has no water_a layer")
            return None
        for src, dest in want:
            with zf.open(src) as fh_in, \
                    open(out_dir / dest, "wb") as fh_out:
                shutil.copyfileobj(fh_in, fh_out)
    return shp_out


def parse_states_arg(s):
    s = s.strip().lower()
    if s == "conus":
        return list(CONUS_STATES)
    if s == "na":
        # Full water-na scope: lower 48 + Alaska + all of Canada. This is
        # what the published water-na pack contains.
        return list(CONUS_STATES) + ["alaska"] + list(CANADA_PROVINCES)
    states = []
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        # Accept both "new-york" and "new_york" / "newyork"
        part = part.replace(" ", "-").replace("_", "-")
        states.append(part)
    return states


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--states", default="conus",
                   help="comma-separated state slugs (geofabrik style: "
                        "'new-york', 'texas', ...) or 'conus' for the "
                        "lower 48")
    p.add_argument("--cache-dir", default="openstreetmapsdata/geofabrik",
                   help="where state zips and extracted shapefiles "
                        "are kept (idempotent — reusing this dir lets "
                        "you re-run the build without re-downloading)")
    p.add_argument("--output", default="water/water_rtree.sqlite",
                   help="output sqlite path (overwrites)")
    p.add_argument("--ocean-shp", default=OCEAN_SHP_DEFAULT,
                   help="OSM coastline polygons shapefile (kept "
                        "alongside inland water). Pass '' to skip.")
    p.add_argument("--ne-lakes",
                   default="openstreetmapsdata/ne_10m_lakes/ne_10m_lakes.shp",
                   help="Natural Earth 10m lakes shapefile, for "
                        "non-US coverage outside the state list. "
                        "Pass '' to skip.")
    p.add_argument("--keep-zips", action="store_true",
                   help="don't delete state zips (or fallback pbfs) "
                        "after extraction (useful for re-running with "
                        "different filters)")
    p.add_argument("--max-vertices", type=int, default=32,
                   help="per-polygon vertex cap (build_water_db.py "
                        "default)")
    p.add_argument("--min-area-km2", type=float, default=0.0,
                   help="passthrough to build_water_db.py: drop inland "
                        "rings smaller than this (declutter; ocean "
                        "never filtered). Default 0 disables.")
    p.add_argument("--keep-fclass", nargs="*", default=None,
                   help="passthrough to build_water_db.py: keep only "
                        "these OSM fclass values (e.g. water "
                        "reservoir). Omit to keep all.")
    p.add_argument("--build-only", action="store_true",
                   help="skip download/extract; only run the build "
                        "step using whatever shapefiles are already "
                        "in the cache dir")
    args = p.parse_args()

    cache_dir = Path(args.cache_dir).resolve()
    cache_dir.mkdir(parents=True, exist_ok=True)
    extracted_dir = cache_dir / "extracted"
    extracted_dir.mkdir(exist_ok=True)
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    states = parse_states_arg(args.states)
    print(f"Plan: {len(states)} state(s): {', '.join(states[:5])}"
          f"{'...' if len(states) > 5 else ''}")
    print(f"Cache: {cache_dir}")
    print(f"Output: {output}")
    print()

    shp_paths = []
    failed = []
    if not args.build_only:
        for i, state in enumerate(states, 1):
            print(f"[{i}/{len(states)}] {state}")
            # Resume support: the zip is deleted after extraction, so a
            # re-run must not re-download states whose layer is already
            # extracted.
            done = (extracted_dir / state.replace("/", "-")
                    / WATER_LAYER_FILES[0])
            if done.exists() and done.stat().st_size > 0:
                print(f"  [extracted] {done.parent.name}")
                shp_paths.append(done)
                continue
            try:
                zip_path = download_state(state, cache_dir)
                shp = extract_water_layer(zip_path, extracted_dir)
            except urllib.error.HTTPError as e:
                if e.code != 404:
                    print(f"  ERROR: {state}: {e}")
                    failed.append(state)
                    continue
                # Regions past Geofabrik's free-shapefile size cap stop
                # getting shp builds and their -latest pointer 404s (BC
                # + Nunavut, issue #104). The pbf extract stays current;
                # extract the same water layer from it instead. Only a
                # 404 routes here — the redirect-to-homepage case means
                # a wrong region name, which the pbf wouldn't fix.
                print(f"  shp.zip unavailable (HTTP 404) — falling "
                      "back to pbf extraction (#104)")
                try:
                    pbf_path = download_state_pbf(state, cache_dir)
                    shp = extract_water_from_pbf(
                        pbf_path,
                        extracted_dir / state.replace("/", "-"))
                except Exception as e2:
                    print(f"  ERROR: {state}: pbf fallback: {e2}")
                    failed.append(state)
                    continue
                shp_paths.append(shp)
                if not args.keep_zips:
                    pbf_path.unlink()
                    print(f"  removed {pbf_path.name} "
                          "(--keep-zips to retain)")
                continue
            except Exception as e:
                print(f"  ERROR: {state}: {e}")
                failed.append(state)
                continue
            if shp:
                shp_paths.append(shp)
                if not args.keep_zips:
                    zip_path.unlink()
                    print(f"  removed {zip_path.name} "
                          "(--keep-zips to retain)")
            else:
                failed.append(state)
    if failed:
        # A CONUS pack silently missing a state's lakes is worse than no
        # pack: fail loud, list the gaps, build nothing.
        print(f"ERROR: {len(failed)} state(s) failed: "
              f"{', '.join(failed)}", file=sys.stderr)
        sys.exit(1)
    if args.build_only:
        # --build-only skipped the download loop, so assemble the input
        # list from whatever the cache holds. This sweep must run ONLY
        # in --build-only mode: the download loop above already appends
        # every requested area (including cache-resumed ones), and
        # sweeping on top of that passed every shapefile twice, doubling
        # each inland polygon in the output — build_water_db.py does
        # plain INSERTs with no dedup (issue #106, caught in the
        # 2026q2r6 candidate: 128 args for 64 areas, 18.9 GB output).
        for sub in sorted(extracted_dir.iterdir()):
            shp = sub / WATER_LAYER_FILES[0]
            if shp.exists():
                shp_paths.append(shp)

    # Belt and braces: a duplicate --osm-water input double-ingests its
    # polygons downstream, so collapse repeats no matter how the list
    # was assembled (e.g. the same state named twice in --states).
    shp_paths = list(dict.fromkeys(shp_paths))

    if not shp_paths:
        print("ERROR: no water shapefiles to build from", file=sys.stderr)
        sys.exit(1)

    print(f"\nBuilding {output} from {len(shp_paths)} water shapefile(s)")
    cmd = [
        sys.executable,
        str(Path(__file__).parent / "build_water_db.py"),
        str(output),
        "--max-vertices", str(args.max_vertices),
    ]
    if args.min_area_km2 > 0:
        cmd += ["--min-area-km2", str(args.min_area_km2)]
    if args.keep_fclass:
        cmd += ["--keep-fclass", *args.keep_fclass]
    if args.ocean_shp:
        cmd += ["--ocean", args.ocean_shp]
    if args.ne_lakes:
        cmd += ["--lake", args.ne_lakes]
    for shp in shp_paths:
        cmd += ["--osm-water", str(shp)]
    print(" ".join(cmd[:6]) + f" ... ({len(shp_paths)} --osm-water args)")
    subprocess.check_call(cmd)
    sz = output.stat().st_size
    print(f"\nDone. Output: {output} ({_fmt_bytes(sz)})")


if __name__ == "__main__":
    main()
