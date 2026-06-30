# HSI Widget Specification

**Status:** Draft v0.1 (working specification)
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
| `NAVTYPE` **PROPOSED** | enum/int | active source *kind*: `0=GPS, 1=VOR, 2=LOC, 3=LOC-BC` (NAVSRC gives the slot; this gives whether NAV1 is a VOR or a localizer) | course/CDI **color** (magenta GPS / green VLOC), TO/FROM applicability, fixed LOC sensitivity |
| `CDISCALE` **PROPOSED** | float (nm) | current full-scale deviation | CDI dot spacing |
| `CDIMODE` **PROPOSED** | enum | `OCN/ENR/TERM/APR/MAPR` (or "VLOC") | scale annunciation |
| `TOFROM` **PROPOSED** | enum/int | `0=OFF/flag, 1=TO, 2=FROM` | TO/FROM indicator |
| `OBSMODE` **PROPOSED** | bool | GPS OBS (suspend sequencing) active | "OBS" annunciation |
| `SUSP` **PROPOSED** | bool | waypoint sequencing suspended | "SUSP" annunciation |
| `BRG1` / `BRG2` **PROPOSED** | float (deg) | bearing to station for pointer 1 / 2 | bearing pointers |
| `BRG1SRC` / `BRG2SRC` **PROPOSED** | enum | source feeding each bearing pointer (GPS/NAV) | pointer symbol/label |
| `DME` / `DIS` **PROPOSED** | float (nm) | distance to active station/waypoint | data field |
| `DTK` **PROPOSED** | float (deg) | desired track | data field |
| `ETE` **PROPOSED** | float (s) | estimated time enroute to waypoint | data field |
| `WPID` **PROPOSED** | string | active waypoint identifier | data field |

> Note: `CDI`/`GSI` are published as a normalized deviation today. If `CDISCALE`
> is added, define clearly whether `CDI` stays normalized (−1..+1 full scale) or
> becomes an absolute nm/dots value — the renderer needs one convention. The
> recommendation is **`CDI` stays normalized; `CDISCALE`/`CDIMODE` are display
> annotation only**, so existing consumers (autopilot) are unaffected.

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
3. **CDI (lateral deviation)** — bar offset from the course pointer along a
   dotted scale; flagged/removed when invalid. Full-scale follows phase:
   **4.0 nm oceanic, 2.0 nm enroute, 1.0 nm terminal, angular on approach/LOC**
   (`CDISCALE`/`CDIMODE`). These are standard RNAV values (§8), not vendor
   numbers.
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
11. **Failure handling** — follow the widget convention: `fail` → red flag /
    remove the affected element; `old`/`bad` → grey. Bearing pointers and CDI
    hide rather than show stale guidance.

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

## 10. Open questions

1. `NAVTYPE` derivation — does fix-gateway know whether a NAV radio is tuned to a
   VOR vs a LOC (frequency-based), or must the source publish it? (X-Plane and
   real CAN-FiX nav radios differ.)
2. Should `CDI` remain normalized with `CDISCALE` as annotation (recommended), or
   carry absolute deviation? Decide once, document in canfix-spec.
3. Map proposed keys onto **existing** CAN-FiX navigation parameters wherever one
   already covers the concept, before proposing new parameter IDs (schema change
   goes through the careful `.ods` process).
4. OBS control hardware: encoder vs on-screen — affects whether the widget needs
   an input path or just writes `COURSE`.
