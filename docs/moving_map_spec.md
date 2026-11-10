# Moving Map — specification

Status: IMPLEMENTED, experimental (spec dated 2026-07-05). The
`moving_map` instrument (`src/pyefis/instruments/map/`, screen type
`moving_map`) is on `dev` with phases A-D of section 10 shipped:
terrain, airports, navaids, roads, rivers and flight-plan layers;
phase E (controls polish) is still open. The rest of this document is
the original design spec and is kept for its rationale. Companion specs:
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
    def hit(self, xform, x, y, tol_px): ... # FP10: [(dist_px, Waypoint)]
                                            # painted within tol_px; default []
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
  - **True-size runways (RWY1, AER-4631):** per airport, once the
    longest surveyed runway (threshold to threshold) is longer on
    screen than that airport's symbol is wide (the ring, or the bare
    >8069 ft strips), the symbol is replaced by every runway at true
    size and position: one polygon per runway from the `runway_ends`
    threshold pair, offset by half the published width (2 px minimum).
    Hard surfaces (ASPH/CONC/PEM, the paved-only rule) fill white;
    turf/gravel/dirt draw hollow; water draws a dashed outline. Edges
    keep the airport colour. Runway numbers sit just short of each
    threshold, upright to a pilot landing on that end, once the runway
    is five font heights long; a number that would overprint the ident
    or another number (close parallels) is skipped. Displaced
    thresholds draw as a bar across the runway when it is wide enough.
    The ident moves to just below the runways. An airport with no
    surveyed runway end keeps its symbol. Runways only: taxiways and
    ramps are CAP-207.
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
  as a suffix when set. One symbol and one label per place (G59,
  pyEfis #375, Bill 2026-11-07): where the airport, navaid or fix layer
  already drew the waypoint this frame (same ident, within 60 m), that
  layer keeps its symbol and label and the route adds only the TO ring
  and the role suffix, on its own line under the ident. User and lat/lon
  points, and any waypoint no database layer is showing (layer off,
  outside its range gate, decluttered), draw in full. While suspended at the MAP with LNAV armed
  (`FPLSTATE`=SUSP, `FPLAPR`=LNAV), a dashed magenta line extends the
  final course past the MAP so the pilot still sees where it leads —
  the exact length is a look call, not a navigation guarantee.
- Route segments (RS4, pyEfis #307): each airway segment in the `FPLS*`
  table is labelled with its ident, bold, along its first leg on the
  airway (entry fix to the next fix, not the direct leg into the entry
  fix), rotated to the leg and kept upright, in that leg's status colour.
  It is skipped when the leg is too short on screen to hold it. The legs
  still ahead in the active segment (`FPLACTSEG`, by the engine's rule
  that a leg belongs to its TO slot's segment) draw 3 px in their own
  colour. `FPLACTSEG` 0 or absent, or a table row that disagrees with the
  slots' `FPLfSGI`, changes nothing. The fixes and legs are unchanged.
- Procedure legs (PA8, pyEfis #239): each leg draws as the path the
  engine flies, from `FPLfPT` and its leg fields
  (`pyefis.flightplan.leg_paths`): `RF`/`AF` as a real arc around
  `FPLfCTRLAT`/`CTRLON`; a `DF` with a coded turn (`FPLfTURN`) as a turn
  in that direction from the previous leg's course, then direct (never
  the short way when the data says otherwise, so the map and the needle
  agree); `CF`/`CA` along the coded course; holds as the racetrack at the
  fix (coded inbound course, turn direction and leg length); `PI` as the
  45/180 shape out to the engine's outbound point. Turn and racetrack
  radii are a standard-rate turn at 120 kt, a chart-like constant rather
  than live groundspeed. The missed approach segment (segment kind
  `missed`) is dashed and vector legs (`VA`/`VM`/`VI`/`FM`) are a dotted
  3 NM "to be vectored" stub; a `CA`/vector point gets no waypoint symbol.
  Altitude constraints of procedure legs (`FPLfALT`, not an airway's MEA)
  label the fix under its ident in chart notation: a bar under the number
  for at-or-above, over it for at-or-below, both for "at", a window as
  ceiling over floor. The geometry is built in `collect()` (on the GUI
  thread, between frames, only when `FPLSEQ`, `FPLLDSEQ` or `MAGVAR`
  changes) as lon/lat polylines and painted through one affine transform
  taken from `MapTransform`, so a frame does no per-vertex work.
- A rejected route draws nothing (procedures brief guardrail 1). After a
  rejected commit the slots still hold the refused route; fix-gateway's
  `FPLLDSEQ` is the `FPLSEQ` of the route the engine actually loaded. When
  the two differ, no leg, fix or label of the slots is drawn -- only the
  active leg, from the engine's `FPLFRLAT`/`LON` -> `WPLAT`/`LON`. A
  gateway without `FPLLDSEQ` draws the slots as before.
- Declutter: labels (waypoint and airway) off above 80 NM (symbols stay), nothing draws
  above 160 NM except the legs.
- Prop `layer_flight_plan` (default on); the `LiveBind` runtime toggle
  rides #96 when it lands (layer toggles are GUI-thread-only today).

### 5.5 Range rings (z=20, default on)

Concentric half/full-range rings with distance labels — the
provider-model proof (section 4): trivial by design, ships v1.

### 5.6 Map style: nav-data-only (`map_style: nav_only`, G12, billmallard/pyEfis#135)

`map_style` selects a presentation, not a layer. `standard` (the
default) is the terrain map above, and renders byte-identical to the
map before this option existed. `nav_only` is a nav-data map on a plain
background, the substrate for the Navigation Display mode (#134):

- **Terrain relief off**, whatever `layer_terrain` and `terrain_mode`
  say. Those two keep their meaning under `standard`.
- **Water stays, on its own switch.** `layer_water` (default on) draws
  lakes and coastline as a flat fill. It uses the same sources as the
  relief render (tile void and sea level, the pack's `.wmask`, the
  water-pack polygons under `water_polygon_max_nm`) with land left
  transparent, so the coastline matches the terrain map exactly. With
  no terrain pack configured, the water-pack polygons alone draw. Under
  `nav_only` the terrain layer IS this water renderer, so
  `set_layer("terrain")` toggles water.
- **Every other layer keeps its own `layer_<id>` switch.** Rivers and
  roads are geographic reference, not relief, so the preset leaves them
  to their keys.
- **Palette.** The background is black, the panel's own darkest state:
  sunlight reflection sets the floor either way, and black gives every
  symbol the full luminance range. Each retained layer was recoloured
  where it under- or over-contrasted against black. Symbols are at
  least 3:1 against both the background and the water fill, labels at
  least 4.5:1. Range rings and roads are recessive reference lines, at
  least 3:1 against the background only. `road_color` and `river_color`
  swap to the style's default only when left at the standard default;
  an explicit colour still wins. Both tables live in
  `instruments/map/layers/__init__.py`. Airspace (section 6) adds its
  keys to both when it lands. The computed ratios are a bound; the
  device check is the glass.

### 5.7 Navigation Display mode (`nd_mode`, G11a/G11b, billmallard/pyEfis#134)

`nd_mode` selects the transport-category ND idiom, built to the spec on
#134 (issuecomment-5552767516) as amended by Bill's G11 rulings
(2026-11-07). `off` (the default) is the map above, pixel-identical to
the map before this option existed. `expanded` is EXPANDED MAP; `ctr`
is CTR MAP (G11b, below). The configurator twin is G11b's makerplane-data
half; until it lands the configurator draws the plain map for an ND
screen.

- **Geometry.** Track-up whatever `orientation` says (the setting is
  kept for when the ND is switched off). Ownship at `h * 0.82`, the HSI
  arc's `own_y`, overriding `ownship_position`. The selected range ends
  on a compass arc centred on ownship (`MapTransform.range_px`), not at
  the top edge, so a feature on the arc is exactly `range_nm` away. On a
  landscape panel the arc reaches up to the TRK box at the top and spans
  the HSI's +/-60 deg. On a tall or narrow panel that radius would leave
  a sliver of arc running through the top corner blocks, so the radius
  shrinks until the arc spans +/-40 deg, and its ends always stay clear
  of the deviation scale. 5 deg ticks, numerals every 30 deg in tens. A
  TRK box (`TRACKM`, MAG) sits over the arc apex with the lubber
  triangle under it.
- **Data blocks**, only fields the 737 material lists and the bus
  carries. Top left: `GS`, `TAS`, wind `WINDDIR`/`WINDSPD` and a wind
  arrow, below the range chip. Top right: the active waypoint per the
  engine rules posted on #134 (FP7): `WPNAME` magenta, ETA = now (UTC) +
  `WPETE` as `HHMM.Mz`, `WPDIS`; drawn only while `FPLSTATE` != 0,
  blank on `VECTORS`, red `XXX` on `fail`, grey on `bad`/`old`. Bottom
  left: the enabled map options (ARPT / WPT / STA), cyan. Not drawn,
  for want of a source: VOR1/VOR2 frequency and DME, the FMC source,
  RNP/ANP, WXR.
- **Vertical deviation scale**, screen-fixed at the right edge, centred
  vertically: a white fixed scale (ticks at +/-0.5 and +/-1 of full
  scale) and a magenta diamond at `GSI` (normalised +/-1, pegged
  beyond), up for positive `GSI` like the HSI's needle. Gated exactly as
  the HSI gates its glideslope: hidden at `GSV` < 0.5, shown on `GSI`'s
  own quality when `GSV` is absent, the pointer hidden on
  `old`/`bad`/`fail`, and the red GS flag when `GSV` says a glidepath is
  present and `GSI` is bad or failed. No digital readout and no RNP band:
  the 737's are in feet and `GSI` is not.
- **CTR MAP** (`ctr`, G11b). The same symbol set framed as a closed
  compass rose with ownship at the panel centre, per the spec's section
  5 ("a closed compass rose instead of an arc, no other confirmed
  differences"). The rose is at the selected range, like the arc. Its
  radius is the largest that keeps the TRK box over its top inside the
  panel, its bottom one text height above the bottom edge and its sides
  inside the arc's reach (clear of the deviation scale). Data blocks,
  TRK box and deviation scale are EXPANDED's, unchanged.
- **No lateral deviation scale** (ruling 1: neither the 737 nor Garmin
  AXIS draws one on the map). **737 colours on the new elements only**
  (ruling 2): layers and ownship keep their palette.
- **Mode key.** `nd_mode_key` names a FIX key that switches the mode at
  runtime (0 = off, 1 = expanded, 2 = ctr), the `orientation_key` precedent: the
  config default seeds the key, then the key drives the mode, and the
  widget never writes it again. The gateway needs the key defined (a
  `custom.yaml` stand-in like `MAPORIENT`, max = the mode count); the
  widget does not mint it.

### 5.8 Traffic (z=50, default on, P3b, billmallard/pyEfis#53)

ADS-B traffic from the FIX `TFCk*` block that fix-gateway's traffic writer
fills from GDL90 (`layers/traffic.py`). The contract is
`docs/fix_dynamic_list_spec.md` section 5; nothing here adds to it.

- Reads a slot only on its `TFCkTGT` write, keys state by the `TGT`
  identity, and discovers the block size from the bus (`TFC1TGT`, `TFC2TGT`,
  ... until a key is missing). No block on the bus: the layer is inert.
- Symbol: an arrowhead along the target's track (true; a magnetic heading is
  converted with `MAGVAR`), a diamond when the track is unknown (`TTYP = 0`,
  or a magnetic heading with no `MAGVAR`).
- Style (GDL90 G§3.5.1.1, G§3.5.1.6): normal = filled white; traffic alert
  (`TFCkALRT = 1`) = yellow, flashing filled/open at 1 Hz, drawn on top;
  degraded (NIC or NACp 4 or lower) = open outline; stale (`TFCkTGT` `old`)
  = grey dashed outline, dropped by the display 12 s after it went stale if
  the writer never evicts it; `TFCkTGT` `fail` = not drawn.
- Data tag: relative altitude `TFCkALT - PALT` in hundreds of feet (`+05`
  above the symbol, `-12` below), `--` when `TFCkALT` is `bad` or `PALT` is
  absent / `old` / `bad` / `fail`. A trend arrow at +-500 fpm; none when
  `TFCkVS` is `bad`.
- `TFC FAIL` chip, bottom left, when `TFCCOUNT` is `fail` (receiver failed)
  or `old` (writer stopped) after it has been seen live. Never live since
  pyEfis started = no receiver fitted, no chip (the gateway's default
  database carries the block either way); a receiver that never comes up
  at all is therefore silent.
- No geometric ownship filter (Bill's F6 ruling): a target on top of ownship
  is drawn.
- Not yet: absolute-altitude mode, air/ground and emitter-category symbols,
  the audible alert, `TFCDROP` display, call-sign labels, hit-test.
- Prop `layer_traffic` (default on).

## 6. Future layers (design targets for the provider seam)

Named now so the interfaces stay honest: `traffic` (shipped as
section 5.8, over FIX keys), `metar_flags` / `fisb_weather` (Stratux FIS-B: NEXRAD raster as a
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

### 7.1 Touch: select, map pointer and banner (FP10, billmallard/pyEfis#186)

Graphical flight plan editing, the guide's third way to build a route
(GNX 375 Pilot's Guide 3-14..3-19, 3-46 "MAPWPT"). Drag-to-pan,
two-finger pinch/rotate and the wheel are unchanged; what a **tap** (a
press/release with under 4 px of travel) does has changed.

| Input | Result |
|-------|--------|
| Tap on one painted object (within **12 px**, inclusive) | Map pointer on it + its banner |
| Tap where several objects are within 12 px | Pointer + a stacked chooser listing all of them, nearest first, one row each (at most 6) + CANCEL; a row opens that object's banner |
| Tap on nothing | Pointer on a bare **map point** there + its banner |
| Tap away while a pointer is up | Clears the pointer (does not place a new one) |
| Banner **X** / chooser **CANCEL** | Clears the pointer |
| **Double-tap** | Recenter (pan + rotation re-lock) and clear the pointer |
| Tap the **CTR** chip (top right, shown while panned/rotated) | Recenter |

**Recenter moved off the single tap.** Before FP10 a single tap re-locked
the view; now a single tap selects. Recenter is the double-tap or the CTR
chip — the chip is visible exactly when there is something to recenter,
so it is the soft key. The auto-revert timer (`gesture_timeout`) still
re-locks on its own, and does not clear a pointer.

**Hit-test.** `MapLayer.hit()` (section 4) answers only for what the
layer's last `paint()` would show: the same range gates (airports <=80 NM,
navaids <=160 NM, fixes <=20 NM and only when the fixes layer is on, plan
waypoints <=160 NM), the same snapshot, nothing from a disabled layer, and
never a database query. `MovingMap.hit_test()` merges the layers' answers,
nearest first, one entry per `(ident, type)` (an airport the flight plan
also draws is listed once). The flight plan layer's answer is the only way
to tap a user or map waypoint, which no database layer draws.

**Banner** (bottom of the map): ident and type (or `MAP POINT` and its
position), then bearing and distance from present position — magnetic
when the gateway publishes `MAGVAR`, otherwise labelled `°T` — terrain
elevation at the point when the terrain layer has tiles there (none over
water), and a navaid's frequency. Soft keys, touch-sized (36-64 px tall):

- **DIRECT TO** — stages `DTO*` for the object, or `MAPWPT` (`DTOTYPE` 6,
  `map`) at the pointer, and issues `FPLCMD DTO`. A plan waypoint is
  matched to its slot by the engine (Appendix C: ident and position within
  0.001 deg). A toast reports the engine's answer, not the request:
  `DIRECT TO <ident>` on a positive `FPLCMDACK`, `REJECTED: <FPLMSG>` on a
  negative one (e.g. `NO POSITION` with no GPS), nothing until it answers.
- **INSERT** — reads the plan on the bus, inserts the object (or `MAPWPT`)
  before the far end of the plan leg nearest the pointer, and publishes.
  Distance to a leg is clamped to its ends, so a point beyond the
  destination lands before it; extending the plan is the FPL page's Add
  Waypoint. A plan with no leg yet (empty, or one waypoint) is appended
  to. Every `flight_plan` instrument re-reads the plan on `FPLSEQ`.
- **CREATE WPT** — opens the `flight_plan` instrument's user-waypoint form
  (Entry page, User tab) with LAT/LON prefilled from the pointer.
- **INFO** — opens WPT Info for the object or point on the `flight_plan`
  instrument.

DIRECT TO and INSERT draw disabled when the flight plan keys are not on the
bus (no gateway `flightplan` plugin); the banner still shows. CREATE WPT
and INFO reach the `flight_plan` instrument through two in-process HMI
signals (`flightplanCreateWaypoint`, `flightplanWptInfo`), which switch its
`tab_section` tab into view — on the bench the Map and Flight Plan are tabs
of one section. There is no screen-YAML verb for them: the payload is a
waypoint or a position, which a button cannot express.

The pointer is geographic: it stays on its point as the aircraft moves and
the view pans, until cleared. Taps need `touch_gestures` on (the same
option that gates drag and pinch).

**Out of FP10, follow-on:** drag-a-leg editing — the guide's temporary
flight plan with Done/Cancel and nine-level Undo (3-17..3-19).

### 7.2 Touch: one-finger zoom rail (G22, billmallard/pyEfis#205)

`zoom_rail: true` draws a vertical range control at the map's left edge
(`zoom_rail_side: right` mirrors it), starting one status-chip height under
the status chip. Pinch stays; the rail is the one-finger path, steadier in
flight than a two-finger gesture. Off by default, so existing screens do
not change.

| Input | Result |
|-------|--------|
| Tap the **+** cap (top) | One rung in (smaller range), stopping at the smallest |
| Tap the **-** cap (bottom) | One rung out, stopping at the largest |
| Tap the track | Jump to the nearest rung |
| Drag on the track | Snaps rung to rung as the finger moves |
| Double-tap a cap | Two steps (never a recenter) |

- **One detent per `range_ladder` rung**, evenly spaced, smallest range at
  the top (up = zoom in). The caps call `range_up` / `range_down` and the
  track sets `range_nm`, so every rail change goes through the single
  range-write path (#202) and lands the rung index on a bound `range_key`.
  The caps step from the range on screen, so after a free pinch to 13.7 NM,
  + goes to 10 and - to 20, the same as a range button.
- **The thumb follows the range from anywhere.** It sits on a rung's detent,
  and between two detents (log-interpolated) for a free pinch or wheel
  range. A `MAPRANGE` write from a button or knob moves it on the next frame.
- **Touch zone.** A column `ZOOM_RAIL_TOUCH_MM` (20 mm) wide at the bezel,
  with 20 mm caps, sized from the panel's physical DPI
  (`pyefis.display_metrics`: the configured `screenDiagonalInches`, then
  Qt, then 96 DPI), and clamped to 24 px .. 25% of the map width. The detent
  track is 38% of the map height. Nothing reaches below 75% of the height,
  clear of the pointer banner. On a short pane the track shrinks first; the
  caps keep their full size until the track would be under a third of the
  rail. Every touch that starts inside the zone belongs to the rail: no pan,
  no map pointer, no recenter.
- **Look.** A slim line with a tick per rung, + and - glyphs, and a filled
  disc thumb, all in opaque light grey with a dark halo, full white while
  touched. While a finger is down the range ("20 NM") shows beside the thumb
  in a larger font, and the map previews the new range the way a pinch
  does (scaled image, one render on settle).
- **Open for Bill on the bench:** ticks only vs range labels on the rail,
  the zoom direction, always visible vs fade after N seconds, and default
  on or off for existing screens.
- **Out of scope:** knob parity (CAPABILITIES design rule 1). `range_up` /
  `range_down` exist but no HMI action or `enc_*` hook reaches them yet;
  CAP-1102 owns that.

## 8. Configurator integration (standard pipeline)

- Factory registration + Props: `range_nm`, `orientation`,
  `ownship_position`, `layers` (per-layer default-on booleans:
  `layer_terrain`, `layer_airports`, `layer_navaids`,
  `layer_airways`, `layer_flight_plan`, `layer_traffic`, `layer_range_rings`,
  `layer_water`), `map_style` (section 5.6),
  `terrain_mode`, symbol options, `db paths` (default to
  /data/makerplane-data locations).
- Range rings (G13, #136): `range_ring_fractions` (comma list of range
  fractions, default `0.5,1`), `range_ring_labels`,
  `range_ring_label_angle` (screen clock degrees, 0 = top),
  `range_ring_color` + `range_ring_opacity` (%), `range_ring_width` and
  `range_ring_label_size` (px, 0 = auto). Colour and opacity style the
  `standard` map only; under `map_style: nav_only` the palette's ring
  greys apply. Defaults draw the original half/full rings; the current range is always in the status chip, never
  only in a ring label.
- Zoom rail (G22, #205): `zoom_rail` (boolean, default off) and
  `zoom_rail_side` (`left` / `right`). The twin draws it (makerplane-data#80,
  G23) at the same position and proportions, thumb on the configured
  `range_nm` rung.
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
all run as they would live. `pinch_out`/`pinch_in`'s bounds default to the
brief's own 10/160 NM but take `--pinch-lo-nm`/`--pinch-hi-nm` overrides
(AER-1216) to probe ranges past the ladder top without inventing a second
scenario -- the result still conforms to this schema, `params.range_to_nm`
just reads the override. Output is always a JSON **array** (one
element per scenario run, so `--scenario all` and a single `--scenario
pinch_out` share one schema) written to `--out` or stdout; progress/
summary lines go to stderr so stdout stays pipeable. Each element:

```jsonc
{
  "schema_version": 3,
  "timestamp": "2026-09-27T18:04:11.203841+00:00",  // UTC, datetime.now(timezone.utc).isoformat()
  "rev": "b4d3349",            // git short SHA, "" outside a checkout
  "host": "beelinkpyefis",     // socket.gethostname()
  "scenario": "pinch_out",
  "widget": {"w": 650, "h": 1040},
  "lat": 35.8, "lon": -78.8,
  "water_max_vertices": 1024,  // the --water-max-vertices cap in force for this run
  "duration_s": 6.48,          // wall-clock time the scenario itself took
  "params": {"range_from_nm": 10.0, "range_to_nm": 160.0,
             "range_actual_nm": 160.0, "events": 90, "event_hz": 60.0,
             "hold_s": 5.0},   // scenario-specific inputs, for repro;
                              // range_actual_nm is on rotate/pan/ladder too
                              // (v2) -- the widget's range_nm at scenario
                              // end, unchanged by rotate/pan, walked to the
                              // ladder's last rung by ladder
  "counters": {                // MapPerfStats.snapshot() -- every MP6 counter
    "frames_painted": 50,
    "paint_ms": {"p50": 0.7, "p95": 1.0, "max": 5.5, "count": 50},
    "layers": {                // keyed by layer id; a layer with no jobs
      "terrain": {"jobs_requested": 1, "jobs_started": 1,
                  "jobs_published": 1, "jobs_superseded": 0,
                  "last_render_ms": 12.3, "max_render_ms": 12.3}
                              // the 4 job-lifecycle counts are a DELTA
                              // across just this scenario (AER-2207) --
                              // MapPerfStats itself keeps them cumulative
                              // for the widget's whole lifetime, but
                              // run_scenario() subtracts back out its own
                              // one-time construction warm-up render so
                              // it isn't counted as the scenario's own.
                              // last_render_ms/max_render_ms are latest/
                              // max-observed, not counts, so they are not
                              // deltaed.
    },                        // (omitted entirely) never appears here
    "water": {"polygons_before": 0, "vertices_before": 0,
              "polygons_after": 0, "vertices_after": 0,
              "qpointf_count": 0},
    "settle_latency_ms": 97.0, // null if no gesture completed a settle
    "probe": {"p50_ms": 10.7, "p95_ms": 10.8, "max_ms": 11.0,
              "count": 256, "over_count": 0,
              "starved_ms": 3.2, "window_ms": 1503.4, "ticks": 150}
                              // count is RING OCCUPANCY, capped at
                              // RING_SIZE=256 (map/perf.py) -- NOT a
                              // tick count. p50/p95/max_ms are computed
                              // over only this trailing ring, so once it
                              // saturates (~2.6 s at the 10 ms tick
                              // period) they are blind to anything
                              // earlier in a longer run; do not cite
                              // them as run-length evidence (AER-2241,
                              // oracle_gate.md reading rules 3-4).
                              // over_count accumulates for the WHOLE
                              // run -- the only p50/p95/max-family field
                              // it is sound to gate on. ticks (v3,
                              // AER-2240) is the honest tick count,
                              // uncapped. starved_ms/window_ms (v3) are
                              // GuiProbe's own O(1) accumulators --
                              // starved_ms sums max(0, gap_ms -
                              // interval_ms) per tick, window_ms sums
                              // gap_ms itself -- so starved_ms /
                              // window_ms is section 5's "GUI-thread
                              // starved <= 10% of the gesture window"
                              // ratio, exactly. ticks/starved_ms/
                              // window_ms are reported here scoped to
                              // the INTERACTION (gesture-bracket start
                              // to settle complete, or to the last
                              // gesture event if no settle lands), not
                              // the whole scenario -- pinch_out's 5 s
                              // deliberate idle hold after the gesture
                              // would otherwise dilute a real stall by
                              // ~4.3x. p50_ms/p95_ms/max_ms/count/
                              // over_count are unchanged: still
                              // whole-scenario cumulative, per the rule
                              // above.
  },
  "summary": "pinch_out: 6.48s, 50 paints (p50=0.7 p95=1.0 max=5.5 ms), "
             "settle=97ms, gui gap p95=10.8ms max=11.0ms >50ms=0; "
             "terrain req=1 pub=1 superseded=0"
}
```

**v1 -> v2 (AER-2225):** added `timestamp`, `water_max_vertices`, and
`params.range_actual_nm` on `rotate`/`pan`/`ladder`. The nine
`schema_version: 1` lines already committed to `makerplane/perf/
map_gestures.jsonl` are not rewritten; a consumer that reads a v1 line
sees those three fields simply absent, which MP9b's judge treats as a
bound rather than a zero.

**v2 -> v3 (AER-2240):** added `counters.probe.starved_ms`/`window_ms`/
`ticks`, scoped to the interaction window described above. Additive
only, per-metric (AER-2233's comparability ruling), so every existing
v1/v2 field and trend stays intact; a consumer reading a pre-v3 line
sees the three fields simply absent.

`--budget <path>` loads a JSON map of `{scenario: [{"path": "a.b.c",
"max": x} | {"min": x}, ...]}`, evaluates each dotted `path` against that
scenario's `counters` (e.g. `"layers.terrain.jobs_requested"`,
`"settle_latency_ms"`, `"probe.over_count"`), and exits non-zero if any
bound is violated (a `path` absent from a run -- e.g. a layer with no
data configured -- is skipped with a warning, not a failure). **Never
gate on `probe.p95_ms`/`probe.max_ms`** -- they are computed over
`GuiProbe`'s `RING_SIZE=256` trailing ring, which saturates in ~2.6 s at
the 10 ms tick period regardless of how long the scenario ran, so on
anything longer than a few seconds they are blind to a stall that has
already scrolled out of the ring (AER-2241, oracle_gate.md reading
rules 3-4); `probe.over_count` accumulates for the whole run and is the
sound field.
`tests/tools/test_bench_map_gestures.py::test_no_shipped_budget_cites_probe_percentile_bounds`
walks every file under `tools/budgets/` and fails the suite if either
path is cited again. Example budgets file matching the acceptance table
in section 5 of the brief:

```json
{
  "pinch_out": [
    {"path": "layers.terrain.jobs_requested", "max": 1},
    {"path": "layers.terrain.jobs_superseded", "max": 0},
    {"path": "settle_latency_ms", "max": 600},
    {"path": "probe.over_count", "max": 0}
  ]
}
```

`rotate`'s paint-count bound is NOT a `--budget` row: the withdrawn
`{"path": "frames_painted", "max": 90}` (AER-1121) was `30 Hz * 3.0 s`
restated as arithmetic, and a healthy tree paints ~93 in ~2.984 s --
computed from the measured sweep length, not a fixed constant. The live
assertion is
`tests/perf/test_map_gestures.py::test_rotate_sweep_paints_are_bounded_by_the_frame_clock`,
which derives its bound from the clock and the measured sweep duration
instead of hard-coding 90.

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

**Pass threshold: `svs.frame_gap_ms.p95 <= 50`; `map.probe.over_count <= 0`.**
(AER-1082, narrowing AER-679's original shared bound; SVS provenance
corrected by AER-1086; map bound corrected from `probe.p95_ms` to
`probe.over_count` by AER-2241 -- see below.) `50` is
`PROBE_GAP_WARN_MS` in `map/perf.py` -- the project's own existing
GUI-thread-stall gate (MP6), and `over_count` is how many ticks crossed
it. For SVS,
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

Instead the map is gated on `probe.over_count` -- `MapPerfStats`'s
`GuiProbe`, a QTimer on the GUI thread measuring its own tick-to-tick
wall-clock gap against its 10 ms period (`map/perf.py`). Because it
free-runs independently of paint/pose gating, it is the objective
GIL-starvation detector: any worker (map or SVS) holding the GIL long
enough to matter shows up here regardless of what triggered it, and it
is blind to the quantization effect above. In the AER-692 run that read
205 ms of `frame_gap_ms`, `probe` read p50 9.7 / p95 10.9 / max 13.6 ms
(`over_count` 0) -- confirming that run's ~300 ms map cadence was
arithmetic, not a stall.

**Gate on `over_count`, not `p95_ms`/`max_ms` (AER-2241).** `probe`'s
`p50_ms`/`p95_ms`/`max_ms` are computed over `_Ring(maxlen=RING_SIZE)`,
`RING_SIZE = 256`, while `over_count` increments on every tick since the
probe started. At the 10 ms tick period the ring saturates in ~2.6 s
regardless of run length -- `counters.probe.count` reads exactly 256 on
every recorded moving-position run, confirming it is always full. On
the moving-position scenario's ~41 s duration that trailing window is
only ~6% of the run: a GIL stall anywhere in the earlier ~38 s has
already scrolled out of the ring by the time the run ends, leaving
`p95_ms`/`max_ms` untouched and the gate reads a false pass
(oracle_gate.md reading rules 3-4: `probe.p95_ms`/`probe.max_ms` are
non-citable on any scenario for exactly this reason). `over_count` has
no such window -- it is evidence about the whole run, so it is the only
probe field a budget should gate on. See
`tools/budgets/moving_position.json` for the shipped `--budget` file
encoding both thresholds, and
`tests/tools/test_bench_map_gestures.py::test_no_shipped_budget_cites_probe_percentile_bounds`
for the guard that keeps a `p95_ms`/`max_ms` bound from coming back.

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
