#!/usr/bin/env python3
"""Export SVS preview terrain patches for the configurator editor.

The configurator (makerplane-data, pyefis.aerocommons.org) previews the
virtual_vfr / SVS instrument with a data-driven static frame rendered on a
<canvas> — real terrain, real runways, the real clearance/palette model —
instead of a fixed captured image. GL can't run in the Worker or be assumed
in the browser, so the editor ships a small JS port of the clearance model
(svs.py/svs_gl.py) and this tool supplies its data: one JSON "patch" per
preview scene containing a two-tier elevation grid (fine near the camera,
coarse to the far range) plus the NASR runways in view.

Scene poses defined here are the single source of truth — the Pi reference
captures (fallback webp + fidelity A/B frames) are taken at these exact
poses via tests/visual_svs_test.py.

Usage (Windows dev box with local SRTM3 + NASR data):
    python tools/export_svs_preview_patch.py [--out DIR] [--scene NAME]
        [--srtm D:/EarthData/srtm3] [--nasr nasr/airports.sqlite]

Output: <out>/<scene>.json, upload to R2 at assets/editor/svs/<scene>.json.
"""

import argparse
import json
import math
import os
import sqlite3
import sys

import numpy as np

SRTM3_SAMPLES = 1201
SRTM3_VOID = -32768
WATER_SENTINEL = -9999          # matches svs.py _WATER_SENTINEL

# Preview scenes. alt_ft is MSL; head true. range_nm bounds the exported
# (and rendered) far field. near-airport state is resolved at export time
# so the browser needs no airport database.
SCENES = {
    # Santa Barbara coast looking north at the Santa Ynez ridge -- the
    # original coastal capture pose.
    "coastal": {
        "lat": 34.4275, "lon": -119.8546, "alt_ft": 2500.0, "head": 0.0,
        "range_nm": 15.0, "water_from_elev": True,
    },
    # Elk Mountains south of Aspen -- the documented polar-LOD A/B view.
    "mountains": {
        "lat": 39.20, "lon": -106.85, "alt_ft": 12500.0, "head": 150.0,
        "range_nm": 15.0, "water_from_elev": False,
    },
    # Telluride: ~3 nm final RWY 9 over the San Miguel valley.
    "approach": {
        "lat": 37.96933, "lon": -107.98168, "alt_ft": 10500.0, "head": 105.0,
        "range_nm": 15.0, "water_from_elev": False,
    },
    # KSBA: 1 nm final RWY 7 at 600 ft AGL (field elev 11 ft).
    "final": {
        "lat": 34.42721, "lon": -119.87481, "alt_ft": 611.0, "head": 89.0,
        "range_nm": 15.0, "water_from_elev": True,
    },
}

COARSE_STEP = 4   # SRTM3 samples per coarse grid step (4/1200 deg ~ 370 m)
FINE_STEP = 1     # full SRTM3 resolution (~92 m)
FINE_RADIUS_NM = 2.5
BACK_MARGIN_NM = 1.5
AIRPORT_PROXIMITY_NM = 5.0      # svs.py airport_proximity_nm default


class TileSampler:
    """Nearest-sample elevation lookup across SRTM3 tiles (<dir>/N34/N34W120.hgt)."""

    def __init__(self, root):
        self.root = root
        self.tiles = {}

    def _tile(self, lat_i, lon_i):
        key = (lat_i, lon_i)
        if key not in self.tiles:
            ns = ("N%02d" % lat_i) if lat_i >= 0 else ("S%02d" % -lat_i)
            ew = ("W%03d" % -lon_i) if lon_i < 0 else ("E%03d" % lon_i)
            path = os.path.join(self.root, ns, ns + ew + ".hgt")
            if not os.path.exists(path):
                raise FileNotFoundError(path)
            self.tiles[key] = np.fromfile(path, dtype=">i2").reshape(
                SRTM3_SAMPLES, SRTM3_SAMPLES)
        return self.tiles[key]

    def grid(self, lats, lons):
        """Sample a rectilinear grid; returns int16 array (len(lats), len(lons))."""
        out = np.empty((len(lats), len(lons)), dtype=np.int16)
        for i, lat in enumerate(lats):
            lat_i = int(math.floor(lat))
            t_row = None
            for j, lon in enumerate(lons):
                lon_i = int(math.floor(lon))
                tile = self._tile(lat_i, lon_i)
                r = int(round((lat_i + 1 - lat) * 1200))
                c = int(round((lon - lon_i) * 1200))
                r = min(max(r, 0), SRTM3_SAMPLES - 1)
                c = min(max(c, 0), SRTM3_SAMPLES - 1)
                out[i, j] = tile[r, c]
        return out


def _ocean_mask(elev):
    """Flood-fill sea-level cells (elev <= 0) from the patch border: open
    ocean reaches the border, inland zero-elevation flats (sloughs, dry
    lakes) do not -- matching what the device's water DB paints blue."""
    from collections import deque
    sea = elev <= 0
    ny, nx = elev.shape
    mask = np.zeros(elev.shape, dtype=bool)
    dq = deque()
    for i in range(ny):
        for j in (0, nx - 1):
            if sea[i, j] and not mask[i, j]:
                mask[i, j] = True; dq.append((i, j))
    for j in range(nx):
        for i in (0, ny - 1):
            if sea[i, j] and not mask[i, j]:
                mask[i, j] = True; dq.append((i, j))
    while dq:
        i, j = dq.popleft()
        for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            a, b = i + di, j + dj
            if 0 <= a < ny and 0 <= b < nx and sea[a, b] and not mask[a, b]:
                mask[a, b] = True; dq.append((a, b))
    return mask


def _tier(sampler, lat_top, lat_bot, lon_w, lon_e, step_samples,
          water_from_elev=False):
    step = step_samples / 1200.0
    lats = np.arange(lat_top, lat_bot - step / 2, -step)
    lons = np.arange(lon_w, lon_e + step / 2, step)
    elev = sampler.grid(lats, lons).astype(int)
    if water_from_elev:
        elev[_ocean_mask(elev)] = WATER_SENTINEL
    elev[elev == SRTM3_VOID] = WATER_SENTINEL
    return {
        "lat_top": round(float(lats[0]), 6), "lon_w": round(float(lons[0]), 6),
        "dlat": round(step, 8), "dlon": round(step, 8),
        "ny": len(lats), "nx": len(lons),
        "elev_m": [[int(v) for v in row] for row in elev.tolist()],
    }


def _runways(nasr, lat0, lat1, lon0, lon1):
    """All NASR runways whose ends fall inside the box, grouped per airport."""
    db = sqlite3.connect(nasr)
    cur = db.cursor()
    cur.execute(
        "SELECT site_no, icao, name, lat, lon, elev_ft FROM airports "
        "WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?",
        (min(lat0, lat1), max(lat0, lat1), min(lon0, lon1), max(lon0, lon1)))
    airports = cur.fetchall()
    runways, apts = [], []
    for site, icao, name, alat, alon, aelev in airports:
        cur.execute(
            "SELECT r.rwy_id, r.width_ft, e.end_id, e.lat, e.lon, e.elev_ft "
            "FROM runways r JOIN runway_ends e "
            "ON r.site_no = e.site_no AND r.rwy_id = e.rwy_id "
            "WHERE r.site_no = ? ORDER BY r.rwy_id, e.end_id", (site,))
        ends = {}
        widths = {}
        for rwy_id, w_ft, end_id, elat, elon, eelev in cur.fetchall():
            if elat is None or elon is None:
                continue
            ends.setdefault(rwy_id, []).append(
                [round(elat, 7), round(elon, 7), round(eelev or aelev, 1)])
            widths[rwy_id] = w_ft or 75
        got = False
        for rwy_id, pair in ends.items():
            if len(pair) == 2:
                runways.append({"id": rwy_id, "icao": icao,
                                "w_ft": widths[rwy_id], "ends": pair})
                got = True
        if got:
            apts.append({"icao": icao, "lat": alat, "lon": alon,
                         "elev_ft": round(aelev, 1)})
    db.close()
    return runways, apts


def export_scene(name, cfg, srtm, nasr, out_dir):
    sampler = TileSampler(srtm)
    lat, lon, head = cfg["lat"], cfg["lon"], cfg["head"]
    rng = cfg["range_nm"]
    m_lat = 110574.0
    m_lon = 111320.0 * math.cos(math.radians(lat))
    # Axis-aligned box around the forward fan (+/-70 deg of heading) with a
    # small margin behind the camera.
    pts = [(0.0, 0.0)]
    for az in range(-70, 71, 5):
        a = math.radians(head + az)
        pts.append((rng * 1852 * math.sin(a), rng * 1852 * math.cos(a)))
    back = BACK_MARGIN_NM * 1852
    e0 = min(p[0] for p in pts) - back; e1 = max(p[0] for p in pts) + back
    n0 = min(p[1] for p in pts) - back; n1 = max(p[1] for p in pts) + back
    lat_bot, lat_top = lat + n0 / m_lat, lat + n1 / m_lat
    lon_w, lon_e = lon + e0 / m_lon, lon + e1 / m_lon
    wfe = bool(cfg.get("water_from_elev"))
    coarse = _tier(sampler, lat_top, lat_bot, lon_w, lon_e, COARSE_STEP,
                   water_from_elev=wfe)
    fr = FINE_RADIUS_NM * 1852
    fine = _tier(sampler,
                 lat + fr / m_lat, lat - fr / m_lat,
                 lon - fr / m_lon, lon + fr / m_lon, FINE_STEP,
                 water_from_elev=wfe)
    runways, airports = _runways(nasr, lat_bot, lat_top, lon_w, lon_e)
    # Near-airport state (svs_gl proximity collapse), resolved at export time.
    near, field_elev = False, None
    best = AIRPORT_PROXIMITY_NM * 1852
    for a in airports:
        d = math.hypot((a["lat"] - lat) * m_lat, (a["lon"] - lon) * m_lon)
        if d <= best:
            best, near, field_elev = d, True, a["elev_ft"]
    patch = {
        "meta": {
            "scene": name, "version": 1,
            "cam": {"lat": lat, "lon": lon, "alt_ft": cfg["alt_ft"],
                    "head": head},
            "range_nm": rng,
            "near_airport": near, "field_elev_ft": field_elev,
            "water_from_elev": bool(cfg.get("water_from_elev")),
            "fine_radius_nm": FINE_RADIUS_NM,
        },
        "tiers": [coarse, fine],   # painter draws coarse first, fine over it
        "runways": runways,
        "airports": airports,
    }
    path = os.path.join(out_dir, name + ".json")
    with open(path, "w") as f:
        json.dump(patch, f, separators=(",", ":"))
    print("%s: %dx%d coarse + %dx%d fine, %d runways, %d airports, %d KB"
          % (name, coarse["nx"], coarse["ny"], fine["nx"], fine["ny"],
             len(runways), len(airports), os.path.getsize(path) // 1024))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="work/svs_patches")
    ap.add_argument("--scene", default=None, help="one scene (default: all)")
    ap.add_argument("--srtm", default="D:/EarthData/srtm3")
    ap.add_argument("--nasr", default=os.path.join(
        os.path.dirname(__file__), "..", "nasr", "airports.sqlite"))
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    names = [args.scene] if args.scene else list(SCENES)
    for name in names:
        export_scene(name, SCENES[name], args.srtm, args.nasr, args.out)


if __name__ == "__main__":
    sys.exit(main())
