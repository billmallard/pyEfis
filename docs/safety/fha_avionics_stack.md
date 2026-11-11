# Functional hazard assessment: pyEfis and its supporting systems

**Nothing in this stack is certified, approved, TSO'd or compliant with any standard named
here.** No authority has reviewed this assessment. It is an engineering hazard assessment for
Experimental Amateur-Built use. A severity in this document describes the worst credible effect of
a failure in an airplane; it is not a classification of the software, and it is not a software
level. The classification of any real installation is the installer's, made per airplane.

**Maintained by:** Safety and Compliance. **Edition:** 2, 2026-11-10. The first edition was dated 2026-11-07. A living document: a change that adds a display function adds or updates
a row here (section 6).

---

## 1. Method

- **Shape:** a functional hazard assessment at proportionate depth: each function, crossed with
  two failure modes, each given a severity. The shape is the one FAA AC 23.1309-1E uses. SAE
  ARP4761A describes the method in full; it is paywalled, and this assessment has not read it.
- **Failure modes:** **L** = total loss of the function, annunciated or obvious. **M** = misleading
  or malfunction **without** warning: the function shows a wrong value as valid.
- **Severity:** per AC 23.1309-1E Appendix 1, for an **IFR, Class I** airplane (single
  reciprocating engine, 6,000 lb or less). That is the worst credible case for the airplanes this
  stack serves. **Cat** Catastrophic, **Haz** Hazardous, **Maj** Major, **Min** Minor. A cell marked
  **TBD** has no Appendix 1 row checked for it and is flagged for analysis, not asserted.
- **Mitigating requirements:** the requirement IDs whose implementation turns an M into an L or
  lowers the probability of the failure. Every ID is written in full, exactly as it appears in its
  spec, with no ranges. IDs beginning `AI-`, `AL-`, `AS-`, `HDG-`, `HSI-`, `TC-`, `VSI-` and `EFIS-`
  are defined in this repository's `docs/*_widget_spec.md` and `docs/requirements.md`. IDs beginning
  `CFX-` are defined in canfix-spec `src/requirements.rst`. A requirement that is specified but not
  implemented is listed as such. **A mitigation is not credited until it has a test.**
- **Open:** what is still not mitigated, not tested or not assessed. Open items are collected in
  section 5.
- **Read against:** pyEfis `dev` at 4fd2af4 (2026-11-10), plus the fixes named in the rows.

## 2. Architecture assumptions

These are the assumptions every row below depends on. A feature that would break one is a design
change to raise with Safety and Compliance before it is built, not after.

**A1. Operating posture (decided 2026-11-07; scope widened 2026-11-08).** pyEfis is **not a sole
attitude source in instrument meteorological conditions. The pilot flies with independent standby
attitude, airspeed and altitude instruments.** The pyEfis `README.rst` and the wiki home page carry
this statement.

**A2. The standby is independent.** "Independent" means the standby shares no sensor, computer,
software, power source or display with the pyEfis path. Appendix 1 says that "dual independent
attitude systems generally meet requirements" for the attitude row; that is the only argument by
which the attitude L cell is met. A standby fed from the same AHRS, the same gateway or the same
bus is not independent, and does not carry the argument.

**A3. Protection never depends on the advisory display.** No stall warning, terrain alert,
engine-limit alert or other protective function relies on pyEfis rendering it. Where pyEfis shows
such a cue, the cue is supplementary to a protection that works with the display dark. pyEfis
has no TAWS alerting, and nothing in this document assumes it does.

**A4. pyEfis is supplemental for navigation.** The installed IFR navigator's database governs any
IFR approach (14 CFR 91.175). pyEfis navigation guidance, procedures and the moving map are
situational awareness.

**A5. One key, one writer.** fix-gateway has no source arbitration; two plugins writing one key
fight, last writer wins. Each installation enables exactly one source per key. Real source
selection is a roadmap item, not a property today (section 3.3, row GW-3).

**A6. Common cause on the primary path.** Attitude, altitude, airspeed, heading and VSI all run in
one pyEfis process on one host, fed by one fix-gateway process. The L rows for those functions are
therefore **not independent events**: a host, power, gateway or process failure takes all of them
at once. Because of this, a standby that carries only attitude would leave the pilot without
airspeed and altitude after a single host failure, which is why A1 names all three.

**A7. Experimental Amateur-Built.** E-AB carries no design standard and no software level. These
assumptions are good engineering practice, not regulatory compliance.

## 3. The assessment

### 3.1 pyEfis: primary flight display

| ID | Function | Mode | Sev. | Mechanism (where in the stack) | Mitigating requirements | Open |
|---|---|---|---|---|---|---|
| PFD-1 | Attitude | L | Cat (App. 1: met by an independent standby, A2) | Host, process or gateway failure; AHRS plugin loss (A6) | AI-ANN-001 (fail display), AI-FAIL-001 (greyed when old or bad); A1, A2 | Only an independent standby lowers this cell (A1, A2) |
| PFD-2 | Attitude | M | Cat | Frozen last value after a hung gateway or socket error (fixed on `dev`, H1); a primary key with no time-to-live never goes old (fixed on `dev`, H2); a bad AHRS solution flagged valid; two sources fighting on `PITCH`/`ROLL` (A5) | AI-ANN-001 and AI-FAIL-001 act only when the flags are set. Recovery aids once the pilot knows: AI-CHEV-001, AI-BANK-001, AI-DCL-001 | No comparator against the standby; detection of a bad solution flagged valid rests on the pilot's scan (O2) |
| PFD-3 | Altitude | L | Haz | As PFD-1 (A6) | AL-ANN-001 | Covered by the A1 standby scope |
| PFD-4 | Altitude | M | Cat | Frozen value (H1, H2); a misset baro setting | AL-ANN-001; AL-BARO-001 (baro setting shown on the tape); AL-TREND-001 (a frozen trend is a cue only in climb or descent) | |
| PFD-5 | Airspeed | L | Maj (Haz at higher performance) | As PFD-1 (A6) | AS-ANN-001 | Covered by the A1 standby scope |
| PFD-6 | Airspeed | M | Maj to Cat | Frozen value (H1, H2); wrong V-speed bands from a bad aircraft profile (H4) | AS-ANN-001; AS-MARK-001, AS-LSA-001, AS-HSA-001 (bands drawn as specified, but from configured values); AI-LIM-001 (pitch-limit marker, implemented; shown only when an `AOA` source such as the onspeed plugin is present) | A3 means stall warning never depends on the display |
| PFD-7 | Heading | L | Maj | As PFD-1 (A6); magnetometer or CAN-FIX `HEAD` loss | HDG-ANN-001, HSI-ANN-001 | |
| PFD-8 | Heading | M | Maj | Undetected error over 10 deg (App. 1 definition); magnetic interference; frozen value (H1, H2) | HDG-ANN-001, HDG-FMT-001, HSI-FAIL-001 | |
| PFD-9 | Vertical speed | L | TBD | As PFD-1 | VSI-ANN-001 | App. 1 row not checked (O3) |
| PFD-10 | Vertical speed | M | Maj (per AC 25-11B Table 4-6, as the VSI spec cites it) | Frozen value; a trend computed from a frozen altitude | VSI-ANN-001, VSI-DISP-001 | App. 1 row not checked (O3) |
| PFD-11 | Turn rate and slip | L | TBD | As PFD-1 | TC-ANN-001 | Severity not assessed (O3) |
| PFD-12 | Turn rate and slip | M | TBD | Frozen or biased lateral acceleration | TC-DISP-001, TC-SLIP-001, TC-SLIP-002, AI-SLIP-001, AI-SLIP-002 | Severity not assessed (O3) |
| PFD-13 | Flight path, wind, TAS, airspeed trend | L | Min (provisional) | As PFD-1; derived keys missing | EFIS-FPM-008 (FPM removed when an input is missing), EFIS-TAS-002 (dashes when TAS is unavailable), EFIS-WIND-011 (wind keys not defined) | Provisional (O3) |
| PFD-14 | Flight path, wind, TAS, airspeed trend | M | TBD (a flight-path marker used as guidance in IMC may exceed Maj) | Derived from wrong inputs with valid flags | EFIS-FPM-011 (FPM colour when an input is degraded), EFIS-WIND-009 (wind state by colour and content). No airspeed-trend requirement handles a bad input | **Assess before any guidance use of the FPM** (O3) |
| PFD-15 | Selected altitude and deviation alert | L/M | TBD | Gateway-computed flag (`ALTSEL`, fix-gateway annunciate plugin) not delivered or not set | AL-BUG-001, EFIS-ALTSEL-002, EFIS-ALTSEL-005, EFIS-ALTSEL-006, EFIS-ALTSEL-009, EFIS-ALTSEL-010 | Severity not assessed; A3 applies to any altitude alerting (O3) |

### 3.2 pyEfis: other functions

| ID | Function | Mode | Sev. | Mechanism | Mitigating requirements | Open |
|---|---|---|---|---|---|---|
| EMS-1 | Powerplant parameters | L | Min to Haz | CAN-FIX node, bus, gateway or host loss | none with an ID | No requirement IDs for the engine widgets (O4) |
| EMS-2 | Powerplant parameters | M | Haz | Wrong limits from a bad aircraft profile, so a missed exceedance (H4); frozen value (H1, H2) | none with an ID | No IDs (O4); A3 for engine alerting |
| NAV-1 | Navigation guidance (HSI, flight plan, procedures) | L | Maj | Source or flight-plan engine loss | HSI-ANN-002 (NAV flag), HSI-ANN-003 (GS flag), HSI-FAIL-001 | |
| NAV-2 | Navigation guidance | M | Maj (LP/LPV Haz in TSO-C146e terms) | Wrong source shown; deviation scaled wrong; stale procedure data | HSI-SRC-001 (active source always annunciated), HSI-DEV-001 (normalised deviation), HSI-FAIL-001; A4 | Flight-plan engine and procedures pack have no requirement IDs (O4) |
| TER-1 | Terrain and obstacle awareness (SVS, map) | L | Min (advisory) | GL failure; no position; pack missing | AI-SVS-001 (no terrain without a valid position, SVS UNAVAIL), EFIS-SVS-002 (terrain viewpoint from FIX position), EFIS-SVS-006 (fallback to the sky/ground gradient when terrain is unavailable) | |
| TER-2 | Terrain and obstacle awareness | M | Up to Haz if trusted like TAWS | Wrong or stale pack; datum or registration error; replayed manifest (H3) | AI-SVS-001; signed manifest and publish gate (makerplane-data); A3 (no TAWS) | Per-kind data quality requirements are not written (O7) |
| MAP-1 | Moving map | L/M | Min / TBD | As TER-1, TER-2 | none with an ID | No requirement IDs (O4) |
| DAT-1 | Data currency annunciation | L | Min | `DataAnnunciation` not shown | none with an ID | (O4) |
| DAT-2 | Data currency annunciation | M | Maj (expired data shown as current) | Updater accepts an older signed manifest (fixed on `dev`, H3) | none with an ID | (O4) |

### 3.3 fix-gateway: the data path

fix-gateway's failures appear in the pyEfis rows as their mechanisms. These rows name them at the
source, so a gateway change can find its row.

| ID | Failure | Effect at the display | Sev. | Mitigation today | Open |
|---|---|---|---|---|---|
| GW-1 | Process crash or orderly close | All PFD functions lost and flagged (PFD-1, 3, 5, 7) | Cat (met only by A2) | Client marks all keys failed on a clean close | Covered by the A1 standby scope |
| GW-2 | Hang, deadlock or socket error | All PFD values frozen and shown valid (PFD-2, 4, 6, 8) | Cat | Client watchdog marks every key failed after 2 s of silence (H1); every displayed key has a time-to-live (H2) | |
| GW-3 | Two sources write one key | Value alternates between sources, each flagged valid | Cat for attitude, by PFD-2 | A5 (configuration rule only) | Source selection is a roadmap item; no interlock (O5) |
| GW-4 | Computed key from bad inputs | Derived value wrong but valid | as PFD-14 | none with an ID | fix-gateway has no requirement IDs (O4) |

### 3.4 CAN-FIX, makerplane-data and the configurator

| ID | Failure | Effect | Sev. | Mitigation today | Open |
|---|---|---|---|---|---|
| CAN-1 | Node or bus loss | EMS-1, PFD-7 | as those rows | CAN hardware CRC; node data flags; CFX-COM-008 (node sends a self-identifying frame at least every 2 s; a "should"), CFX-ELE-001, CFX-ELE-002, CFX-ELE-003 (supply range, reverse polarity) | CFX-COM-008 binds the node to send, not the receiver to notice silence: nothing requires fix-gateway's CAN-FIX plugin to flag a node that stops (O6) |
| CAN-2 | Corrupted or wrong-unit frame accepted | EMS-2, PFD-8 | as those rows | CAN hardware CRC; CFX-COM-005 (no data type or unit substitution); CFX-COM-001 (mandatory node messages, sub-items .1 to .6) | CFX-COM-005 is a sender obligation; no receiver-side range or unit check is specified (O6) |
| PKG-1 | Corrupted or tampered pack | TER-2, NAV-2 | as those rows | Ed25519 manifest, verify before trust, per-pack sha256, atomic swap | none |
| PKG-2 | Older valid manifest replayed | DAT-2, TER-2 | Maj | The updater refuses a signed manifest older than its cache (H3) | |
| PKG-3 | Source data wrong at ingest | TER-2, NAV-2 | as those rows | `schema_guard`, publish gate, pack reports bound into the manifest | Data quality requirements per kind (O7) |
| CFG-1 | Wrong V-speeds or engine limits saved | PFD-6, EMS-2 | Haz to Cat | The configurator server rejects an out-of-order or out-of-range profile (H4) | The profile reaches the aircraft by a manual install; the human check against the POH leaves no record (tool inventory, row C1) |

### 3.5 Fixes cited in the rows

Each was a known path to a misleading or wrong cell in the first edition. Each is merged to its
repository's `dev` branch with tests; this document does not say which release carries it.

| Ref | What was wrong | Fix | Test evidence |
|---|---|---|---|
| H1 | A gateway that hung with its socket open left the last attitude and air data on the glass, shown valid | pyEfis#411: a client watchdog marks every key failed after 2 s of silence; red XXX | `tests/test_fix_watchdog.py` against the real client and a fake gateway; on the Beelink bench a stopped gateway went red XXX within 2 s |
| H2 | Three displayed keys (`TIMEL`, `EGTMAX1`, `CHTMAX1`) had a time-to-live of 0, so they never went old | fix-gateway#140: time-to-live 2000 ms on those keys, plus a test over every key pyEfis displays | Unit test; fails on the previous `dev` for exactly those keys |
| H3 | The device updater accepted an older, validly signed manifest, so expired data could be shown as current | makerplane-data#167: refuse a manifest older than the cache | Unit tests that fail on the previous `dev`; replay refused on the Pi 5 bench with the production key |
| H4 | The configurator saved an aircraft profile with V-speeds or bands out of order | makerplane-data#168: server-side validation, one rule per test | 18 tests; 15 fail against the previous checks |

## 4. What this assessment says

1. **The Catastrophic cells are all M cells, plus one L cell that only the standby can lower.**
   Every M cell on the primary path rests on the data flags being set. H1 and H2 closed the two
   known paths by which they were not. A path nobody has found yet is still detected only by the
   pilot's cross-check against the standby (O2).
2. **The standby is load-bearing.** It is the only thing that lowers the attitude L cell, and the
   only cross-check for an M cell the stack fails to flag. That is why A1 and A2 exist.
3. **The instrument specs are a real mitigation record.** Every primary instrument has an
   annunciation requirement (AI-ANN-001, AL-ANN-001, AS-ANN-001, HDG-ANN-001, VSI-ANN-001,
   TC-ANN-001, HSI-ANN-001, HSI-ANN-002, HSI-ANN-003), each with tests. Those requirements convert
   M into L, but only once the flag reaches them.

## 5. Open items

| # | Open item | Rows | Owner, path |
|---|---|---|---|
| O1 | **Closed 2026-11-08.** The standby's scope is attitude, airspeed and altitude (A1, A6); the user documentation carries it | PFD-1, PFD-3, PFD-5, GW-1 | Done |
| O2 | No comparator between pyEfis and the standby; detection of an unflagged M rests on the pilot | PFD-2 | Not proposed now |
| O3 | Severity not checked against an App. 1 row: VSI, turn and slip, FPM and derived vectors, altitude alerting | PFD-9 to PFD-15 | Safety and Compliance, next edition |
| O4 | Functions with no requirement IDs: engine widgets, moving map, data annunciation, flight-plan engine, fix-gateway | EMS-1, EMS-2, NAV-2, MAP-1, DAT-1, DAT-2, GW-4 | Owners of each spec |
| O5 | No interlock against two sources on one key | GW-3 | Source selection on the fix-gateway roadmap |
| O6 | CAN-FIX requirements bind senders only: nothing specifies that a receiver flags a silent node or an out-of-range frame | CAN-1, CAN-2 | fix-gateway CAN-FIX plugin |
| O7 | No data quality requirements per pack kind (accuracy, resolution, completeness, timeliness) | TER-2, PKG-3 | makerplane-data check catalogue |

## 6. Keeping it current

- **A change that adds a display function adds or updates a row here.** A row needs the function,
  both modes, a severity or TBD, the mechanism, and the requirement IDs, written in full. A
  contributor who cannot assign a severity writes TBD and asks Safety and Compliance; the row is
  what is required, not the classification.
- A change that weakens an assumption in section 2 is raised before it is built.
- This file is the one copy. Other repositories link here rather than copying it.

## 7. Sources

- FAA AC 23.1309-1E, Appendix 1 (severity by function) and Figure 2. Read.
- FAA AC 25-11B Table 4-6, as cited by `docs/vsi_widget_spec.md`.
- 14 CFR 91.175 (IFR approach minimums and navigation).
- This repository's `docs/ai_widget_spec.md`, `airspeed_widget_spec.md`, `altimeter_widget_spec.md`,
  `heading_widget_spec.md`, `hsi_widget_spec.md`, `tc_widget_spec.md`, `vsi_widget_spec.md`,
  `requirements.md`, `instrument_verification_status.md`, `README.rst`.
- canfix-spec `src/requirements.rst` (32 IDs).
- The fix pull requests in section 3.5.
- **Not read:** SAE ARP4761A and ARP4754B (paywalled). The shape here is from FAA public guidance
  and the SAE abstract.
