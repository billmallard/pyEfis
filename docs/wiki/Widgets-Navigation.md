# Navigation

The moving map, the flight plan page and the nav status line. What each shows
and how a pilot uses it is on its own page, linked under each heading; this
page is the full option list. Each table is generated from pyEFIS's instrument
registry; see [Widget Reference](Widget-Reference#how-to-read-these-pages). The
HSI is on [Flight Instruments](Widgets-Flight-Instruments#horizontal_situation_indicator).

All three work with fix-gateway's flight-plan engine, which flies the plan; see
[Flight Plan Engine](https://github.com/billmallard/fix-gateway/wiki/Flight-Plan-Engine)
in the fix-gateway wiki.

---

## `moving_map`

<!-- generated:moving_map -->

**Moving Map** · palette category `navigation`

How it reads and flies: [Moving Map](Moving-Map).

FIX keys it reads by default: `LAT`, `LONG`, `TRACKM`.

| Option | Configurator label | Default | Values | What it does |
|---|---|---|---|---|
| `range_nm` | Range (NM) | `10` | 1 to 500 | distance from the ownship anchor to the top edge |
| `range_key` | Range control key | empty | FIX key | optional FIX key that cycles the range at runtime (a button 'change value wrap' / the knob steps the ladder index). Empty = fixed range |
| `range_ladder` | Range ladder | `2,5,10,20,40,80,160` |  | comma list of ranges the range buttons step through |
| `zoom_rail` | Zoom rail | off | on / off | one-finger range control under the status chip: a vertical rail with one detent per range ladder rung, zoom in at the top. Tap +/- to step one rung, tap the rail to jump to a rung, or drag the thumb. Its touch zone is 20 mm wide and claims every touch inside it |
| `zoom_rail_side` | Zoom rail side | `left` | `left`, `right` | map edge the zoom rail sits on |
| `orientation` | Orientation | `track_up` | `track_up`, `north_up` | track-up rotates the world; north-up rotates ownship |
| `orientation_key` | Orientation control key | empty | FIX key | optional FIX key that switches orientation at runtime (0=track_up, 1=north_up). Empty = fixed |
| `touch_gestures` | Touch gestures | on | on / off | two-finger pinch=zoom, drag=pan, twist=rotate; mouse wheel zooms and left-drag pans / Shift-drag rotates on desktop; a tap selects (map pointer, Direct To / Insert banner) and a double-tap or the CTR chip re-centres. Off = touch/wheel/drag/tap input ignored |
| `gesture_timeout` | Gesture auto-revert (s) | `30` | 0 to 600 | seconds after a two-finger pan/rotate before the view re-locks to ownship and the configured orientation. 0 = stay where left until a double-tap, the CTR chip or an HMI recenter |
| `gesture_frame_rate` | Gesture frame rate (Hz) | `30` | 10 to 60 | repaint clock rate while a pinch/pan/rotate gesture is live (zoom_by/pan_by/rotate_by mark a frame dirty rather than repainting per event); the normal frame rate applies the rest of the time |
| `pinch_rotate_threshold_deg` | Pinch rotate threshold (deg) | `15` | 0 to 90 | cumulative twist a pinch must reach before it rotates the view; below this a pinch is zoom-only, so a couple of degrees of finger wobble does not nudge orientation |
| `pinch_pan_threshold_px` | Pinch pan threshold (px) | `20` | 0 to 200 | centroid movement (screen px) a pinch must reach before it pans the view; below this a pinch is zoom-only |
| `ownship_position` | Ownship position (%) | `50` | 0 to 100 | ownship anchor, percent up from the bottom (30 = classic look-ahead offset) |
| `symbol_color` | Ownship colour | `#ffff00` | colour | colour of the top-down ownship symbol |
| `map_style` | Map style | `standard` | `standard`, `nav_only` | standard = terrain map; nav_only = terrain relief off (whatever layer_terrain says) and the nav layers repainted for a plain black background. Water follows layer_water, every other layer keeps its own switch |
| `layer_water` | Layer: water (nav_only) | on | on / off | under map_style nav_only: lakes and coastline as a flat dark-blue fill, no relief. Under standard, water is part of the terrain image and this switch is not used |
| `layer_range_rings` | Layer: range rings | on | on / off | concentric range rings around ownship with distance labels (half and full range unless range ring fractions says otherwise) |
| `range_ring_fractions` | Range ring fractions | `0.5,1` |  | comma list of ring radii as fractions of the current range (1 = the top edge). 0.5,1 = half and full range (ND convention); 0.25,0.5,0.75,1 = four even rings. Values outside 0-2 are ignored |
| `range_ring_labels` | Range ring labels | on | on / off | print each ring's distance on the ring. The current range stays in the top-left status chip either way |
| `range_ring_label_angle` | Range ring label position (deg) | `0` | 0 to 359, step 1 | where the labels sit on each ring, clockwise from straight up on the screen: 0 = top, 90 = right, 180 = bottom, 270 = left. Move it off a data block |
| `range_ring_color` | Range ring colour | `#ffffff` | colour | ring and ring-label colour |
| `range_ring_opacity` | Range ring opacity (%) | `55` | 0 to 100, step 1 | ring and ring-label opacity |
| `range_ring_width` | Range ring width (px) | `0` | 0 to 10, step 0.5 | ring line width; 0 = auto (0.2% of the map width, at least 1 px) |
| `range_ring_label_size` | Range ring label size (px) | `0` | 0 to 48, step 1 | ring label font pixel size; 0 = auto (2.5% of the map width, at least 8 px) |
| `layer_terrain` | Layer: terrain | on | on / off | hillshaded hypsometric terrain relief |
| `tile_path` | Terrain tile path | empty |  | GLO-30/SRTM HGT tree (the SVS tile_path; on the Pi /data/makerplane-data/terrain/tiles) |
| `layer_roads` | Layer: roads | on | on / off | roads from the highways pack, LOD by range: interstates when zoomed out (<=80 NM), arterials added as you zoom in (primary <=20 NM, secondary <=5 NM) |
| `highway_db_path` | Roads db path | empty |  | highways.sqlite (the SVS highway_db_path; on the Pi /data/makerplane-data/highways/current/highways.sqlite) |
| `road_color` | Road colour | `#c0c0c0` | colour | road line colour (arterial classes draw thinner and slightly transparent) |
| `road_casing_color` | Road casing colour | `#5a5a5a` | colour | outline drawn under a road once zoomed in far enough that it draws at its true width (a few NM and in) |
| `layer_rivers` | Layer: rivers | on | on / off | rivers/waterways as lines from the rivers pack, LOD by range: major rivers when zoomed out, canals and streams added close in |
| `river_db_path` | Rivers db path | empty |  | rivers.sqlite (shares the highways schema; on the Pi /data/makerplane-data/rivers/current/rivers.sqlite) |
| `river_color` | River colour | `#4a6d8c` | colour | waterway line colour (smaller waterways draw thinner and slightly transparent) |
| `layer_airports` | Layer: airports | on | on / off | FAA sectional airport symbols with ident labels (declutters by zoom) |
| `nasr_db_path` | Airport db path | empty |  | NASR airports.sqlite (the SVS nasr_db_path; on the Pi /data/makerplane-data/navdata/current/airports.sqlite) |
| `layer_navaids` | Layer: navaids | on | on / off | VOR/NDB symbols with ident and frequency |
| `layer_fixes` | Layer: waypoints | off | on / off | named fixes as open triangles (shown at/below 20 NM) |
| `layer_airways` | Layer: airways | off | on / off | victor/T-route segments with idents |
| `navaid_db_path` | Navaid db path | empty |  | navaids.sqlite (tools/build_navaid_db.py; on the Pi /data/makerplane-data/navaids/current/navaids.sqlite) |
| `layer_flight_plan` | Layer: flight plan | on | on / off | active route: past/active/future legs, waypoint symbols, direct-to and the suspended-at-MAP extended final course (no database, reads the FIX flight-plan bus) |
| `terrain_mode` | Terrain mode | `relief` | `relief`, `caution` | relief = sectional-style hypsometric; caution = TAWS-style amber/red relative to altitude |
| `water_db_path` | Water db path | empty |  | water.sqlite (the SVS water_db_path; on the Pi /data/makerplane-data/water/current/water.sqlite). When set, lakes and coastline from the water pack are rasterized into the terrain image |
| `water_max_vertices` | Water vertex cap | `512` | 16 to 1024, step 16 | per-polygon vertex cap for map water rasterization (higher = more coastline/lake detail per rebuild) |
| `water_raster` | Water raster path | `numpy` | `numpy`, `qt` | numpy = vectorised even-odd scanline fill (MP5, default); qt = legacy per-vertex QPointF/QPolygonF/drawPath path, kept for one release of A/B |
| `water_polygon_max_nm` | Water polygon cutover (NM) | `20` | 0 to 320, step 5 | above this range the crisp coastline/lake polygon overlay is skipped in favour of the terrain pack's water-mask channel (one gather, MP10c); packs with no mask at the chosen level always draw polygons |
| `map_perf_log` | Perf: log summary | off | on / off | print a MapPerfStats summary every 2s (frames, paint ms p50/p95/max, per-layer job counts, water counts, settle latency, GUI-thread gap probe) -- mirrors svs_perf_log. Dev/bench diagnostic; off by default |
| `map_perf_overlay` | Perf: overlay chip | off | on / off | draw a small on-screen perf stats chip (dev only) |

<!-- /generated -->

The repaint rate outside gestures is `frame_rate` (10 Hz by default, 1 to 30).
It is not in the configurator's list; set it in YAML.

---

## `flight_plan`

<!-- generated:flight_plan -->

**Flight Plan** · palette category `navigation`

How it reads and flies: [Flight Plan](Flight-Plan).

FIX keys it reads by default: `FPLCOUNT`, `FPLNAME`, `FPLSEQ`, `FPLSTATE`, `FPLACTLEG`, `FPLAPR`, `FPLINTEG`.

| Option | Configurator label | Default | Values | What it does |
|---|---|---|---|---|
| `flightplan_dir` | Flight plan directory | empty |  | directory for stored routes/user waypoints/recent list (<dir>/routes/*.json, user_waypoints.json, recent.json); blank disables catalog Store and FastFind's Recent/User tabs |
| `nasr_db_path` | Airport db path | empty |  | NASR airports.sqlite for FastFind/nearest airport lookup (same path as the moving map's nasr_db_path) |
| `navaid_db_path` | Navaid db path | empty |  | navaids.sqlite for FastFind/nearest navaid and fix lookup (same path as the moving map's navaid_db_path) |
| `procedures_db_path` | Procedures db path | empty |  | the procedures pack for SID/STAR/approach lookup (on the Pi /data/makerplane-data/procedures/current/procedures.sqlite) |
| `columns` | Columns | `DTK,DIS,CUM` |  | comma-separated FPL page data columns, in order; choices DTK, DIS, CUM, ETE, ETA |
| `keypad` | On-screen keypad | on | on / off | show the gloved-finger on-screen keypad on the Entry/Direct To Waypoint pages and any text/lat-lon prompt |
| `keyboard` | Physical keyboard | off | on / off | let a physical keyboard drive an open ident-entry surface (Entry page, Direct To page's Waypoint tab, or a text/lat-lon prompt) while it is open |
| `default_page` | Default page | `fpl` | `fpl`, `entry` | page shown when the instrument first paints |
| `hmi_group` | HMI group | empty |  | optional name so 'flightplan page'/'flightplan direct to' HMI actions can target this instrument; blank = every flight_plan instrument on the screen |
| `active_color` | Active leg colour | `#ff00ff` | colour | colour of the active (TO) leg's row |
| `future_color` | Future leg colour | `#ffffff` | colour | colour of upcoming (not yet flown) legs |
| `past_color` | Past leg colour | `#808080` | colour | colour of already-flown legs |
| `row_height_mm` | List row height (mm) | `14` | 6 to 30, step 0.5 | physical height of one flight-plan row on the glass. Geometry, not text size: it sets the row pitch, the type icon and the row font. A taller pane shows MORE legs at this height rather than fewer, larger ones. Needs screenDiagonalInches to be correct for the device. |

<!-- /generated -->

Give it an `encoder_order` to put it in the knob's order. Routes, user
waypoints and the recent list are kept under `flightplan_dir`: `routes/*.json`,
`user_waypoints.json` and `recent.json`.

---

## `nav_status`

<!-- generated:nav_status -->

**Nav Status** · palette category `navigation`

How it reads and flies: [Flight Plan](Flight-Plan#the-nav-status-line).

FIX keys it reads by default: `FPLSTATE`, `FPLPHASE`, `WPFROM`, `WPNAME`, `WPNEXT`, `WPDIS`, `WPETE`.

| Option | Configurator label | Default | Values | What it does |
|---|---|---|---|---|
| `show_distance` | Show distance | on | on / off | distance to the TO waypoint (WPDIS), nm |
| `show_ete` | Show ETE | on | on / off | time to the TO waypoint (WPETE), H:MM; '--:--' below 30 kt ground speed |
| `show_phase` | Show phase | on | on / off | flight phase / CDI scale annunciation (FPLPHASE): ENR, TERM, LNAV, ... green; LOI yellow |
| `hmi_group` | HMI group | empty |  | hmi_group of the flight_plan instrument a tap opens; blank = every flight_plan instrument |
| `tap_screen` | Tap screen | empty |  | screen to show before opening the FPL page on a tap (the screen holding the flight_plan instrument); blank = stay on this screen |
| `active_color` | Active waypoint colour | `#ff00ff` | colour | colour of the TO waypoint ident (WPNAME) |
| `text_color` | Text colour | `#ffffff` | colour | colour of the FROM/NEXT idents, separators and data |

<!-- /generated -->
