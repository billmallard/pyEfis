# Flight plan widget

Status: ACTIVE (FP5c, 2026-10-05) — touch, physical keyboard and encoder.
All five pages (FPL, Entry, Direct To, Catalog, WPT Info), the
physical-keyboard input path and the encoder path are live. Full plan:
`makerplane/briefs/flight_plan_plan.md` section 3.4-3.5; tracking epic
pyEfis#181; the data layer is pyEfis#183 (AER-804), FP5a is pyEfis#185
(AER-805), FP5b is pyEfis#187 (AER-807), FP5c is pyEfis#188 (AER-810).

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
- **`airways.py`** (PA2, procedures epic) — `AirwayGraph`: lookup + expansion
  over the `procedures` pack's `airways`/`airway_legs` tables (`expand()`
  emits ordinary `type="fix"` waypoints; no leg model needed for an airway
  segment).
- **`procedures.py`** (PA5, procedures epic) — `ProcedureIndex`: lookup over
  the same pack's `procedures`/`transitions`/`legs` tables (departures,
  arrivals, approaches) by airport/kind/runway/transition. Query-only — it
  does not assemble a transition into a flyable leg sequence (PA7/PA9, needs
  the PA3 leg model) and does not enforce the whole-procedure-rejection
  guardrail (the engine, PA4). Wired into this widget via the
  `procedures_db_path` option and `_ensure_procedure_index()`, lazily, the
  same pattern as `nasr_db_path`/`navaid_db_path` -> `_ensure_waypoint_index`
  — PA7's PROC page is the first real consumer.
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
  **Load Airway** (PA6, AER-1605 — see below), Activate Leg (`ACT k`),
  Direct To (stages + `DTO k`), WPT Info (full detail, see below), Set Role
  (None/IAF/FAF/MAP/MAHP — refused with a message on a second FAF/MAP or a
  MAP before the FAF), Remove. Footer: Add Waypoint (Entry page, append),
  Direct To (the DTO page), Catalog (the Catalog page), Menu (Invert, Store,
  Clear, Suspend/Resume, CDI Scale 0.3/1.0/2.0/AUTO, Delete — Clear and
  Delete both confirm and both reset the working plan; a distinct "Delete"
  semantic can be added if the guide's usage turns out to need one).
- **Load Airway** (PA6, AER-1605, brief section 3.5) — offers every airway
  through the tapped fix (`AirwayGraph.airways_through_fix`, PA2), then an
  exit fix from that airway's ordered points, each annotated with its
  published MEA/ceiling when the pack carries one; `AirwayGraph.expand()`
  inserts the intermediate fixes (never the entry fix again) right after the
  tapped row, tagged `extra["airway"]`. A run of consecutively tagged fixes
  paints as one collapsed row ("V27 → RZS") *permanently* — there is no
  on-page expansion (PA16, AER-2088: Bill found tap-to-expand "confusing" and
  "clutter" on his first on-glass look at PA6; per-fix access lives on the
  map instead, which draws every fix regardless — see
  `instruments/map/layers/flight_plan.py`, unaffected by this since it reads
  the FP1 bus, not this page's display grouping). Tapping the collapsed row
  opens its row menu, anchored on the group's last member (its exit fix) the
  same way the row's own DTK/DIS/CUM columns are; **Remove** from that menu
  takes the whole tagged span, not just the anchor fix (`_group_containing` in
  `_row_menu_remove`). An `AirwayError` (unknown airway, a fix not on it, a
  one-way violation) or a route already too close to `MAX_WAYPOINTS` for the
  whole segment leaves the plan untouched and shows the reason — never a
  partial airway. The tag is display-only: the FP1 bus
  (`fixbridge.RouteSlot`) carries id/lat/lon/type/role per slot, nothing that
  says "this fix came from an airway", so `_sync_plan_from_bridge` carries it
  forward across a commit's publish/read-back by matching id + lat/lon at the
  same slot — a safe no-op the moment anything else shifts that slot.
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

### Encoder (FP5c)

The instrument takes the screen encoder through the standard `enc_*`
protocol (`screens/screenbuilder_encoder.py`): give it an `encoder_order`
option on a screen that names `encoder` / `encoder_button` FIX keys. Turning
the knob moves the screen-level highlight onto it (an orange outline round
the whole instrument); a push takes control; it keeps control until a long
push backs out of the FPL page or the screen's `encoder_timeout` (default
10 s of no knob activity) expires.

**What the knob walks.** Inside the instrument the knob moves a focus box
(orange) over a ring built from the same per-frame tap targets touch uses —
everything tappable on the topmost layer, in paint order. So the ring on the
FPL page is the waypoint rows then the soft keys; on an open menu or confirm
box it is only that box (never the dimmed page behind it); and a control
added for touch later is reachable by knob with no extra code. The ring wraps.
Scrollable menus keep their ▲/▼ rows as ring entries — push one to page the
list.

| Where | Turn | Push | Long push (>= 600 ms) |
|-------|------|------|------------------------|
| FPL page, nothing focused (on entry) | focus the first row / last soft key | open Direct To with the active waypoint pre-selected and **Activate** focused, so a second push activates it (guide 3-45) | release the knob to the screen |
| FPL page, a row or soft key focused | next/previous element (the ring includes "nothing focused") | open the row menu / press the soft key | release the knob to the screen |
| Any menu, picker, confirm box, WPT Info | next/previous item | choose it | close it (one level) |
| Ident field (Entry page, DTO Waypoint tab) | scroll the character under the cursor through `A`-`Z`, `0`-`9`, space | a character is under the cursor: keep it and advance; blank under the cursor: accept the field, taking the FastFind prediction (cyan suffix); nothing typed yet: leave the field and walk the page (suggestions, tabs, rows, X) | cancel the page (as Escape) |
| Entry / DTO / Catalog page, field not being edited | next/previous element | choose it (push the field to edit it again) | leave the page |

Focus defaults when a surface opens: the FPL page starts with nothing
focused; the Entry page and the DTO Waypoint tab start editing the field;
the DTO page starts on **Activate** when it already has a target, else on the
first row; a confirm box starts on **No**; every other menu starts on its
first item. The on-screen keypad is left out of the ring while the field has
the knob — the knob replaces it. Turning onto space and pushing is the same
as pushing on a blank: the ident set has no spaces, so a space means "nothing
here".

**Long push.** `abstract.py` has no long-press convention to inherit, so the
threshold is the instrument's `enc_long_press_ms` (600 ms,
`ENC_LONG_PRESS_MS`). Long push is opt-in at the controller: an instrument
in control that defines `enc_long_clicked()` and a positive
`enc_long_press_ms` gets its pushes on *release* (`enc_clicked()`) or when
the hold reaches the threshold (`enc_long_clicked()`, from a timer, without
waiting for release). Every other instrument keeps the original act-on-press
behaviour.

**One knob, not two.** The guide's knob table (1-11..1-13) is a dual
concentric: outer = field/cursor, inner = character/list. The screen
encoder protocol carries one encoder and one button, so the cursor advance
is a push instead of an outer-ring turn. A dual-knob mapping would need a
second encoder key in the protocol and is not part of FP5c.

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

**Text size.** The common `font_percent` option (schema `common_options`, not
redeclared as a Prop — [instrument_spec.md](instrument_spec.md)) is honoured,
but for this widget it scales the built-in text sizes (`0.8` or `80` = 80%,
unset = 100%) rather than being a fraction of the widget's height: every font
here is already sized from its own header/row/footer/box. Independently, in a
pane taller than it is wide every font is also scaled by width/height
(`_FONT_FIT_ASPECT = 1.0`), because the text rects are width fractions and Qt
does not clip overflowing text — a ~657x1003 tab otherwise overlaps its
header and footer labels. Square and landscape panes are unaffected. Only
fonts scale; layout and tap targets never do. Evidence:
[images/fp_font_scale](images/fp_font_scale/README.md).

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

## Encoder catalogue (#97)

pyEfis#97 (exporting per-instrument encoder options and a capability
catalogue to the schema) has not landed. When it does, `flight_plan` gets its
catalogue row and an `encoder_order` Prop in whichever of the two PRs merges
second; until then `encoder_order` is honoured from screen YAML exactly as
for every other encoder instrument (`screenbuilder_options.apply_options`).
