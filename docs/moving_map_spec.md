# Moving Map — specification

Status: SPEC (2026-07-05). Development has not started; work will
happen on a dedicated branch off `display-changes`. Companion specs:
`svs_rendering.md` (rendering lessons), pyAvMap `docs/MFD-Assessment`
(prior art; see section 2), makerplane-data
`docs/canfix_configurator.md` (provider-model precedent).

## 1. What this is

A top-down **moving map instrument** for pyEfis: a widget placed and
sized like any other through the configurator, showing ownship over
terrain with toggleable information layers — terrain relief, airports
with FAA sectional symbology, navaids/waypoints/airways, and an open
**layer-provider model** so future sources (ADS-B weather/traffic via
Stratux, lightning, airspace, range rings, flight plan) plug in
without touching the core.

It is "much more than an instrument", but architecturally it IS one:
registered in `screenbuilder_factory`, options in the editor schema,
a twin preview in the configurator, FIX-database position/track
driving it. Everything we learned shipping the SVS applies.

## 2. Relationship to pyAvMap (decided direction)

pyAvMap is the dormant PyQt5 raster moving map. The MFD assessment
verdict was "scoped yes — port to PyQt6 + screenbuilder instrument".
This spec **supersedes the port**: we build a new, vector-first
pyEfis-native widget that reuses pyEfis's own data backends (the SVS
collectors' sqlite/HGT stack) rather than pyAvMap's chart-raster
pipeline. Rationale: the data, caching, and perf lessons already live
in this repo; a raster **sectional-chart layer** remains attractive
later and slots in as one more provider (section 6), which is where
pyAvMap's tile logic can be mined if wanted.

## 3. Widget architecture

- **Class**: `pyefis/instruments/map/__init__.py`, `MovingMap(QWidget)`
  (plain QWidget + QPainter; no QGraphicsScene — the map repaints as a
  whole on pan/zoom, and layer pixmap caching does the heavy lifting;
  no GL requirement, so it renders offscreen for CI/screenshots and
  runs on GL-less panels).
- **FIX inputs**: LAT/LONG (position), TRACKM/HEAD (orientation), GS
  (ground speed for the track vector), ALT (terrain-relative coloring,
  later TAWS layer). Standard fail/old/bad handling: stale position
  greys the ownship + annunciates; the map does NOT freeze silently.
- **Projection**: local azimuthal-equidistant about the screen
  center — x = (lon-lon0)·M·cos(lat0), y = (lat-lat0)·M, the same
  small-area flat-earth math the SVS uses (`M_PER_DEG_LAT`, shared
  helper). Error is negligible below ~250 NM range. One
  `MapTransform` object (center, range_nm, rotation, widget size)
  owns ALL world->screen math; every layer receives it. No layer does
  its own projection arithmetic (the `_project_point` lesson).
- **Orientation modes**: `north_up` and `track_up` (option +
  runtime-togglable). Track-up rotates the transform, not the layers.
- **Range**: `range_nm` option (default 10), stepped through a
  configurable ladder (2/5/10/20/40/80/160) by HMI actions.
- **Ownship**: fixed at a configurable screen anchor
  (`ownship_position`, percent up from bottom, default 50; 30 gives
  the classic look-ahead offset). Aircraft symbol reuses the AI's
  `aircraft_symbol`/`symbol_color`/`symbol_scale` style vocabulary,
  drawn top-down.

## 4. Layer-provider model (the core design)

```python
class MapLayer:                    # pyefis/instruments/map/layers/base.py
    id: str                        # "terrain", "airports", ...
    label: str                     # button/menu text
    z: int                         # paint order (terrain lowest)
    default_on: bool
    def configure(self, config): ...        # per-layer options dict
    def collect(self, view):  ...           # ASYNC: gather/derive data for
                                            # the view window (worker thread)
    def paint(self, painter, xform): ...    # SYNC: draw cached results
    def on_toggle(self, on): ...            # free/acquire resources
```

- **Registry**: `LAYER_REGISTRY` dict + entry-point-style registration
  so out-of-tree layers can be added (the engine/airport provider
  precedent). The widget instantiates layers named in its config,
  ordered by `z`.
- **Threading contract (SVS issue #74 lessons, non-negotiable)**:
  `collect()` runs on worker threads serialised by ONE shared
  collect slot; results are immutable snapshots swapped in for
  `paint()`. Per-feature work in collect() must be vectorised numpy /
  sqlite — no Python per-element loops on the GIL during cruise.
  `paint()` only blits pixmaps and draws pre-transformed primitives.
- **Caching**: each layer caches keyed on (tile/window, range bucket,
  data edition). Terrain caches rendered QImages per tile+zoom;
  vector layers cache query results per window and re-project each
  frame (cheap) or cache pixmaps when static in world space.
- **Real-time toggles**: HMI actions (see 7) flip `layer.enabled` and
  repaint; toggling never reloads data that is still cached.

## 5. v1 layers (Bill's list)

### 5.1 Terrain (z=0, default on)
- Source: the GLO-30/SRTM HGT tree already on the Pi
  (`/data/makerplane-data/terrain/tiles`) through the existing
  `TileCache` — same tiles as the SVS, zero new data.
- Render: hypsometric relief — numpy hillshade (NW light) + the
  sectional-style elevation palette, downsampled per zoom via the
  Track-1c mip pyramid (`TileCache.get_mip` — already built and
  cached; the map is its second consumer). Rendered per-tile to
  QImage on the worker, LRU-cached; repaint = blit + rotate.
- Option `terrain_mode`: `relief` (absolute hypsometric) or
  `caution` (TAWS-style relative coloring vs ALT: amber <1000 ft,
  red <100 ft below aircraft — the SVS clearance palette, top-down).

### 5.2 Airports (z=30, default on)
- Source: NASR `airports.sqlite` via the existing airport_db
  (multi-provider merge included — Canada shows up for free).
- **FAA sectional symbology** (Aeronautical Chart Users' Guide):
  - towered = blue, non-towered = magenta (tower data: NASR TWR file
    — add to the airports pack build; until then all magenta like a
    chart without tower info, annunciated in docs);
  - hard-surface runways 1500-8069 ft: circle with runway-orientation
    tick(s) inside, drawn from the real runway geometry we already
    carry; >8069 ft: runway outline symbol (no circle); unpaved:
    plain circle; seaplane/heli: reserved symbols later.
  - services (fuel) tick marks around the circle: data-gated, later.
  - Labels: ident, declutter by zoom (full name off; ident-only
    under 40 NM; nothing above 80 NM except selected).
- Decluttering is per-zoom and deterministic (grid-bucket keep-top-N
  by runway length) so the picture is stable frame to frame.

### 5.3 Navaids / waypoints / airways (z=40/45, default: navaids on,
airways off)
- **New data**: NASR NAV (VOR/NDB/DME), FIX (named fixes), AWY
  (victor/T-route segments) files -> a new `navdata` pack member
  (`navaids.sqlite`: navaids, fixes, airway segments with from/to
  fix geometry). Built in makerplane-data by the proven cyclical
  pipeline (28-day AIRAC, staged-next included). This is the one new
  data workstream v1 needs; it is already on the makerplane-data
  roadmap ("navaids/fixes = quick win").
- Symbols: sectional-standard — VOR compass rose hexagon, VORTAC /
  VOR-DME variants, NDB stippled disc, fixes as open triangles;
  airways as light blue lines with ident boxes at midpoints.
- CIFP remains GPL-deferred; NASR covers all three feature classes
  for US. (Procedure geometry = future layer, not v1.)

### 5.4 Flight plan (z=45, default on, FP6, billmallard/pyEfis#184)

- **No database, no worker** — pure `paint()` like `RangeRingsLayer`
  (5.5): the whole route block, active-leg state and direct-to point
  already live on the FIX bus via the FP4 `flightplan.fixbridge.FixBridge`
  read-back (`read_route`/`read_engine`/`read_direct_to`). With no FP1
  keys published, the layer paints nothing and never raises (the
  construct-never-raises convention, `CLAUDE.md`).
- Legs between consecutive route slots: past (before the active leg)
  gray `#808080` 2 px, the active leg magenta `#ff00ff` 3 px drawn from
  `FPLFRLAT/LON` (the direct-to activation point when it differs from
  the previous slot) to the TO waypoint (`WPLAT/WPLON`), next/future
  legs white 2 px. Off-route direct-to (`FPLSTATE`=DIRECT,
  `FPLACTLEG`=0) draws every plan leg gray plus a separate magenta line
  from the activation point to `DTO*`. Great-circle legs are drawn as
  straight screen segments — no subdivision: at a leg near the edge of
  the 160 NM range the chord-vs-geodesic pixel error stays under 0.5 px
  through an 80 NM leg and only crosses 1 px past ~110 NM (verified
  numerically against `MapTransform.to_screen`).
- Waypoint symbols reuse the 5.2/5.3 glyph vocabulary (circle/hexagon/
  stippled-disc/triangle) colored by route status rather than navdata
  source; the current TO waypoint (or the DTO point, off-route) is
  ringed magenta. Ident labels take the role (`FAF`/`MAP`/`IAF`/`MAHP`)
  as a suffix when set. While suspended at the MAP with LNAV armed
  (`FPLSTATE`=SUSP, `FPLAPR`=LNAV), a dashed magenta line extends the
  final course past the MAP so the pilot still sees where it leads —
  the exact length is a look call, not a navigation guarantee.
- Declutter: labels off above 80 NM (symbols stay), nothing draws
  above 160 NM except the legs.
- Prop `layer_flight_plan` (default on); the `LiveBind` runtime toggle
  rides #96 when it lands (layer toggles are GUI-thread-only today).

### 5.5 Range rings (z=20, default on)

Concentric half/full-range rings with distance labels — the
provider-model proof (section 4): trivial by design, ships v1.

## 6. Future layers (design targets for the provider seam)

Named now so the interfaces stay honest: `traffic` (ADS-B via
Stratux — FIX keys or a side TCP feed; symbol set = TIS-B standard),
`metar_flags` / `fisb_weather` (Stratux FIS-B: NEXRAD raster as a
tile layer — raster layers must be first-class), `lightning`,
`airspace` (NASR CLS_ARSP/SUA — high value, data build like 5.3),
`obstacles` (DOF, already on-device), `sectional_raster` (FAA VFR
chart tiles; mine pyAvMap), and graphical editing on the map (FP10:
hit-test a waypoint -> Direct To / Insert). Each is "a provider +
maybe a pack"; none require core changes if sections 4's contract
holds.

## 7. Controls (buttons/encoder — hardware pending)

The map exposes HMI actions only; binding them to physical buttons /
touch / encoder is screen YAML, decided when the controller exists:

- `map:range_up` / `map:range_down` — step the range ladder.
- `map:orient` — toggle north-up / track-up.
- `map:layer:<id>` — toggle a layer (e.g. `map:layer:airports`).
- `map:layers` — cycle a small on-map layer legend/menu (encoder-
  friendly single-button UX, mirrors the existing listbox patterns).
A transient on-map legend chip shows current range + active layers
for 3 s after any action (so button UX works blind of the menu).

## 8. Configurator integration (standard pipeline)

- Factory registration + Props: `range_nm`, `orientation`,
  `ownship_position`, `layers` (per-layer default-on booleans:
  `layer_terrain`, `layer_airports`, `layer_navaids`,
  `layer_airways`, `layer_flight_plan`, `layer_range_rings`),
  `terrain_mode`, symbol options, `db paths` (default to
  /data/makerplane-data locations).
- Editor twin: static top-down preview — a canvas rendering a small
  baked terrain patch (the SVS preview-patch pattern; one scene is
  enough) with sample airport/navaid symbols honoring the layer
  checkboxes. Fidelity rule applies: symbols in the twin ARE the
  widget's symbol code paths, ported once.
- `offscreen_renderable: true` (QPainter-only) — reference PNGs via
  `tools/render_instrument.py`, so the twin gets real renders to
  match, unlike the GL-locked SVS.

## 9. Performance budget (Pi 5, alongside the SVS)

- Target: smooth at 5 Hz map refresh (position interpolation may
  drive up to 10 Hz); the map must never steal the SVS's frame
  budget: collect work rides the SAME shared collect slot the SVS
  collectors use, so the two instruments serialise instead of
  stacking GIL bursts.
- Terrain tile render: <100 ms/tile on the worker, amortised by LRU;
  pan/zoom shows cached tiles immediately, refines async.
- Vector layers: <5 ms paint at 200 features on-screen; declutter
  keeps N bounded.
- Memory: tile cache capped (~150 MB), navaids/airports queries
  windowed by view.

### 9.1 Gesture benchmark harness (MP7) JSON schema

`tools/bench_map_gestures.py` (briefs/map_gesture_perf_plan.md section 4,
pyEfis #98) builds a real `MovingMap` offscreen against the mock FIX db
`conftest.py` uses for the unit tests and drives it through a named
scenario (`pinch_out`, `pinch_in`, `rotate`, `pan`, `ladder`, or `all`),
pumping the Qt event loop at 1 kHz so the widget's own gesture gating
(MP1), worker publication (MP2), frame clock (MP3) and MP6 perf counters
all run as they would live. Output is always a JSON **array** (one
element per scenario run, so `--scenario all` and a single `--scenario
pinch_out` share one schema) written to `--out` or stdout; progress/
summary lines go to stderr so stdout stays pipeable. Each element:

```jsonc
{
  "schema_version": 1,
  "rev": "b4d3349",            // git short SHA, "" outside a checkout
  "host": "beelinkpyefis",     // socket.gethostname()
  "scenario": "pinch_out",
  "widget": {"w": 650, "h": 1040},
  "lat": 35.8, "lon": -78.8,
  "duration_s": 6.48,          // wall-clock time the scenario itself took
  "params": {"range_from_nm": 10.0, "range_to_nm": 160.0,
             "range_actual_nm": 160.0, "events": 90, "event_hz": 60.0,
             "hold_s": 5.0},   // scenario-specific inputs, for repro
  "counters": {                // MapPerfStats.snapshot() -- every MP6 counter
    "frames_painted": 50,
    "paint_ms": {"p50": 0.7, "p95": 1.0, "max": 5.5, "count": 50},
    "layers": {                // keyed by layer id; a layer with no jobs
      "terrain": {"jobs_requested": 1, "jobs_started": 1,
                  "jobs_published": 1, "jobs_superseded": 0,
                  "last_render_ms": 12.3, "max_render_ms": 12.3}
    },                        // (omitted entirely) never appears here
    "water": {"polygons_before": 0, "vertices_before": 0,
              "polygons_after": 0, "vertices_after": 0,
              "qpointf_count": 0},
    "settle_latency_ms": 97.0, // null if no gesture completed a settle
    "probe": {"p50_ms": 10.7, "p95_ms": 10.8, "max_ms": 11.0,
              "count": 256, "over_count": 0}
  },
  "summary": "pinch_out: 6.48s, 50 paints (p50=0.7 p95=1.0 max=5.5 ms), "
             "settle=97ms, gui gap p95=10.8ms max=11.0ms >50ms=0; "
             "terrain req=1 pub=1 superseded=0"
}
```

`--budget <path>` loads a JSON map of `{scenario: [{"path": "a.b.c",
"max": x} | {"min": x}, ...]}`, evaluates each dotted `path` against that
scenario's `counters` (e.g. `"layers.terrain.jobs_requested"`,
`"settle_latency_ms"`, `"probe.max_ms"`), and exits non-zero if any bound
is violated (a `path` absent from a run -- e.g. a layer with no data
configured -- is skipped with a warning, not a failure). Example
budgets file matching the acceptance table in section 5 of the brief:

```json
{
  "pinch_out": [
    {"path": "layers.terrain.jobs_requested", "max": 1},
    {"path": "layers.terrain.jobs_superseded", "max": 0},
    {"path": "settle_latency_ms", "max": 600},
    {"path": "probe.max_ms", "max": 50}
  ],
  "rotate": [{"path": "frames_painted", "max": 90}]
}
```

### 9.2 Moving-position mode (AER-679) JSON schema

`tools/bench_map_gestures.py --moving-position` (briefs/
map_gesture_perf_plan.md section 5, AER-679) drives LAT/LONG continuously
at `--gs`/`--heading`/`--position-hz` for `--duration` seconds, instead of
running a static `--scenario` -- every gesture scenario above pins LAT/
LONG, a regime AER-677 found the aircraft is never actually in (the SVS
frame gap collapses from ~25 ms to ~699 ms only once real position motion
is driven). One result record, appended to the same JSON array the
gesture scenarios use (`"scenario": "moving_position"`):

```jsonc
{
  "schema_version": 1,
  "rev": "b4d3349", "host": "beelinkpyefis",
  "scenario": "moving_position",
  "target": "both",              // "map" | "svs" | "both"
  "widget": {"w": 650, "h": 1040},
  "lat": 35.8, "lon": -78.8,
  "duration_s": 40.02,
  "params": {"gs_kt": 130.0, "heading_deg": 280.0,
             "position_hz": 20.0, "duration_s": 40.0},
  "counters": {
    "svs": {                     // present when --target is svs|both
      "frame_gap_ms": {"p50": 24.1, "p95": 698.9, "p99": 701.2,
                       "max": 705.0, "count": 799},
      "frame_total_ms": {"p50": 5.9, "p95": 6.8, "p99": 7.4,
                         "max": 9.1, "count": 799},
      "collectors": {           // hit/miss per SVS collector cache
        "water": {"hit": 40, "miss": 759, "hit_rate": 0.05},
        "highways": {"hit": 612, "miss": 187, "hit_rate": 0.766},
        "obstacles": {"hit": 799, "miss": 0, "hit_rate": 1.0},
        "airports": {"hit": 799, "miss": 0, "hit_rate": 1.0}
      }
    },
    "map": {                     // present when --target is map|both;
                                 // every MP6 counter (see 9.1) plus:
      "frame_gap_ms": {"p50": 30.1, "p95": 33.5, "p99": 40.0,
                       "max": 55.2, "count": 799},
      "frames_painted": 799, "paint_ms": {...}, "layers": {...},
      "water": {...}, "settle_latency_ms": null, "probe": {...}
    }
  },
  "summary": "moving_position: 40.0s @ 130 kt hdg 280, 20 Hz -- "
             "svs gap p50=24.1 p95=698.9 p99=701.2 max=705.0 ms (n=799); "
             "map gap p50=30.1 p95=33.5 p99=40.0 max=55.2 ms (n=799)",
  "caveat": "the 20 Hz LAT/LONG bus writer driving this run is itself "
           "Python load, comparable to X-Plane's own update rate but "
           "not present in a pure-pyEfis idle measurement -- read these "
           "numbers as \"pyEfis under motion comparable to X-Plane,\" "
           "not a pure-pyEfis figure (AER-677)."
}
```

`frame_gap_ms`/`frame_total_ms` are the SVS analogue of
`ai/svs.py`'s own `frame.gap_between_svs`/`frame.svs_total` perf-log
lines, captured from OUTSIDE the renderer (that profiler has no public,
non-self-clearing read API -- see `_install_svs_hooks`'s docstring) so no
production code changes were needed. `collectors` distinguishes "renderer
slow" (`frame_total_ms` high) from "renderer starved" (`frame_gap_ms`
high while `frame_total_ms` stays low and collector `miss` counts are
high) -- the exact distinction that diagnosed AER-677. A collector
"miss" means that call started a new background collect-worker thread
(the only event that puts new GIL-held work in flight under this
architecture); anything else -- an exact cache hit, or promoting an
already-finished worker's result -- is a "hit," since both cost ~0 on the
render thread.

**Pass threshold: `svs.frame_gap_ms.p95 <= 50`; `map.probe.p95_ms <= 50`.**
(AER-1082, narrowing AER-679's original shared bound; SVS provenance
corrected by AER-1086.) `50` is `PROBE_GAP_WARN_MS` in `map/perf.py` --
the project's own existing GUI-thread-stall gate (MP6). For SVS,
`frame_gap_ms.p95` IS that gate: SVS redraws on its own frame clock, so
a stalled render thread shows up directly as an inflated paint-to-paint
gap. The bar was originally justified by an AER-677 measurement of
"healthy SVS gap ~25 ms (40 fps)" -- that figure came from the
DEMO-contaminated era (bench demo pattern sweeping ALT continuously
with LAT/LONG pinned, so the widget repainted on its own frame clock
with no position-driven collector load), the same set of numbers
AER-677 itself retired, so it was never a valid baseline for a gate
meant to cover position-driven motion.

AER-1086 re-measured on healthy current `dev` using this harness's own
`--moving-position --target svs` mode (130 kt/280 deg/20 Hz, 41 s): p50
33.0 / p95 34.0 / p99 34.9 / max 35.6 ms, with collector hit rates
>99% and `frame_total_ms` staying ~4.6-5.0 ms (render itself is cheap,
not starved). Note this requires a real GL context -- the `offscreen`
Qt platform cannot create a `QOpenGLWidget` at all (`SVS: OpenGL draw
failed ... no current GL context`); run with `QT_QPA_PLATFORM=xcb` and
`DISPLAY` pointed at the bench's existing X server instead (GLX
tolerates a second concurrent client fine; no need to stop the live
`pyefis.service`). This measurement also settles AER-1086's suspected
"floored at the drive period" mechanism: SVS repaints on its own
free-running 30 fps `QTimer` (`ai/__init__.py`'s `set_frame_rate`,
default 30), not on position change, so the ~33 ms gap tracks that
timer's nominal 33.3 ms period regardless of the 20 Hz position-drive
rate. 50 ms keeps clean margin (~16 ms, ~32%) above this real healthy
baseline and two orders of magnitude below AER-677's ~699 ms
(1.4 fps) reproduced defect.

The map does NOT gate on `frame_gap_ms.p95`. AER-692 found the map's
paint-to-paint gap is dominated by pose-quantization arithmetic, not
render health: at 10 NM half-range on a 1040 px widget one screen pixel
is ~35.6 m, and at 130 kt it takes ~266 ms to move the half-pixel the
pose gate requires before a repaint is even requested, plus up to one
10 Hz frame-clock period on top -- so a correctly-behaving map reads
~205 ms p50 / ~292 ms p95 in that scenario, comfortably over a 50 ms
bound with every layer a structural no-op. A bound that is always red
for defect-free code isn't a gate. `frame_gap_ms` is still reported for
`map` (a recorded observable, useful for eyeballing update cadence) but
nothing budgets on it.

Instead the map is gated on `probe.p95_ms` -- `MapPerfStats`'s
`GuiProbe`, a QTimer on the GUI thread measuring its own tick-to-tick
wall-clock gap against its 10 ms period (`map/perf.py`). Because it
free-runs independently of paint/pose gating, it is the objective
GIL-starvation detector: any worker (map or SVS) holding the GIL long
enough to matter shows up here regardless of what triggered it, and it
is blind to the quantization effect above. In the AER-692 run that read
205 ms of `frame_gap_ms`, `probe` read p50 9.7 / p95 10.9 / max 13.6 ms
-- confirming that run's ~300 ms map cadence was arithmetic, not a
stall. See `tools/budgets/moving_position.json` for a ready-to-use
`--budget` file encoding both thresholds.

## 10. Phases

- **A — skeleton**: widget + MapTransform + ownship + range rings
  layer + range/orient actions; factory/schema/twin; offscreen
  renders. (The provider model proves out with the trivial layer.)
- **B — terrain**: TileCache + mip hypsometric/hillshade tiles, LRU,
  caution mode.
- **C — airports**: sectional symbols from airport_db + declutter;
  tower data added to the airports pack build (makerplane-data).
- **D — navaids/fixes/airways**: the new navaids.sqlite pack
  (makerplane-data cyclical pipeline) + the two vector layers.
- **E — controls polish**: legend chip, layer menu UX with the real
  controller hardware.
- Each phase ships behind the standard two-repo pipeline (factory ->
  schema -> R2 -> twin) and lands on the Pi for flight eval.

## 11. Decisions (Bill, 2026-07-05)

1. **Split-screen**: expected down the road; since the widget is
   freely placeable/sizable in the configurator, split layouts come
   for free — no special casing, just don't assume full-screen.
2. **Orientation**: configurator property (`orientation`,
   track_up/north_up — pilots fight endlessly; we don't pick sides).
   Boot default track_up.
3. **Pack growth approved** (TWR for tower coloring; more packs
   expected generally).
4. **Range ladder**: configurable property (`range_ladder`, comma
   list; default 2,5,10,20,40,80,160).
5. **Terrain default**: configurator property; default `relief`.

Development branch: `moving-map` (off display-changes).
