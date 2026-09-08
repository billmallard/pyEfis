# FIX Database Keys

pyEFIS draws **FIX keys** — named values in the in-memory FIX database fed by
fix-gateway. This page is a glossary of the keys the shipped widgets consume.
See [Concepts §1](Concepts#1-the-fix-database-the-data-bus) for how keys,
quality flags, and aux values work.

> **Canonical source:** the master registry of keys, their types, and their
> CAN-FIX parameter IDs lives in **fix-gateway / CAN-FIX**, not in pyEFIS.
> pyEFIS only *reads* keys. Keys, ranges, and units below reflect how the
> shipped pyEFIS configs and the test mock database define them; your
> fix-gateway may add more.

## Air data

| Key | Units | Meaning | Read by |
|-----|-------|---------|---------|
| `IAS` | knots | Indicated airspeed (carries V-speed aux values) | airspeed widgets |
| `TAS` | knots | True airspeed | `airspeed_box`, `airspeed_tape` (TAS box), AI |
| `GS` | knots | Ground speed | `airspeed_box` |
| `ALT` | ft | Indicated/baro altitude | altimeter widgets |
| `VS` | ft/min | Vertical speed | `vsi_*`, `altimeter_trend_tape` |
| `BARO` | inHg | Altimeter setting (Kollsman) | altimeter, baro buttons |
| `OAT` / `CAT` | °C | Outside / calibrated air temp | EMS gauges |

**`IAS` aux values** (V-speeds, drive the airspeed-tape color bands):
`Vs`, `Vs0`, `Vno`, `Vne`, `Vfe`, `Va`, `Vx`, `Vy`, `Vmc`, `V1`, `V2`.

## Attitude & inertial

| Key | Units | Meaning | Read by |
|-----|-------|---------|---------|
| `PITCH` | deg | Pitch angle | AI, `virtual_vfr` |
| `ROLL` | deg | Roll/bank angle | AI, `virtual_vfr` |
| `ALAT` | g | Lateral acceleration (slip/skid ball) | AI, `turn_coordinator` |
| `ROT` | deg/s | Rate of turn | `turn_coordinator` |

## Navigation & position

| Key | Units | Meaning | Read by |
|-----|-------|---------|---------|
| `HEAD` | deg | Magnetic heading | `heading_display`, `heading_tape`, HSI |
| `HEADBUG` | deg | Selected heading bug | HSI heading bug, `value_text` |
| `TRACK` | deg | GPS ground track | AI flight-path marker |
| `COURSE` | deg | Selected course (of the selected nav source) | HSI, `virtual_vfr` heading source |
| `CDI` | −1..1 | Course deviation (of the selected nav source) | HSI |
| `GSI` | −1..1 | Glideslope deviation (of the selected nav source) | HSI |
| `NAVSRC` | — | Selected nav source: `0`=GPS, `1`=NAV1, `2`=NAV2 | source-select button (writes it); HSI reads `COURSE`/`CDI`/`GSI` |
| `LAT` / `LONG` | deg | Position | `virtual_vfr` / SVS |
| `HWIND` | knots | Headwind component (− = tailwind) | `wind_display` |
| `XWIND` | knots | Crosswind component (+ = from right) | `wind_display` |

> **Nav-source selection.** `COURSE` / `CDI` / `GSI` are *canonical* keys that
> always carry whichever source the pilot has selected with `NAVSRC`. The
> per-source values (GPS vs NAV1 vs NAV2 course/deviation) live in **fix-gateway**
> (keys like `GPSCRS`, `NAV1CDI`, …); its `compute` plugin's `select` function
> routes the chosen one into `COURSE`/`CDI`/`GSI`. pyEFIS only reads the canonical
> keys — bind the HSI to those, and a `value_text` to `NAVSRC` (or a button that
> cycles it) for the source annunciation. A button using
> [`change value wrap`](Widgets-Text-and-Interactive#actions) on `NAVSRC` cycles
> the source.

## Flight plan

The flight-plan **engine lives in fix-gateway** (`flightplan` plugin, FP2);
pyEFIS's `src/pyefis/flightplan/fixbridge.py` (FP4) publishes the route to
these keys and reads the engine's guidance back. See
`makerplane/briefs/flight_plan_plan.md` section 3.2 Appendix A and
billmallard/pyEfis#181 for the full contract; this table covers what the
bridge touches.

| Key | Units | Meaning | Written by |
|-----|-------|---------|------------|
| `FPLfID` / `FPLfLAT` / `FPLfLON` (`f`=1..50) | str/deg/deg | Route slot ident + position | editor |
| `FPLfTYPE` / `FPLfROLE` | int | Slot type (0 unk..6 map) / approach role (0 none..4 mahp) | editor |
| `FPLCOUNT` | — | Slots in use (0..50) | editor |
| `FPLNAME` | — | Route name | editor |
| `FPLSEQ` | — | Commit counter — consumers act only on this changing, written last | editor |
| `DTOID` / `DTOLAT` / `DTOLON` / `DTOTYPE` | — | Direct-to staging | editor |
| `FPLCMD` | — | `"<seq> VERB [arg]"` (`ACT`/`DTO`/`DTOX`/`SUSP`/`RESUME`/`SCALE`) | editor |
| `FPLCMDACK` / `FPLMSG` | — | Ack (negative = rejected) / last message | engine |
| `FPLSTATE` / `FPLACTLEG` | — | 0 NONE/1 LEG/2 DIRECT/3 SUSP / slot of the TO waypoint | engine |
| `FPLPHASE` / `FPLAPR` / `FPLINTEG` | — | Flight-phase annunciation / approach state / integrity gate | engine |
| `CDISCALE` | nm | Full-scale CDI deflection (2.0 ENR, 1.0 TERM, ramps to 0.3 LNAV) | engine |
| `FPLCRS` / `FPLXTK` / `FPLCDI` / `FPLTF` | deg/nm/−1..1/— | Desired track / cross-track / deviation / TO-FROM | engine |
| `WPDIS` / `WPETE` | nm / s | Distance / time to the TO waypoint | engine |
| `WPFROM` / `WPNEXT` | — | FROM / NEXT idents | engine |
| `FPLREMDIS` / `FPLREMETE` | nm / s | Remaining distance / time to the end of the plan | engine |
| `GPSSRC` | — | 0 = internal plan, 1 = external navigator | pilot |

`WPLAT`/`WPLON`/`WPNAME` (existing keys, see Navigation & position above) are
written by the engine while a plan is active. `GPSSRC` selects `{FPLCRS,
EXTCRS} -> GPSCRS` etc. into the canonical `GPSCRS`/`GPSCDI`/`GPSTF`, which
`NAVSRC` then carries on into `COURSE`/`CDI`/`TOFROM` as usual — the HSI is
unmodified by this epic.

## Engine / EMS (representative)

These are bound to gauges through [Preferences](Preferences-and-Styling)
(`gauges:` slots like `ARC1`, `BAR15`) and the EMS includes. Exact names/IDs
come from fix-gateway/CAN-FIX; the shipped example configs use:

| Key | Meaning |
|-----|---------|
| `TACH1` | Engine RPM |
| `OILP1` / `OILT1` | Oil pressure / temperature |
| `EGT11`–`EGT14` | Exhaust gas temp per cylinder; `EGTMAX1` = hottest |
| `CHT11`–`CHT14` | Cylinder head temp per cylinder; `CHTMAX1` = hottest |
| `FUELP1` / `FUELF1` | Fuel pressure / flow |
| `FUELQT` / `FUELQ1`–`FUELQ3` | Fuel quantity (total / tanks) |
| `VOLT` / `CURRNT` | Bus voltage / current |
| `HTOT1` | (engine health/aux, per config) |

Each engine key supplies its green/yellow/red bands via its **aux values**
(`Min`/`Max`/`lowWarn`/`lowAlarm`/`highWarn`/`highAlarm`) — see
[Concepts §2](Concepts#2-the-color-state-model-gauges).

## System / UI

| Key | Type | Meaning |
|-----|------|---------|
| `TSBTN<node><n>` | bool | Touchscreen button (node-scoped, e.g. `TSBTN112`) |
| `BTN<n>` / `ENC<n>` | bool / int | Physical button / rotary encoder inputs |
| `HIDEBUTTON` | bool | Hide/show on-screen buttons (menu timeout) |
| `MAVREQADJ`, `MAVADJ`, `MAVSTATE`, `MAVMODE` | mixed | MAVLink/autopilot request & state keys (trim/AP) |

## A note on quality flags

Every key carries `old` / `bad` / `fail` / `annunciate` flags independent of its
value (see [Concepts §3](Concepts#3-data-quality--states)). Buttons can read any
of these in conditions as `KEY.old`, `KEY.bad`, `KEY.fail`, `KEY.annunciate`,
and aux values as `KEY.aux.<name>` — see
[Widgets-Text-and-Interactive](Widgets-Text-and-Interactive).
