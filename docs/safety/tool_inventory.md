# Tool inventory for the avionics stack

**Nothing in this stack is certified, approved or compliant, and this inventory qualifies no
tool.** No authority has reviewed it. It lists every tool that produces or verifies something we
ship to an aircraft, and asks one question of each: if the tool is wrong, does anything
independent of it catch the error before it reaches the aircraft?

**Maintained by:** Safety and Compliance. **Edition:** 2, 2026-11-10 (AER-5323). The first edition,
2026-11-07, was AER-5035. It is read beside the hazard assessment, `fha_avionics_stack.md` in this
folder.

## The question

The question is the tool criterion in FAA AC 20-115D: a tool matters when its output eliminates,
reduces or automates a verification step and is not itself checked. The last column answers it:

- **Yes** means nothing independent of the tool checks what it produced, or the tool is itself
  the verifier and its pass is the evidence.
- **No** means a downstream check would catch the tool's error, or the tool's output never
  reaches the aircraft.
- **No, conditional** means the answer is No only while the row it names gets an independent
  check. Until then it inherits that row's Yes.

**Not read:** RTCA DO-330 (tool qualification) and DO-200B (aeronautical data processing). Both
are paywalled. The column says whether a tool's output is relied on unchecked, not how either
standard would grade the tool. No row assigns a level.

**Sources.** The first edition read the code at these heads on 2026-11-07:
- billmallard/makerplane-data `dev` @ 6abc9d4;
- billmallard/pyEfis `dev` @ 8017016;
- billmallard/fix-gateway `dev` @ 5f1625c;
- billmallard/canfix-spec `master` @ 081f5fa.

This edition updates the rows whose findings have since been fixed, citing each fix's pull request,
and reads the makerplane-data check catalogue again at `dev` @ cb6607b (2026-11-10). Other rows are
as first read.

Paths below are relative to each repo. "Gate" means the makerplane-data publish gate. "Check IDs"
are the catalogue in makerplane-data `packtools/report.py`.

## A. Producers of data packs (makerplane-data, with builders that live in pyEfis)

Since makerplane-data#177 (AER-5181), every pack built by a pyEfis builder records the pyEfis
commit that built it (finding 1). That makes A1 to A3, A7 and A8 traceable after the fact; it does
not check their output, so it moves no answer below.

| # | Tool | Produces (and where it reaches the aircraft) | What independently checks the output today | Relied on unchecked |
|---|---|---|---|---|
| A1 | Airports builder: pyEfis `tools/build_airport_db.py`, run by makerplane-data `packtools/build` as a subprocess | Airports navdata pack: runway thresholds, alignments, elevations, VGSI. SVS runways and the moving map | Input: `schema_guard` checks the live NASR column contracts (SG-001 to SG-004). Output, at the gate: PACK-001 to PACK-004, SQL-001, ROW-001 to ROW-003, GEO-001, GEO-002, UNQ-001. These check structure, counts against the previous edition, and coordinate validity. XS-001 compares field elevation against Copernicus terrain, and is non-blocking. Nothing that blocks compares built values against the source or a second source. Unit tests: pyEfis `tests/tools/test_build_airport_db.py` | **Yes** |
| A2 | Obstacles builder: pyEfis `tools/build_obstacle_db.py`, same path | Obstacles pack from the FAA DOF. Obstacle display | Gate OBS-001 (row floor) and the common checks. XS-002 compares obstacle base against terrain, non-blocking. I found no unit test for this builder in either repo | **Yes** |
| A3 | Navaids builder: pyEfis `tools/build_navaid_db.py`, same path | Navaids pack. Map and HSI | Common, GEO and UNQ checks. Unit tests: `tests/tools/test_build_navaid_db.py` | **Yes** |
| A4 | Procedures and airways builder: `packtools/arinc424.py`, `packtools/build/procedures.py` | Procedures pack from CIFP: legs, airways, MSA, Grid MORA. Flight plan and procedure display | Gate PROC-TBL-001, PROC-FIX-001, PROC-AWY-001, PROC-AWY-002, PROC-MSA-001 to PROC-MSA-004, PROC-MORA-001 to PROC-MORA-004, all structural or count checks. PROC-GLD-001 (golden fixture) runs against the parser, not against a built pack. PROC-DIFF-001 (differential against a commercial database) is "not yet run (AER-1702)" | **Yes.** This is the row with the most at stake |
| A5 | Airspace builder: `packtools/build/airspace.py` | Airspace sectors. Map | ASP-001 (closed simple polygons) and ASP-002 (floor below ceiling). ASP-003 reconciles CIFP sectors with the source file. It is the one gate check that reads the source back, but it is our own code reading our own input | **Yes** |
| A6 | Plates: `packtools/make_plates.py`, `dtpp.py`, `build/plates.py`, `build/georef.py` | Plate pack: FAA d-TPP PDFs, plus a georeferencing transform per plate that places ownship on the chart | The catalogue has no plates content check; the gate runs only PACK-001 to PACK-004. `georef.py` holds back one control point as a residual check and gates ownship on it. That check lives inside the builder. I did not check whether the PDFs are carried byte for byte | **Yes**, for the georeferencing transform |
| A7 | Terrain: `packtools/make_terrain.py`, packing tiles built off-pipeline by pyEfis `tools/build_terrain_mips.py`, `build_terrain_mosaic.py`, `build_water_masks.py`, all run by hand on a workstation. Plus `scripts/make_glo30_tiles.py`, the expected tile set | Terrain packs: HGT tiles, mips, mosaic, water masks. SVS and terrain shading | Blocking: TER-001 (file sizes), TER-002 (inside region), TER-003 (mask present), TER-006 (no tile lost). Non-blocking: TER-004 (sampled range and voids), TER-007, TER-008. TER-005 compares spot heights against FAA field elevations. It is the closest thing to an independent content check, and it is non-blocking | **Yes** |
| A8 | Roads and water: `packtools/make_roads.py` with pyEfis `tools/build_highway_db.py`; pyEfis `tools/build_water_db.py` | Roads and water vector packs. Advisory map layers | OSM-001, OSM-002, OSM-004 and OSM-006 (counts and lengths per region and per state, bounding boxes). OSM-005 (coverage image) is rendered by the report site | **No**, while these layers stay advisory (hazard assessment rows TER-1, MAP-1). The water masks inside terrain packs are row A7, not this row |

## B. Manifest, currency and integrity (makerplane-data)

| # | Tool | Produces | What independently checks the output today | Relied on unchecked |
|---|---|---|---|---|
| B1 | Cycle arithmetic: `packtools/cycles.py` | The effective and expiry window in `pack_meta` and the manifest, which drives the device's currency display | 8 unit tests in `tests/test_cycles.py`. The gate refuses an (id, cycle) already published. Nothing compares the window against the FAA's published effective dates at publish. A wrong window displays expired data as current | **Yes** |
| B2 | Manifest writer: `packtools/publish.py`, `manifest.py` | The manifest entries: sha256, size, URL, report binding | The gate checks sha256 and size against the file, and the record's sha256 against the file being signed. The device then recomputes each pack's sha256 against the signed manifest and refuses a mismatch (`pyefis_data/core.py`). An error fails closed: a lost pack, not a misleading one | **No** |
| B3 | Signer and verifier: `packtools/signing.py` (PyNaCl ed25519, minisign wire format) | `manifest.json.minisig`, the root of the trust chain | Unit tests: tampered data, wrong key, tampered trusted comment, malformed signature. The device verifies through the same module (`pyefis_data/core.py` imports `packtools.signing`). Since makerplane-data#181 (AER-5240), CI installs the stock `minisign` binary and `tests/test_minisign_interop.py` checks `packtools.signing` against it in both directions, so a defect the two halves share no longer passes unseen (finding 3) | **No** as a tool. Signature checking runs on the device, in the updater, so it is checked as device software |

## C. Producers of configuration (configurator, fix-gateway, pyEfis, CAN-FIX)

| # | Tool | Produces | What independently checks the output today | Relied on unchecked |
|---|---|---|---|---|
| C1 | `aircraft.ini` generator: `configurator/public/aircraft.html`, `buildIni()`, running in the browser | `aircraft.ini`: V-speeds, display ranges and warn and alarm bands in FIX native units. The user installs it by hand into fix-gateway `init_data`. **These are the thresholds of the display's cues** | In the browser, `validate()` blocks Save and Download on a value outside its fix-gateway bounds. V-speed and band ordering only warn in the browser. Since makerplane-data#168 (AER-5060), the server rejects a saved profile that breaks the ordering, value or unit rules, one rule per test; the browser still builds the download, so a bad `aircraft.ini` can be downloaded without ever being saved. On the device, I found no ordering check in fix-gateway. The human check is the header line "VERIFY AGAINST YOUR POH", which is an instruction and leaves no record | **Yes**, for the file as installed: the server check covers a saved profile, not a downloaded file, and nothing checks the file on the device (finding 4) |
| C2 | Parameter schema exporter: fix-gateway `src/fixgw/tools/export_param_schema.py` | `aircraft_params_schema.json`: keys, units, bounds and multiplicity. It drives C1's forms and C1's hard bounds | `tests/tools/test_export_param_schema.py`. Its errors reach the aircraft only through C1's output | **No, conditional** on C1 getting an independent check. Until then it inherits C1's Yes |
| C3 | Panel editor: `configurator/public/editor.html`, which loads js-yaml 4.1.0 from jsdelivr | The native pyEfis screen YAML, pulled and installed by `pyefis_data/config_pull.py` | `install_config` checks only that a `screens` block exists, then snapshots for rollback. After restart it checks the process: PID stable, service active, no Traceback in the log; otherwise it rolls back. That catches a crash. It does not catch an instrument bound to the wrong FIX key, a wrong range, or a moved or missing instrument. Only the pilot looking at the panel does, with no record | **Yes** |
| C4 | Instrument schema exporter: pyEfis `src/pyefis/editor/schema.py`, `tools/build_editor_assets.py` | `schema.json` and palette thumbnails for the editor, served from R2 | It reads the screen-builder factory registry directly, so the type list and default keys cannot drift by construction | **No, conditional** on C3 getting an independent check |
| C5 | CAN-FIX JSON generator: canfix-spec `src/canfix_json.py` | `src/canfix.json` from the master spreadsheet `src/CAN-FIX.ods`: parameter ids, types, units, scaling, min and max | `tests/test_canfix_spec.py`: structural tests (ids unique and in range, types valid, min and max parseable). Since canfix-spec#6 (AER-5241), CI fails when `canfix.json` no longer matches the spreadsheet (finding 5). That catches drift between the two files, not a wrong value entered in the spreadsheet. I did not trace this file's downstream consumers (the node library, the gateway plugin) | **Yes**. A scaling or type error in the spreadsheet mis-scales a parameter on the bus, and the tests check shape and agreement, not values |
| C6 | Documentation generators: canfix-spec `canfix_xml.py`, `parameters.py`, `tools/gen_param_reference.py`; makerplane-data `packschema.py`, `schemasite.py`, `reportsite.py` | The spec site, the wiki parameter page, and the pack-format and report sites | None needed | **No**. Nothing reaches an aircraft. If a node build turns out to consume `canfix.xml`, that file moves to row C5 |

## D. Verification tools

| # | Tool | Verifies | What independently checks the tool | Relied on unchecked |
|---|---|---|---|---|
| D1 | Publish gate: makerplane-data `packtools/gate.py` with the catalogue in `report.py` | Every pack before signing. On an unattended run its accept is the release decision | `tests/test_gate.py` and `tests/gatefake.py`. QA reviewed the catalogue (AER-4102). Each check states what it cannot see | **Yes**. It is a verification tool whose pass is the evidence |
| D2 | Input contract guard: makerplane-data `packtools/schema_guard.py` | Live FAA downloads, before build | Its own unit tests (`tests/test_schema_guard.py`) | **Yes**, for the same reason as D1, for input validation |
| D3 | Test runners: pytest (all four repos); `npm test` in the configurator | Unit and integration tests | None | **Yes**, wherever a passing test is the only check on shipped content |
| D4 | Coverage: pytest-cov in pyEfis and fix-gateway (branch coverage, posted as a PR comment by `python-coverage-comment-action`, no minimum threshold). I found none in makerplane-data or canfix-spec | Structural coverage | None | **Yes**, if a coverage figure is ever used as evidence. None is today |
| D5 | flake8 (`E9,F63,F7,F82`: syntax errors and undefined names) | Lint | Not needed | **No**. Nothing rests on it |
| D6 | Record tools: the DCO check in CI, `scripts/spdx_check.py`, GitHub branch protection | Provenance and licensing records | Not needed | **No**. They produce records, not shipped content |

## What the inventory found

These are gaps against the question above. None is a claim that a tool is wrong.

1. **Fixed (makerplane-data#177, AER-5181).** The navdata builders ran from whatever pyEfis `dev`
   was at build time, and no pack recorded which pyEfis commit built it. Each pack now records
   that commit. Pinning the builder version is still open.
2. **No navdata kind has an independent content check that blocks.** PROC-DIFF-001 has not run.
   PROC-GLD-001 runs against the parser in unit tests, not against the pack. TER-005, XS-001 and
   XS-002 are non-blocking. For A1 to A5 and A7, nothing independent of our own code that blocks a
   publish compares content against a second source. That is why every one of those rows reads
   Yes, and why the single differential in AER-1702 would move more rows than any other work item.
3. **Fixed (makerplane-data#181, AER-5240).** Sign and verify were one implementation, so a defect
   both halves shared would pass every test. CI now checks them against the stock `minisign`
   binary.
4. **The configuration that sets the display's cue thresholds (C1) and the panel bindings (C3) is
   checked on the device only by the pilot, and that check leaves no record.** makerplane-data#168
   (AER-5060) closed the server half of C1 for a saved profile; a downloaded file is still built and checked only in the browser. Neither has a recorded human check.
5. **Fixed (canfix-spec#6, AER-5241).** `canfix.json` was not reconciled against its spreadsheet,
   so a hand edit to either side passed CI. CI now fails on a mismatch.
6. **Plates have no kind-specific gate checks.** The ownship residual check lives inside the
   builder (A6), and the gate cannot see a plate whose transform passed its own residual and is
   still wrong.

## Keeping it current

Update a row when a change adds or replaces a tool that produces or verifies shipped content, or
when it moves a row's independent check. A row's answer changes only when its third column
changes. This file is the one copy; other repositories link here rather than copying it.
