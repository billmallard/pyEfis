#  SPDX-License-Identifier: GPL-2.0-or-later
"""The measurement half of the pack-dependent moving-map perf budgets
(MP8b-2, briefs/map_gesture_perf_plan.md section 5; pyEfis #98,
AER-1135).

Shared, deliberately, between the pytest budgets
(``tests/perf/test_map_pack_budgets.py``) and the baseline minter
(``tools/map_perf_baseline.py``). If minting measured one thing and the
test asserted on another, the 1.5x tolerance would be comparing two
different numbers and the baseline would be worthless -- so there is
exactly one implementation of each metric and both callers import it.

Everything drives the MP7 harness (``tools/bench_map_gestures.py``) the
same way ``test_map_gestures.py`` does, rather than re-implementing
widget construction: what CI asserts, what the bench measures and what a
baseline records are then the same code path by construction.

Nothing here asserts. Every function returns a number (or ``None`` when
the data it needs is absent) and the caller decides what that means --
the split that keeps "was not measured" from being rounded to "passed".
"""

from __future__ import annotations

import importlib.util
import json
import math
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_ROOT = Path(__file__).resolve().parents[2]

#: Section 5's own configuration: "Beelink, Raleigh scene, 650x1040,
#: warm". The widget size is part of every timing row's meaning (the
#: terrain window is sized from the widget diagonal) and part of the
#: VOLUME row's meaning too (MP4 decimates per image pixel), so it is
#: never left to a default.
SCENE_W, SCENE_H = 650, 1040

#: The decode cap the appliance runs. ``vertices_after`` is a direct
#: function of it, so the volume budget is meaningless without it pinned
#: -- and the bench's own default is 512, which answers a different
#: question. Same reasoning as test_map_gestures._WATER_MAX_VERTICES.
WATER_MAX_VERTICES = 1024

SCENES = {
    "raleigh": {"lat": 35.8, "lon": -78.8},
    "key_west": {"lat": 24.55, "lon": -81.78},
}

#: Seconds to pump waiting for a cold terrain+water render to publish.
#: Generously over the 0.6 s budget on purpose: this is a TIMEOUT, not a
#: budget. A machine slow enough to need more than this reports
#: ``None`` (not measured) rather than a truncated number that would
#: read as a fast render.
RENDER_TIMEOUT_S = 90.0


def load_bench():
    """``tools/bench_map_gestures.py`` as a module (tools/ is not a
    package -- same helper as tests/perf/test_map_gestures.py)."""
    spec = importlib.util.spec_from_file_location(
        "bench_map_gestures", _ROOT / "tools" / "bench_map_gestures.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# The render window's real footprint -- see footprint_covers_window()
# ---------------------------------------------------------------------------

#: ``MovingMap.ownship_position``'s default, as a fraction. The ownship
#: sits at mid-screen, so ``cy = h * (1 - 0.5)``, and the nominal
#: ``range_nm`` is anchor-to-top-edge -- which is why the window a render
#: actually reads is so much wider than the range suggests. Getting this
#: wrong (0.25) under-stated the window by 1.5x on the first pass here;
#: it was caught by ``test_render_window_matches_the_water_query_box``,
#: which is why that test exists rather than trusting the arithmetic.
_OWNSHIP_ANCHOR_FRAC = 0.5

#: ``water_db.NM_PER_DEG_LAT``. The guard's whole job is to reproduce
#: ``WaterDB.polygons_in_range``'s query box, so it uses that module's
#: constant and not a metres-per-degree of its own.
_NM_PER_DEG_LAT = 60.0


def effective_range_nm(range_nm: float, w: int = SCENE_W, h: int = SCENE_H,
                       anchor_frac: float = _OWNSHIP_ANCHOR_FRAC) -> float:
    """The ``range_nm`` ``TerrainLayer._draw_water_numpy`` passes to
    ``polygons_in_range``, which is NOT the widget's ``range_nm``.

    ``_render`` sizes the window to cover the ROTATED viewport: the
    widget's half-diagonal in metres, oversized 1.25x, and the widget's
    ``range_nm`` measures anchor-to-top-edge rather than anchor-to-
    corner. At 650x1040 with the ownship at mid-screen, a nominal
    160 NM render reads a 235.6 NM window."""
    cy = max(1.0, h * (1.0 - anchor_frac))
    px_per_m = max(1.0, cy) / max(1.0, range_nm * 1852.0)
    half_diag_m = 0.5 * math.hypot(w, h) / px_per_m * 1.25
    n = int(min(1024, max(64, 2 * half_diag_m * px_per_m)))
    mpp = 2 * half_diag_m / n
    return ((n - 1) / 2.0 * mpp) / 1852.0


#: Mirror of ``TerrainLayer._WATER_FULL_MAX_NM``. Above it the layer
#: drops the ocean coastline and size-filters lakes, so the drawn
#: polygon set changes DISCONTINUOUSLY. AER-1149: compared against the
#: widget's own NOMINAL ``range_nm`` (what the pilot selected), not the
#: WINDOW range from ``effective_range_nm`` above -- a window-range
#: comparison made the full/wide split a function of widget aspect
#: ratio, so the range ladder's own 160 NM top stop stayed full-detail
#: on a portrait screen and silently dropped the coastline on a
#: landscape one (the finding this constant's value now reflects: 160
#: NM is the range ladder's own shipped/default maximum --
#: ``MovingMap.range_ladder``, hard-clamped by ``_range_bounds`` --
#: measured safe on the water-na 2026q2r6 pack at every shipped aspect,
#: 120,576 vertices worst case against the 150k budget). Mirrored
#: rather than imported because the guard has to run before any widget
#: exists; kept honest by
#: ``test_the_wide_water_cliff_constant_still_matches_the_renderer``,
#: which imports the real thing and requires the two to agree.
WATER_FULL_OVERLAY_MAX_NM = 160.0


def wide_water_mode(range_nm: float, w: int = SCENE_W, h: int = SCENE_H,
                    anchor_frac: float = _OWNSHIP_ANCHOR_FRAC) -> bool:
    """Is a render at nominal ``range_nm`` on the WIDE side of the
    cliff -- ocean dropped, lakes size-filtered?

    This is ``TerrainLayer._draw_water_numpy``'s ``wide`` flag,
    predicted from the NOMINAL range alone (AER-1149) -- ``w``/``h``/
    ``anchor_frac`` are accepted only so callers that still pass a
    geometry keep working; the answer no longer depends on them,
    which is the point (the same pilot-selected range means the same
    thing on every shipped screen layout)."""
    return range_nm > WATER_FULL_OVERLAY_MAX_NM


def full_overlay_max_nominal_nm(w: int = SCENE_W, h: int = SCENE_H,
                                anchor_frac: float = _OWNSHIP_ANCHOR_FRAC
                                ) -> float:
    """The largest nominal (pilot-facing) ``range_nm`` at which the full
    water overlay still draws.

    AER-1149: geometry-independent by construction now -- the gate
    compares the widget's own ``range_nm`` to the constant directly, so
    this is just the constant. ``w``/``h``/``anchor_frac`` are accepted
    for call-site compatibility with the pre-AER-1149 geometry-dependent
    version (203.7 NM at 650x1040, 170.0 NM at 300x300, 123.6 NM at
    800x480) and otherwise ignored."""
    return WATER_FULL_OVERLAY_MAX_NM


def cliff_margin(range_nm: float, w: int = SCENE_W, h: int = SCENE_H,
                 anchor_frac: float = _OWNSHIP_ANCHOR_FRAC) -> dict:
    """How close a scene sits to the wide-water cliff, as numbers a
    skip/fail message can quote.

    ``fraction`` is signed against the NOMINAL range (AER-1149):
    negative = full overlay with that much room to spare, positive =
    already wide by that much. ``effective_nm`` (the query window) is
    still reported -- it is what the pack is actually asked to cover --
    but no longer decides ``wide``."""
    eff = effective_range_nm(range_nm, w, h, anchor_frac)
    frac = (range_nm - WATER_FULL_OVERLAY_MAX_NM) / WATER_FULL_OVERLAY_MAX_NM
    return {
        "nominal_nm": range_nm,
        "effective_nm": round(eff, 1),
        "threshold_nm": WATER_FULL_OVERLAY_MAX_NM,
        "wide": range_nm > WATER_FULL_OVERLAY_MAX_NM,
        "fraction": round(frac, 4),
        "nominal_at_cliff_nm": round(
            full_overlay_max_nominal_nm(w, h, anchor_frac), 1),
        "widget": (w, h),
    }


def render_window_span_deg(range_nm: float, lat: float,
                           w: int = SCENE_W, h: int = SCENE_H,
                           anchor_frac: float = _OWNSHIP_ANCHOR_FRAC
                           ) -> tuple[float, float]:
    """(lat_span_deg, lon_span_deg) of the box a render at ``range_nm``
    actually queries the water pack for.

    Mirrors ``TerrainLayer._render``'s window sizing followed by
    ``WaterDB.polygons_in_range``'s degree box (``range_nm / 60`` in
    latitude, divided by ``cos(lat)`` in longitude). Duplicated rather
    than imported because the value is needed before any widget exists
    -- to decide whether a fixture pack is even big enough to measure
    against -- and importing either module pulls in PyQt6.

    This is the arithmetic that shows a 2x2 deg fixture window does not
    cover a 160 NM render: at 650x1040 the window spans 7.9 deg of
    latitude and, at Raleigh, 9.7 deg of longitude -- 76 square degrees
    against the cutter's 9."""
    eff = effective_range_nm(range_nm, w, h, anchor_frac)
    lat_span = 2.0 * eff / _NM_PER_DEG_LAT
    lon_span = lat_span / max(1e-6, math.cos(math.radians(lat)))
    return lat_span, lon_span


#: The declaration every cut pack carries --
#: ``make_map_perf_fixture.FOOTPRINT_MANIFEST_NAME``. Duplicated rather
#: than imported for the same reason as everything else in this module:
#: the value is wanted before any widget (or tool) is loaded, and
#: ``pack_declared_bbox`` has to answer for a pack that was cut by some
#: other checkout's copy of the tool. Kept honest by
#: ``test_the_manifest_name_still_matches_the_cutter``.
FOOTPRINT_MANIFEST_NAME = "footprint.json"

#: How far a declared scene centre may sit from the centre being
#: measured before the manifest is treated as describing a different
#: pack. ``SCENES`` here and ``make_map_perf_fixture.SCENES`` both carry
#: the centres as exact decimal literals and the manifest round-trips
#: them through JSON, so the honest tolerance is "float noise", not a
#: geographic allowance. Anything larger is a different scene and must
#: be caught, not accommodated.
_CENTRE_EPS_DEG = 1e-6


def _load_footprint_manifest(pack_root) -> dict | None:
    if pack_root is None:
        return None
    path = Path(os.fspath(pack_root)) / FOOTPRINT_MANIFEST_NAME
    try:
        manifest = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return manifest if isinstance(manifest, dict) else None


def pack_declared_centre(pack_root) -> tuple[float, float] | None:
    """(lat, lon) the pack states it was cut around, or ``None``.

    The provenance half of the declaration -- see ``pack_coverage`` for
    why a bbox is worthless without it."""
    manifest = _load_footprint_manifest(pack_root)
    if manifest is None:
        return None
    try:
        return float(manifest["lat"]), float(manifest["lon"])
    except (KeyError, TypeError, ValueError):
        return None


def pack_declared_bbox(pack_root, layer: str = "water"
                       ) -> tuple[float, float, float, float] | None:
    """(min_lat, max_lat, min_lon, max_lon) that a pack DECLARES it
    covers for *layer*, read from its ``footprint.json``, or ``None``
    when the pack carries no declaration (a pre-AER-1142 cut) or the
    declaration does not name *layer*.

    This is the objective fact about a pack's extent, and it is the one
    a coverage decision should be made on. ``water_coverage_bbox``
    below is an inference from the data and it is not equivalent -- see
    ``pack_coverage`` for the measurement of where they diverge."""
    manifest = _load_footprint_manifest(pack_root)
    if manifest is None:
        return None
    try:
        bbox = manifest["layers"][layer]["bbox"]
    except (KeyError, TypeError):
        return None
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return None
    try:
        return tuple(float(v) for v in bbox)
    except (TypeError, ValueError):
        return None


def water_coverage_bbox(water_db) -> tuple[float, float, float, float] | None:
    """(min_lat, max_lat, min_lon, max_lon) of the polygons actually
    PRESENT in a water pack, or ``None`` if it holds none.

    Note what this is and is not. It is the extent of the data; it is
    NOT the box the pack was cut to, and it is not safe to read as one.
    ``make_map_perf_fixture.cut_water`` selects on bbox OVERLAP and
    keeps every selected polygon WHOLE (deliberately -- a renderer
    positioned inside the window must get the whole polygon), so a
    single ocean polygon straddling the cut edge drags this MIN/MAX out
    past the cut in the direction that reads as MORE coverage.

    Measured on the published North America pack (water-na, 2026q2r6),
    Raleigh, against the 160 NM window: a 7.60 x 11.00 deg cut, 0.127
    deg SHORT of the window in latitude at both ends, yields a data
    extent of 30.9995..40.0005 lat -- which contains the window, so
    this proxy reports covered when the cut does not. The over-report
    happens to stop at ~0.13 deg there only because that pack's ocean
    polygons are themselves clipped to whole-degree tiles; nothing in
    the format guarantees that.

    So: cross-check only. ``pack_declared_bbox`` decides."""
    import sqlite3
    try:
        con = sqlite3.connect(f"file:{os.fspath(water_db)}?mode=ro", uri=True)
    except Exception:
        return None
    try:
        row = con.execute(
            "SELECT MIN(min_lat), MAX(max_lat), MIN(min_lon), MAX(max_lon) "
            "FROM water_polygons").fetchone()
    except Exception:
        return None
    finally:
        con.close()
    if row is None or row[0] is None:
        return None
    return tuple(float(v) for v in row)


def footprint_covers_window(bbox, lat: float, lon: float, range_nm: float,
                            w: int = SCENE_W, h: int = SCENE_H,
                            source: str = "bbox") -> dict:
    """Does a pack's coverage ``bbox`` contain the render window at
    ``range_nm``?

    This is the guard that decides whether a VOLUME budget measured
    against a given pack is evidence. A pack smaller than the window
    silently truncates the scene: the renderer draws every polygon it
    can find, finds fewer, and the vertex count comes in low -- which
    reads as a comfortable pass. Measured on the real North America
    pack, a 160 NM Raleigh render rasterizes 102,034 vertices; against
    a 3x3 deg cut of the same pack it rasterizes 14,259, or 14% of the
    truth, against a 150,000 budget. Nothing is wrong with the
    renderer in the second case and nothing goes red -- the budget has
    simply stopped measuring anything, which is the exact failure mode
    MP8a deferred this row to avoid.

    Returns a dict rather than a bool so the caller can say WHY in a
    skip message: a number the reader can act on beats "insufficient
    coverage".

    *source* is echoed back untouched and names where ``bbox`` came
    from ("declared" / "data-extent"). It changes no arithmetic; it is
    carried so a skip message states its own evidence, because the two
    sources are not equally trustworthy and a reader acting on the
    message needs to know which one answered."""
    lat_span, lon_span = render_window_span_deg(range_nm, lat, w, h)
    need = {"lat_lo": lat - lat_span / 2.0, "lat_hi": lat + lat_span / 2.0,
            "lon_lo": lon - lon_span / 2.0, "lon_hi": lon + lon_span / 2.0}
    if bbox is None:
        return {"covers": False, "source": source,
                "reason": "pack declares no coverage and holds no water "
                          "polygons",
                "need": need, "have": None,
                "need_span_deg": (round(lat_span, 3), round(lon_span, 3)),
                "have_span_deg": None, "pack_area_vs_window": None}
    have = {"lat_lo": bbox[0], "lat_hi": bbox[1],
            "lon_lo": bbox[2], "lon_hi": bbox[3]}
    covers = (have["lat_lo"] <= need["lat_lo"]
              and have["lat_hi"] >= need["lat_hi"]
              and have["lon_lo"] <= need["lon_lo"]
              and have["lon_hi"] >= need["lon_hi"])
    have_area = ((have["lat_hi"] - have["lat_lo"])
                 * (have["lon_hi"] - have["lon_lo"]))
    need_area = lat_span * lon_span
    return {
        "covers": covers, "source": source,
        "need": need, "have": have,
        "need_span_deg": (round(lat_span, 3), round(lon_span, 3)),
        "have_span_deg": (round(have["lat_hi"] - have["lat_lo"], 3),
                          round(have["lon_hi"] - have["lon_lo"], 3)),
        "pack_area_vs_window": round(min(1.0, have_area / need_area), 3)
        if need_area > 0 else None,
        "reason": "" if covers else (
            f"pack covers ({source}) "
            f"{have['lat_lo']:.2f}..{have['lat_hi']:.2f} lat / "
            f"{have['lon_lo']:.2f}..{have['lon_hi']:.2f} lon; a {range_nm:.0f} "
            # w/h, not SCENE_W/SCENE_H: this function is called at other
            # geometries and the window it computed is the caller's, so
            # quoting the module default here would misreport it.
            f"NM render at {w}x{h} reads "
            f"{need['lat_lo']:.2f}..{need['lat_hi']:.2f} lat / "
            f"{need['lon_lo']:.2f}..{need['lon_hi']:.2f} lon "
            f"({lat_span:.2f} x {lon_span:.2f} deg)"),
    }


def pack_coverage(pack_root, water_db, lat: float, lon: float,
                  range_nm: float, w: int = SCENE_W, h: int = SCENE_H,
                  layer: str = "water") -> dict:
    """The coverage verdict for a pack, decided on what the pack
    DECLARES and cross-checked against what it actually holds.

    AER-1156. The guard used to decide on ``water_coverage_bbox`` alone,
    which is an inference from the data and can over-report (see that
    function). Since AER-1142 every cut pack writes ``footprint.json``
    stating the exact bbox each layer was cut to, and
    ``footprint_manifest``'s own docstring says why a consumer should
    read it: "a consumer test can check 'is my window a subset of what
    this pack DECLARES it covers?' ... instead of re-deriving the
    cutter's own geometry rule a second time".

    Precedence, and the reason for it:

    * ``declared`` wins when present. It is a written fact about the
      cut, not an inference from what happened to land inside it.
    * ``data-extent`` is the fallback, for a pre-AER-1142 pack that
      carries no declaration. It still beats no guard at all, and the
      returned ``source`` says which answered so a skip message cannot
      overstate its own evidence.

    The declaration is not taken on trust: it is first checked to be
    describing THIS scene. ``footprint.json`` carries the centre it was
    cut around, and a declaration whose centre is not the centre being
    measured is a declaration about some other pack -- the truth-blind
    case, where a PASS is a measurement of nothing. That is refused
    outright rather than fallen back from, because a mismatched
    manifest means the pack's provenance is unknown and the data extent
    would be answering for a pack nobody can name.

    Note what is deliberately NOT cross-checked: the data extent is not
    required to sit inside the declared box. ``cut_water`` keeps edge
    polygons whole, so overhang is normal, and on the published
    water-na pack the largest single polygon bbox spans 5.46 deg of
    latitude and 7.99 of longitude -- a tolerance loose enough not to
    false-alarm on that would be loose enough to catch nothing. The
    centre check has teeth and cannot false-alarm; a span tolerance has
    neither property. The extent is returned alongside regardless, so a
    reader can see both numbers."""
    declared = pack_declared_bbox(pack_root, layer)
    centre = pack_declared_centre(pack_root)
    extent = water_coverage_bbox(water_db) if water_db else None

    if declared is not None and centre is not None:
        d_lat, d_lon = centre
        if (abs(d_lat - lat) > _CENTRE_EPS_DEG
                or abs(d_lon - lon) > _CENTRE_EPS_DEG):
            return {
                "covers": False, "source": "declared",
                "declared_bbox": declared, "data_extent_bbox": extent,
                "centre_matches": False,
                "need": None, "have": None,
                "need_span_deg": None, "have_span_deg": None,
                "pack_area_vs_window": None,
                "reason": (
                    f"{FOOTPRINT_MANIFEST_NAME} declares a pack centred on "
                    f"({d_lat}, {d_lon}) but this measurement is of "
                    f"({lat}, {lon}) -- the manifest does not describe this "
                    "pack, so neither its declaration nor the pack's own "
                    "extent can be trusted to say what was cut"),
            }

    bbox, source = ((declared, "declared") if declared is not None
                    else (extent, "data-extent"))
    out = footprint_covers_window(bbox, lat, lon, range_nm, w, h,
                                  source=source)
    out["declared_bbox"] = declared
    out["data_extent_bbox"] = extent
    out["centre_matches"] = None if centre is None else True
    return out


# ---------------------------------------------------------------------------
# Widget construction + the individual measurements
# ---------------------------------------------------------------------------

def build(bench, app, scene="raleigh", *, tile_path="", water_db="",
          highway_db="", range_nm=40.0, water_raster="numpy",
          w=SCENE_W, h=SCENE_H, water_max_vertices=WATER_MAX_VERTICES,
          extra=()):
    """A MovingMap wired exactly the way the MP7 bench wires it, warmed
    with the same first-tick settle ``run_scenario`` does."""
    lat, lon = SCENES[scene]["lat"], SCENES[scene]["lon"]
    argv = ["--w", str(w), "--h", str(h), "--lat", str(lat), "--lon", str(lon)]
    if tile_path:
        argv += ["--tile-path", str(tile_path)]
    if water_db:
        argv += ["--water-db", str(water_db), "--water-raster", water_raster,
                 "--water-max-vertices", str(water_max_vertices)]
    if highway_db:
        argv += ["--highway-db", str(highway_db)]
    argv += list(extra)
    widget = bench.build_widget(bench._parse_args(argv))
    widget.range_nm = range_nm
    widget.show()
    widget._build_layers()
    bench._pump(app, 0.3)
    return widget


def _await_publish(bench, app, widget, layer_id="terrain",
                   timeout_s=RENDER_TIMEOUT_S, step_s=0.5):
    """Pump until ``layer_id`` has published at least one render, or the
    timeout expires. Returns the snapshot, or ``None`` on timeout -- a
    timeout is "not measured", never a fast number."""
    waited = 0.0
    while waited < timeout_s:
        bench._pump(app, step_s)
        waited += step_s
        snap = widget.perf.snapshot()
        ls = snap["layers"].get(layer_id)
        if ls and ls.get("jobs_published", 0) >= 1:
            return snap
    return None


def measure_water_volume(bench, app, scene, tile_path, water_db,
                         range_nm=160.0, water_raster="numpy",
                         w=SCENE_W, h=SCENE_H,
                         water_max_vertices=WATER_MAX_VERTICES) -> dict | None:
    """Section 5's "water vertices rasterized at 160 NM" row, plus the
    companions that make it a real observation (see the volume test)."""
    widget = build(bench, app, scene, tile_path=tile_path, water_db=water_db,
                   range_nm=range_nm, water_raster=water_raster, w=w, h=h,
                   water_max_vertices=water_max_vertices)
    snap = _await_publish(bench, app, widget)
    widget.hide()
    app.processEvents()
    if snap is None:
        return None
    out = dict(snap["water"])
    out["terrain_jobs_published"] = snap["layers"]["terrain"]["jobs_published"]
    out["terrain_render_ms"] = snap["layers"]["terrain"]["max_render_ms"]
    return out


def measure_terrain_render_ms(bench, app, scene, tile_path, water_db,
                              range_nm, **kw):
    """Section 5: "terrain+water worker render @ <range>"."""
    widget = build(bench, app, scene, tile_path=tile_path, water_db=water_db,
                   range_nm=range_nm, **kw)
    snap = _await_publish(bench, app, widget)
    widget.hide()
    app.processEvents()
    if snap is None:
        return None
    return snap["layers"]["terrain"]["max_render_ms"]


def measure_pinch_out(bench, app, scene, tile_path, water_db, **kw):
    """Section 5's "settle latency, pinch 10 -> 160 NM" and "GUI-thread
    starved ... max gap" rows, from one MP7 ``pinch_out``.

    Returns both from the same run on purpose: they are two readings of
    one gesture, and measuring them in separate runs would let a
    baseline pair a settle from a quiet run with a gap from a busy one."""
    widget = build(bench, app, scene, tile_path=tile_path, water_db=water_db,
                   range_nm=10.0, **kw)
    bench.scenario_pinch_out(app, widget)
    snap = widget.perf.snapshot()
    widget.hide()
    app.processEvents()
    return {
        "settle_latency_ms_pinch_out": snap["settle_latency_ms"],
        "probe_max_gap_ms_pinch": snap["probe"]["max_ms"],
        "probe_p95_gap_ms_pinch": snap["probe"]["p95_ms"],
        "probe_gaps_over_warn": snap["probe"]["over_count"],
        "terrain_jobs_published":
            snap["layers"].get("terrain", {}).get("jobs_published", 0),
    }


def measure_paint_p95(bench, app, scene, tile_path, water_db,
                      range_nm=40.0, **kw):
    """Section 5: "map paint p95 @ 40 NM, all layers". Driven with the
    MP7 rotate sweep, which is the scenario that paints most (one paint
    per frame-clock tick for 3 s) -- a p95 over 20 paints would be a
    percentile of noise."""
    widget = build(bench, app, scene, tile_path=tile_path, water_db=water_db,
                   range_nm=range_nm, **kw)
    _await_publish(bench, app, widget)
    widget.perf.paint_ms.__init__()          # measure the sweep only
    bench.scenario_rotate(app, widget)
    snap = widget.perf.snapshot()
    widget.hide()
    app.processEvents()
    return {"paint_ms_p95_40nm": snap["paint_ms"]["p95"],
            "paint_count": snap["paint_ms"]["count"]}


def measure_roads_render_ms(bench, app, scene, tile_path, highway_db,
                            range_nm=80.0, **kw):
    """Section 5: "roads worker render @ 80 NM". ``None`` when no highway
    pack was supplied -- the honest answer, and the reason
    ``build_baseline`` simply omits the row rather than recording a
    zero that would later gate at 1.5x of nothing."""
    if not highway_db:
        return None
    widget = build(bench, app, scene, tile_path=tile_path,
                   highway_db=highway_db, range_nm=range_nm, **kw)
    snap = _await_publish(bench, app, widget, layer_id="roads")
    widget.hide()
    app.processEvents()
    if snap is None:
        return None
    return snap["layers"]["roads"]["max_render_ms"]


def measure_all(*, tile_path="", water_db="", highway_db="", scene="raleigh",
                w=SCENE_W, h=SCENE_H,
                water_max_vertices=WATER_MAX_VERTICES) -> dict:
    """Every baselineable metric, one pass. Used by
    ``tools/map_perf_baseline.py mint``."""
    from PyQt6.QtWidgets import QApplication
    bench = load_bench()
    lat, lon = SCENES[scene]["lat"], SCENES[scene]["lon"]
    bench._bootstrap_fix_db(lat, lon, 90.0, 3000.0)
    app = QApplication.instance() or QApplication([])
    common = dict(w=w, h=h, water_max_vertices=water_max_vertices)

    out = {}
    out["terrain_render_ms_160nm"] = measure_terrain_render_ms(
        bench, app, scene, tile_path, water_db, 160.0, **common)
    out["terrain_render_ms_300nm"] = measure_terrain_render_ms(
        bench, app, scene, tile_path, water_db, 300.0, **common)
    out.update({k: v for k, v in measure_pinch_out(
        bench, app, scene, tile_path, water_db, **common).items()
        if k in ("settle_latency_ms_pinch_out", "probe_max_gap_ms_pinch")})
    out["paint_ms_p95_40nm"] = measure_paint_p95(
        bench, app, scene, tile_path, water_db, **common)["paint_ms_p95_40nm"]
    out["roads_render_ms_80nm"] = measure_roads_render_ms(
        bench, app, scene, tile_path, highway_db, **common)
    return out
