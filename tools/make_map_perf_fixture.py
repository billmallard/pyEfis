#!/usr/bin/env python3
#  SPDX-License-Identifier: GPL-2.0-or-later
"""Cut a small geographic-window perf fixture pack out of the real
moving-map data packs (MP8b, briefs/map_gesture_perf_plan.md's MP8 item;
pyEfis #98, AER-1133; reworked per AER-1140's ruling, AER-1142).

MP8a (AER-1121, pyEfis #207) landed the count-based moving-map perf
budgets in ``tests/perf/test_map_gestures.py`` -- pipeline properties
(renders per pinch, paints per sweep, QPointF count) that need no real
data and run in CI with the Qt ``offscreen`` platform. What that file
explicitly deferred is a **volume** budget: how much real water/terrain/
road geometry a real scene holds at 160 NM. A synthetic fixture answers
a different question and would pass at any threshold -- MP8b's job is
the fixture that makes that budget meaningful.

This tool cuts a window out of the FULL real packs (terrain mip pyramid,
terrain mosaic, ``water.sqlite``, a highway db, a navaid db) that the
data-manager pipeline builds and pyEfis reads at runtime -- it does not
build those packs itself (see ``tools/build_terrain_mips.py``,
``build_terrain_mosaic.py``, ``build_water_db.py``, ``build_highway_db.py``,
``build_navaid_db.py`` for that). Output is a directory with the exact
on-disk layout the runtime readers expect (``TileCache.get_mip``/
``get_mosaic`` in ``src/pyefis/instruments/ai/svs.py``, ``WaterDB`` in
``water_db.py``, ``HighwayDB`` in ``highway_db.py``, the navaid layers in
``src/pyefis/instruments/map/layers/navaids.py``), verified against those
same reader classes in ``tests/tools/test_make_map_perf_fixture.py`` --
not merely produced by inspection of their schemas.

Two scenes (brief's Track 4 MP8 item), both dense, both real perf traps:

    raleigh    35.8, -78.8    the brief's own reference scene
    key_west   24.55, -81.78  dense multi-ring coastline (the 08-13
                               stutter scene; the #44 island-hole case)

**AER-1140's ruling, and what changed here (AER-1142).** QA cut against the
real production tiles and found the original cutter could produce neither
scene: a 3x3 native-tile grid (the whole-degree window the old
``WINDOW_DEG = 2.0`` expanded to) is 233.4 MB against a 209.7 MB cap on its
own, and that same 2-degree window captured only 14% of Raleigh's water
vertices at 160 NM -- so a volume budget asserted against it would pass
with a real rasterizer regression hiding underneath. Elon's ruling on
AER-1140 (read it before touching this file again) made four changes,
none of which is "shrink the window" or "raise the cap":

1. **The cap gates the packaged tarball, not the raw directory.**
   ``MAX_PACK_BYTES`` traces to CI fetch time -- the compressed download --
   not to the uncompressed bytes on disk. ``cut_scene`` no longer raises on
   raw size; ``package_scene`` raises on the tarball's size. Raw size is
   still recorded (``stats["raw_bytes"]``) as an advisory stat.
2. **Terrain is cut concentrically by mip level, not as one uniform grid.**
   ``TerrainLayer._render`` (``src/pyefis/instruments/map/layers/
   terrain.py:290-308``) picks a mip level from ``round(log2(mpp /
   native))``, and ``mpp`` is *linear in range_nm* for a fixed widget
   geometry -- so each level owns a closed, non-overlapping range band, and
   a cell far from the scene centre is NEVER sampled at native or a shallow
   mip. Copying it there is dead weight, not margin. ``terrain_level_bands``
   below derives each level's own reach (the half-diagonal at the TOP of
   its band) by literally calling the same mip-selection formula the
   renderer uses, not by transcribing a hand-computed table -- the ruling's
   own instruction: "derive the radii in code from the selector, the table
   is the instance, the selector is the rule."
3. **Water/highway/navaid/fixes footprints are derived per-layer, not one
   shared ``WINDOW_DEG``.** Each vector layer decides its own query extent
   at its own widest asserted range (water and highway from the same
   half-diagonal geometry terrain uses; navaid/airway/fixes from
   ``navaids.py``'s own ``_bbox`` formula) -- see ``cut_scene``.
4. **The anti-vacuity test.** ``WINDOW_DEG = 2.0`` shipped with a comment
   that correctly predicted under-coverage and no test to catch it, which
   is exactly why it shipped anyway. ``tests/tools/
   test_make_map_perf_fixture.py`` carries a test that fails against that
   old literal-window behaviour and passes against the derivation here.

**AER-1143's amendment (a second QA finding, same heartbeat as the ruling
above).** Two things change what this module builds; the four changes
above are unaffected:

5. **The footprint is a function of the WIDGET, not of the scene.** A
   square 300x300 render reads FURTHER than a 650x1040 one at the same
   ``range_nm`` (``0.5*hypot(w,h)/cy`` with ``cy = h*(1-anchor)`` --
   the square geometry's ratio is larger), so "the window" is only
   well-defined once a widget geometry is picked, and picking the wrong
   one (or transcribing someone else's number) under-covers silently.
   ``PERF_WIDGET_ENVELOPES`` below lists every widget geometry actually
   asserted against this pack across the perf suite; every per-layer
   footprint is the WIDEST radius across that whole list at the range it
   is asserted at, derived in code, never a single hard-coded widget.
6. **The pack declares its own footprint; a consumer compares rather
   than re-derives.** ``cut_scene`` writes ``footprint.json`` into the
   output directory: per vector layer, the cut bbox and the
   ``(w, h, ownship_position, range_nm)`` envelope it was derived from.
   Two independent implementations of one geometric rule (the cutter's
   and a consumer test's) is exactly how ``WINDOW_DEG = 2.0`` drifted
   from the layers it was meant to cover -- the fix is not a better
   derivation on either side, it is one derivation, declared, and a
   "required subset-of declared" comparison on the consumer's side. A
   consumer MAY keep its own independent computation too, as a
   cross-check that fires loudly on mismatch -- that is what would catch
   the producer (this file) being wrong, which a pure subset check on a
   self-reported number cannot.

Cutting and publishing the ACTUAL packs (the real production terrain/
water/highway/navaid trees) is out of scope for this file -- AVIONICS-DATA
owns that (AER-1134). This tool is what they run.

Usage, cutting from a real pack tree on a workstation that holds it
(never on the EFIS device -- same rule as the builder tools)::

    python tools/make_map_perf_fixture.py cut --scene raleigh \\
        --tile-root /data/makerplane-data/terrain/tiles \\
        --water-db  /data/makerplane-data/water/current/water.sqlite \\
        --highway-db /data/makerplane-data/highways/current/highway.sqlite \\
        --navaid-db  /data/makerplane-data/navaids/current/navaids.sqlite \\
        --out dist/perf-fixtures/raleigh

Add ``--publish`` to additionally push the packaged tarball to R2 under
``test-fixtures/<scene>/`` (mirrors the existing wrangler convention in
``.github/workflows/editor-assets.yml``: it skips cleanly with a warning,
exit 0, when ``CLOUDFLARE_API_TOKEN``/``CLOUDFLARE_ACCOUNT_ID`` are unset
rather than failing a CI run that has no secrets). A successful publish
also rewrites this scene's entry in ``tools/perf_fixtures.json`` -- the
checked-in, sha256-pinned manifest ``fetch_fixture`` reads.

On-demand fetch side (what a perf test in ``tests/perf/`` calls)::

    from tools.make_map_perf_fixture import fetch_fixture
    path = fetch_fixture("raleigh")   # None if PYEFIS_PERF_FIXTURE unset

``fetch_fixture`` never touches the network unless ``PYEFIS_PERF_FIXTURE``
is truthy (CI sets it; a bare local ``pytest`` run must skip cleanly, not
fail) and never adds a runtime dependency -- download/verify/extract are
stdlib (``urllib``, ``hashlib``, ``tarfile``).

**Honest limitation, current as of AER-1142.** The ``sha256``/``url``
fields in ``tools/perf_fixtures.json`` start ``null`` for both scenes.
Producing the real packs requires (a) access to the full production
terrain/water/highway/navaid packs, which live in the data-manager
pipeline's storage, not in a pyEfis checkout, and (b) R2 write
credentials. Neither is available in the sandbox this rework was authored
in either -- the concentric-cut/per-layer-footprint math below is
exercised against synthetic packs in the test suite, the same way MP8a's
count budgets are, but the **measured** tarball ratio against the real
packs (the number that decides whether 200 MB actually holds) still needs
AVIONICS-DATA's access (AER-1134). Whoever runs ``cut --publish`` against
the real packs fills the manifest in; until then ``fetch_fixture`` raises
a clear, actionable ``PerfFixtureUnavailable`` rather than silently
returning nothing or fabricating a pin.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import sqlite3
import sys
import tarfile
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_TOOLS_DIR = _ROOT / "tools"
MANIFEST_PATH = _TOOLS_DIR / "perf_fixtures.json"

#: The brief's Track 4 MP8 scenes. lat/lon is the window centre; a real
#: full-pack tile root/water/highway/navaid db must be supplied on the
#: command line -- this dict only pins scene identity and pose, the way
#: ``export_svs_preview_patch.py``'s ``SCENES`` pins configurator poses.
SCENES = {
    "raleigh": {"lat": 35.8, "lon": -78.8},
    "key_west": {"lat": 24.55, "lon": -81.78},
}

MIP_LEVELS = (1, 2, 3, 4, 5, 6)          # matches build_terrain_mips.MAX_LEVEL
MOSAIC_LEVELS = (4, 5, 6)                # matches build_terrain_mosaic default

#: Traces to CI fetch time, not to physics (AER-1140's ruling) -- fetch
#: time is a property of the COMPRESSED tarball a CI job downloads, so
#: this is checked against ``package_scene``'s tarball bytes, not the raw
#: cut directory (see MAX_PACK_BYTES's use below). A scene over this is a
#: real problem to escalate, not a window to quietly shrink.
MAX_PACK_BYTES = 200 * 1024 * 1024

SRTM3_VOID = -32768

#: camera.py's own constant (``M_PER_DEG_LAT``), duplicated for the same
#: Qt-free reason WATER_SCHEMA/tile_name below are duplicated rather than
#: imported: this tool must stay usable with no Qt/PyQt6 installed.
M_PER_DEG_LAT = 111139.0

# ---------------------------------------------------------------------------
# Per-layer footprint derivation (AER-1142, per AER-1140's ruling).
#
# Every footprint below is derived from the SAME formula the runtime layer
# itself uses to decide what it reads at a given range -- never a literal
# window copied from a table. ``WINDOW_DEG = 2.0`` shipped with a comment
# that correctly predicted under-inclusion and no test to catch it; this
# section is both the fix and the reason a future editor should derive,
# not transcribe.
# ---------------------------------------------------------------------------

#: A single default geometry for the low-level, single-widget helpers
#: below (``_terrain_render_geometry`` and everything built directly on
#: it) -- convenient for ad hoc/test calls, but NOT what the cutter uses
#: to size a real cut. AER-1143's amendment: the footprint is a function
#: of the WIDGET, and this module must derive for the widest widget any
#: budget asserts against, not transcribe one. See
#: ``PERF_WIDGET_ENVELOPES`` immediately below for that list.
PERF_WIDGET_W = PERF_WIDGET_H = 300
#: MapWidget.ownship_position's own default (map/__init__.py) -- 50%
#: up from the bottom edge, i.e. screen-centred.
PERF_OWNSHIP_ANCHOR_FRAC = 0.50

#: Every ``(w, h, ownship_anchor_frac)`` widget geometry a REAL,
#: pack-dependent perf assertion is known to run against, across the
#: whole perf suite -- not just "the" perf widget. AER-1143's amendment
#: to the AER-1140 ruling: "the footprint is derived from (w, h,
#: ownship_position, range_nm, lat), and must be cut for the widest such
#: tuple any budget asserts at, across every widget geometry in the
#: suite. Not from a scene, and not from either table."
#:
#: A square widget reads FURTHER than a portrait one at the same
#: ``range_nm`` -- the ratio that matters is ``hypot(w, h) / cy`` with
#: ``cy = h * (1 - anchor)``, and that ratio is 2.83 for 300x300 against
#: 2.36 for 650x1040 -- a constant multiplier independent of range_nm
#: (``_terrain_render_geometry`` is linear in range for fixed geometry),
#: so 300x300 is the wider candidate at every range these two are
#: compared at, not merely at 160 NM.
#:
#:   - (300, 300, 0.50): ``tests/perf/test_map_gestures.py``'s MP8a
#:     count-budget widget (``_W = _H = 300``). Its own budgets are
#:     synthetic-data-only today (no real pack), but it is still a
#:     widget geometry a future pack-dependent assertion could run
#:     against, and it happens to be the wider of the two below.
#:   - (650, 1040, 0.50): ``tests/perf/test_map_pack_budgets.py``'s
#:     ``measure.SCENE_W``/``SCENE_H`` -- the actual widget the real,
#:     pack-dependent volume/timing rows (MP8b-2, AER-1135) run against.
#:
#: Adding a THIRD geometry that some future real-pack budget asserts
#: against means adding it HERE, not editing the derivation math below --
#: the whole point of deriving from a list rather than one constant.
PERF_WIDGET_ENVELOPES = (
    (300, 300, 0.50),
    (650, 1040, 0.50),
)

#: map/__init__.py's own ``range_ladder`` default
#: (``"2,5,10,20,40,80,160"``) -- the top is the widest range any budget
#: can assert at; nothing wider is reachable and nothing narrower needs
#: covering.
RANGE_LADDER_TOP_NM = 160.0
#: roads.py RoadsLayer._BAND_BASE's own coarsest band -- above this the
#: roads layer is hidden and never queried at all.
HIGHWAY_MAX_RANGE_NM = 80.0
#: navaids.py NavaidsLayer/AirwaysLayer._MAX_RANGE.
NAVAID_MAX_RANGE_NM = 160.0
#: navaids.py FixesLayer._MAX_RANGE (fixes are range-gated -- ~70k of them
#: nationwide need it to stay usable).
FIXES_MAX_RANGE_NM = 20.0
#: navaids.py _DbLayer._bbox's own literal box half-width factor and
#: cos(lat) floor (the floor avoids a division blow-up near the poles;
#: irrelevant at these scenes' latitudes but kept for fidelity).
NAVAID_BBOX_NM_TO_DEG = 2.2 / 60.0
NAVAID_COS_LAT_FLOOR = 0.2

#: bench_map_gestures.py's own scenario_pan parameters (3 s at 60 Hz, 3 px
#: per event) -- the pan excursion the native (level-0) footprint must
#: survive without walking the render centre out of the cut cell(s) and
#: making TileCache.get() return None (which silently falls back the mip
#: selector's `native` pitch to 1200, per terrain.py:306-308).
_PAN_EVENTS = 180
_PAN_PX_PER_EVENT = 3.0
#: A native/level-0 footprint wider than this (2x2 whole-degree cells) is
#: no longer "one native tile plus pan margin" -- a 3x3 ring alone is
#: 233 MB and busts the cap on its own (AER-1140's ruling). Past this the
#: cutter raises rather than silently grow the native ring.
MAX_NATIVE_CELLS = 4


def _terrain_render_geometry(range_nm: float, w: int = PERF_WIDGET_W,
                              h: int = PERF_WIDGET_H,
                              anchor_frac: float = PERF_OWNSHIP_ANCHOR_FRAC):
    """Mirror ``TerrainLayer._render``'s own window-sizing math EXACTLY
    (``terrain.py:292-297``) -- ``half_diag_m`` (half-diagonal of the
    oversized, track-up-safe window, in metres) and ``mpp`` (metres per
    image pixel). Every footprint derived below goes through this one
    function, so a change to the renderer's sizing constants (the 1.25
    oversize factor, the pixel-count clamp) is inherited automatically
    instead of drifting out of sync with a hand-copied formula."""
    cy = max(1.0, h * (1.0 - anchor_frac))
    px_per_m = cy / max(1.0, range_nm * 1852.0)
    half_diag_m = 0.5 * math.hypot(w, h) / px_per_m * 1.25
    n = int(min(1024, max(64, 2 * half_diag_m * px_per_m)))
    mpp = 2 * half_diag_m / n
    return half_diag_m, mpp, cy


def _mip_for_range(range_nm: float, native_m: float, **geom_kwargs) -> int:
    """The mip level ``TerrainLayer._render`` would pick at *range_nm*
    (``terrain.py:308``), given a native tile pitch of *native_m* metres."""
    _, mpp, _ = _terrain_render_geometry(range_nm, **geom_kwargs)
    return max(0, min(6, int(round(math.log2(max(1.0, mpp / native_m))))))


def _band_top_nm(level: int, native_m: float,
                  ladder_top_nm: float = RANGE_LADDER_TOP_NM,
                  **geom_kwargs) -> float:
    """The largest range (up to *ladder_top_nm*) at which the renderer's
    own mip selector still picks *level* -- found by binary-searching the
    SAME selector the renderer calls at paint time, not by inverting its
    formula by hand. ``mpp`` is monotonically increasing in ``range_nm``
    for fixed widget geometry, so the selector is monotonic and the search
    converges on the exact band boundary."""
    if _mip_for_range(ladder_top_nm, native_m, **geom_kwargs) <= level:
        return ladder_top_nm
    lo, hi = 1e-3, ladder_top_nm
    for _ in range(60):
        mid = (lo + hi) / 2.0
        if _mip_for_range(mid, native_m, **geom_kwargs) <= level:
            lo = mid
        else:
            hi = mid
    return lo


def _half_diag_nm(range_nm: float, **geom_kwargs) -> float:
    half_diag_m, _, _ = _terrain_render_geometry(range_nm, **geom_kwargs)
    return half_diag_m / 1852.0


def _deg_radius(nm: float, lat: float) -> tuple[float, float]:
    """Nautical miles -> (lat degrees, lon degrees) at *lat*. 1 NM is
    exactly 1/60 deg of latitude; a degree of longitude is narrower by
    cos(lat), so the same NM radius is WIDER in longitude degrees."""
    lat_deg = nm / 60.0
    lon_deg = lat_deg / max(1e-6, math.cos(math.radians(lat)))
    return lat_deg, lon_deg


def _navaid_bbox_deg(range_nm: float, lat: float) -> tuple[float, float]:
    """Mirrors ``navaids.py`` ``_DbLayer._bbox`` EXACTLY (its own
    NM->degree factor and cos-lat floor are NOT the same as
    ``_deg_radius``'s -- this is deliberately a separate function rather
    than a shared one, so a change to either formula shows up as a diff
    here instead of silently reusing the wrong constant)."""
    d = range_nm * NAVAID_BBOX_NM_TO_DEG
    dl = d / max(NAVAID_COS_LAT_FLOOR, math.cos(math.radians(lat)))
    return d, dl


def _bbox_from_radius(lat: float, lon: float, radius_lat_deg: float,
                       radius_lon_deg: float):
    return (lat - radius_lat_deg, lat + radius_lat_deg,
            lon - radius_lon_deg, lon + radius_lon_deg)


def _widest_half_diag_nm(range_nm: float,
                          envelopes=PERF_WIDGET_ENVELOPES) -> tuple[float, tuple]:
    """The widest half-diagonal reach, in NM, at *range_nm* across every
    ``(w, h, anchor_frac)`` in *envelopes* -- and which envelope won, so
    a caller can declare it (``footprint_manifest``). AER-1143's
    amendment: the footprint is a function of the widget, so any single
    hard-coded geometry is a claim about which widget is widest, and this
    is the one place that claim is settled, by computing it rather than
    asserting it."""
    best_radius, best_env = None, None
    for (w, h, anchor) in envelopes:
        radius_nm = _half_diag_nm(range_nm, w=w, h=h, anchor_frac=anchor)
        if best_radius is None or radius_nm > best_radius:
            best_radius, best_env = radius_nm, (w, h, anchor)
    return best_radius, best_env


def _pan_excursion_deg(lat: float, native_m: float,
                        **geom_kwargs) -> tuple[float, float]:
    """Worst-case centre drift ``bench_map_gestures.py``'s ``scenario_pan``
    (3 s at 60 Hz, 3 px/event) can walk the render centre while native
    (level 0) is still the selected mip -- evaluated at the TOP of
    native's own band (the widest range native is ever read at, so the
    worst-case excursion within native's whole operating range), mirroring
    ``MapWidget.pan_by``'s own screen-px -> world-metre conversion
    (``map/__init__.py``). Applied symmetrically in both directions: which
    way the finger drags is a test detail, not a fixture property to
    pin.

    NOT widened across ``PERF_WIDGET_ENVELOPES`` (unlike the vector-layer
    footprints below) -- see ``terrain_level_bands``'s docstring for why
    the terrain/native derivation stays single-geometry."""
    band_top_nm = _band_top_nm(0, native_m, **geom_kwargs)
    _, _, cy = _terrain_render_geometry(band_top_nm, **geom_kwargs)
    px_per_m = cy / max(1.0, band_top_nm * 1852.0)
    exc_m = (_PAN_EVENTS * _PAN_PX_PER_EVENT) / px_per_m
    exc_lat_deg = exc_m / M_PER_DEG_LAT
    exc_lon_deg = exc_m / (M_PER_DEG_LAT * max(1e-6, math.cos(math.radians(lat))))
    return exc_lat_deg, exc_lon_deg


def terrain_level_bands(lat: float, lon: float, native_m: float,
                         levels=range(7),
                         ladder_top_nm: float = RANGE_LADDER_TOP_NM,
                         **geom_kwargs) -> dict:
    """For every mip level 0 (native) .. 6, the whole-degree cell range
    this scene's terrain render actually reads at that level -- each
    level cut to the half-diagonal at the TOP of its own selection band
    (the mip clamp is monotonic in range, so that top is also the level's
    widest reach; a cell further out than that is never sampled at this
    level by any range the renderer selects it for). AER-1140's ruling:
    "derive the radii in code from the selector, do not transcribe the
    table -- the table is the instance, the selector is the rule."

    Deliberately single-geometry, NOT widened across
    ``PERF_WIDGET_ENVELOPES`` the way the vector-layer footprints in
    ``cut_scene`` are (AER-1143's amendment). The two are not the same
    question: a vector layer's footprint is "how far does a query box at
    a FIXED asserted range reach", which grows monotonically with a
    wider/flatter widget at that SAME range -- so the widest widget is
    unambiguous. A terrain level's band is "at what range does THIS
    geometry's OWN mip selector stop choosing this level", and that
    range scales with ``cy`` (`h * (1 - anchor)`), not with the
    half-diagonal ratio -- a portrait 650x1040 widget reaches a given mip
    level at a LARGER range than the square 300x300 one, precisely
    because its taller ``cy`` keeps ``mpp`` finer for longer. Taking a
    per-level max across geometries would therefore inflate levels 0-5
    non-uniformly by the OTHER geometry's mip-selection boundary, not by
    anything this level's own selector ever reads at -- a real behaviour
    change to terrain sizing that Elon's amendment did not ask for
    ("my ~72 MB terrain sizing stands. Water does not."). Terrain stays
    keyed to the single ``PERF_WIDGET_W``/``PERF_WIDGET_H`` geometry."""
    bands = {}
    for level in levels:
        band_top_nm = _band_top_nm(level, native_m, ladder_top_nm,
                                    **geom_kwargs)
        radius_nm = _half_diag_nm(band_top_nm, **geom_kwargs)
        radius_lat_deg, radius_lon_deg = _deg_radius(radius_nm, lat)
        lat_cells = _cell_range(lat - radius_lat_deg, lat + radius_lat_deg)
        lon_cells = _cell_range(lon - radius_lon_deg, lon + radius_lon_deg)
        bands[level] = {
            "band_top_nm": band_top_nm,
            "radius_nm": radius_nm,
            "radius_lat_deg": radius_lat_deg,
            "radius_lon_deg": radius_lon_deg,
            "lat_cells": lat_cells,
            "lon_cells": lon_cells,
        }
    return bands


def native_footprint(lat: float, lon: float, native_m: float,
                      **geom_kwargs):
    """The level-0 (native) cell footprint: the level's own band radius
    (tiny -- a couple NM) widened to also cover the pan-excursion margin
    (``_pan_excursion_deg``), so a ``pan_by`` sweep during the volume-perf
    scenario cannot walk the render centre out of the cut cell(s) (the
    "fails loudly, never quietly under-covers" mechanism trap from
    AER-1140's ruling). Raises ``PerfFixtureError`` if the resulting
    footprint needs more than ``MAX_NATIVE_CELLS`` whole-degree cells --
    native tiles are the expensive ones (a 3x3 ring alone busts the cap),
    so past a small margin this is a scene-pose problem to report, not a
    ring to silently widen."""
    band0 = terrain_level_bands(lat, lon, native_m, levels=(0,),
                                 **geom_kwargs)[0]
    exc_lat, exc_lon = _pan_excursion_deg(lat, native_m, **geom_kwargs)
    lat_radius = max(band0["radius_lat_deg"], exc_lat)
    lon_radius = max(band0["radius_lon_deg"], exc_lon)
    lat_cells = _cell_range(lat - lat_radius, lat + lat_radius)
    lon_cells = _cell_range(lon - lon_radius, lon + lon_radius)
    n_cells = len(lat_cells) * len(lon_cells)
    if n_cells > MAX_NATIVE_CELLS:
        raise PerfFixtureError(
            f"scene centre ({lat}, {lon}): the native-tile footprint "
            f"(band radius +/-{band0['radius_lat_deg']:.3f} lat / "
            f"+/-{band0['radius_lon_deg']:.3f} lon, pan-excursion margin "
            f"+/-{exc_lat:.3f} lat / +/-{exc_lon:.3f} lon) needs "
            f"{n_cells} whole-degree native cells, over the "
            f"{MAX_NATIVE_CELLS}-cell sanity cap (a 3x3 ring alone is "
            "233 MB and busts the pack on its own -- AER-1140). Move the "
            "scene pose away from a whole-degree boundary, or get a "
            "ruling on widening the cap.")
    return lat_cells, lon_cells


class PerfFixtureError(RuntimeError):
    """Cutting/packaging failed in a way the operator must act on."""


class PerfFixtureUnavailable(RuntimeError):
    """fetch_fixture was asked for a scene with no usable pinned manifest
    entry -- distinct from "PYEFIS_PERF_FIXTURE unset" (which is a clean
    ``None`` return, not an error)."""


# ---------------------------------------------------------------------------
# Loading sibling tools/*.py modules (tools/ is not a package -- same
# pattern tests/tools/test_bench_map_gestures.py and
# tests/perf/test_map_gestures.py already use).
# ---------------------------------------------------------------------------

def _load_tool(name: str):
    spec = importlib.util.spec_from_file_location(
        name, _TOOLS_DIR / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# HGT tile naming -- mirrors src/pyefis/instruments/ai/svs.py tile_name /
# _hgt_path exactly (duplicated, not imported: svs.py imports PyQt6 at
# module scope, and this tool must stay usable with no Qt installed, the
# same reason tools/build_terrain_mips.py never imports svs.py for this).
# ---------------------------------------------------------------------------

def tile_name(lat: int, lon: int) -> str:
    ns = "N" if lat >= 0 else "S"
    ew = "E" if lon >= 0 else "W"
    return f"{ns}{abs(lat):02d}{ew}{abs(lon):03d}"


def _ns_dir(lat: int) -> str:
    return f"{'N' if lat >= 0 else 'S'}{abs(lat):02d}"


def _hgt_path(tile_root: Path, lat: int, lon: int) -> Path | None:
    name = tile_name(lat, lon)
    for p in (tile_root / _ns_dir(lat) / f"{name}.hgt",
              tile_root / f"{name}.hgt",
              tile_root / f"{name}.HGT"):
        if p.exists():
            return p
    return None


def _native_pitch_m(hgt_path: Path) -> float:
    """The native sample pitch (metres/sample) of an HGT tile, derived
    from its file size alone (big-endian int16, square) -- no numpy
    dependency needed just to learn a tile's side, and this tool
    deliberately carries none (module docstring)."""
    n_samples = hgt_path.stat().st_size // 2
    side = int(round(math.sqrt(n_samples)))
    return M_PER_DEG_LAT / (side - 1)


def _cell_range(lo: float, hi: float) -> range:
    """Integer SW-corner degree cells whose [c, c+1) span overlaps
    [lo, hi). May include one extra cell when ``hi`` lands exactly on an
    integer -- harmless over-inclusion, never a missed cell."""
    return range(math.floor(lo), math.floor(hi) + 1)


# ---------------------------------------------------------------------------
# Terrain: native tile, concentric mip pyramid, mosaic
# ---------------------------------------------------------------------------

def cut_terrain(src_root: Path, dst_root: Path, lat: float, lon: float,
                 mip_levels=MIP_LEVELS,
                 mosaic_levels=MOSAIC_LEVELS) -> dict:
    """Concentric mip cut (AER-1142, per AER-1140's ruling): each level is
    copied only for the whole-degree cells its OWN selection band's widest
    reach touches, not a single uniform grid shared by every level. A cell
    several degrees from the centre is never opened at native or a
    shallow mip -- it is only ever sampled at whatever level its range
    selects, so copying it at any other level is dead weight, not safety
    margin. Level 0 (native) additionally covers the pan-excursion margin
    (``native_footprint``).

    Requires the native tile under the scene centre to exist FIRST: its
    pixel pitch is ``native``, the mip selector's own reference
    (terrain.py:306-308) -- without it every level's band would be
    derived from the wrong pitch. Raises loudly rather than falling back
    to a guessed pitch, matching the runtime's own "fail loud, don't
    silently shift 1.6x coarser" trap that motivated this rework."""
    src_root = Path(src_root)
    dst_root = Path(dst_root)
    centre_path = _hgt_path(src_root, math.floor(lat), math.floor(lon))
    if centre_path is None:
        raise PerfFixtureError(
            f"the native tile under the scene centre ({lat}, {lon}) is "
            f"missing from {src_root} -- the mip selector "
            "(terrain.py:306-308) needs it to derive `native`; without "
            "it every level would silently shift ~1.6x coarser (falling "
            "back to a 1200-sample assumption). Check --tile-root, not "
            "the window size.")
    native_m = _native_pitch_m(centre_path)

    bands = terrain_level_bands(lat, lon, native_m, levels=(0,) + tuple(mip_levels))
    native_lat_cells, native_lon_cells = native_footprint(lat, lon, native_m)

    native_copied = 0
    native_bytes = 0
    for la in native_lat_cells:
        for lo_ in native_lon_cells:
            src = _hgt_path(src_root, la, lo_)
            if src is None:
                continue
            dst = dst_root / _ns_dir(la) / f"{tile_name(la, lo_)}.hgt"
            dst.parent.mkdir(parents=True, exist_ok=True)
            data = src.read_bytes()
            dst.write_bytes(data)
            native_copied += 1
            native_bytes += len(data)

    mip_copied = {level: 0 for level in mip_levels}
    mip_bytes = 0
    per_level_cells = {0: native_copied}
    for level in mip_levels:
        band = bands[level]
        n_this_level = 0
        for la in band["lat_cells"]:
            for lo_ in band["lon_cells"]:
                msrc = _hgt_path(src_root / ".mip" / str(level), la, lo_)
                if msrc is None:
                    continue
                mdst = (dst_root / ".mip" / str(level) / _ns_dir(la)
                        / f"{tile_name(la, lo_)}.hgt")
                mdst.parent.mkdir(parents=True, exist_ok=True)
                data = msrc.read_bytes()
                mdst.write_bytes(data)
                mip_copied[level] += 1
                mip_bytes += len(data)
                n_this_level += 1
        per_level_cells[level] = n_this_level

    build_terrain_mosaic = _load_tool("build_terrain_mosaic")
    mosaic_meta = {}
    for level in mosaic_levels:
        if mip_copied.get(level, 0) == 0:
            continue     # no mip tiles at this level in the window -> nothing to stitch
        meta = build_terrain_mosaic.build_level(dst_root, level)
        if meta is not None:
            mosaic_meta[level] = meta

    band_stats = {
        lvl: {k: v for k, v in b.items() if k not in ("lat_cells", "lon_cells")}
        for lvl, b in bands.items()
    }

    return {
        "native_tiles": native_copied,
        "native_bytes": native_bytes,
        "native_m": native_m,
        "mip_tiles": mip_copied,
        "mip_bytes": mip_bytes,
        "mosaic_levels": mosaic_meta,
        "bands": band_stats,
        "per_level_cells": per_level_cells,
    }


# ---------------------------------------------------------------------------
# water.sqlite
# ---------------------------------------------------------------------------

def cut_water(src_path: Path, dst_path: Path, bbox) -> dict:
    """Bbox-overlap copy of water_polygons/waterway_lines, rtree rebuilt
    from the copied rows -- see WaterDB.polygons_in_range's plain-B-tree
    predicate (water_db.py) for why this exact inequality shape (and not
    a stricter "fully contained" test) is the right cut: a polygon whose
    bbox only partially overlaps the window must still be kept WHOLE, not
    clipped, matching what a real renderer positioned inside the window
    would fetch for it."""
    lat_lo, lat_hi, lon_lo, lon_hi = bbox
    if dst_path.exists():
        dst_path.unlink()
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(dst_path))
    try:
        con.executescript(WATER_SCHEMA)
        con.execute("ATTACH DATABASE ? AS src", (str(src_path),))
        stats = {}
        for table, rtree in (("water_polygons", "water_rtree"),
                              ("waterway_lines", "waterway_rtree")):
            cur = con.execute(
                f"INSERT INTO {table} SELECT * FROM src.{table} "
                "WHERE max_lat > ? AND min_lat < ? "
                "AND max_lon > ? AND min_lon < ?",
                (lat_lo, lat_hi, lon_lo, lon_hi))
            con.execute(
                f"INSERT INTO {rtree} (id, min_lat, max_lat, min_lon, max_lon) "
                f"SELECT id, min_lat, max_lat, min_lon, max_lon FROM {table}")
            stats[table] = cur.rowcount
        stats["vertex_bytes"] = con.execute(
            "SELECT COALESCE(SUM(LENGTH(vertices)), 0) FROM water_polygons"
        ).fetchone()[0]
        stats["vertices"] = stats["vertex_bytes"] // 16
        con.commit()
        con.execute("DETACH DATABASE src")
    finally:
        con.close()
    _vacuum(dst_path)
    return stats


#: Verbatim from tools/build_water_db.py's SCHEMA (not imported: that
#: module pulls in mapbox_earcut at top level for tessellation, a
#: build-time-only dependency this cutter has no use for and should not
#: force onto whoever just wants to cut a fixture). Keep in sync by hand.
WATER_SCHEMA = """
CREATE TABLE IF NOT EXISTS water_polygons (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    min_lat   REAL NOT NULL,
    max_lat   REAL NOT NULL,
    min_lon   REAL NOT NULL,
    max_lon   REAL NOT NULL,
    kind      TEXT NOT NULL,
    elev_ft   REAL,
    vertices  BLOB NOT NULL,
    triangles BLOB,
    rings     BLOB
);
CREATE INDEX IF NOT EXISTS idx_bbox
    ON water_polygons(min_lat, max_lat, min_lon, max_lon);
CREATE INDEX IF NOT EXISTS idx_kind ON water_polygons(kind);
CREATE VIRTUAL TABLE IF NOT EXISTS water_rtree USING rtree(
    id,
    min_lat, max_lat,
    min_lon, max_lon
);
CREATE TABLE IF NOT EXISTS waterway_lines (
    id INTEGER PRIMARY KEY,
    fclass TEXT NOT NULL,
    min_lat REAL, max_lat REAL, min_lon REAL, max_lon REAL,
    verts BLOB NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS waterway_rtree USING rtree(
    id, min_lat, max_lat, min_lon, max_lon
);
"""


# ---------------------------------------------------------------------------
# highway db
# ---------------------------------------------------------------------------

#: Verbatim from tools/build_highway_db.py's SCHEMA. Loaded as a literal
#: for the same reason as WATER_SCHEMA above -- consistency, and this
#: one in particular has no problematic top-level import today, but a
#: cutter tool should not be coupled to a builder's import graph at all.
HIGHWAY_SCHEMA = """
CREATE TABLE highway_lines (
    id INTEGER PRIMARY KEY,
    fclass TEXT NOT NULL,
    min_lat REAL, max_lat REAL, min_lon REAL, max_lon REAL,
    verts BLOB NOT NULL,
    flags INTEGER NOT NULL DEFAULT 0,
    ref TEXT
);
CREATE VIRTUAL TABLE highway_rtree USING rtree(
    id, min_lat, max_lat, min_lon, max_lon
);
"""


def cut_highway(src_path: Path, dst_path: Path, bbox) -> dict:
    lat_lo, lat_hi, lon_lo, lon_hi = bbox
    if dst_path.exists():
        dst_path.unlink()
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(dst_path))
    try:
        con.executescript(HIGHWAY_SCHEMA)
        con.execute("ATTACH DATABASE ? AS src", (str(src_path),))
        cur = con.execute(
            "INSERT INTO highway_lines SELECT * FROM src.highway_lines "
            "WHERE max_lat >= ? AND min_lat <= ? "
            "AND max_lon >= ? AND min_lon <= ?",
            (lat_lo, lat_hi, lon_lo, lon_hi))
        n = cur.rowcount
        con.execute(
            "INSERT INTO highway_rtree (id, min_lat, max_lat, min_lon, max_lon) "
            "SELECT id, min_lat, max_lat, min_lon, max_lon FROM highway_lines")
        vertex_bytes = con.execute(
            "SELECT COALESCE(SUM(LENGTH(verts)), 0) FROM highway_lines"
        ).fetchone()[0]
        con.commit()
        con.execute("DETACH DATABASE src")
    finally:
        con.close()
    _vacuum(dst_path)
    return {"highway_lines": n, "vertex_bytes": vertex_bytes,
            "vertices": vertex_bytes // 8}


# ---------------------------------------------------------------------------
# navaid db -- flat lat/lon tables, no rtree (build_navaid_db.py's own
# inline schema; there is no importable SCHEMA constant there to reuse,
# so this mirrors it literally -- keep the two in sync by hand).
# ---------------------------------------------------------------------------

NAVAID_SCHEMA = """
CREATE TABLE navaids (id TEXT, type TEXT, name TEXT, freq TEXT,
                      elev_ft REAL, lat REAL, lon REAL);
CREATE TABLE fixes (id TEXT, use_code TEXT, lat REAL, lon REAL);
CREATE TABLE awy_segments (awy_id TEXT, seq INTEGER,
                           p1 TEXT, lat1 REAL, lon1 REAL,
                           p2 TEXT, lat2 REAL, lon2 REAL);
"""

NAVAID_INDEXES = """
CREATE INDEX idx_nav_ll ON navaids(lat, lon);
CREATE INDEX idx_fix_ll ON fixes(lat, lon);
CREATE INDEX idx_seg_ll ON awy_segments(lat1, lon1);
"""


def cut_navaid(src_path: Path, dst_path: Path, bbox) -> dict:
    """navaids/fixes: plain lat/lon-in-range copy. awy_segments: kept if
    EITHER endpoint falls in the window (mirrors AirwaysLayer's own
    OR-of-two-BETWEENs query, src/pyefis/instruments/map/layers/
    navaids.py) -- an airway that only clips the window's edge must
    still render its segment across it, the same reason water/highway
    rows are kept whole rather than clipped."""
    lat_lo, lat_hi, lon_lo, lon_hi = bbox
    if dst_path.exists():
        dst_path.unlink()
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(dst_path))
    try:
        con.executescript(NAVAID_SCHEMA)
        con.execute("ATTACH DATABASE ? AS src", (str(src_path),))
        stats = {}
        for table in ("navaids", "fixes"):
            cur = con.execute(
                f"INSERT INTO {table} SELECT * FROM src.{table} "
                "WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?",
                (lat_lo, lat_hi, lon_lo, lon_hi))
            stats[table] = cur.rowcount
        cur = con.execute(
            "INSERT INTO awy_segments SELECT * FROM src.awy_segments "
            "WHERE (lat1 BETWEEN ? AND ? AND lon1 BETWEEN ? AND ?) "
            "   OR (lat2 BETWEEN ? AND ? AND lon2 BETWEEN ? AND ?)",
            (lat_lo, lat_hi, lon_lo, lon_hi, lat_lo, lat_hi, lon_lo, lon_hi))
        stats["awy_segments"] = cur.rowcount
        con.commit()
        con.execute("DETACH DATABASE src")
        con.executescript(NAVAID_INDEXES)
        con.commit()
    finally:
        con.close()
    _vacuum(dst_path)
    return stats


def _vacuum(path: Path):
    con = sqlite3.connect(str(path))
    try:
        con.execute("VACUUM")
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Packaging
# ---------------------------------------------------------------------------

def _dir_size(root: Path) -> int:
    return sum(p.stat().st_size for p in root.rglob("*") if p.is_file())


def package(out_dir: Path, dest_tarball: Path) -> tuple[int, str]:
    """tar.gz ``out_dir`` and return (size_bytes, sha256_hex) of the
    archive. Byte-for-byte deterministic given the same file CONTENTS
    (sorted member order; mtime/uid/gid/mode/gzip-header-mtime all
    zeroed) -- so re-cutting from the same source packs reproduces the
    same sha256, which is the whole point of pinning one (AER-1133:
    "reproducible from the real packs with the exact command
    recorded")."""
    import gzip
    dest_tarball.parent.mkdir(parents=True, exist_ok=True)
    members = sorted(p for p in out_dir.rglob("*") if p.is_file())
    with open(dest_tarball, "wb") as raw:
        # filename="" suppresses gzip's embedded original-filename header
        # field (FNAME) -- without it, two tarballs with byte-identical
        # CONTENT still differ because gzip records the destination
        # path's basename, and package() is called with a different
        # dest_tarball name per scene.
        with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0,
                            filename="") as gz:
            with tarfile.open(fileobj=gz, mode="w") as tar:
                for m in members:
                    info = tar.gettarinfo(
                        m, arcname=str(m.relative_to(out_dir)))
                    info.mtime = 0
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    info.mode = 0o644
                    with open(m, "rb") as f:
                        tar.addfile(info, f)
    digest = hashlib.sha256()
    with open(dest_tarball, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    size = dest_tarball.stat().st_size
    return size, digest.hexdigest()


def package_scene(out_dir: Path, dest_tarball: Path,
                   max_bytes: int = MAX_PACK_BYTES) -> tuple[int, str]:
    """``package()`` *out_dir*, then gate on the TARBALL bytes --
    ``MAX_PACK_BYTES`` traces to CI fetch time, which is the compressed
    download, not the raw cut directory (AER-1140's ruling: "a
    requirement whose stated reason is fetch time, gated on a quantity
    that is not fetched, does not trace to its reason"). Raw directory
    size (``cut_scene``'s ``stats["raw_bytes"]``) is an advisory stat
    only; this is the check that raises."""
    size, sha256 = package(out_dir, dest_tarball)
    if size > max_bytes:
        raise PerfFixtureError(
            f"packaged tarball {size / 1e6:.0f} MB exceeds the "
            f"{max_bytes / 1e6:.0f} MB budget -- CI fetch time, not raw "
            "disk (AER-1140's ruling). This is a real finding, not a "
            "knob to turn: report the breakdown above and get a ruling "
            "on the number before publishing.")
    return size, sha256


# ---------------------------------------------------------------------------
# footprint.json -- the pack DECLARES what it was cut to cover (AER-1143's
# amendment, requirement 5)
# ---------------------------------------------------------------------------

FOOTPRINT_MANIFEST_NAME = "footprint.json"


def footprint_manifest(scene: str, lat: float, lon: float, *,
                        water_bbox, highway_bbox, navaid_bbox,
                        water_env=None, highway_env=None,
                        navaid_range_nm: float = NAVAID_MAX_RANGE_NM,
                        window_deg: float | None = None) -> dict:
    """The declaration written to ``footprint.json`` inside every cut
    pack: per vector layer, the exact bbox that was cut and the
    ``(w, h, ownship_position, range_nm)`` envelope it was derived from.

    This is the mechanism half of AER-1143's amendment: a consumer test
    computing its own required render window can check "is my window a
    subset of what this pack DECLARES it covers?" -- a comparison against
    an objective, written fact -- instead of re-deriving the cutter's own
    geometry rule a second time and trusting the two derivations stay in
    sync. Keeping an independent computation too, as a cross-check on
    this declaration, is still the consumer's job (and a good one -- it
    is what would catch THIS file deriving the wrong number); this
    manifest only removes the need for that to be the sole check.

    *water_env*/*highway_env* are the winning ``(w, h, anchor_frac)``
    tuple from ``_widest_half_diag_nm``/``terrain_level_bands``' band 6,
    or ``None`` when *window_deg* overrode the per-layer derivation --
    navaid has no widget envelope at all (``_navaid_bbox_deg`` is a pure
    function of range and latitude, matching ``navaids.py``'s own
    ``_bbox``, which never reads a widget size)."""
    def _layer(bbox, env, range_nm):
        envelope = ({"override_window_deg": window_deg} if window_deg is not None
                    else {"w": env[0], "h": env[1],
                          "ownship_position_frac": env[2],
                          "range_nm": range_nm})
        return {"bbox": list(bbox), "envelope": envelope}

    return {
        "scene": scene, "lat": lat, "lon": lon,
        "considered_envelopes": [list(e) for e in PERF_WIDGET_ENVELOPES],
        "layers": {
            "water": _layer(water_bbox, water_env, RANGE_LADDER_TOP_NM),
            "highway": _layer(highway_bbox, highway_env, HIGHWAY_MAX_RANGE_NM),
            "navaid": {
                "bbox": list(navaid_bbox),
                "envelope": ({"override_window_deg": window_deg}
                            if window_deg is not None
                            else {"range_nm": navaid_range_nm, "lat": lat}),
            },
        },
    }


# ---------------------------------------------------------------------------
# cut: one scene, end to end
# ---------------------------------------------------------------------------

def cut_scene(scene: str, tile_root: Path, water_db: Path, highway_db: Path,
              navaid_db: Path, out_dir: Path,
              window_deg: float | None = None) -> dict:
    """Cut one scene's terrain (concentric mip pyramid) + water/highway/
    navaid vector layers. No size gate here any more -- see
    ``package_scene`` (AER-1140's ruling moved the gate to the packaged
    tarball).

    *window_deg*, when given, overrides the per-layer derivation below
    with a single uniform +/- half-window for water/highway/navaid (NOT
    terrain, which is always cut concentrically by mip level) -- a manual
    escape hatch for quick local debugging. Left ``None`` (the default),
    each vector layer's footprint is derived from that layer's own query
    formula at its own widest asserted range, which is what a real
    publish run must use."""
    if scene not in SCENES:
        raise PerfFixtureError(
            f"unknown scene {scene!r}; known scenes: {sorted(SCENES)}")
    lat, lon = SCENES[scene]["lat"], SCENES[scene]["lon"]

    out_dir = Path(out_dir)
    if out_dir.exists() and any(out_dir.iterdir()):
        raise PerfFixtureError(
            f"{out_dir} already has content; remove it first "
            "(refusing to merge into a stale cut)")
    out_dir.mkdir(parents=True, exist_ok=True)

    stats = {"scene": scene, "lat": lat, "lon": lon}

    stats["terrain"] = cut_terrain(Path(tile_root), out_dir, lat, lon)

    water_env = highway_env = None
    if window_deg is not None:
        half = window_deg / 2.0
        water_bbox = highway_bbox = navaid_bbox = (
            lat - half, lat + half, lon - half, lon + half)
        stats["footprints"] = {"override_window_deg": window_deg}
    else:
        water_radius_nm, water_env = _widest_half_diag_nm(RANGE_LADDER_TOP_NM)
        water_lat_deg, water_lon_deg = _deg_radius(water_radius_nm, lat)
        water_bbox = _bbox_from_radius(lat, lon, water_lat_deg, water_lon_deg)

        highway_radius_nm, highway_env = _widest_half_diag_nm(
            HIGHWAY_MAX_RANGE_NM)
        hwy_lat_deg, hwy_lon_deg = _deg_radius(highway_radius_nm, lat)
        highway_bbox = _bbox_from_radius(lat, lon, hwy_lat_deg, hwy_lon_deg)

        nav_lat_deg, nav_lon_deg = _navaid_bbox_deg(NAVAID_MAX_RANGE_NM, lat)
        navaid_bbox = _bbox_from_radius(lat, lon, nav_lat_deg, nav_lon_deg)

        stats["footprints"] = {
            "water_deg": (water_lat_deg, water_lon_deg),
            "highway_deg": (hwy_lat_deg, hwy_lon_deg),
            "navaid_deg": (nav_lat_deg, nav_lon_deg),
        }

    stats["water"] = cut_water(Path(water_db), out_dir / "water.sqlite",
                                water_bbox)
    stats["highway"] = cut_highway(Path(highway_db),
                                    out_dir / "highway.sqlite", highway_bbox)
    stats["navaid"] = cut_navaid(Path(navaid_db), out_dir / "navaids.sqlite",
                                  navaid_bbox)

    manifest = footprint_manifest(
        scene, lat, lon, water_bbox=water_bbox, highway_bbox=highway_bbox,
        navaid_bbox=navaid_bbox, water_env=water_env, highway_env=highway_env,
        navaid_range_nm=NAVAID_MAX_RANGE_NM, window_deg=window_deg)
    (out_dir / FOOTPRINT_MANIFEST_NAME).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    stats["footprint_manifest"] = manifest

    stats["raw_bytes"] = _dir_size(out_dir)   # advisory only -- see package_scene
    return stats


# ---------------------------------------------------------------------------
# Manifest + fetch
# ---------------------------------------------------------------------------

def _load_manifest(path: Path = MANIFEST_PATH) -> dict:
    if not path.is_file():
        raise PerfFixtureError(f"manifest not found: {path}")
    return json.loads(path.read_text())


def _save_manifest(manifest: dict, path: Path = MANIFEST_PATH):
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def _truthy(value: str | None) -> bool:
    return bool(value) and value.strip().lower() not in ("", "0", "false",
                                                          "no", "off")


def fetch_fixture(scene: str, cache_dir: Path | None = None,
                   manifest_path: Path = MANIFEST_PATH) -> Path | None:
    """Return the extracted fixture directory for ``scene``, or ``None``
    without touching the network when ``PYEFIS_PERF_FIXTURE`` is not
    set -- the "a local run without it must skip cleanly" contract
    (AER-1133). Raises ``PerfFixtureUnavailable`` (not a silent None) if
    the flag IS set but no usable pin exists for this scene, so CI fails
    loudly on a real misconfiguration rather than quietly skipping a
    budget it was told to run."""
    if not _truthy(os.environ.get("PYEFIS_PERF_FIXTURE")):
        return None

    manifest = _load_manifest(manifest_path)
    entry = manifest.get("scenes", {}).get(scene)
    if not entry or not entry.get("sha256") or not entry.get("url"):
        raise PerfFixtureUnavailable(
            f"PYEFIS_PERF_FIXTURE is set but scene {scene!r} has no "
            f"published pin in {manifest_path} yet. Run "
            "`make_map_perf_fixture.py cut --scene "
            f"{scene} --publish` against the real data packs with R2 "
            "credentials, then re-check in the updated manifest.")

    cache_dir = Path(cache_dir or os.environ.get("PYEFIS_FIXTURE_CACHE")
                     or (Path.home() / ".cache" / "pyefis-fixtures"))
    cache_dir.mkdir(parents=True, exist_ok=True)
    tarball = cache_dir / f"{scene}.tar.gz"
    extracted = cache_dir / scene
    sha_marker = cache_dir / f"{scene}.sha256"

    if (extracted.is_dir() and sha_marker.is_file()
            and sha_marker.read_text().strip() == entry["sha256"]):
        return extracted     # already fetched + verified this exact pin

    _download(entry["url"], tarball)
    digest = hashlib.sha256()
    with open(tarball, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    got = digest.hexdigest()
    if got != entry["sha256"]:
        tarball.unlink(missing_ok=True)
        raise PerfFixtureUnavailable(
            f"scene {scene!r}: downloaded tarball sha256 {got} does not "
            f"match the pinned {entry['sha256']} in {manifest_path} -- "
            "not extracting a fixture that does not match its pin.")

    if extracted.is_dir():
        import shutil
        shutil.rmtree(extracted)
    extracted.mkdir(parents=True)
    with tarfile.open(tarball, "r:gz") as tar:
        tar.extractall(extracted, filter="data")
    sha_marker.write_text(entry["sha256"])
    return extracted


def _download(url: str, dest: Path):
    with urllib.request.urlopen(url) as resp, open(dest, "wb") as out:
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cmd_cut(args) -> int:
    stats = cut_scene(args.scene, args.tile_root, args.water_db,
                       args.highway_db, args.navaid_db, args.out,
                       window_deg=args.window_deg)
    print(json.dumps(stats, indent=2, default=str))

    tarball = Path(args.out).with_suffix(".tar.gz")
    size, sha256 = package_scene(Path(args.out), tarball,
                                  max_bytes=args.max_bytes)
    print(f"packaged {tarball} : {size / 1e6:.1f} MB  sha256={sha256}  "
          f"(raw dir {stats['raw_bytes'] / 1e6:.1f} MB, advisory)")

    if args.publish:
        _publish(args.scene, tarball, size, sha256)
    else:
        print("(not publishing -- pass --publish to push to R2 and pin "
              "the manifest)")
    return 0


def _publish(scene: str, tarball: Path, size: int, sha256: str) -> bool:
    """Push ``tarball`` to R2 under test-fixtures/<scene>/, mirroring the
    existing wrangler convention in .github/workflows/editor-assets.yml:
    skip cleanly (return False, exit 0) with a warning when credentials
    are absent -- this is a CI-safe no-op, not a failure, on a fork or a
    dev box with no secrets. On success, rewrite this scene's manifest
    entry so fetch_fixture can find it."""
    token = os.environ.get("CLOUDFLARE_API_TOKEN")
    account = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
    if not token or not account:
        print("WARNING: CLOUDFLARE_API_TOKEN/CLOUDFLARE_ACCOUNT_ID not set "
              "-- skipping publish (the pack was still cut and packaged "
              f"locally at {tarball}).")
        return False

    import shutil
    import subprocess
    if shutil.which("npx") is None:
        print("WARNING: npx not found -- skipping publish.")
        return False

    key = f"test-fixtures/{scene}/{scene}.tar.gz"
    cmd = ["npx", "--yes", "wrangler@4", "r2", "object", "put",
           f"makerplane-configs/{key}", "--file", str(tarball),
           "--content-type", "application/gzip", "--remote"]
    print(f"publishing: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)

    url = f"https://makerplane-configs.r2.dev/{key}"
    manifest = (_load_manifest() if MANIFEST_PATH.is_file()
                else {"scenes": {}})
    manifest.setdefault("scenes", {})[scene] = {
        "lat": SCENES[scene]["lat"], "lon": SCENES[scene]["lon"],
        "sha256": sha256, "url": url, "bytes": size,
    }
    _save_manifest(manifest)
    print(f"manifest updated: {MANIFEST_PATH}")
    return True


def _cmd_fetch(args) -> int:
    os.environ.setdefault("PYEFIS_PERF_FIXTURE", "1")
    path = fetch_fixture(args.scene, cache_dir=args.cache_dir)
    if path is None:
        print("PYEFIS_PERF_FIXTURE is unset even after --fetch forced it "
              "on; this should not happen", file=sys.stderr)
        return 1
    print(path)
    return 0


def _parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="command", required=True)

    cut = sub.add_parser("cut", help="cut + package one scene from real packs")
    cut.add_argument("--scene", required=True, choices=sorted(SCENES))
    cut.add_argument("--tile-root", required=True,
                     help="terrain tile tree root (holds <NSdir>/*.hgt "
                          "and .mip/)")
    cut.add_argument("--water-db", required=True)
    cut.add_argument("--highway-db", required=True)
    cut.add_argument("--navaid-db", required=True)
    cut.add_argument("--out", required=True, help="output directory")
    cut.add_argument("--window-deg", type=float, default=None,
                     help="override: one uniform +/- half-window for "
                          "water/highway/navaid instead of each layer's "
                          "own derived footprint (terrain is always cut "
                          "concentrically by mip level regardless)")
    cut.add_argument("--max-bytes", type=int, default=MAX_PACK_BYTES)
    cut.add_argument("--publish", action="store_true",
                     help="push the packaged tarball to R2 and pin the "
                          "manifest (skips cleanly with no credentials)")
    cut.set_defaults(func=_cmd_cut)

    fetch = sub.add_parser("fetch", help="fetch + verify a published scene")
    fetch.add_argument("--scene", required=True, choices=sorted(SCENES))
    fetch.add_argument("--cache-dir", default=None)
    fetch.set_defaults(func=_cmd_fetch)

    return ap.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv)
    try:
        return args.func(args)
    except (PerfFixtureError, PerfFixtureUnavailable) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
