# Moving Map

The moving map shows where you are over terrain, water, roads, airports, navaids
and the flight plan. On the bench panel it fills the **Map** tab of the
right-hand tab column. The instrument type is `moving_map`.

![The bench's Map tab on the KSMX RNAV 30, 10 nm north up: the flown leg grey, the active leg to CIMSO magenta with CIMSO ringed, the legs ahead white with their altitude constraints, the missed approach dashed, airways in blue, roads in grey, and the yellow ownship arrow](../images/map/bench_map_approach.png)

## Reading it

| Element | What it shows |
|---|---|
| **Status chip** (top left) | The range and orientation: `10 NM  NORTH UP` or `10 NM  TRK UP`. `NO POS` is added when the position is stale. |
| **Ownship** | An arrow pointing along your ground track, yellow by default. It turns grey when the position is stale. |
| **Range rings** | Rings at half and full range by default, labelled with their distance in nm. |
| **Terrain** | Shaded relief coloured by elevation, from green at sea level to white at 14,000 ft, lit from the north-west. Water is blue. |
| **Roads** | Grey, wider and bolder for bigger roads. |
| **Rivers** | Thin blue lines. |
| **Airports** | Magenta. A hard-surface airport is a circle with its runways drawn inside at their real orientation. A field with a runway over 8,069 ft shows the runways alone, and a soft field is a plain circle. Zoomed in far enough, runways draw to true size. |
| **Navaids** | A VOR is a hexagon with a centre dot, an NDB a stippled disc. The label is the ident, with the frequency at 40 nm and below. |
| **Waypoints** | Open triangles with idents, at 20 nm and below, when the layer is on. |
| **Airways** | Blue lines, with each airway's ident at 80 nm and below, when the layer is on. |

Towered and untowered airports look the same today; there is no airspace or
obstacle layer on the map.

### The flight plan

| Drawn as | Means |
|---|---|
| Magenta line | The active leg. The waypoint you are flying to is ringed in magenta. |
| White line | Legs ahead. |
| Grey line | Legs already flown. |
| Dashed line | Missed-approach legs. |
| Dotted line | Vector legs. |
| Racetrack | A hold or procedure turn, drawn as its pattern. |
| Entry at a hold | The parallel or teardrop entry fix-gateway's engine will fly into the next hold, and its name (`PARALLEL`, `TEARDROP` or `DIRECT`, or `PAR`/`TDP`/`DIR` on a small map) above the hold fix, at 80 nm and below. Dashed while it is the engine's prediction, solid once the engine reports it is flying that entry. A direct entry draws nothing but the name. With a gateway that does not publish the entry, the racetrack is drawn alone. |
| Rounded corner | A fly-by turn: the arc fix-gateway's engine will fly at that waypoint. The leg into it ends at the middle of the arc, where the engine moves on to the next leg. A corner stays square where the engine turns no arc, or where a leg next to it is too short or is a hold or vector. |
| Magenta line from where you were | An off-route Direct-To. |
| Dashed magenta line past the runway | The extended final course, 5 nm, while the plan is suspended at the missed approach point. |
| Magenta line through the waypoint, in OBS | GPS OBS: the course you set, through the waypoint you are flying to. It runs 30 nm or 1.5 map ranges each side of the waypoint, whichever is longer. The plan's leg into that waypoint is then drawn white, like the legs ahead. See [Flight Plan](Flight-Plan#the-menu). |

A line longer than 110 nm is drawn along its great circle, through points no
more than 20 nm apart, so it shows the course the engine flies. This applies to
plan legs, hold and procedure-turn patterns, the Direct-To line and the OBS
line.

Waypoint symbols follow their type: hexagon for a VOR, stippled disc for an
NDB, triangle for a fix, circle for an airport, filled diamond for a user
waypoint and filled square for a point made on the map. Labels carry `IAF`,
`FAF`, `MAP` or `MAHP` where the procedure says so, and altitude constraints
are drawn with chart-style bars: a bar above for at-or-below, below for
at-or-above, both for at. Where the airport, navaid or waypoint layer already
shows the place, the plan keeps that layer's symbol and ident and adds only
the ring and the role.

![The bench in the WINCH hold, 10 nm north up: the hold drawn as a magenta racetrack at WINCH, with the coastline, Avila and the airports around San Luis Obispo](../images/map/bench_map_hold.png)

### Traffic

With the traffic layer on (the default) and fix-gateway publishing ADS-B
traffic, each target is drawn at its position:

| Drawn as | Means |
|---|---|
| White arrowhead | A target, pointing along its track. A diamond when its track is not known. |
| Number by the symbol | Relative altitude in hundreds of feet: `+05` is 500 ft above you, `-12` is 1,200 ft below, `00` is level. It sits above the symbol for traffic above you and below it otherwise. `--` when the target's altitude or your pressure altitude (`PALT`) is not available. |
| Arrow to the right | The target is climbing or descending at 500 ft/min or more. |
| Yellow, flashing | An alerted target. |
| Open outline | A target with degraded position accuracy (NIC or NACp of 4 or less). |
| Grey, dashed | A stale target, with no recent report. It goes when fix-gateway drops it, or 12 seconds after its last report at the latest. |

An amber **TFC FAIL** at the bottom left means the traffic source has failed or
stopped reporting after it was working, so an empty map does not mean an empty
sky. An installation that has never had traffic shows nothing.

### What hides as you zoom out

| Item | Shown at or below |
|---|---|
| Waypoints | 20 nm |
| Airport idents, navaid frequencies | 40 nm |
| Airport symbols, airway labels, flight-plan labels and constraints | 80 nm |
| Navaids, airways, flight-plan symbols | 160 nm |
| Roads | 5 nm for secondary roads up to 80 nm for motorways |

Where airports crowd together, the two with the longest runways in each patch
of the map are kept.

### ND mode: EXPANDED MAP

With `nd_mode: expanded` the map is drawn as a navigation display. It is
always track up, whatever `orientation` says, and ownship sits 82% of the way
down, whatever `ownship_position` says. The selected range reaches the compass
arc instead of the top edge.

![ND EXPANDED on the bench's map panel, 10 NM, tracking 072 toward KSBA: the compass arc with the TRK 072 MAG box, GS, TAS and wind top left, KSBA with its ETA and distance top right, ARPT, WPT and STA bottom left, and the vertical deviation scale at the right edge](../images/aer5085_nd_expanded/panel/nd_approach_standard.png)

| Element | What it shows |
|---|---|
| **Compass arc** | At the selected range, ticks every 5°, a numeral every 30° in tens (`6` is 060). Labelled magnetic: the map turns by true track, and the arc is offset by `MAGVAR`, so the bearing under the pointer is the TRK box's. With no `MAGVAR` published the arc reads true. |
| **TRK box** | `TRK`, the magnetic track and `MAG` over the top of the arc, with a pointer under it. Grey when `TRACKM` is stale. |
| **Top left** | `GS` and `TAS`, then the wind as direction°/speed with an arrow pointing the way it blows. |
| **Top right** | The active waypoint in magenta, its ETA in UTC (`HHMM.Mz`, now plus `WPETE`) and its distance in NM. Only while a plan is active (`FPLSTATE` not 0); ETA and distance are left out in the `VECTORS` phase. |
| **Bottom left** | The map layers that are on, in cyan: `ARPT` (airports), `WPT` (waypoints), `STA` (navaids). |
| **Vertical deviation scale** | Right edge, from `GSI`, with a magenta diamond pointer. Hidden when `GSV` is published and below 0.5 (no glidepath). When the scale is up and `GSI` is stale, bad or failed, the diamond is removed and a red `GS` flag shows, as on the HSI. This includes an older gateway that publishes no `GSV`. |

A failed value in a data block reads red `XXX`; an old or bad one is grey. A
key fix-gateway does not define is left out.

#### CTR MAP

With `nd_mode: ctr` the map shows the same elements around a full compass rose,
with ownship at the centre of the panel. The rose is at the selected range, so
the range reaches the same distance ahead and behind. It is sized to fit the
panel under the TRK box, clear of the deviation scale.

![ND CTR MAP on the bench's map panel, 10 NM, tracking 072 toward KSBA: the full compass rose round the centred ownship, with the same TRK box, data blocks and deviation scale as EXPANDED](../images/aer5262_nd_ctr/panel/nd_ctr_approach_standard.png)

## Using it

- **Zoom:** pinch, or the mouse wheel on a desktop. Zoom is continuous between
  the smallest and largest range on the **range ladder**. Buttons or a knob
  bound to the map step through the ladder's ranges instead.
- **Pan and rotate:** drag to pan; twist two fingers to rotate. Shift- or
  Ctrl-drag rotates with a mouse.
- **Back to your position:** double-tap, or tap the amber **CTR** chip in the
  top right. The map re-centres by itself 30 seconds after the last gesture.
- **Orientation** is track up or north up. It is set in the configurator, or
  switched by a key bound to the map. Track up puts the true ground track
  (`TRACK`) at the top, so your path over the ground runs straight up the
  screen; the ownship arrow points along the true track in north up.

### Tap something

Tap a symbol and the map puts a pointer on it and opens a banner along the
bottom: the ident and type, then the bearing and distance from you, the
terrain elevation and any frequency. Tap where several symbols overlap and you
get a list to choose from; tap open ground and you get a **MAP POINT** at that
position.

![Tap on RZS: the pointer on the VOR, and the banner with RZS VOR, 012° 7.8 NM, ELEV 3596 FT, 114.9 and its five keys (an earlier bench capture, no position)](../images/fp10_map_edit/01_tap_rzs_banner.png)

| Key | What it does |
|---|---|
| **DIRECT TO** | Fly direct to it. A toast says `DIRECT TO <ident>`, or `REJECTED:` and the reason. |
| **INSERT** | Insert it into the flight plan, in the nearest leg. |
| **CREATE WPT** | Make a user waypoint here, on the Flight Plan tab. |
| **INFO** | Open its details on the Flight Plan tab. |
| **X** | Close the banner. |

**DIRECT TO** and **INSERT** need fix-gateway's flight-plan engine; without it
they are greyed. **CREATE WPT** and **INFO** bring the Flight Plan tab forward.
See [Flight Plan](Flight-Plan).

## When data is missing

- **`NO POS`** and a grey ownship: `LAT` or `LONG` is stale. The map stays at
  the last position it had.
- **A layer is empty:** its navdata pack is not installed, or its path is not
  set. The map does not say which; check
  [Data Status](Data-Status-Updates-and-Notices).

## Customizing

### In the configurator

Select the map in the Panel Editor; its options are in **Properties**. The most
used, with defaults and the bench panel's value where it differs:

| Option | Default | Bench | What it does |
|---|---|---|---|
| Range (`range_nm`) | 10 nm | | Distance from the ownship to the top edge at start; to the compass arc in ND mode. |
| Range ladder (`range_ladder`) | `2,5,10,20,40,80,160` | `2,10,50,200,500,2000` | The ranges the buttons step through; also the zoom limits. |
| Range control key (`range_key`) | | | A FIX key that steps the range. |
| Zoom rail (`zoom_rail`) | off | | A one-finger zoom strip down one edge. |
| Orientation (`orientation`) | `track_up` | `north_up` | |
| Orientation control key (`orientation_key`) | | | A FIX key: 0 track up, 1 north up. |
| ND mode (`nd_mode`) | `off` | | `expanded` draws the [ND EXPANDED MAP](#nd-mode-expanded-map); `ctr` draws [CTR MAP](#ctr-map). |
| ND mode control key (`nd_mode_key`) | | | A FIX key: 0 off, 1 expanded, 2 ctr. |
| Touch gestures (`touch_gestures`) | on | | Off ignores every touch and the wheel. |
| Gesture auto-revert (`gesture_timeout`) | 30 s | | 0 stays where you leave it. |
| Ownship position (`ownship_position`) | 50 | | Percent up from the bottom; 30 shows more ahead. |
| Map style (`map_style`) | `standard` | | `nav_only` drops the relief for a black background. |
| Terrain mode (`terrain_mode`) | `relief` | | `caution` lays the synthetic vision's hazard bands over the relief: amber within 1,000 ft below you, red within 500 ft, magenta above you. Near an airport, the runway environment gets no band. |
| Terrain hazard palette (`terrain_palette`) | `clearance` | `subdued`, `high_contrast` | The band colours in `caution` mode, the same schemes as the synthetic vision palette. |
| Caution and warning clearance (`clearance_green_ft`, `clearance_yellow_ft`) | 1,000 ft, 500 ft | | The band thresholds in `caution` mode, the same defaults as the synthetic vision. |
| Layer: terrain / roads / rivers / airports / navaids / flight plan / traffic / range rings | on | | |
| Layer: waypoints (`layer_fixes`) | off | on | |
| Layer: airways (`layer_airways`) | off | on | |
| Range ring fractions (`range_ring_fractions`) | `0.5,1` | | |
| Terrain tile path, Airport db path, Navaid db path, Roads db path, Water db path | | the installed packs | Where each navdata pack is installed. |

Ring colour, width and label position, road and river colours, the water
rendering options and the gesture thresholds are in the same Properties list.

### In YAML

Trimmed from the bench panel:

```yaml
- type: moving_map
  options:
    orientation: north_up
    range_ladder: 2,10,50,200,500,2000
    layer_airways: true
    layer_fixes: true
    terrain_mode: relief
    tile_path: /data/makerplane-data/terrain/tiles
    nasr_db_path: /data/makerplane-data/navdata/current/airports.sqlite
    navaid_db_path: /data/makerplane-data/navaids/current/navaids.sqlite
    water_db_path: /data/makerplane-data/water/current/water.sqlite
    highway_db_path: /data/makerplane-data/highways/current/highways.sqlite
```

### Feeding it

The map reads `LAT`, `LONG`, `TRACK`, `TRACKM`, `ALT` and `MAGVAR`, and the flight-plan
keys fix-gateway's flight-plan engine publishes. ND mode also reads `GS`, `TAS`,
`WINDDIR`, `WINDSPD`, `WPDIS`, `WPETE`, `GSI` and `GSV`. The traffic layer
reads fix-gateway's traffic block (`TFCCOUNT` and the `TFCn...` slot keys) and
`PALT`; the fly-by arcs come from `FPLfTA`. The map writes `DTOID`, `DTOLAT`,
`DTOLON`, `DTOTYPE` and `FPLCMD` for a Direct-To, the route block for an
insert, and the range index to `range_key` when one is set. See
[FIX Database Keys](FIX-Database-Keys).

## See also

- [Flight Plan](Flight-Plan)
- [The HSI](The-HSI)
- [Flight Plan Engine](https://github.com/billmallard/fix-gateway/wiki/Flight-Plan-Engine) (fix-gateway wiki)
