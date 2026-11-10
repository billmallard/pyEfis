# Attitude & SVS

The attitude display, with or without synthetic vision. What it shows and how
to read it is on [Attitude and Synthetic Vision](Attitude-and-Synthetic-Vision);
this page is the full option list and the data the terrain needs. Each table
is generated from pyEFIS's instrument registry; see
[Widget Reference](Widget-Reference#how-to-read-these-pages).

| `type:` | What it is |
|---|---|
| `virtual_vfr` | The attitude display with synthetic-vision terrain, as a configurator panel uses it. |
| `atitude_indicator` | The attitude display alone. |

The type name `atitude_indicator` is spelt with one `t`, and must be written
that way.

---

## `virtual_vfr`

<!-- generated:virtual_vfr -->

**Virtual VFR / Synthetic Vision** · palette category `attitude`

How it reads and flies: [Attitude and Synthetic Vision](Attitude-and-Synthetic-Vision).

FIX keys it reads by default: `PITCH`, `LAT`, `LONG`, `COURSE`, `ALT`, `ROLL`, `ALAT`, `TAS`.

| Option | Configurator label | Default | Values | What it does |
|---|---|---|---|---|
| `aircraft_symbol` | Aircraft symbol | `classic` | `classic`, `garmin`, `brackets`, `none` | classic split-wing bars + dot; garmin G3X-style two-tone bat wing + horizon barbs; brackets GRT-style L-brackets; none hides the symbol (SVS-as-background) (g1000/gi275 remain accepted in YAML for back-compat) |
| `symbol_color` | Symbol colour | `#ffff00` | colour | colour of the fixed aircraft reference symbol |
| `symbol_scale` | Symbol scale | `1` | 0.3 to 3, step 0.05 | multiplies the reference symbol size -- wingspan and proportions together (1 = standard) |
| `horizon_position` | Horizon position (% up) | `50` | 40 to 80, step 1 | 50 = centred (default); ~67 = two-thirds up the screen |
| `preview_scene` | Preview scene (editor) | `mountains` | `mountains`, `approach`, `final` | which stylised backdrop the editor twin shows (preview only; the device renders real terrain) |
| `show_fpm` | Flight-path marker | on | on / off | GPS flight-path marker (needs VS/GS/TRACK/HEAD) |
| `pitchDegreesShown` | Pitch field of view (deg) | `50` |  | total vertical pitch span shown |
| `minorDiv` | Minor division (deg) | `1` |  | pitch interval between the smallest ladder ticks |
| `majorDiv` | Major division (deg) | `5` |  | pitch interval between the longer ladder ticks |
| `numberedDiv` | Numbered division (deg) | `10` |  | pitch interval at which ladder lines get a number |
| `visiblePitchAngle` | Pitch label range (deg) | `25` |  | ladder marks fade out beyond this from current pitch |
| `pitchOpacity` | Pitch ladder opacity | `0.6` | 0 to 1 | pitch-ladder opacity (0 = invisible, 1 = solid) |
| `bankOpacity` | Bank display opacity | `1` | 0 to 1 | bank scale, roll pointer, standard-rate diamonds and slip/skid ball together (0 = hidden, 1 = solid) |
| `horizonOpacity` | Horizon line opacity | `1` | 0 to 1 | the white zero-pitch reference line (0 = hidden, 1 = solid) |
| `tick_autoscale` | Auto-scale tick widths to font | on | on / off | off = use the explicit tick-width / bank-size pixels below |
| `minorDivWidth` | Minor tick width (px) | `10` |  | length of the minor pitch ticks (auto-scale off) |
| `majorDivWidth` | Major tick width (px) | `40` |  | length of the major pitch ticks (auto-scale off) |
| `numberedDivWidth` | Numbered tick width (px) | `50` |  | length of the numbered pitch ticks (auto-scale off) |
| `drawBankMarkers` | Standard-rate bank markers | on | on / off | show the bank-angle tick arc across the top |
| `bankAngleMaximum` | Max indicated bank (deg) | `25` |  | largest bank angle marked on the bank arc |
| `excessiveBankDeg` | Excessive-bank caution (deg) | `60` | 30 to 65, step 1 | the bank scale and pointer turn amber past this bank; set it above the steepest turn this aircraft is flown in on purpose (60 clears the 45 and 50 deg steep turns) |
| `bankBugTolerance` | Bank bug tolerance (+/- deg) | `5` | 1 to 10, step 1 | half-width of the cyan band around the target-bank bug (BANKBUG); the ACS steep turns are flown to +/-5 |
| `touch_edit` | Touch to set bank bug | on | on / off | touch the bank scale, then turn the knob to set the target-bank bug (BANKBUG) in 5 deg steps, from off up to 60 or the excessive-bank caution if lower; push or the timeout ends the edit |
| `bankMarkSize` | Bank tick size (px) | `10` |  | length of the bank-arc ticks (auto-scale off) |
| `bank_position` | Bank scale position (%) | `50` | 0 to 100 | vertical position of the bank-arc centre, percent up from the bottom (50 = centred, the classic look); the whole cluster incl. pointer and slip ball moves with it |
| `bank_radius` | Bank scale radius (% height) | `33.333` | 10 to 60, step 0.1 | radius of the bank arc as a percent of widget height (33.3 = the classic height/3); an explicit bankAngleRadius px in YAML overrides it |
| `pitch_ladder_avoid_bank` | Ladder stops below bank arc | off | on / off | G1000-style declutter: the ladder climbs into the bank arch but stops below the slip/skid ball |
| `horizon_heading_marks` | Horizon heading marks | off | on / off | tick marks + labels for compass heading along the horizon |
| `horizon_heading_interval` | Heading tick interval (deg) | `10` | 1 to 45, step 1 | degrees of heading between the horizon ticks |
| `horizon_heading_label_interval` | Heading label interval (deg) | `20` | 5 to 90, step 5 | degrees of heading between the numeric labels |
| `horizon_heading_tick_length` | Heading tick length (px) | `5` | 1 to 30, step 1 | length of the horizon heading ticks (px) |
| `horizon_heading_color` | Heading mark colour | `#ffffff` | colour | colour of the horizon heading ticks and labels |
| `svs_enabled` | Synthetic vision enabled | off | on / off | master on/off (rendered on the device; not shown in the editor preview). Off falls back to the legacy CIFP Virtual VFR overlay, which is DEPRECATED (to be removed) and needs a separate FAA CIFP download; on needs no CIFP data |
| `svs_tile_path` | Terrain tile path | empty |  | SRTM3 HGT tile directory on the device |
| `svs_range_nm` | Range (NM) | `50` |  | (rendered on the device; not shown in the editor preview) |
| `svs_auto_range` | Auto range by altitude | on | on / off | (rendered on the device; not shown in the editor preview) |
| `svs_min_range_nm` | Min auto range (NM) | `8` |  | (rendered on the device; not shown in the editor preview) |
| `svs_palette` | Terrain palette | `clearance` | `clearance`, `subdued`, `high_contrast` | clearance-band colour scheme (rendered on the device; not shown in the editor preview) |
| `svs_clearance_green_ft` | Safe clearance (ft) | `1000` |  | green at/above this height over terrain |
| `svs_clearance_yellow_ft` | Caution clearance (ft) | `500` |  | amber above this; red below |
| `svs_terrain_grid` | Terrain grid | `0.35` | 0 to 1 | (rendered on the device; not shown in the editor preview) |
| `svs_terrain_texture` | Terrain texture | `0.35` | 0 to 1 | (rendered on the device; not shown in the editor preview) |
| `svs_safe_gradient` | Safe-band gradient | on | on / off | (rendered on the device; not shown in the editor preview) |
| `svs_earth_curvature` | Earth curvature | on | on / off | (rendered on the device; not shown in the editor preview) |
| `svs_haze` | Distance haze | on | on / off | (rendered on the device; not shown in the editor preview) |
| `svs_haze_distance_nm` | Haze distance (NM) | `40` |  | (rendered on the device; not shown in the editor preview) |
| `svs_dof_db_path` | Obstacle DB path | empty |  | FAA DOF database on the device (optional) |
| `svs_water_db_path` | Water DB path | empty |  | water-polygon database on the device (optional) |
| `svs_highway_db_path` | Highway DB path | empty |  | highway database on the device (optional) |
| `svs_road_color` | Road colour | `#535353` | colour | ribbon fill colour (rendered on the device; not shown in the editor preview) |
| `svs_road_casing_color` | Road casing colour | `#4a4a4a` | colour | darker outline drawn under the fill (rendered on the device; not shown in the editor preview) |
| `svs_road_casing_m` | Road casing width (m) | `2.5` | 0 to 20 | casing half-width add-on over the class width (rendered on the device; not shown in the editor preview) |
| `svs_road_min_px` | Road minimum width (px) | `1.5` | 0.5 to 10, step 0.1 | screen-space floor so distant ribbons never drop below this many pixels wide (rendered on the device; not shown in the editor preview) |
| `svs_road_subdivide_m` | Road subdivide length (m) | `150` | 20 to 1000 | segments longer than this, within subdivide range, are split so the ribbon follows rolling terrain (rendered on the device; not shown in the editor preview) |
| `svs_road_subdivide_nm` | Road subdivide range (NM) | `4` | 0 to 20 | subdivision only applies this close to the aircraft (rendered on the device; not shown in the editor preview) |
| `svs_road_lift_ft` | Road lift (ft) | `2` | 0 to 50 | height above sampled terrain the ribbon is drawn at (rendered on the device; not shown in the editor preview) |
| `svs_road_max_vertices` | Road vertex cap | `400000` | 10000 to 1000000 | hard cap on extruded vertices per array (casing/fill each); over the cap, far-tier ramps are dropped first, then far-tier trunks (rendered on the device; not shown in the editor preview) |
| `svs_papi` | PAPI lights | on | on / off | draw the installed PAPI at its published glide path angle and side, from the NASR airports pack (only where one is installed) (rendered on the device; not shown in the editor preview) |
| `svs_perf_log` | Perf: log summary | off | on / off | print an SVS per-frame profiler summary every 2s (collector/draw timings) to the log -- mirrors map_perf_log. Dev/bench diagnostic; off by default (rendered on the device; not shown in the editor preview) |

<!-- /generated -->

Synthetic vision draws only with **Synthetic vision enabled** on. With it off,
the instrument falls back to the legacy CIFP overlay, which is deprecated and
needs a separate FAA CIFP download.

### How the terrain options reach the renderer

The configurator writes the terrain options flat, each with an `svs_` prefix.
pyEFIS strips the prefix and lays them over any nested `svs:` block, so a flat
option wins over the same key in `svs:`. Some renderer keys are not in the
configurator's list and can only be set in the `svs:` block:

| `svs:` key | Default | What it does |
|---|---|---|
| `nasr_db_path` | empty | The airports pack: runways, PAPI and airport flags. |
| `airport_provider_dir` | empty | A directory of extra airport packs, found automatically. |
| `cifp_path`, `cifp_index_path` | empty | Airport data from CIFP, used only when the airports pack is not available. |
| `paved_only` | `true` | Draw only paved runways. |
| `airport_proximity_nm` | `5` | Within this distance of an airport, low terrain is drawn green; 0 turns this off. |
| `airport_gate_agl_ft` | `400` | How far above field elevation that rule reaches. |
| `obstacle_min_agl_ft` | `200` | Shortest obstacle drawn. |
| `detail_distance_nm` | `3` | Runways closer than this get their markings. |
| `papi_range_nm` | `5` | How far away a PAPI is drawn. |
| `road_widths_m` | see below | Road width per road class, in metres per carriageway. |
| `water_max_vertices` | the pack's default | Vertex cap per water polygon. |
| `heightmap_max_px` | `4096` | Largest terrain texture. |
| `msaa_samples` | `2` | Anti-aliasing samples. |
| `frame_rate` | `30` | Terrain frame rate, 5 to 60. |

`road_widths_m` defaults: motorway 16, trunk 13, primary 11, secondary 8, motorway
and trunk links 7, primary and secondary links 6; any other class 7. Override
any subset, for example `road_widths_m: {motorway: 18}`. A dual carriageway is
two ways, each drawn at its own width.

Any data path that is missing or unreadable drops that layer; the rest still
draws.

### PAPI

A PAPI is drawn only where the airports pack lists one (`P2L`, `P2R`, `P4L` or
`P4R`) with a published glide path angle; pyEFIS never assumes 3 degrees. The
row sits on its published side, abeam the 1,000 ft aiming point, 50 ft outside
the runway edge. The boxes are set as FAA AC 150/5340-30 describes: a 4-box row
at the published angle +30', +10', -10' and -30' from the runway outward, a
2-box row at +/-15'. It shows within the PAPI's +/-10 degree azimuth coverage,
within `papi_range_nm`, ahead of the nose and not behind terrain. VASI and
other systems are not drawn. The PAPI does not write `GSI`.

### Example

The bench panel's attitude display, trimmed:

```yaml
- type: virtual_vfr
  row: 0
  column: 0
  span: {rows: 110, columns: 130}
  options:
    aircraft_symbol: garmin
    horizon_position: 68
    svs_enabled: true
    svs_clearance_green_ft: 2500
    svs_clearance_yellow_ft: 1500
    svs_tile_path: /data/makerplane-data/terrain/tiles
    svs_water_db_path: /data/makerplane-data/water/current/water.sqlite
    svs_highway_db_path: /data/makerplane-data/highways/current/highways.sqlite
    svs_dof_db_path: /data/makerplane-data/obstacles/current/obstacles.sqlite
    svs:
      nasr_db_path: /data/makerplane-data/navdata/current/airports.sqlite
      airport_provider_dir: /data/makerplane-data/airports
```

One terrain option in the configurator's list has no effect on the device
today: **Terrain palette**
([#394](https://github.com/billmallard/pyEfis/issues/394)). Terrain is always
drawn filled; the old **Fill terrain** option was removed because no wireframe
mode exists ([#395](https://github.com/billmallard/pyEfis/issues/395)). A saved
screen that still carries `svs_terrain_fill` loads normally and the key is
ignored.

### FIX keys

| Key | Used for |
|---|---|
| `PITCH`, `ROLL` | Attitude (pitch held to +/-90, roll to +/-180). |
| `ALAT` | The slip indicator (held to +/-0.3 g). |
| `TAS` | The standard-rate marks. |
| `LAT`, `LONG`, `ALT` | Where the terrain is drawn from. Old, bad, failed or missing: no terrain, and `SVS UNAVAIL`. |
| `HEAD`, `MAGVAR` | Which way the terrain faces, and the horizon heading marks. |
| `VS`, `GS`, `TRACK`, `VPATH` | The flight path marker. |
| `AOA` and its `Warn` aux | The pitch-limit indicator, drawn `Warn` minus `AOA` degrees above the aircraft symbol when that is 8 or less. Old, bad, failed, missing, or no `Warn`: not drawn. |
| `COURSE` | The legacy CIFP overlay's heading. |

Any of `PITCH`, `ROLL`, `ALAT` or `TAS` old or bad turns the sky grey; any
failed shows a dark grey display with a red `XXX`.

---

## `atitude_indicator`

The same attitude symbology on a square face, without terrain.

![Attitude indicator](../images/atitude_indicator.png)

<!-- generated:atitude_indicator -->

**Attitude Indicator** · palette category `attitude`

How it reads and flies: [Attitude and Synthetic Vision](Attitude-and-Synthetic-Vision).

FIX keys it reads by default: `PITCH`, `ROLL`, `ALAT`, `TAS`.

| Option | Configurator label | Default | Values | What it does |
|---|---|---|---|---|
| `aircraft_symbol` | Aircraft symbol | `classic` | `classic`, `garmin`, `brackets`, `none` | classic split-wing bars + dot; garmin G3X-style two-tone bat wing + horizon barbs; brackets GRT-style L-brackets; none hides the symbol (SVS-as-background) (g1000/gi275 remain accepted in YAML for back-compat) |
| `symbol_color` | Symbol colour | `#ffff00` | colour | colour of the fixed aircraft reference symbol |
| `symbol_scale` | Symbol scale | `1` | 0.3 to 3, step 0.05 | multiplies the reference symbol size -- wingspan and proportions together (1 = standard) |
| `show_fpm` | Flight-path marker | on | on / off | GPS flight-path marker (needs VS/GS/TRACK/HEAD) |
| `pitchDegreesShown` | Pitch field of view (deg) | `50` |  | total vertical pitch span shown |
| `minorDiv` | Minor division (deg) | `1` |  | pitch interval between the smallest ladder ticks |
| `majorDiv` | Major division (deg) | `5` |  | pitch interval between the longer ladder ticks |
| `numberedDiv` | Numbered division (deg) | `10` |  | pitch interval at which ladder lines get a number |
| `visiblePitchAngle` | Pitch label range (deg) | `25` |  | ladder marks fade out beyond this from current pitch |
| `pitchOpacity` | Pitch ladder opacity | `0.6` | 0 to 1 | pitch-ladder opacity (0 = invisible, 1 = solid) |
| `bankOpacity` | Bank display opacity | `1` | 0 to 1 | bank scale, roll pointer, standard-rate diamonds and slip/skid ball together (0 = hidden, 1 = solid) |
| `horizonOpacity` | Horizon line opacity | `1` | 0 to 1 | the white zero-pitch reference line (0 = hidden, 1 = solid) |
| `tick_autoscale` | Auto-scale tick widths to font | on | on / off | off = use the explicit tick-width / bank-size pixels below |
| `minorDivWidth` | Minor tick width (px) | `10` |  | length of the minor pitch ticks (auto-scale off) |
| `majorDivWidth` | Major tick width (px) | `40` |  | length of the major pitch ticks (auto-scale off) |
| `numberedDivWidth` | Numbered tick width (px) | `50` |  | length of the numbered pitch ticks (auto-scale off) |
| `drawBankMarkers` | Standard-rate bank markers | on | on / off | show the bank-angle tick arc across the top |
| `bankAngleMaximum` | Max indicated bank (deg) | `25` |  | largest bank angle marked on the bank arc |
| `excessiveBankDeg` | Excessive-bank caution (deg) | `60` | 30 to 65, step 1 | the bank scale and pointer turn amber past this bank; set it above the steepest turn this aircraft is flown in on purpose (60 clears the 45 and 50 deg steep turns) |
| `bankBugTolerance` | Bank bug tolerance (+/- deg) | `5` | 1 to 10, step 1 | half-width of the cyan band around the target-bank bug (BANKBUG); the ACS steep turns are flown to +/-5 |
| `touch_edit` | Touch to set bank bug | on | on / off | touch the bank scale, then turn the knob to set the target-bank bug (BANKBUG) in 5 deg steps, from off up to 60 or the excessive-bank caution if lower; push or the timeout ends the edit |
| `bankMarkSize` | Bank tick size (px) | `10` |  | length of the bank-arc ticks (auto-scale off) |
| `bank_position` | Bank scale position (%) | `50` | 0 to 100 | vertical position of the bank-arc centre, percent up from the bottom (50 = centred, the classic look); the whole cluster incl. pointer and slip ball moves with it |
| `bank_radius` | Bank scale radius (% height) | `33.333` | 10 to 60, step 0.1 | radius of the bank arc as a percent of widget height (33.3 = the classic height/3); an explicit bankAngleRadius px in YAML overrides it |
| `pitch_ladder_avoid_bank` | Ladder stops below bank arc | off | on / off | G1000-style declutter: the ladder climbs into the bank arch but stops below the slip/skid ball |
| `horizon_heading_marks` | Horizon heading marks | off | on / off | tick marks + labels for compass heading along the horizon |
| `horizon_heading_interval` | Heading tick interval (deg) | `10` | 1 to 45, step 1 | degrees of heading between the horizon ticks |
| `horizon_heading_label_interval` | Heading label interval (deg) | `20` | 5 to 90, step 5 | degrees of heading between the numeric labels |
| `horizon_heading_tick_length` | Heading tick length (px) | `5` | 1 to 30, step 1 | length of the horizon heading ticks (px) |
| `horizon_heading_color` | Heading mark colour | `#ffffff` | colour | colour of the horizon heading ticks and labels |

<!-- /generated -->

It draws terrain only if a nested `svs:` block with `enabled: true` is in its
options; the flat `svs_` options are read by `virtual_vfr` only.
