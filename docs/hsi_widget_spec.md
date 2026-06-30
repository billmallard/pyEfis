# HSI Widget Specification

**Status:** Draft v0.2 (working specification)
**Widget type:** `horizontal_situation_indicator`
**Source:** [`src/pyefis/instruments/hsi/__init__.py`](../src/pyefis/instruments/hsi/__init__.py)
**Registry:** [`src/pyefis/screens/screenbuilder_factory.py`](../src/pyefis/screens/screenbuilder_factory.py) (`type="horizontal_situation_indicator"`)

This is the first of the per-instrument specifications (see issue: "Per-widget
specifications + documentation"). It is meant to be the **template** for the
others: each widget is a small application, and this document captures its
purpose, its data contract, its appearance options, its behaviors, and a phased
plan to bring it to parity with market-leading HSIs.

---

## 1. Purpose

A Horizontal Situation Indicator combines a **directional gyro / compass** with a
**course deviation indicator (CDI)** in one instrument: a rotating compass card
under a fixed aircraft symbol, a selected-course pointer, a lateral deviation
bar, a glideslope/glidepath scale, and a set of selectable markers (heading bug,
bearing pointers, ground-track diamond). It answers, at a glance: *which way am I
pointing, which way is my course, and how far off it am I.*

## 2. Design principles

1. **The widget is a display, not a controller.** It renders state published on
   the FIX bus and (with an OBS control) may *write* a single selected-course
   value, but it does not own navigation logic. Source selection, deviation
   scaling, and waypoint sequencing live upstream (fix-gateway / the navigator).
2. **One canonical key per concept, fed by a selector.** The HSI reads
   `COURSE` / `CDI` / `GSI`; fix-gateway's `compute` `select` routes the active
   source (`NAVSRC`) into those canonical keys. The widget never has to know
   which radio is active to draw the needle — but it *does* need a published
   *source descriptor* to color and annotate correctly (see §4).
3. **Layout-vs-FIX boundary (issue #64).** Appearance and feature toggles are
   **editor options** (written into the screen YAML). Live navigation quantities
   and their scaling are **FIX-database values** (published by fix-gateway). This
   spec labels every field as one or the other. V-speed-style "which is which"
   mistakes are the main thing this boundary prevents.
4. **Conventions, not clones (see §8).** The HSI follows long-established
   symbology conventions so a pilot reads it without retraining. Those
   conventions come from open standards and decades of practice, cited in §8 —
   not from any one vendor's copyrighted material.
5. **Two repos move together.** New behavior that needs new data is a
   **canfix-spec / fix-gateway** change first (the data contract), then a pyEfis
   widget change. Build the data before the pixels.

## 3. Current state (implemented)

**FIX keys read** (`dbkeys=["COURSE","CDI","GSI","HEAD"]` plus internal
subscriptions):

| Key | Role | Notes |
|---|---|---|
| `HEAD` | rotates the compass card | magnetic heading |
| `COURSE` | selected-course pointer (magenta) | canonical, fed by `select` from `NAVSRC` |
| `CDI` | lateral deviation bar | canonical; `cdi_enabled` |
| `GSI` | glideslope/glidepath needle | canonical; `gsi_enabled` |
| `HEADBUG` | selected-heading bug (cyan) | `heading_bug_enabled` |
| `TRACK` + `GS` | GPS ground-track diamond (magenta) | `track_indicator_enabled`, gated by `track_min_speed` |

**Editor options (category 1, today):** `cdi_enabled`, `gsi_enabled`,
`fg_color`, `bg_color`, `bg_opacity`, `needle_color`, `needle_width`,
`course_color`, `heading_bug_enabled`, `heading_bug_color`,
`track_indicator_enabled`, `track_color`, `track_min_speed`.

**Source-selection chain (fix-gateway, config-driven — already built):**
`NAVSRC` (`0=GPS, 1=NAV1, 2=NAV2`, `max=3` so a button cycles 0→1→2→0) →
`compute` `select` routes `{GPS,NAV1,NAV2}{CRS,CDI,GSI}` into `COURSE`/`CDI`/`GSI`
→ `compute` `remap` produces `XPHSISRC` for X-Plane HSI feedback. The on-screen
"control" is a **generic `button`** instrument configured to cycle `NAVSRC`;
there is no dedicated nav-source widget.

**Known code-clarity debt:** the `COURSE` value is handled by a method named
`setHeadingBug` (and stored as `_headingSelect`), while the actual heading bug
uses `setHdgBug`. Rename to `setCoursePointer` / `_courseSelect` during the first
implementation phase to remove the trap.

## 4. Data contract — existing and proposed

The HSI's competitiveness is mostly a **data** problem: the renderer is
straightforward once the values exist. Keys below marked **PROPOSED** do not yet
exist and must be added to the CAN-FiX schema (the master spreadsheet
`src/CAN-FIX.ods` in [canfix-spec](https://billmallard.github.io/canfix-spec/) —
*do not hand-edit the generated json/xml*) and published by fix-gateway before
the widget can use them. Map to existing CAN-FiX navigation parameters where one
already fits; only add where there is a genuine gap.

### 4.1 Existing (in fix-gateway `ahrs.yaml`)
`HEAD`, `HEADBUG`, `TRACK`, `TRACKM`, `GS`, `COURSE`, `CDI`, `GSI`, `NAVSRC`,
`GPSCRS/GPSCDI/GPSGSI`, `NAV1CRS/NAV1CDI/NAV1GSI`, `NAV2CRS/NAV2CDI/NAV2GSI`,
`XPHSISRC`.

### 4.2 Proposed additions

| Key | Type | Meaning | Drives |
|---|---|---|---|
| `NAVTYPE` **PROPOSED** | enum/int | active source *kind*: `0=GPS, 1=VOR, 2=LOC, 3=LOC-BC` (NAVSRC gives the slot; this gives whether the active radio is a VOR or a localizer) | course/CDI **colour** (magenta GPS / green VLOC); whether TO/FROM applies (VOR yes, LOC/GPS no) |
| `NAVPHASE` **PROPOSED** *(optional)* | enum/string | navigator phase-of-flight annunciation (`ENR/TERM/APR/...`) — **display-only text** | mode label (the widget never uses it to scale CDI) |
| `TOFROM` **PROPOSED** | enum/int | `0=OFF/flag, 1=TO, 2=FROM` | TO/FROM indicator |
| `OBSMODE` **PROPOSED** | bool | GPS OBS (suspend sequencing) active | "OBS" annunciation |
| `SUSP` **PROPOSED** | bool | waypoint sequencing suspended | "SUSP" annunciation |
| `BRG1` / `BRG2` **PROPOSED** | float (deg) | bearing to station for pointer 1 / 2 | bearing pointers |
| `BRG1SRC` / `BRG2SRC` **PROPOSED** | enum | source feeding each bearing pointer (GPS/NAV) | pointer symbol/label |
| `DME` / `DIS` **PROPOSED** | float (nm) | distance to active station/waypoint | data field |
| `DTK` **PROPOSED** | float (deg) | desired track | data field |
| `ETE` **PROPOSED** | float (s) | estimated time enroute to waypoint | data field |
| `WPID` **PROPOSED** | string | active waypoint identifier | data field |

> **Decision (CDI scaling).** `CDI`/`GSI` stay **strictly normalized** (−1..+1 =
> full-scale deflection / the standard dots). Full-scale is owned by the
> **navigation source**, per FAA needle-deflection standards — VOR ±10° (≈2° per
> dot), LOC ±2.5° (much more sensitive), GPS 2.0 nm enroute / 1.0 nm terminal /
> angular on approach (FAA-H-8083-15B; AIM; AC 20-138 / TSO-C146). The widget
> renders the dots it is given and **never computes scaling** — this also keeps
> existing consumers (the autopilot) unaffected. No `CDISCALE` key is added; the
> normalized convention already present in the widget is correct.

## 5. Appearance options (category 1 — editor)

### 5.1 Existing
See §3. Keep all.

### 5.2 Proposed

| Option | Kind | Purpose |
|---|---|---|
| `source_auto_color` | boolean | color course pointer + CDI by `NAVTYPE` (magenta GPS / green VOR-LOC) instead of the static `course_color`. Default **on**. |
| `vloc_color` | color | the "green" used when the source is VOR/LOC (default `#00ff00`). |
| `orientation` | enum | `north_up` (full 360 rose, today) / `heading_up` / `track_up` / `arc` (120° expanded HSI). |
| `bearing1_enabled` / `bearing2_enabled` | boolean | show bearing pointer 1 / 2. |
| `bearing_color` | color | bearing-pointer color (default cyan `#00ffff`). |
| `tofrom_enabled` | boolean | show the TO/FROM indicator. |
| `data_fields` | enum/multi | which corner data fields to show (CRS, HDG, DIS, DTK, GS, ETE, source). |
| `aircraft_symbol` | enum | reference-symbol style. |
| `rose_labels` | enum | cardinal letters vs numerals; tick density. |

The `visiblePointers` array (top/bottom/right/left tick visibility) already
exists internally — expose it if useful.

## 6. Behaviors and modes

Each item: what it does, the input(s), the convention.

1. **Compass card** — rotates so current `HEAD` is under the lubber line
   (north-up today; §5.2 adds heading-/track-up and arc).
2. **Course pointer** — arrow to `COURSE`. Convention: **single-line for source
   1, double-line for source 2**; colored magenta for GPS, green for VOR/LOC
   (gated by `source_auto_color` + `NAVTYPE`).
3. **CDI (lateral deviation)** — bar offset from the course pointer along the
   standard dotted scale, drawn from the **normalized** `CDI` value. Full-scale is
   defined by the **navigation source** (VOR ±10°, LOC ±2.5°, GPS 2.0/1.0 nm by
   phase — FAA-H-8083-15B), not by the widget: the display renders the dots it is
   given and never scales. Hidden/flagged when the signal is invalid (see 11). An
   optional `NAVPHASE` annunciation (ENR/TERM/APR) is display-only text from the
   navigator.
4. **TO/FROM** — for VOR sources; hidden for LOC and (typically) GPS.
5. **Glideslope / glidepath (VDI)** — vertical deviation scale + diamond from
   `GSI`; shown on ILS/LPV/approach.
6. **Heading bug** — cyan marker at `HEADBUG`.
7. **Ground-track diamond** — magenta diamond at `TRACK`, gated by `GS ≥
   track_min_speed`. (Implemented.)
8. **Bearing pointers 1 & 2** — cyan needles pointing to `BRG1`/`BRG2`;
   single-line (1) / double-line (2); **hidden when heading is invalid**; they
   never override and are visually separated from the deviation bar. Each has a
   selectable source label.
9. **OBS mode** — when an OBS control sets the course, `COURSE` becomes
   pilot-settable; with a GPS source, asserting `OBSMODE` suspends waypoint
   sequencing and holds the active-to waypoint; annunciate **"OBS"**. **"SUSP"**
   annunciated from `SUSP`.
10. **Data fields** — corner readouts: selected course (CRS), selected heading
    (HDG), distance (DIS/DME), desired track (DTK), ground speed (GS), ETE,
    active waypoint, and the **navigation-source annunciation** (e.g. "GPS",
    "VOR1", "LOC1") colored to match the pointer.
11. **Signal-driven visibility (failure handling)** — the display shows what it
    **receives**, not what is selected. A needle (CDI, GSI, bearing pointer)
    appears only when a valid signal for it is present; with no signal it **hides**
    — the digital equivalent of a mechanical needle parking in the bezel —
    regardless of which source is selected (e.g. selecting LOC with no localizer
    received shows no needle). Follow the widget convention: `fail` → remove /
    red flag; `old`/`bad` → grey. Never show stale or sourceless guidance.

## 7. Phased implementation plan

Ordered by impact-per-effort; each phase is shippable and testable on its own.

- **P0 — cleanup + foundation (pyEfis only).** Rename the `setHeadingBug`/
  `_headingSelect` course-pointer code; add the appearance scaffolding
  (`source_auto_color`, `vloc_color`) with `NAVTYPE` read defensively (absent →
  current static behavior). No new data required.
- **P1 — source annunciation + auto-coloring.** Add `NAVTYPE` to canfix-spec +
  fix-gateway (derive from `NAVSRC` + which NAV radio is a LOC). Widget: color
  course/CDI by source, single/double-line pointer, on-face source label. *This
  is the single biggest visual step toward parity — the data is almost all there.*
- **P2 — TO/FROM + CDI scale annunciation.** Add `TOFROM`, `CDISCALE`,
  `CDIMODE`; draw the TO/FROM arrow and the scale/mode label. `CDI` stays
  normalized.
- **P3 — data fields.** Add `DME/DIS`, `DTK`, `ETE`, `WPID`; render the
  configurable corner readouts (CRS/HDG/GS already available).
- **P4 — bearing pointers.** Add `BRG1/BRG2` (+ source + valid); render the two
  cyan needles with source labels and the heading-invalid hide rule.
- **P5 — OBS control + mode.** Add an OBS/CRS control (encoder or button writing
  `COURSE`; `OBSMODE`/`SUSP` flags) and the OBS/SUSP annunciations.
- **P6 — orientation modes.** Heading-up / track-up / arc (120°) expanded HSI.

Each phase: implement widget + factory `Prop`s, regenerate `schema.json` →
R2, update the `editor.html` twin to match (fidelity rule), add unit tests and a
visual test case.

## 8. Conventions and standards basis (and sourcing note)

The symbology in this spec is **industry convention**, grounded in open
references — not proprietary to any vendor:

- **FAA Instrument Flying Handbook, FAA-H-8083-15B** — HSI, CDI, RMI/bearing
  pointers, OBS, TO/FROM.
- **FAA AIM** (1-1, GPS/RNAV) — CDI full-scale by phase (2.0 nm enroute, 1.0 nm
  terminal, angular approach), mode behavior.
- **AC 20-138 / TSO-C146** (GPS/WAAS) — RNAV CDI scaling and flight-phase modes.
- **AC 25-11** (Electronic Flight Deck Displays) — color conventions (magenta for
  the active GPS course, green for VOR/LOC, cyan for selected/bearing markers)
  and symbology guidance.
- **[CAN-FiX specification](https://billmallard.github.io/canfix-spec/)** — the
  data contract these keys live in.

**Sourcing note (for next developers):** vendor pilot's guides (e.g. the Garmin
GI 275 guide kept in `docs/` for reference) were read only to *confirm* these
conventions and the expected pilot workflow. This document is written
independently and cites the open standards above; no vendor text, diagrams, or
trade dress are reproduced. Match the *conventions* (which are unprotected and a
safety benefit); never copy a competitor's *expression*. See the project README
for the broader open-source posture.

## 9. Test cases

Log a manual/visual test case (label `test-case`) for each, recording heading,
source, and expected appearance:

- Source switch GPS→NAV1→NAV2: pointer color/line-style and on-face label change.
- CDI valid/invalid: needle hides + flag on invalid.
- Track diamond above/below `track_min_speed`.
- Bearing pointers with heading invalid → hidden.
- OBS mode: course settable, "OBS"/"SUSP" annunciated, no auto-sequence.
- TO/FROM for a VOR; absent for LOC and GPS.
- Failure/stale: `fail` red, `old`/`bad` grey.

## 10. Resolved questions and remaining work

1. **Signal-driven visibility (resolved).** The display reflects the *received*
   signal, not the selection: needles hide when no valid signal is present,
   regardless of the source selected (§6.11). The active source's **type** (for
   the magenta/green colouring) is published *with* the signal by the producing
   source/plugin; for X-Plane, fix-gateway derives it. Remaining work: ensure the
   active source publishes `NAVTYPE` and per-needle validity.
2. **CDI normalization (resolved).** `CDI`/`GSI` stay strictly normalized; the
   navigation source owns full-scale per FAA standards (§4.2 decision,
   FAA-H-8083-15B). `CDISCALE` dropped — the existing normalized convention is
   correct.
3. **Map to existing CAN-FiX parameters (remaining).** Audit the existing CAN-FiX
   navigation parameters and map the proposed keys onto them before proposing any
   new parameter IDs — the working assumption is that most or all already exist.
   Any genuine addition goes through the careful `.ods` process.
4. **Control and interaction (scoped — see §11).** Both physical knob controllers
   and on-screen touch-select are needed; this is a panel-wide interaction model,
   not an HSI-only concern.

## 11. Control and interaction (OBS and beyond)

Setting values on the HSI (and other widgets) — selected course (OBS/CRS),
heading bug, nav source, baro — needs **two complementary input paths**. They are
not either/or; both are wanted:

**A. Physical knob / button controllers.** Hardware the pilot reaches for without
looking. In the test environment the **Octavi IFR-1**
(<https://www.octavi.net/ifr-1>) and **Knobster**
(<https://siminnovations.com/knobster/>) drive X-Plane today over USB HID. The
clean integration point is the **FIX bus**, giving three routes:
- *Sim path (works today):* controller → X-Plane → fix-gateway (reads datarefs) →
  pyEfis. Fine for bench testing.
- *Real-aircraft USB path:* a small **fix-gateway source plugin** reads the USB
  HID controller and writes FIX keys (`COURSE`, `HEADBUG`, `NAVSRC`, baro).
  Mirrors the existing plugin pattern; no sim required.
- *Native CAN-FiX path:* a purpose-built **CAN-FiX knob node** (Arduino +
  `can-fix-arduinolib`) publishes `COURSE`/`HEADBUG` straight onto the bus — the
  most "native" option and the one the protocol intends.

**B. On-screen touch-select + adjust.** Touch a value field (CRS, HDG, baro) to
make it the active edit target, then adjust it (encoder, on-screen +/−, or a
second knob), with a clear highlight and an edit timeout. pyEfis already has an
**encoder/HMI edit mechanism** (`AbstractGauge` encoder-edit state,
`hmi/menu.py`) — this is an *extension* of it with a touch-to-select layer, not a
new subsystem. Should be **web-UI toggleable** (enable/disable touch editing per
panel).

**C. Dedicated controller surface (optional).** A second Pi with a 5" touch
display as a control head. Because fix-gateway is **networked (TCP)**, a second
pyEfis instance can run a "controller screen" (buttons + encoder UI) that writes
FIX keys over the network — reusing the whole stack instead of building anew.

**Open-source prior art to evaluate** (survey — candidates, not yet vetted):
- **MobiFlight** — open-source framework binding hardware (encoders, buttons,
  displays) to flight-sim variables; primarily MSFS with X-Plane support. A
  reference for the hardware-binding model.
- **XCSoar / OpenVario** — open-source soaring computer + open touch hardware
  (7" Pi-class). Its **InfoBox** pattern (touch a field → adjust) is a proven
  open-source touch-select interaction worth studying directly.
- **TouchPi** — Raspberry Pi + touchscreen handheld project; evaluate as a
  reference design for the dedicated-controller hardware (C).
- **AvareX / Avare** — open-source touch EFB (Android); touch interaction model.
- **FlightGear Canvas** — open-source instrument-UI toolkit; interaction ideas.
- **`can-fix-arduinolib`** — already in the MakerPlane org; the basis for a native
  CAN-FiX knob node.
- *(Commercial benchmark, not OSS):* **Air Manager / Air Player** (Sim
  Innovations, makers of Knobster) — the de-facto touch-panel-plus-knob UX to
  match.

This control work is broader than the HSI — it is a **panel-wide interaction
model**. The HSI's OBS/CRS control is its first concrete consumer; spec the
interaction model once and the heading bug, baro, and nav-source controls reuse
it. Track it as its own issue.
