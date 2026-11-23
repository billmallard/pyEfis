# FIX Database Keys

pyEFIS draws **FIX keys**, the named values fix-gateway publishes, and writes
some back when the pilot sets something. This page lists the keys the shipped
instruments and configuration read and write. The master list of keys, their
types and their CAN-FIX parameters belongs to fix-gateway and CAN-FIX, not to
pyEFIS; your fix-gateway may define more. How keys, quality flags and aux
values work is on
[Customizing Beyond the Configurator](Customizing-Beyond-the-Configurator#the-data).

## Air data

| Key | Units | Meaning | Read by | Written by |
|---|---|---|---|---|
| `IAS` | kt | Indicated airspeed; carries the V-speed aux values | airspeed tape and dial, `airspeed_box` | |
| `TAS` | kt | True airspeed | the airspeed tape's TAS box, `airspeed_box`, the attitude display (standard-rate marks) | |
| `GS` | kt | Groundspeed | `airspeed_box`, the HSI (track diamond), the flight path marker | |
| `ALT` | ft | Indicated altitude | altitude tape and dial, synthetic vision, the moving map | |
| `VS` | ft/min | Vertical speed | VSI instruments, the flight path marker | |
| `BARO` | inHg | Altimeter setting, always in inHg on the bus | altitude tape | the altitude tape's box, the baro buttons |
| `ALTSEL` | ft | Selected altitude | altitude tape, `autopilot_panel` | the altitude tape's box, the autopilot panel's ALT SEL box |
| `OAT` | °C | Outside air temperature | text readouts on the stock screens; switched by **Units** | |
| `PALT`, `DALT` | ft | Pressure and density altitude | text readouts on the stock screens; `PALT` also the traffic on the map and in synthetic vision | |

**`IAS` aux values:** `Vs`, `Vs0`, `Vno`, `Vne` and `Vfe`. They draw the
airspeed bands; see
[Airspeed, Altitude and Vertical Speed](Airspeed-Altitude-and-Vertical-Speed#airspeed-tape).

## Attitude

| Key | Units | Meaning | Read by |
|---|---|---|---|
| `PITCH` | deg | Pitch | attitude displays |
| `ROLL` | deg | Bank | attitude displays |
| `ALAT` | g | Lateral acceleration (slip) | attitude displays, `turn_coordinator` |
| `ROT` | deg/s | Rate of turn | `turn_coordinator`, the HSI (turn-rate trend) |
| `VPATH` | deg | Flight path angle, used before `VS`/`GS` while it is current (not old, bad or failed) | flight path marker |
| `AOA` | deg | Angle of attack; its `Warn` aux is the stall-warning AOA | the attitude displays' pitch-limit indicator |

## Heading, position and navigation

| Key | Units | Meaning | Read by | Written by |
|---|---|---|---|---|
| `HEAD` | deg | Magnetic heading | HSI, heading instruments, synthetic vision | |
| `MAGVAR` | deg | Magnetic variation | synthetic vision, the moving map, the flight plan page | |
| `TRACK` | deg | GPS ground track, true | flight path marker, the moving map | |
| `TRACKM` | deg | GPS ground track, magnetic | HSI (track diamond), the moving map | |
| `LAT`, `LONG` | deg | Position | synthetic vision, the moving map, the flight plan page, listbox Nearest sort | |
| `HEADBUG` | deg | Selected heading | HSI, `autopilot_panel` | the HSI's HDG edit, the heading-bug buttons, the autopilot panel's HDG box |
| `NAVSRC` | | Selected nav source: `0` NAV1, `1` NAV2, `2` GPS | HSI | the HSI's source tab |
| `COURSE` | deg | Course of the selected source | HSI | |
| `CDI` | -1 to 1 | Lateral deviation of the selected source | HSI | |
| `CDIV` | | Lateral deviation valid | HSI | |
| `TOFROM` | | TO/FROM of the selected source | HSI | |
| `GSI` | -1 to 1 | Vertical deviation of the selected source | HSI, `virtual_vfr` | |
| `GSV` | | Vertical deviation valid | HSI | |
| `NAVTYPE` | | VOR or LOC, for the source tab; nothing in fix-gateway publishes it today | HSI | |
| `NAVSUPP` | | 1 when the selected NAV radio is a supplemental receiver | HSI (amber `SUPP` mark) | |
| `NAV1CRS`, `NAV2CRS` | deg | Course set on each NAV radio | | the HSI's CRS edit |
| `BRG1`, `BRG2` | deg | Bearing pointers 1 and 2 | HSI | |
| `BRG1SRC`, `BRG2SRC` | | What each bearing pointer points at | HSI | the HSI's BRG tab and bearing labels |
| `VOR1BRG`, `VOR2BRG` | deg | Bearing to each VOR | HSI (CRS push) | |
| `TFCCOUNT`, `TFCnTGT` and the `TFCn` slot fields | | ADS-B traffic targets, from fix-gateway's traffic writer | the moving map's traffic layer, synthetic vision traffic | |
| `HWIND`, `XWIND` | kt | Headwind (negative is tailwind), crosswind (positive is from the right) | `wind_display` | |

**Nav-source selection.** `COURSE`, `CDI`, `TOFROM` and `GSI` always carry the
source `NAVSRC` selects. The per-source keys (`NAV1CRS`, `NAV1CDI`, `GPSCRS`
and so on) live in fix-gateway, whose `compute` plugin routes the selected one
into the canonical keys. See [The HSI](The-HSI#nav-sources) and
[The HSI: feeding it](The-HSI#feeding-it). `NAVSRC` is 0 NAV1, 1 NAV2, 2 GPS.
The HSI's source tab and the shipped `cdi-source` button both cycle it in that
order and colour it the same way: green for a NAV source, magenta for GPS.

## Flight plan

The flight-plan engine is fix-gateway's `flightplan` plugin; see
[Flight Plan Engine](https://github.com/billmallard/fix-gateway/wiki/Flight-Plan-Engine).
The flight plan page writes the route and commands to these keys and reads the
engine's guidance back. fix-gateway's key table is the authority; this table is
what pyEFIS touches.

| Key | Units | Meaning | Written by |
|---|---|---|---|
| `FPLfID` / `FPLfLAT` / `FPLfLON` (`f` = 1 to 100) | text / deg / deg | Route slot ident and position | pyEFIS |
| `FPLfTYPE` / `FPLfFLAGS` | | Slot type (0 unknown to 6 map point) / flags (`0x01` fly-over, `0x02` IAF, `0x04` FAF, `0x08` MAP, `0x10` MAHP, `0x20` coded procedure) | pyEFIS |
| `FPLfPT` / `FPLfCRS` / `FPLfDST` | / deg mag / nm | Leg path terminator (`TF` by default) / course / distance or radius | pyEFIS |
| `FPLfALT` / `FPLfSPD` | / kt | Altitude constraint (`"+7000"`; an airway leg's MEA) / speed constraint | pyEFIS |
| `FPLfCTRLAT` / `FPLfCTRLON` / `FPLfTURN` | deg / deg / | Arc centre / turn direction (RF, AF and holds) | pyEFIS |
| `FPLfSGI` | | The segment row this slot belongs to | pyEFIS |
| `FPLSfKIND` / `FPLSfID` | | Segment kind (0 waypoint, 1 airway, 2 departure, 3 arrival, 4 approach, 5 missed) / ident (`V27`) | pyEFIS |
| `FPLSfENT` / `FPLSfEXT` / `FPLSfFIRST` / `FPLSfLAST` | | Segment entry and exit idents, first and last slot | pyEFIS |
| `FPLSEGCNT`, `FPLCOUNT` | | Segment rows / slots in use | pyEFIS |
| `FPLNAME`, `FPLDBCYC` | | Route name / AIRAC cycle the airways and procedures came from | pyEFIS |
| `FPLAPRTYPE` | | Type of the loaded approach (`RNAV`, `ILS`, `VOR`), empty with none | pyEFIS |
| `FPLSEQ` | | Commit counter, written last; the engine acts when it changes | pyEFIS |
| `DTOID` / `DTOLAT` / `DTOLON` / `DTOTYPE` | | Direct-To target | pyEFIS |
| `FPLCMD` | | `"<seq> VERB [arg]"`: `ACT`, `DTO`, `DTOX`, `SUSP`, `RESUME`, `SCALE`, `OBS <deg>`, `OBS OFF` (OBS from the flight plan menu, and from the HSI's CRS knob in OBS) | pyEFIS |
| `FPLCMDACK` / `FPLMSG` | | Acknowledgement (negative is a rejection) / last message | engine |
| `FPLSTATE` / `FPLACTLEG` | | 0 none, 1 leg, 2 direct, 3 suspended, 4 OBS / slot of the TO waypoint | engine |
| `FPLPHASE` / `FPLAPR` / `FPLINTEG` | | Phase / approach state / integrity | engine |
| `FPLSUSPMAP` | | Suspended at the missed approach point | engine |
| `FPLLDSEQ` | | The `FPLSEQ` of the route the engine has loaded; differs from `FPLSEQ` after a refused commit | engine |
| `FPLHOLDSLOT` / `FPLHOLDENT` / `FPLHOLDCOMMIT` | | Slot of the next hold (0 none) / its entry, `DIRECT`, `TEARDROP`, `PARALLEL` or empty / true once the entry is being flown, false while it is a prediction | engine |
| `CDISCALE` | nm | Full-scale deflection | engine |
| `FPLCRS` / `FPLXTK` / `FPLCDI` / `FPLTF` | deg / nm / -1 to 1 / | Desired track / cross-track / deviation / TO-FROM | engine |
| `FPLFRLAT` / `FPLFRLON` | deg | Where a Direct-To started | engine |
| `WPNAME` / `WPLAT` / `WPLON` | | The TO waypoint | engine |
| `WPFROM` / `WPNEXT` | | FROM and NEXT idents | engine |
| `WPDIS` / `WPETE` | nm / s | Distance and time to the TO waypoint | engine |
| `FPLREMDIS` / `FPLREMETE` | nm / s | Distance and time to the end of the plan | engine |
| `FPLACTSEG` / `FPLSEGREM` | / nm | Segment of the TO slot / distance left in it | engine |
| `FPLALERT` | | Engine alert | engine |
| `FPLfTA` | nm | Fly-by turn anticipation at slot `f`, 0 for no arc; the map draws the turn from it | engine |
| `FPLTURN` | | `L` or `R` while the engine flies the turn coded at the start of a direct-to-fix leg | engine |
| `GPSSRC` | | 0 pyEFIS's plan, 1 an external navigator | fix-gateway configuration |

The `nav_status` line reads `FPLSTATE`, `FPLPHASE`, `WPFROM`, `WPNAME`,
`WPNEXT`, `WPDIS`, `WPETE`, `FPLAPRTYPE`, `FPLDBCYC` and `FPLTURN`. The HSI
reads `FPLSTATE`, `GPSSRC` and `GPSBRG` for GPS OBS; see
[The HSI](The-HSI#gps-obs).

## Autopilot

The autopilot is a fix-gateway source; see [Autopilot](Autopilot). pyEFIS
reads its state and sends it requests.

| Key | Meaning | Read by | Written by |
|---|---|---|---|
| `APENG`, `FDENG`, `YDENG` | Autopilot engaged, flight director on, yaw damper on | `autopilot_panel`; `ap_annunciator` (`APENG`, `YDENG`); the attitude displays' flight director (`FDENG`) | the autopilot |
| `APLAT`, `APVERT` | The active lateral and vertical modes (`HDG`, `GPS`, `ALT`, `VS` and so on) | `autopilot_panel`, `ap_annunciator` | the autopilot |
| `APLATARM`, `APVERTARM` | The armed lateral and vertical modes, a comma list (`GS,ALT`) | `autopilot_panel`, `ap_annunciator` | the autopilot |
| `APALTCAP` | Capturing the selected altitude | `autopilot_panel`, `ap_annunciator`, the altitude tape (ALTSEL box border) | the autopilot |
| `APALTREF` | The altitude ALT hold is holding | `ap_annunciator` | the autopilot |
| `APDISC` | Disconnect alert, held by the autopilot until acknowledged | `ap_annunciator` | the autopilot |
| `APCAPS` | The modes the autopilot can fly, a comma list | `autopilot_panel` | the autopilot |
| `APMSG` | The autopilot's message | `autopilot_panel` | the autopilot |
| `FDPITCH`, `FDROLL` | Flight director commanded pitch and bank | the attitude displays | the autopilot |
| `APCMD` | A request: a key name (`HDG`, `AP`, `LVL` and so on), or `DISC` | | `autopilot_panel` (key presses), `ap_annunciator` (`DISC` to acknowledge a disconnect) |
| `APCMDSEQ` | Request counter, written after `APCMD`; the autopilot acts when it changes | | `autopilot_panel`, `ap_annunciator` |
| `VSSEL` | Selected vertical speed, ft/min | `autopilot_panel`, `ap_annunciator`, `vsi_pfd`, an altitude tape set to `VS` | the autopilot panel's VS box |
| `IASSEL` | Selected airspeed, kt; 0 is no target | `autopilot_panel`, `ap_annunciator`, the airspeed tape | the autopilot panel's IAS box, the airspeed tape's IAS box |

The airspeed tape, the altitude tape and `vsi_pfd` also check that `APENG`,
`YDENG`, `APLAT`, `APLATARM`, `APVERT`, `APVERTARM`, `APALTCAP` and `APDISC`
are current before they draw an autopilot cue. `HEADBUG` and `ALTSEL`, which
the panel also sets, are in the tables above.

## Engine

Gauges take any key through `dbkey`; the stock screens bind these through
gauge slots (`ARC1`, `BAR15`; see
[Customizing Beyond the Configurator](Customizing-Beyond-the-Configurator#gauge-slots-gauges)):

| Key | Meaning |
|---|---|
| `TACH1` | Engine RPM |
| `MAP1` | Manifold pressure |
| `OILP1` / `OILT1` | Oil pressure / temperature |
| `H2OT1` | Coolant temperature |
| `EGT11` to `EGT14` | Exhaust gas temperature per cylinder; `EGTMAX1` is the hottest |
| `CHT11` to `CHT14` | Cylinder head temperature per cylinder; `CHTMAX1` is the hottest |
| `FUELP1` / `FUELF1` | Fuel pressure / flow |
| `FUELQT`, `FUELQ1` to `FUELQ3` | Fuel quantity, total and per tank |
| `VOLT` / `CURRNT` | Bus voltage / current |
| `THR1` | Throttle |

Each key's range and limits are its aux values (`Min`, `Max`, `lowWarn`,
`lowAlarm`, `highWarn`, `highAlarm`); see
[Engine Monitoring](Engine-Monitoring#reading-a-gauge). The EGT buttons write
`EGTBTN1` to `EGTBTN4`.

## Buttons, controls and system

| Key | Meaning | Written by |
|---|---|---|
| `TSBTN{id}<n>` | Touchscreen buttons, one set per display (`TSBTN112` on display 1) | buttons |
| `ENC3`, `ENC4`, `BTN3` | The knob's turn, outer ring and push, as the stock `hmi/encoder_input.yaml` names them | the knob hardware |
| `ENC1` | The menu's encoder | the knob hardware |
| `HIDEBUTTON` | Hides the stock screens' buttons | pyEFIS (button timeout), the **Show Menu** button |
| `SYSMENU` | Opens the [system menu](The-Panel-at-a-Glance#the-system-menu) when it changes from `false` to `true`. A momentary command, like a button: write `true` on the press and `false` on the release. A key held `true` does not reopen the menu once it is closed, and a press while the menu is open does nothing. pyEFIS only reads it. Without `SYSMENU` in the database this route is off, with a warning in the log; the corner swipe still works | a control head or knob binding |
| `DIM` | Display brightness step | the dimmer buttons |
| `TRIMP`, `TRIMR`, `TRIMY` | Trim position | the trim buttons |
| `MAPRANGE`, `MAPORIENT`, `MAPTERRAIN`, `MAPNDMODE` | Map range, orientation, terrain layer and ND mode, when a panel binds them | map buttons |
| `MAVSTATE`, `MAVMODE`, `MAVMSG`, `MAVADJ`, `MAVWPVALID` | Autopilot state, mode, message, adjustment, waypoint valid | |
| `MAVREQADJ`, `MAVREQTRIM`, `MAVREQGUIDED`, `MAVREQCRUISE` | Autopilot requests | autopilot buttons |
| `COM*{radio_id}` | Radio frequencies and status for the MGL radio screens (`COMACTFREQ1`) | radio controls |
| `PYEFIS_VERSION` | pyEFIS's version | pyEFIS |
| `GATEWAY_VERSION`, `ACID`, `TIMEZ`, `TIMEL` | Gateway version, aircraft ID, UTC and local time, shown on the stock screens | |
| `DEMOLIVE` | The gateway's demo source is running. pyEFIS shows the DEMO marking while it is true and current | the demo source |
| `DEMOPAGE` | The page the demo script wants up, `SCREEN` or `SCREEN/TAB`. Followed only in kiosk mode | the demo source |
| `DEMOLOOP` | Changes each time the demo route starts over. In kiosk mode it triggers the visitor reset ([Demo kiosk](Customizing-Beyond-the-Configurator#demo-kiosk)) | the demo source |

## Quality flags

Every key carries `old`, `bad`, `fail` and `annunciate` flags beside its value.
Instruments show them as each page describes. Button conditions can test them
as `KEY.old`, `KEY.bad`, `KEY.fail` and `KEY.annunciate`, and read aux values
as `KEY.aux.<name>`; see
[Text & Interactive](Widgets-Text-and-Interactive#conditions).
