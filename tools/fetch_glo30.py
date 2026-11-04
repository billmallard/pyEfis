#!/usr/bin/env python3
"""
Fetch Copernicus GLO-30 DEM tiles from the AWS Open Data bucket.

P6 of docs/svs_structural_plan.md: GLO-30 replaces SRTM3 as the terrain
source (global coverage — fixes the SRTM >60N hole over northern
Canada; 30 m resolution). This tool downloads the raw 1x1 degree
Cloud-Optimized GeoTIFFs; the HGT conversion step lives separately so
the (large, slow) download and the (fast, re-runnable) conversion can
be iterated independently.

No authentication required. Resumable: existing complete files are
skipped, so re-running after an interruption continues where it left
off. Partial downloads go to a .part file and are renamed on success.

Usage:
    python tools/fetch_glo30.py --dest D:/EarthData/glo30 \
        --tiles-file glo30_tiles.txt                    # exactly these tiles
    python tools/fetch_glo30.py --dest D:/EarthData/glo30 \
        --min-lat 14 --max-lat 72 --min-lon -170 --max-lon -52
    python tools/fetch_glo30.py --dest ... --dry-run     # count + size only

Pick the tiles one of two ways; there is no default.

--tiles-file / --tiles name the tiles exactly (N34W119 form). A file has
one tile per line, with the name as the first whitespace field; blank
lines and # comments are skipped, and "-" reads stdin. That accepts
makerplane-data's packtools/data/glo30_tiles.txt (every tile in a
terrain region) and the output of its `make_glo30_tiles.py --check-tree`
(the region tiles a tree lacks) as they are. Use this path for a pack
build: a bounding box around the regions also covers land outside all
of them (AER-4710: 185 tiles in the box when the tree lacked 89).

--min-lat/--max-lat/--min-lon/--max-lon select a box; all four are
required, and the bounds are inclusive tile SW corners. The example
above is the window the NAS North America tree was fetched with.

The bucket's tileList.txt enumerates land tiles only — ocean cells have
no tile, which matches the renderer's missing-tile-is-water convention.
"""

import argparse
import concurrent.futures
import os
import re
import sys
import urllib.request

BUCKET = "https://copernicus-dem-30m.s3.amazonaws.com"
NAME_RE = re.compile(
    r"Copernicus_DSM_COG_10_([NS])(\d+)_00_([EW])(\d+)_00_DEM")


def tile_latlon(name):
    m = NAME_RE.fullmatch(name.strip())
    if not m:
        return None
    lat = int(m.group(2)) * (1 if m.group(1) == "N" else -1)
    lon = int(m.group(4)) * (1 if m.group(3) == "E" else -1)
    return lat, lon


BBOX = ("min_lat", "max_lat", "min_lon", "max_lon")
SHORT_RE = re.compile(r"([NS])(\d+)([EW])(\d+)")


def short_latlon(tile):
    """N34W119 -> (34, -119); None if it is not a tile name."""
    m = SHORT_RE.fullmatch(tile.strip().upper())
    if not m:
        return None
    lat = int(m.group(2)) * (1 if m.group(1) == "N" else -1)
    lon = int(m.group(4)) * (1 if m.group(3) == "E" else -1)
    return lat, lon


def read_tile_names(lines):
    """First whitespace field of each line; blanks and # comments skipped."""
    out = []
    for ln in lines:
        ln = ln.strip()
        if ln and not ln.startswith("#"):
            out.append(ln.split()[0])
    return out


def select_listed(inventory, tiles):
    """Inventory names for the listed tiles, and the listed tiles that
    have none (ocean, or a name that is not a tile)."""
    by_ll = {}
    for name in inventory:
        ll = tile_latlon(name)
        if ll is not None:
            by_ll[ll] = name
    wanted, absent, seen = [], [], set()
    for t in tiles:
        key = short_latlon(t) or t
        if key in seen:
            continue
        seen.add(key)
        name = by_ll.get(key)
        if name is None:
            absent.append(t)
        else:
            wanted.append(name)
    return wanted, absent


def select_bbox(inventory, min_lat, max_lat, min_lon, max_lon):
    """Inventory names whose SW corner is in the inclusive box."""
    wanted = []
    for name in inventory:
        ll = tile_latlon(name)
        if ll is None:
            continue
        lat, lon = ll
        if min_lat <= lat <= max_lat and min_lon <= lon <= max_lon:
            wanted.append(name)
    return wanted


def load_tile_list(dest):
    """Download (or reuse) the bucket's tile inventory."""
    cache = os.path.join(dest, "tileList.txt")
    if not os.path.exists(cache):
        print("fetching tile inventory ...")
        urllib.request.urlretrieve(f"{BUCKET}/tileList.txt", cache)
    with open(cache) as f:
        return [ln.strip() for ln in f if ln.strip()]


def fetch_one(name, dest):
    """Download one tile. Returns (name, bytes, skipped)."""
    out = os.path.join(dest, f"{name}.tif")
    if os.path.exists(out) and os.path.getsize(out) > 0:
        return name, os.path.getsize(out), True
    url = f"{BUCKET}/{name}/{name}.tif"
    part = out + ".part"
    try:
        with urllib.request.urlopen(url, timeout=120) as r, \
                open(part, "wb") as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
        os.replace(part, out)
        return name, os.path.getsize(out), False
    except Exception:
        if os.path.exists(part):
            os.remove(part)
        raise


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--dest", required=True)
    ap.add_argument("--tiles", nargs="+", metavar="TILE",
                    help="specific tiles e.g. N60W136")
    ap.add_argument("--tiles-file", metavar="PATH",
                    help="file of tiles, one per line ('-' for stdin)")
    for b in BBOX:
        ap.add_argument(f"--{b.replace('_', '-')}", dest=b, type=int)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    box = [getattr(args, b) for b in BBOX]
    by_list = args.tiles is not None or args.tiles_file is not None
    if by_list and any(v is not None for v in box):
        ap.error("pick tiles by list or by bounding box, not both")
    if not by_list and any(v is None for v in box):
        ap.error("give --tiles-file/--tiles, or all of --min-lat "
                 "--max-lat --min-lon --max-lon (there is no default)")

    os.makedirs(args.dest, exist_ok=True)
    inventory = load_tile_list(args.dest)
    if by_list:
        listed = list(args.tiles or [])
        if args.tiles_file == "-":
            listed += read_tile_names(sys.stdin)
        elif args.tiles_file:
            with open(args.tiles_file) as f:
                listed += read_tile_names(f)
        wanted, absent = select_listed(inventory, listed)
        for t in absent:
            print(f"  no GLO-30 tile for {t} (ocean, or a bad name)")
        what = (f"{len(wanted)} of {len(wanted) + len(absent)} "
                f"listed tiles exist")
    else:
        wanted = select_bbox(inventory, *box)
        what = (f"{len(wanted)} tiles in bbox "
                f"[{box[0]}..{box[1]}] x [{box[2]}..{box[3]}]")
    have = sum(1 for n in wanted
               if os.path.exists(os.path.join(args.dest, n + ".tif")))
    print(f"{what}; {have} already present")
    if args.dry_run:
        return

    done = have
    failed = []
    todo = [n for n in wanted
            if not os.path.exists(os.path.join(args.dest, n + ".tif"))]
    total_bytes = 0
    with concurrent.futures.ThreadPoolExecutor(args.workers) as pool:
        futs = {pool.submit(fetch_one, n, args.dest): n for n in todo}
        for fut in concurrent.futures.as_completed(futs):
            name = futs[fut]
            try:
                _, size, _ = fut.result()
                total_bytes += size
                done += 1
                if done % 25 == 0:
                    print(f"  {done}/{len(wanted)} "
                          f"({total_bytes / 1e9:.1f} GB this run)",
                          flush=True)
            except Exception as e:
                failed.append(name)
                print(f"  FAILED {name}: {e}", flush=True)
    print(f"complete: {done}/{len(wanted)} tiles, "
          f"{total_bytes / 1e9:.1f} GB downloaded this run, "
          f"{len(failed)} failures")
    if failed:
        print("re-run to retry the failures (existing files are skipped)")
        sys.exit(1)


if __name__ == "__main__":
    main()
