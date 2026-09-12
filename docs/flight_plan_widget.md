# Flight plan widget

Status: ACTIVE (FP5b, 2026-09-12) — touch + physical keyboard. All five
pages (FPL, Entry, Direct To, Catalog, WPT Info) and the physical-keyboard
input path are live. The encoder path is FP5c — not wired yet. Full plan:
`makerplane/briefs/flight_plan_plan.md` section 3.4-3.5; tracking epic
pyEfis#181; the data layer is pyEfis#183 (AER-804), FP5a is pyEfis#185
(AER-805), this item is pyEfis#187 (AER-807).

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

## The `flight_plan` instrument (FP5a/b)

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
  Activate Leg (`ACT k`), Direct To (stages + `DTO k`), WPT Info (full
  detail, see below), Set Role (None/IAF/FAF/MAP/MAHP — refused with a
  message on a second FAF/MAP or a MAP before the FAF), Remove. Footer: Add
  Waypoint (Entry page, append), Direct To (the DTO page), Catalog (the
  Catalog page), Menu (Invert, Store, Clear, Suspend/Resume, CDI Scale
  0.3/1.0/2.0/AUTO, Delete — Clear and Delete both confirm and both reset the
  working plan; a distinct "Delete" semantic can be added if the guide's
  usage turns out to need one).
- **Entry** (Add/Insert) — an ident field with FastFind: typed characters
  white, the predicted suffix (nearest match by distance from a mode-dependent
  reference point — the aircraft when appending to an empty plan, the last
  waypoint when appending, the midpoint of the neighbours when inserting)
  cyan; "NO MATCHES"/"DUPLICATE FOUND" annunciations; a top-5 suggestion
  strip; tabs Recent/Nearest/FPL/User with a type filter
  (All/Apt/VOR/NDB/Fix/User) — the User tab has a "+ CREATE USER WAYPOINT"
  row (below) above its list; an on-screen keypad (A-Z, 0-9, Backspace,
  Clear, Enter — the `keypad` option, default true).
- **Direct To (DTO)** (FP5b, brief 3.5 item 3) — tabs **Waypoint** (the same
  ident field/suggestion-strip/keypad as Entry, bound in direct-to mode),
  **FPL** (the active plan's waypoints), **NRST APT** (`WaypointIndex.nearest`
  filtered to airports — nearest first within 200 nm, up to 25, with bearing,
  distance and longest runway). Tapping a row in FPL/NRST APT selects it as
  the pending target (highlighted cyan); typing an ident on the Waypoint tab
  and pressing Enter activates immediately. The footer button reads
  **Activate** (stages `DTO*` then issues `DTO <k>` for an FPL-tab target,
  plain `DTO` otherwise) or **Remove** (issues `DTOX`) whenever a direct-to is
  already active (`FPLSTATE` = DIRECT) — this takes priority over whatever
  tab/target is showing. Either action returns to the FPL page.
- **Catalog** (FP5b, brief 3.5 item 4) — `Catalog.list()`, nearest-modified
  first, each row showing name, distance to the route's first waypoint from
  present position (cached per slug/mtime), waypoint count and comment; a
  lock glyph marks `managed_` (configurator-owned) routes. Tapping a row opens
  Activate / Invert & Activate / Edit / Copy / Delete (Edit and Delete are
  omitted for `managed_` rows — refused per `catalog.py`); Activate and Invert
  & Activate confirm first when the working plan has unsaved edits
  (`_plan_dirty` and non-empty). Edit loads the stored route into the working
  copy **without** publishing it to the bus — Store (FPL page Menu) writes it
  back; nothing else touches the live route until the next edit commits.
  Copy prompts for a new name via the generic modal keypad and writes a new
  slug, leaving the original untouched — including for `managed_` sources,
  since only the write side is refused. Footer: New (clears the working plan,
  same unsaved-edit confirm) and Delete All (confirms once, skips and reports
  any `managed_` entries).
- **WPT Info** (FP5b, brief 3.5 item 5) — resolves the tapped waypoint through
  `WaypointIndex.lookup` for the richer record (elevation, frequency) when one
  exists; shows ident/type, name, lat/lon as DD MM.MM, elevation/frequency
  where known, and bearing/distance from present position, refreshed at 1 Hz
  by a `QTimer` while the page is open. User waypoints (`type == "user"`) get
  Edit (comment, lat, lon via the generic modal — ident rename is not
  supported, `UserWaypointStore.edit` has no id parameter) and Delete, refused
  with the guide's message while the ident is in the active plan
  (`WaypointInUseError`).

### The generic modal (Catalog Copy, user waypoints)

A small reusable keypad overlay (`_modal_open`/`_modal_key`/`_modal_enter`/
`_modal_do_cancel`) drives every free-text or lat/lon prompt that isn't the
Entry/DTO ident field: Catalog Copy's new-name prompt, and the user-waypoint
create/edit wizard (ident -> comment -> lat -> lon, chained via each step's
`on_enter` callback). Numeric mode swaps the A-Z keypad rows for digits,
`.`/`-` and N/S/E/W; lat/lon parsing/formatting is decimal degrees with a
hemisphere suffix (e.g. `34.4262N`), not the WPT Info display's DD MM.MM —
entry and display are deliberately different representations of the same
value.

### Physical keyboard (FP5b)

While the `keyboard` option is true and an ident-entry surface is open (the
Entry page, the DTO page's Waypoint tab, or the generic modal), the widget
takes Qt focus (`setFocusPolicy(StrongFocus)` always; `setFocus()`/
`clearFocus()` each paint, tracked by `_keyboard_active()`) and its
`keyPressEvent` consumes A-Z/0-9 (uppercased), Backspace, Enter/Return,
Escape (cancel), Up/Down (moves a selection cursor over the suggestion strip
or duplicate chooser; Enter then picks it), Tab (cycles the current page's
sub-tabs), and `.`/`-`. Every other key — and every key while no entry
surface is open — is left un-accepted (`event.ignore()` +
`super().keyPressEvent(event)`) so Qt's normal propagation carries it to
`gui.py`'s `keyPress` signal and `hmi/keys.py` bindings exactly as before this
instrument existed. **A bound HMI key that collides with A-Z while an entry
surface is open is shadowed by the field** — e.g. a keybinding on plain `D`
will not fire while the Entry/DTO ident field has focus; rebind such keys
with a modifier, or accept the shadowing while that page is open.

### HMI verbs

Registered in `hmi/actionclass.py` and `editor/schema.py` `_ACTIONS`. The
argument is `"<payload> [group]"`: an optional trailing word names the target
instrument's `hmi_group` (blank = every `flight_plan` instrument on the
screen, the `checklist` broadcast precedent).

| Verb | Payload |
|------|---------|
| `flightplan page` | `fpl` returns to the FPL page (closing any open menu/entry); `dto`/`catalog` open those pages |
| `flightplan direct to` | blank opens the DTO page; an ident stages and activates direct-to that waypoint immediately (the guide's knob shortcut) |

### Options (`InstrumentSpec` Props)

| Option | Default | Meaning |
|--------|---------|---------|
| `flightplan_dir` | `""` | directory for stored routes/user waypoints/recent list; blank disables catalog Store and the Recent/User tabs |
| `nasr_db_path` | `""` | `airports.sqlite` for FastFind/nearest (same name as `moving_map`'s) |
| `navaid_db_path` | `""` | `navaids.sqlite` for FastFind/nearest (same name as `moving_map`'s) |
| `columns` | `"DTK,DIS,CUM"` | comma-separated FPL page columns; choices DTK, DIS, CUM, ETE, ETA |
| `keypad` | `true` | show the on-screen keypad on the Entry/DTO Waypoint pages and the generic modal |
| `keyboard` | `false` | let a physical keyboard drive an open ident-entry surface (see above) |
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

## Coming in FP5c

The encoder path (`enc_selectable` etc. via `encoder_order`): inner turn =
character or list scroll, push = enter, long push = back.
