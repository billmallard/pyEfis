# Flight plan widget

Status: ACTIVE (FP5a, 2026-09-08) — touch. The `flight_plan` instrument's FPL
and Entry pages, keypad, and touch input path are live. Direct To / Catalog /
WPT Info pages and the physical-keyboard path are FP5b; the encoder path is
FP5c — neither is wired yet. Full plan: `makerplane/briefs/flight_plan_plan.md`
section 3.4-3.5; tracking epic pyEfis#181; the data layer is pyEfis#183
(AER-804), this item pyEfis#185 (AER-805).

## Data layer (`src/pyefis/flightplan/`)

Qt-free (no `PyQt6` import anywhere in the package — the instrument (FP5a)
and the map layer (FP6) wrap these plain-Python classes in Qt signals
themselves). Every DB-backed object is construct-never-raises with
`.available`/`.ready` reporting the actual state.

- **`geo.py`** (FP3, extended FP4) — spherical-earth bearing, distance,
  cross-track and along-track distance (`R = 3440.065` nm). Matches the
  formulas fix-gateway's `flightplan` engine (FP2) uses, asserted against the
  same reference-fixture table in both repos so the two implementations
  cannot drift apart.
- **`waypoints.py`** (FP3) — `WaypointIndex`: in-memory identifier index over
  the on-device `airports.sqlite`/`navaids.sqlite` packs, FastFind (`prefix`),
  `nearest`, plus `UserWaypointStore` and `RecentList`.
- **`model.py`** (FP4) — `Waypoint` and `FlightPlan`, the editor's working
  copy of a route: `insert_before`/`insert_after`/`remove` (mutate in place —
  the editor commits every edit immediately, per section 3.4), `invert()`
  (returns a new plan with roles cleared — an approach does not survive
  reversal), `set_role()` (at most one FAF and one MAP, the MAP must follow
  the FAF), `approach()`, `leg(i)`/`cumulative(i)`/`total_nm` (the FPL page's
  DTK/DIS/CUM columns), and `to_json()`/`from_json()` for the `"mp-route/1"`
  schema (Appendix B of the brief), preserving any field neither this version
  nor the schema currently knows about.
- **`catalog.py`** (FP4) — `Catalog(dir)` over
  `<userdir>/routes/<slug>.json` (atomic tmp-file + `os.replace` writes):
  `list`/`load`/`save`/`delete`/`copy`/`invert`. Slugs beginning `managed_`
  are reserved for configurator-delivered routes (FP9) and are read-only on
  the device. `invert()` returns the inverted plan without persisting it —
  "the stored plan is unchanged" (GNX guide 3-36); `copy()` is the catalog
  write that duplicates a stored route under a new name.
- **`fixbridge.py`** (FP4) — `FixBridge(fix_module)` wraps `pyavtools.fix`:
  `publish(plan)` writes the Appendix A route block (every slot, blanking
  whatever a shorter previous plan left behind, then `FPLCOUNT`/`FPLNAME`,
  then `FPLSEQ` last), `stage_direct_to(wp)`, `command(verb, arg, on_ack)`
  (writes `FPLCMD`, delivers the `FPLCMDACK`/`FPLMSG` answer to a plain
  callback), and `read_route()`/`read_engine()` plus `add_listener()` for the
  bus-driven read-back (fires on `FPLSEQ` or any engine-output change).
  `available` is False — every method a no-op — if the gateway does not
  define the FP1 keys yet.

## FIX keys

See the *Flight plan* section of
[FIX-Database-Keys](wiki/FIX-Database-Keys.md) for the key table; the
authoritative registry (types, ranges, CAN-FIX IDs) lives in fix-gateway.

## The `flight_plan` instrument (FP5a)

`type: flight_plan`, category `navigation`. An app-like instrument (the
`checklist` precedent, [checklist_widget.md](checklist_widget.md)): a working
copy of a `flightplan.model.FlightPlan` that commits through
`flightplan.fixbridge.FixBridge.publish` after every edit, then re-reads the
bus (`FixBridge.read_route()`/`read_engine()`) so a second display agrees.
When `FixBridge.available` is False (the gateway does not define the FP1
keys), the instrument annunciates `FPL: GATEWAY KEYS MISSING` and the pages
render read-only — it never raises.

### Pages

- **FPL** (default) — header: route name, `FPLREMDIS`/`FPLREMETE`, a state
  badge (LEG/DIRECT/SUSP from `FPLSTATE`), approach state
  (APR ARM/LNAV/MISSED from `FPLAPR`) and `LOI` (`FPLINTEG` false). List: type
  icon, ident (+ role abbreviation IAF/FAF/MAP/MAHP when set), the `columns`
  option's data columns (DTK/DIS/CUM computed from `flightplan.geo`; ETE from
  `WPETE` on the active row only; ETA not yet computed). The TO row
  (`FPLACTLEG`) is `active_color`, earlier rows `past_color`, later rows
  `future_color`. Tapping a row opens a menu: Insert Before, Insert After,
  Activate Leg (`ACT k`), Direct To (stages + `DTO k`), WPT Info (ident/lat/lon
  stub), Set Role (None/IAF/FAF/MAP/MAHP — refused with a message on a second
  FAF/MAP or a MAP before the FAF), Remove. Footer: Add Waypoint (Entry page,
  append), Direct To (Entry page in direct-to mode until FP5b's DTO page),
  Catalog (stub — FP5b), Menu (Invert, Store, Clear, Suspend/Resume, CDI
  Scale 0.3/1.0/2.0/AUTO, Delete — Clear and Delete both confirm and both
  reset the working plan; a distinct "Delete" semantic can be added if the
  guide's usage turns out to need one).
- **Entry** (Add/Insert/Direct To) — an ident field with FastFind: typed
  characters white, the predicted suffix (nearest match by distance from a
  mode-dependent reference point — the aircraft when appending to an empty
  plan or direct-to, the last waypoint when appending, the midpoint of the
  neighbours when inserting) cyan; "NO MATCHES"/"DUPLICATE FOUND"
  annunciations; a top-5 suggestion strip; tabs Recent/Nearest/FPL/User with a
  type filter (All/Apt/VOR/NDB/Fix/User); an on-screen keypad (A-Z, 0-9,
  Backspace, Clear, Enter — the `keypad` option, default true).

### HMI verbs

Registered in `hmi/actionclass.py` and `editor/schema.py` `_ACTIONS`. The
argument is `"<payload> [group]"`: an optional trailing word names the target
instrument's `hmi_group` (blank = every `flight_plan` instrument on the
screen, the `checklist` broadcast precedent).

| Verb | Payload |
|------|---------|
| `flightplan page` | `fpl` returns to the FPL page (closing any open menu/entry); `dto`/`catalog` are reserved for FP5b |
| `flightplan direct to` | blank opens the Entry page in direct-to mode; an ident stages and activates direct-to that waypoint immediately |

### Options (`InstrumentSpec` Props)

| Option | Default | Meaning |
|--------|---------|---------|
| `flightplan_dir` | `""` | directory for stored routes/user waypoints/recent list; blank disables catalog Store and the Recent/User tabs |
| `nasr_db_path` | `""` | `airports.sqlite` for FastFind/nearest (same name as `moving_map`'s) |
| `navaid_db_path` | `""` | `navaids.sqlite` for FastFind/nearest (same name as `moving_map`'s) |
| `columns` | `"DTK,DIS,CUM"` | comma-separated FPL page columns; choices DTK, DIS, CUM, ETE, ETA |
| `keypad` | `true` | show the on-screen keypad on the Entry page |
| `keyboard` | `false` | let a physical keyboard drive the Entry page; not yet implemented (FP5b) |
| `default_page` | `"fpl"` | page shown when the instrument first paints (`fpl`\|`entry`) |
| `hmi_group` | `""` | HMI verb targeting (see above) |
| `active_color` | `#ff00ff` | active (TO) leg row colour |
| `future_color` | `#ffffff` | upcoming leg row colour |
| `past_color` | `#808080` | already-flown leg row colour |

### Stock screen

`config/screens/flightplan.yaml` (`SCREEN_FLIGHTPLAN`): `moving_map` on the
left, `flight_plan` on the right, at the shipped 110x200 grid. A corner button
(`buttons/screen-flightplan-pfd.yaml`) on both PFD and FLIGHTPLAN toggles
between them (the `screen-map-pfd.yaml` `SCREEN`-toggle pattern), so the bench
boots into something testable.

### Configurator twin

The widget is app-like; per the brief, a static palette SVG twin (the
`checklist` precedent — no dedicated `build*` render in `editor.html`) plus
curated schema metadata is acceptable. `tools/build_editor_assets.py` picks
`flight_plan` up automatically once registered; the R2 upload and any
configurator-side twin work live in `makerplane-data` and are out of this PR's
repo boundary (see the PR description).

## Coming in FP5b/c

FP5b: Direct To / Catalog / WPT Info pages, the physical-keyboard input path.
FP5c: the encoder path (`enc_selectable` etc. via `encoder_order`).
