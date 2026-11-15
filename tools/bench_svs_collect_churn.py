#!/usr/bin/env python3
"""AER-678: measure SVS collector cache-key churn under a synthetic 20 Hz
moving-position drive, isolated to the collector layer -- no GL context, no
fixgw, no running pyefis process required.

The issue's own diagnosis is that the render thread is starved, not
overloaded: frame.svs_total stays ~6 ms while frame.gap_between_svs
collapses under motion. The mechanism is GIL contention -- when the shared
cache key churns every sample (because the position-quantization step is
itself derived from a chattering auto-range reading), every one of the
eight collectors kicks a fresh background worker thread every frame
instead of serving a cached hit, and those workers' GIL-held bursts
compete with whatever thread is timing the "frame" for CPU slices.

This tool drives the exact same _collect_* call sequence
SVSRenderer._render_overlays uses, over a real track at a real ground
speed, sampling real on-bench SRTM/water/highway/obstacle/airport data,
and reports the wall-clock gap between successive drive steps -- the
same signal frame.gap_between_svs captures in the live GL renderer, one
layer down. Compare before/after a working-tree change with two runs.
"""
import argparse
import math
import statistics
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pyefis.instruments.ai.svs import SVSRenderer  # noqa: E402

DEFAULT_DATA = dict(
    tile_path="/data/makerplane-data/terrain/tiles",
    water_db_path="/data/makerplane-data/water/current/water.sqlite",
    nasr_db_path="/data/makerplane-data/navdata/current/airports.sqlite",
    dof_db_path="/data/makerplane-data/obstacles/current/obstacles.sqlite",
    highway_db_path="/data/makerplane-data/highways/current/highways.sqlite",
)

# A stub glyph atlas so the flags/markings collectors' text-layout code
# runs for real instead of short-circuiting on "no atlas".
_ATLAS_UVS = {c: (0.0, 0.0, 1.0, 1.0)
              for c in "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"}


def percentile(values, pct):
    if not values:
        return float("nan")
    values = sorted(values)
    k = (len(values) - 1) * (pct / 100.0)
    f, c = math.floor(k), math.ceil(k)
    if f == c:
        return values[int(k)]
    return values[f] + (values[c] - values[f]) * (k - f)


def drive(lat0, lon0, alt_ft, heading_deg, speed_kt, hz, duration_s, ppd,
         boundary_nm=None, jitter_ft=0.0, jitter_hz=0.5):
    cfg = dict(DEFAULT_DATA, enabled=True)
    r = SVSRenderer(cfg)
    if not r.ready:
        raise SystemExit(f"SVS not ready -- check DATA paths: {cfg}")

    if boundary_nm is not None:
        # Auto-range hovering near a 5 NM bucket edge is the reported
        # anomaly (issue text: "a range hovering near a boundary
        # invalidates all eight caches"). Centre alt_ft so the RAW
        # horizon_range sits on a boundary (edges at 2.5, 7.5, 12.5,
        # ... NM), then oscillate a small amount around it -- the same
        # order of magnitude as ADC/altimeter noise, not a real climb.
        ground_m, _ = r._sample_elevations(
            np.array([[lat0]]), np.array([[lon0]]))
        ground_ft = float(ground_m[0, 0]) * 3.28084
        target_agl_ft = (boundary_nm / 1.22) ** 2
        alt_ft = ground_ft + target_agl_ft

    dt = 1.0 / hz
    n_samples = int(duration_s * hz)
    nm_per_s = speed_kt / 3600.0
    dlat_per_s = nm_per_s / 60.0 * math.cos(math.radians(heading_deg))
    dlon_per_s = (nm_per_s / 60.0 * math.sin(math.radians(heading_deg))
                  / math.cos(math.radians(lat0)))

    gaps_ms = []
    range_keys = set()
    collect_keys = set()
    last = None
    t0 = time.perf_counter()
    for i in range(n_samples):
        t = i * dt
        lat = lat0 + dlat_per_s * t
        lon = lon0 + dlon_per_s * t
        alt = alt_ft + jitter_ft * math.sin(2.0 * math.pi * jitter_hz * t)

        now = time.perf_counter()
        if last is not None:
            gaps_ms.append((now - last) * 1000.0)
        last = now

        range_nm = r._auto_range_nm(lat, lon, alt)
        if hasattr(r, "_collect_key"):
            # _auto_range_nm returns the RAW, continuously-varying
            # rendered extent (AER-678 review) -- it is _collect_range_nm,
            # the hysteresis bucket _auto_range_nm stashes as a side
            # effect, that actually feeds every collector's cache key.
            # Measure that, not the raw return value, or this tool would
            # report the fixed build as if it still churned.
            key_range_nm = r._collect_range_nm
            range_keys.add(key_range_nm)
            collect_keys.add(r._collect_key(lat, lon, key_range_nm))
        else:
            # Pre-fix idiom (AER-678), inlined so this same script can
            # measure the "before" side without the shared helper.
            range_keys.add(range_nm)
            step = max(0.01, range_nm / 2000.0)
            collect_keys.add((round(lat / step) * step,
                              round(lon / step) * step,
                              round(range_nm / 5.0) * 5.0))
        r._collect_water_triangles(lat, lon, range_nm)
        hwy = r._collect_highways(lat, lon, alt, range_nm, ppd)
        r._collect_obstacles(lat, lon, alt, range_nm, _ATLAS_UVS)
        r._collect_runway_polygons(lat, lon, alt, range_nm, heading_deg)
        r._collect_runway_markings(lat, lon, alt, range_nm, heading_deg)
        r._collect_airport_flags(lat, lon, alt, range_nm, ppd, _ATLAS_UVS)

        target = t0 + (i + 1) * dt
        sleep_for = target - time.perf_counter()
        if sleep_for > 0:
            time.sleep(sleep_for)

    return {
        "n_samples": n_samples,
        "gaps_ms": gaps_ms,
        "n_distinct_range_buckets": len(range_keys),
        "n_distinct_collect_keys": len(collect_keys),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--lat", type=float, default=34.4275)
    ap.add_argument("--lon", type=float, default=-119.8546)
    ap.add_argument("--alt-ft", type=float, default=2500.0)
    ap.add_argument("--heading-deg", type=float, default=87.0)
    ap.add_argument("--speed-kt", type=float, default=130.0)
    ap.add_argument("--hz", type=float, default=20.0)
    ap.add_argument("--duration-s", type=float, default=60.0)
    ap.add_argument("--ppd", type=float, default=1_000_000.0)
    ap.add_argument("--boundary-nm", type=float, default=None,
                    help="Centre alt_ft so raw auto-range sits on this "
                         "5 NM bucket edge (e.g. 22.5), overriding --alt-ft.")
    ap.add_argument("--jitter-ft", type=float, default=0.0,
                    help="Sinusoidal AGL jitter amplitude around alt_ft "
                         "(or the boundary altitude), simulating "
                         "altimeter/demo-animation noise.")
    ap.add_argument("--jitter-hz", type=float, default=0.5)
    args = ap.parse_args()

    result = drive(args.lat, args.lon, args.alt_ft, args.heading_deg,
                   args.speed_kt, args.hz, args.duration_s, args.ppd,
                   boundary_nm=args.boundary_nm, jitter_ft=args.jitter_ft,
                   jitter_hz=args.jitter_hz)
    gaps = result["gaps_ms"]
    expected_ms = 1000.0 / args.hz
    print(f"samples={result['n_samples']} "
          f"distinct_range_buckets={result['n_distinct_range_buckets']} "
          f"distinct_collect_keys={result['n_distinct_collect_keys']}")
    print(f"drive-step gap ms (target {expected_ms:.1f} ms): "
          f"p50={percentile(gaps, 50):.2f} "
          f"p90={percentile(gaps, 90):.2f} "
          f"p99={percentile(gaps, 99):.2f} "
          f"max={max(gaps):.2f} "
          f"mean={statistics.mean(gaps):.2f}")


if __name__ == "__main__":
    main()
