# Flight plan widget

Status: DATA LAYER ONLY (FP4, 2026-09-08). This document starts with the
`src/pyefis/flightplan/` data layer FP4 delivers; the `flight_plan` instrument
itself (pages, keypad, HMI verbs, stock screen, options table) is FP5a and
completes this document. Full plan: `makerplane/briefs/flight_plan_plan.md`
section 3.4-3.5; tracking epic pyEfis#181; this item pyEfis#183 (AER-804).

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

## Coming in FP5a/b/c

The `flight_plan` instrument (`type: flight_plan`, category `navigation`):
FPL / Entry / DTO / Catalog / WPT Info pages, on-screen keypad, FastFind
autofill, row menus, HMI verbs (`flightplan:page`, `flightplan:direct_to`),
`InstrumentSpec` options and configurator twin, a stock
`config/screens/flightplan.yaml`, and the touch / physical-keyboard / encoder
input paths. This section will be filled in as those items land.
