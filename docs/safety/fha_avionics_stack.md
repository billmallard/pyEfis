# Functional hazard assessment: pyEfis and its supporting systems

**Nothing in this stack is certified, approved, TSO'd or compliant with any standard named
here.** No authority has reviewed this assessment. It is an engineering hazard assessment for
Experimental Amateur-Built use. A severity in this document describes the worst credible effect of
a failure in an airplane; it is not a classification of the software, and it is not a software
level. The classification of any real installation is the installer's, made per airplane.

**Maintained by:** Safety and Compliance. **Edition:** 5, 2026-11-21. Edition 4 was dated 2026-11-18, edition 3 earlier the same day, edition 2 2026-11-10 and the first edition 2026-11-07. A living document: a change that adds a display function adds or updates
a row here (section 6). Evidence added between editions is noted in section 8.

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
- **Read against:** pyEfis `dev` at 5bb6dec2 (2026-11-18), plus the fixes named in the rows. What
  edition 5 adds or changes (A8, PFD-9 to PFD-15, CFG-2, GW-5, section 4 item 3) was read against
  pyEfis `dev` at bb2d25be and fix-gateway `dev` at 10c0f768 (both 2026-11-21).

## 2. Architecture assumptions

These are the assumptions every row below depends on. A feature that would break one is a design
change to raise with Safety and Compliance before it is built, not after.

**A1. Operating posture (decided 2026-11-07; scope widened 2026-11-08).** pyEfis is **not a sole
attitude source in instrument meteorological conditions. The pilot flies with independent standby
attitude, airspeed and altitude instruments.** The pyEfis `README.rst` and the wiki home page carry
this statement.

**A2. The standby is independent, element by element (restated in edition 4).** The standby has
its own transducers, its own computer and software if it has any, its own power source and its
own display; it shares none of them with the pyEfis path. It **does** share the airplane's pitot
and static ports, unless the installation provides separate ones. That is the conventional
light-airplane installation: the standby airspeed indicator and altimeter tee off the same pitot
and static lines as the air data computer. The port is the sensing element, so a blocked port
gives the primary and the standby the same wrong value, and the standby cross-check cannot catch
it. That failure is row ADS-1 (section 3.1.2); it does not reach attitude, which has no shared
port. Edition 2 said the standby shares no sensor at all; for air data that was not true of the
installations this stack serves. Appendix 1 says that "dual independent
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

**A8. A source flags data it knows is invalid as `fail`, not `bad` (added in edition 5).** pyEfis
draws the two flags differently. A `fail` or `old` value is removed: red XXX, no number. A `bad`
value stays on the glass as a suspect display: the airspeed and altitude tapes keep their moving
scale and show the readout in amber inside an amber frame, and the VS readout is amber, never a
white, live-looking value (AS-ANN-001, AL-ANN-001, VSI-ANN-001). That is right for data that may be
good, and wrong for data the source knows is garbage: a plugin that marks a dead sensor only `bad`
puts an amber number on the glass where a red XXX belongs. fix-gateway holds to this today. `bad`
comes from a source's quality bit (CAN-FIX, netfix) or is carried by `compute.py` from a bad input;
no shipped computed output writes `IAS`, `ALT` or `VS`. A source or computed key that sets `bad`
for data it knows is invalid breaks this assumption, and is raised before it is built.

## 3. The assessment

### 3.1 pyEfis: primary flight display

| ID | Function | Mode | Sev. | Mechanism (where in the stack) | Mitigating requirements | Open |
|---|---|---|---|---|---|---|
| PFD-1 | Attitude | L | Cat (App. 1: met by an independent standby, A2) | Host, process or gateway failure; AHRS plugin loss (A6) | AI-ANN-001 (fail display), AI-FAIL-001 (greyed when old or bad); A1, A2 | Only an independent standby lowers this cell (A1, A2) |
| PFD-2 | Attitude | M | Cat | Frozen last value after a hung gateway or socket error (fixed on `dev`, H1); a primary key with no time-to-live never goes old (fixed on `dev`, H2); a bad AHRS solution flagged valid; two sources fighting on `PITCH`/`ROLL` (A5); a hung display (section 3.1.1); a pitch offset mis-dialled on the gateway encoder (GW-5) | AI-ANN-001 and AI-FAIL-001 act only when the flags are set. Recovery aids once the pilot knows: AI-CHEV-001, AI-BANK-001, AI-DCL-001 | No comparator against the standby; detection of a bad solution flagged valid rests on the pilot's scan (O2); a hung display has no mitigation in pyEfis (O8); a pitch offset has no bound or display (O10) |
| PFD-3 | Altitude | L | Haz | As PFD-1 (A6) | AL-ANN-001 | Covered by the A1 standby scope for a host loss. A blocked static port is not a loss: it is ADS-1, and the standby goes with it |
| PFD-4 | Altitude | M | Cat | Frozen value (H1, H2); a misset baro setting; a hung display (section 3.1.1); a blocked static port, shared with the standby (ADS-1) | AL-ANN-001; AL-BARO-001 (baro setting shown on the tape); AL-TREND-001 (a frozen trend is a cue only in climb or descent) | A hung display has no mitigation in pyEfis (O8). A blocked static port is not caught by the standby (ADS-1, O9) |
| PFD-5 | Airspeed | L | Maj (Haz at higher performance) | As PFD-1 (A6) | AS-ANN-001 | Covered by the A1 standby scope for a host loss. A blocked pitot is not a loss: it is ADS-1, and the standby goes with it |
| PFD-6 | Airspeed | M | Maj to Cat | Frozen value (H1, H2); wrong V-speed bands from a bad aircraft profile (H4); a hung display (section 3.1.1); a blocked pitot or static port, shared with the standby (ADS-1) | AS-ANN-001; AS-MARK-001, AS-LSA-001, AS-HSA-001 (bands drawn as specified, but from configured values); AI-LIM-001 (pitch-limit marker, implemented; shown only when an `AOA` source such as the onspeed plugin is present) | A3 means stall warning never depends on the display. A hung display has no mitigation in pyEfis (O8). A blocked pitot or static port is not caught by the standby (ADS-1, O9) |
| PFD-7 | Heading | L | Maj | As PFD-1 (A6); magnetometer or CAN-FIX `HEAD` loss | HDG-ANN-001, HSI-ANN-001 | |
| PFD-8 | Heading | M | Maj | Undetected error over 10 deg (App. 1 definition); magnetic interference; frozen value (H1, H2); a hung display (section 3.1.1) | HDG-ANN-001, HDG-FMT-001, HSI-FAIL-001 | A hung display has no mitigation in pyEfis (O8) |
| PFD-9 | Vertical speed | L | Min (App. 1, A1-6) | As PFD-1 (A6) | VSI-ANN-001 | |
| PFD-10 | Vertical speed | M | Min (App. 1, A1-6: Maj only where the operating rules require VS, which Part 91 outside Category II does not) | Frozen value; a trend computed from a frozen altitude; a blocked static port reads zero (ADS-1); a gauge configured to be editable writes VS itself (CFG-2) | VSI-ANN-001, VSI-DISP-001 | A VS that is wrong because altitude is frozen or the static port is blocked is graded on PFD-4 and ADS-1, not here |
| PFD-11 | Turn rate and slip | L | Min (App. 1, A1-3) | As PFD-1 (A6) | TC-ANN-001 | App. 1 notes that rate of turn is generally required for Part 91 IFR unless a third attitude is installed. A6 means a host loss takes it with attitude; whether the installation then meets that rule is the installer's |
| PFD-12 | Turn rate and slip | M | Min (App. 1, A1-3: Minor in IMC while an attitude display works) | Frozen or biased lateral acceleration | TC-DISP-001, TC-SLIP-001, TC-SLIP-002, AI-SLIP-001, AI-SLIP-002 | Minor rests on a working attitude display: the standby (A1) |
| PFD-13 | Flight path, wind, TAS, airspeed trend | L | Min (App. 1, A1-3, flight path vector; no App. 1 row for wind, TAS or trend) | As PFD-1; derived keys missing | EFIS-FPM-008 (FPM removed when an input is missing), EFIS-TAS-002 (dashes when TAS is unavailable), EFIS-WIND-011 (wind keys not defined) | Wind, TAS and trend: graded Minor here, because none is flown to and each sits beside the primary value it derives from |
| PFD-14 | Flight path, wind, TAS, airspeed trend | M | Maj (App. 1, A1-3, flight path vector: a misleading marker "could cause the pilot to temporarily maneuver the aircraft using erroneous guidance information") | Derived from wrong inputs with valid flags | EFIS-FPM-011 (FPM colour when an input is degraded), EFIS-WIND-009 (wind state by colour and content). No airspeed-trend requirement handles a bad input | Maj holds while the FPM is a display cue only. Driving a flight director or coupled guidance from it is a new row, assessed first. The airspeed trend has no requirement for a bad input (O4) |
| PFD-15 | Selected altitude and deviation alert | L/M | L: Min. M: Maj (App. 1 has no altitude-alerting row; its visual-alert row, A1-11, grades by what is monitored) | Gateway-computed flag (`ALTSEL`, fix-gateway annunciate plugin) not delivered or not set; a false alert; a bug drawn away from the value set | AL-BUG-001, EFIS-ALTSEL-002, EFIS-ALTSEL-005, EFIS-ALTSEL-006, EFIS-ALTSEL-009, EFIS-ALTSEL-010 | The alert supplements the altimeter (A3). A missed alert the pilot relied on is graded one step above an annunciated loss. Both grades assume the altitude itself is right; a wrong altitude is PFD-4 |
| ADS-1 | Air data: altitude, airspeed, vertical speed (common pitot or static blockage) | M | Cat (as PFD-4; PFD-6 up to Cat) | A blocked pitot or static port, shared by the pyEfis air data source and the standby (A2, section 3.1.2). Both show the same wrong value, each valid | Outside this stack: a heated pitot for IFR, an alternate static source, the preflight inspection. In this stack: none implemented. A GPS plausibility cue is the candidate (O9) | The standby cross-check does not detect it (A2); the GPS cue is not built (O9) |

#### 3.1.1 A hung display: one mechanism behind PFD-2, 4, 6 and 8

Every function on the PFD is drawn by one GUI thread, and the client watchdog that H1 added runs
on that same thread: it is a Qt timer (`src/pyefis/fix_watchdog.py`, the `QTimer` import and the
timer it creates). A call on the GUI thread that does not return stops all of it at once. Examples
are a GL driver call in the synthetic vision or the map, and a database read that blocks on a
lock. Then:

- nothing is repainted, so the glass keeps the last attitude, altitude, airspeed and heading,
  drawn with the flags they had, which were valid;
- the watchdog cannot run, so it never marks the data failed, however long the stall lasts. A
  stall that ends does not trip it either, because the gateway kept answering throughout;
- the process does not exit, so the service manager's restart never fires.

H1 closed the frozen-and-valid case for a hung gateway. It does not cover a hung display. **No
mitigation exists inside pyEfis today.** The pilot's cross-check against the independent standby
(A1, A2) is the only detection, as for any misleading failure the stack does not flag (O2). This
is a further instance of the common cause in A6: one thread, as well as one process and one
host.

A candidate remedy is a frame-liveness check that runs off the GUI thread and blanks the display or
flags it failed when the PFD has not repainted for a set time (O8). Its threshold is a safety
cue, and it is not set here.

#### 3.1.2 A common pitot or static blockage: ADS-1

The air data source behind pyEfis and the standby airspeed indicator and altimeter usually share
one pitot line and one static line (A2). A blocked port is a single failure that reaches both:

- **Pitot blocked, drain open** (ice, an insect nest): indicated airspeed decays toward zero.
- **Pitot and drain blocked:** the pitot pressure is trapped, so indicated airspeed rises in a
  climb and falls in a descent, like an altimeter.
- **Static blocked:** altitude freezes, vertical speed reads zero, and airspeed reads low in a
  climb and high in a descent.

Every one of these is drawn with valid flags on both the primary and the standby. The pyEfis
annunciation requirements (AL-ANN-001, AS-ANN-001, VSI-ANN-001) act on the data flags, and the
flags are good: the transducer is measuring correctly the pressure it is given. The pilot's
cross-check against the standby (A1, O2) has nothing to compare, because the standby is fed the
same pressure.

The mitigations that lower the likelihood are airframe provisions, outside this stack: a heated
pitot for flight in visible moisture, an alternate static source, and the preflight inspection of
the ports and covers. The installer owns them.

The stack can add a detection cue from a source that shares no port: GPS. Two comparisons are
available from keys the FIX database already defines:

- **Altitude:** `GPS_ELLIPSOID_ALT` against `ALT`. The two are not the same quantity: the GPS
  value is height above the ellipsoid, not above mean sea level, and baro altitude departs from
  true altitude with temperature. The comparison can therefore catch a frozen altitude in a climb
  or a descent, or a gross disagreement, but not a small error.
- **Speed:** `GS` against `IAS`. They differ by the wind and by the TAS correction, so the
  comparison can catch an airspeed that decays toward zero or tracks altitude, not a small error.

The cue is not built (O9). Its thresholds and how it is shown are safety-cue choices, and they are
not set here. A cue of this kind only converts the M cell toward L once it has a test.

### 3.2 pyEfis: other functions

| ID | Function | Mode | Sev. | Mechanism | Mitigating requirements | Open |
|---|---|---|---|---|---|---|
| EMS-1 | Powerplant parameters | L | Min to Haz | CAN-FIX node, bus, gateway or host loss | none with an ID | No requirement IDs for the engine widgets (O4) |
| EMS-2 | Powerplant parameters | M | Haz | Wrong limits from a bad aircraft profile, so a missed exceedance (H4); frozen value (H1, H2); a gauge configured to be editable writes the engine value itself (CFG-2) | none with an ID | No IDs (O4); A3 for engine alerting |
| NAV-1 | Navigation guidance (HSI, flight plan, procedures) | L | Maj | Source or flight-plan engine loss | HSI-ANN-002 (NAV flag), HSI-ANN-003 (GS flag), HSI-FAIL-001 | |
| NAV-2 | Navigation guidance | M | Maj (LP/LPV Haz in TSO-C146e terms) | Wrong source shown; a supplemental receiver read as a primary nav radio; deviation scaled wrong; stale procedure data | HSI-SRC-001 (active source always annunciated), HSI-SRC-002 (a supplemental source, `NAVSUPP` = 1 from the gateway, is marked `SUPP`; SDRVOR3), HSI-DEV-001 (normalised deviation), HSI-FAIL-001; A4. Bearing pointers are cyan, fixed to VOR1 / VOR2, never GPS and never on the CDI's own source, so a bearing needle cannot read as a second course pointer (HSI-COLOR-001, spec 6.8; HSIBRG1, HSIBRG4) | Flight-plan engine and procedures pack have no requirement IDs (O4) |
| NAV-3 | Supplemental-source coupling caution (planned: BACKLOG SDRVOR4, not built) | L | TBD | The caution is not raised while the autopilot is coupled to a supplemental source: the gateway `cas` row is missing or its inputs are lost. The source stays marked `SUPP` on the HSI (HSI-SRC-002) | none yet: the row is specified in SDRVOR4 | Not built. No adapter couples to a bus NAV source today. Severity is for Safety and Compliance. By the project owner's ruling (SDRVOR3, 2026-11-21) coupling is never refused on `NAVSUPP`, so this caution is the only autopilot-side cue |
| NAV-4 | Supplemental-source coupling caution | M | TBD | The caution is raised with a primary nav radio coupled (a nuisance caution), or it stays up after the source changes | none yet | Not built; as NAV-3 |
| NAV-5 | ADF bearing on an HSI bearing pointer (planned: BACKLOG ADF1, ADF2; not built) | L | TBD (App. 1, A1-4, display of primary navigation information: loss is Maj, Min if two navigation systems are installed) | Receiver loss, the receiver in ANT or OFF (`ADF1RB` stays `fail`), or `HEAD` invalid: the needle is removed. The readout keeps "ADF" with dashes and the frequency, or shows "ANT", so the pilot sees the pointer is gone | none yet: HSI-ANN-001 and HSI-FAIL-001 are to apply to the ADF pointer as to the VOR pointers (specified in ADF2) | Not built. Graded as primary navigation only where a route segment or procedure relies on the NDB alone. Severity is for Safety and Compliance |
| NAV-6 | ADF bearing on an HSI bearing pointer | M | TBD (App. 1, A1-4 has no NDB row: misleading navigation is Maj for Category I ILS, and the ADF spike names Haz as the candidate on an NDB approach) | (a) An erroneous relative bearing with no warning: lightning, precipitation static, or night interference from a distant station. AIM 1-1-2.d: "ADF receivers do not have a 'flag' to warn the pilot when erroneous bearing information is being displayed". (b) The wrong station: the receiver mistuned, or the ident looked up from the frequency names a different NDB on the same frequency. (c) A heading error shifts `ADF1BRG` (`HEAD` + `ADF1RB`), so the card reading is wrong by the heading error, while the needle's angle from the nose stays the true relative bearing. This is the PFD-8 mechanism, as on a real RMI. (d) A display or compute stage that smooths or holds a bearing the receiver has flagged | Planned, none credited (no test yet): the receiver's own invalid flag drives `bad` on `ADF1RB`, and `ADF1BRG` inherits `old`, `bad` and `fail` from both `HEAD` and `ADF1RB` (MAOS-DESIGN roadmap 9.1 ADF block; ADF1); the pointer is hidden on `bad` or `fail` and never smoothed or held (ADF1, ADF2); the tuned frequency is always shown, so the pilot can identify the station aurally (AIM 1-1-2.d; FAA-H-8083-15B ch. 9 p. 9-8, operational errors of ADF); the ident is marked as a lookup, in a lighter style and never marked as checked, and no `ADF1IDENT` key exists, so no ident on the glass implies a check that never happened (ADF2); the pointer is cyan and never drives the CDI (HSI-COLOR-001); for (c), the PFD-8 mitigations (HDG-ANN-001, HSI-ANN-001) | (a) has no display-side detection at all: the receiver's flag covers loss of signal, not a steady false bearing, so the mitigation is the pilot's continuous aural identification and cross-check. No requirement IDs yet: ADF2 adds them to `hsi_widget_spec.md`. Severity is for Safety and Compliance |
| TER-1 | Terrain and obstacle awareness (SVS, map) | L | Min (advisory) | GL failure; no position; pack missing | AI-SVS-001 (no terrain without a valid position, SVS UNAVAIL), EFIS-SVS-002 (terrain viewpoint from FIX position), EFIS-SVS-006 (fallback to the sky/ground gradient when terrain is unavailable) | |
| TER-2 | Terrain and obstacle awareness | M | Up to Haz if trusted like TAWS | Wrong or stale pack; datum or registration error; replayed manifest (H3) | AI-SVS-001; signed manifest and publish gate (makerplane-data); A3 (no TAWS) | Per-kind data quality requirements are not written (O7) |
| TER-3 | Terrain depiction: the height the SVS camera is drawn from | M | As TER-2 | The camera height input disagrees with the surface the SVS draws: a simulator runway at a different height from the NASR threshold, DEM error (GLO-30 is a surface model, so trees and buildings stand above a field), or a wrong height source. Without a floor the picture puts the aircraft under the runway or the terrain, with no warning | AI-SVS-004 (the camera never goes below the drawn surface plus an eye height; past a 30 ft band it is still lifted and the SVS shows amber SVS HGT, so a large error is annunciated, not hidden) | A height input that reads too high is not detected. A too-low input inside the 30 ft band is lifted silently; the band is the project owner's ruling (SVSFLOOR1), sized against measured simulator-versus-NASR runway heights |
| MAP-1 | Moving map | L/M | Min / TBD | As TER-1, TER-2 | none with an ID | No requirement IDs (O4) |
| DAT-1 | Data currency annunciation | L | Min | `DataAnnunciation` not shown | none with an ID | (O4) |
| DAT-2 | Data currency annunciation | M | Maj (expired data shown as current) | Updater accepts an older signed manifest (fixed on `dev`, H3) | none with an ID | (O4) |
| ANN-1 | Configurable annunciator lamps (`annunciator`, ANN1) | L | Min | A bound key missing from the database, never fresh, or old/bad/failed: the lamp is empty or drawn stale, so the pilot sees the loss; GL is not involved (QPainter) | ANN-STALE-001 (stale look, never the last state), ANN-EMPTY-001 (empty before first fresh data and for a missing key) | Minor holds while a lamp only repeats a state the pilot can confirm elsewhere (the switch, the gauge, the CAS window). A lamp that is the only indication of a system is graded by that system's function, not here |
| ANN-2 | Configurable annunciator lamps | M | TBD (Maj if a lamp is the only indication of its system) | A condition the builder wrote wrong (an inverted test, the wrong key); a key with no time-to-live (`tol` 0) whose source died holds its last value and is never old; a local condition asking for red or amber | ANN-LVL-001 (red and amber only from the key's own `annunciate` flag, so the alert limit lives once, in the gateway; a local condition asking for them draws at advisory and logs); ANN-STALE-001; ANN-RO-001 (writes no key, so it cannot become a second writer, A5) | The binding is installer configuration, like CFG-2: no check proves a condition means what its label says. A `tol` 0 key's freshness is the gateway's (H2). Severity for Safety and Compliance |
| MNU-1 | System menu overlay (any function under it) | L | Min | An unintended corner swipe or a `SYSMENU` write opens the overlay: the card covers the top-right of the panel and the scrim dims every instrument. It is obvious, and it ends on one tap outside the card (the tap is consumed, not passed through), on Close, or by itself after the idle timeout | none with an ID; A1 | Minor holds only while the overlay is bounded: it opens on a `SYSMENU` rising edge only, and nothing on the bus extends it (O4) |
| MNU-2 | System menu overlay | M | n/a | None: the overlay shows no value of its own, and every value under it keeps its own flags | none | |

#### 3.2.1 Crew alerting (CAS): CAS-1 to CAS-7

Added with CAS3 (pyEfis `cas_window` and `cas_marker`), on the CAS2 gateway plugin
(fix-gateway `plugins/cas.py`). The design and its severities are the makerplane brief
`briefs/crew_alerting.md` section 11, which Safety and Compliance set in its review of that brief. CAS is
supplementary (A3): every instrument keeps its own flags and colours, and CAS only adds a
message. `CASW-` IDs are defined in `docs/cas_widget_spec.md`. The gateway side has no
requirement IDs (O4); its mitigations are named by the CAS2 tests that prove them, in
fix-gateway `tests/plugins/cas/test_cas.py`.

| ID | Function | Mode | Sev. | Mechanism | Mitigating requirements | Open |
|---|---|---|---|---|---|---|
| CAS-1 | Crew alerting (CAS window and marker) | L | Min | The `cas` plugin stopped or crashed; a gateway hang; the link to the gateway lost | CASW-LOC-001 (`GATEWAY LINK LOST` when the link watchdog trips), CASW-LOC-002 (`CAS FAIL` when a list key is missing, old, bad or failed, or the list is not rewritten for 4.5 s), CASW-STALE-001; gateway: every `CAS*` key rewritten each second with tol 3 s (CAS2 tests); every instrument cue stays (A3) | **Two senses since CAS4:** warnings and cautions, the local `GATEWAY LINK LOST` and `CAS FAIL` included, sound a tone on every display host with an audio output, until acknowledged (CASW-AUR-001 to CASW-AUR-005), so the alert reaches the pilot wherever the window is placed. Reading the message still takes the visual cue, and its placement is an **installation requirement on the builder, not a pyEfis check** (project owner's ruling, 2026-11-23; Safety and Compliance review of CAS3): a `cas_marker` or `cas_window` in the primary field of view of every screen the pilot flies from, with the message one touch away (CASW-MRK-001); wiki *Designing Your Panel*, section **Installation requirement: crew alerts in your primary field of view**, and `cas_widget_spec.md` §7. Nothing annunciates a layout that breaks it. **The tone's own loss is not annunciated.** A missing audio device or a pulled USB adapter is logged and retried (CASW-AUR-006). A muted or zero mixer, a pulled audio cable, or a fault in the intercom or headset is not detected at all: pyEfis writes the tone and nothing is heard. In every case the visual cue remains, which is the slice-1 baseline (CAS-8). A display host with no audio output stays one-sense (O11) |
| CAS-1u | Crew alerting | L, not annunciated | Maj | No screen carries a window or a marker; a window clipped off the glass | CASW-LOC-004 (`CAS NOT SHOWN` once the `CAS*` keys are live, and an error in the log); gateway: `CAS TEST` at every start, held until a display or the panel button acknowledges it, 10-minute backstop (CAS2b, fix-gateway#247) | **`CAS TEST` is credited from CAS2b (fix-gateway#247 and the bench change in pyEfis#572) on.** The 5 s design was not: it cleared before any display drew (`docs/aer-6346-evidence/README.md`, Finding). Held, it was drawn at boot and after a gateway restart and stayed until touched (bench step 14, fix-gateway `doc/evidence/aer-6497-cas-test/`; the `CAS NOT SHOWN` half passed in the earlier run, `docs/aer-6346-evidence/README.md`). Until CAS2b is on the panel, a window clipped off the glass, zero-sized or covered has no cockpit mitigation. **What the credit covers** (Safety and Compliance re-read): the pilot's power-up check, as for a lamp test. It proves each window or marker the pilot sees `CAS TEST` on (the white line, or the flashing advisory marker) before the first touch. One touch clears it on every screen, so a second screen is proven only if it is looked at first, and the check must say so. After the 10-minute backstop an unacknowledged test clears with nothing on the glass, so a clipped window found later than that is not caught; the check belongs before taxi. `CAS TEST` is an advisory and `CASTOP` is the highest unacknowledged level, so it cannot mask a caution or warning. A `CASACK` clears it only when it covers its sequence, so a stale value re-sent on reconnect does not (the CAS-6 rule). A screen the pilot flies from with no window or marker, while another screen has one, breaks the installation requirement (wiki *Designing Your Panel*, section **Installation requirement: crew alerts in your primary field of view**). The configurator's per-layout advisory (BACKLOG `LAYADV1`, rule 1; makerplane-data `configurator/public/layout_advisory.js`) checks it. When a window or marker is placed anywhere in the layout, each screen with none always showing, or with only a disabled one, is warned in the editor and in comments at the head of the saved layout, naming the shipped alerts with no other cue on that screen. Rule 2 warns of a window or marker past its screen's grid, with no size, or disabled. This lowers the likelihood, not the severity. Residual: a layout written or edited outside the configurator gets no advisory, and pyEfis only logs it, not annunciated (brief R13); a window covered by another instrument is not detected; and whether a surface sits within 15 degrees of the pilot's line of sight depends on how the display is mounted, which only the builder can check. Since CAS4 a warning or caution still sounds on such a panel once `CASSEQ` reads good (CASW-AUR-005), but the message stays unreadable, so Maj is unchanged |
| CAS-2 | One alert | L (missing while its condition exists) | Maj | The catalogue omits the key (the CHT5/6 case); an inhibit holds on a failed input; text refused at load | gateway: the per-entry catalogue tests, and refusal at load is logged with the entry named (CAS2 tests) | Revisit at slice 2, when engine limits add mechanisms. The tone (CAS4) follows `CASTOP`, so it shares this row's mechanisms: an alert the plugin never raises sounds nothing either |
| CAS-3 | Crew alerting | M (false or nuisance alert) | Maj for the systematic mechanisms; Min for an isolated one | A limit judged on a failed value; cold-start limits; `NAV FAIL` on a source never received | gateway: alerts judged on valid inputs only, the C5 trigger for `NAV FAIL`, `clear_delay` (CAS2 tests); display: CASW-LOC-005 (its two link alerts hold 2 s after clearing, so an intermittent link does not flap them) | Engine limits are held to slice 2 |
| CAS-4 | Crew alerting | M (stale list shown as current) | Maj | A display keeps the last slots after the gateway stops or the plugin stops | CASW-STALE-001 (only local alerts are shown during link loss or `CAS FAIL`, and for 2 s after they clear), CASW-LOC-001, CASW-LOC-002 (the list-age check also covers a gateway that stops sending while the link watchdog is off), CASW-SRC-002 (the list is read only in one piece, between two equal `CASSEQ` reads); a read that raises on every poll is `CAS FAIL` and clears the list (`test_cas_fail_when_every_read_raises`, `tests/instruments/cas/test_model.py`) | |
| CAS-5 | Crew alerting | M (misleading text or level) | Maj | The wrong key bound to a text in the catalogue, for example left and right tanks swapped | gateway: one test per shipped entry asserting its exact text and level (CAS2 tests); display: CASW-SRC-001 (a slot is parsed exactly, and a malformed one is dropped and logged, never repaired), CASW-WIN-002 (each level in its own colour) | An installer's own catalogue entries are tested by nobody: the catalogue is installer-owned |
| CAS-6 | Crew alerting | M (alert acknowledged before it is seen) | Maj for warnings, Min otherwise | A stale `CASACK` after a restart; a button press racing a new alert; button chatter | gateway: `CASSEQ` monotonic across restarts, a `CASACK` above it ignored, the button debounced (CAS2 tests); display: CASW-ACK-001 (a touch writes the `CASSEQ` of the list drawn, never a newer one), CASW-MRK-001 (a touch on the marker opens the list and acknowledges nothing) | The button race remains by design (brief 6.5), which is why the button is optional. One acknowledge covers every message up to the `CASSEQ` drawn, including lines beyond the window's last row (brief 6.5) |
| CAS-7 | The gateway data path, through CAS | M | As GW-1 and GW-2 | A blocking `cas` callback; an unhandled exception on an aux write | gateway: the callback only records and queues, on its own thread, and catches its own exceptions (CAS2 tests; brief bench step 13) | Display side: the CAS widgets poll 16 items every 125 ms on the GUI thread. That is not yet measured on the bench. It adds load to the GUI thread that O8 covers. Closed by a Pi 5 measurement (eglfs, PFD with SVS): paint interval, SVS frame rate and time per `_tick`, with CAS quiet and with 12 unacknowledged messages flashing |
| CAS-8 | Alert tone | L, not annunciated | Min | Mixer muted or at zero (found this way on the Beelink bench during CAS4); audio cable, intercom input or headset disconnected; `AuralVolume` 0; no audio device or adapter pulled (these two are logged) | CASW-AUR-006 (logged and retried, the display carries on); every visual cue stays (CASW-LOC-001/002, the marker) | Not annunciated, and not proven at power-up: `CAS TEST` is an advisory and advisories have no tone (CASW-AUR-002), so the boot lamp test does not reach the speaker. O11(b) |

### 3.3 fix-gateway: the data path

fix-gateway's failures appear in the pyEfis rows as their mechanisms. These rows name them at the
source, so a gateway change can find its row.

| ID | Failure | Effect at the display | Sev. | Mitigation today | Open |
|---|---|---|---|---|---|
| GW-1 | Process crash or orderly close | All PFD functions lost and flagged (PFD-1, 3, 5, 7) | Cat (met only by A2) | Client marks all keys failed on a clean close | Covered by the A1 standby scope |
| GW-2 | Hang, deadlock or socket error | All PFD values frozen and shown valid (PFD-2, 4, 6, 8) | Cat | Client watchdog marks every key failed after 2 s of silence (H1); every displayed key has a time-to-live (H2) | The watchdog runs on the display's GUI thread, so it does not cover a hung display (section 3.1.1, O8) |
| GW-3 | Two sources write one key | Value alternates between sources, each flagged valid | Cat for attitude, by PFD-2 | A5 (configuration rule only) | Source selection is a roadmap item; no interlock (O5) |
| GW-4 | Computed key from bad inputs | Derived value wrong but valid | as PFD-14 | none with an ID | fix-gateway has no requirement IDs (O4) |
| GW-5 | Pitch offset mis-dialled on a gateway encoder | Attitude biased by the offset, shown valid (PFD-2) | Cat, by PFD-2 | pyEfis never writes `PITCHSET`: it is in the sensed and computed class, and the write audit fails on a pyEfis write (core_modules.yaml) | The shipped `rpi_rotary_encoder` connection writes `BARO` when the knob is turned with the push held, and `PITCHSET` when it is turned without. `rpi_bno055` adds `int(PITCHSET)` to the sensor pitch before it writes `PITCH`. The key's range is -180 to +180 deg, and nothing displays the offset. Only the standby cross-check catches it (A1, O10) |

### 3.4 CAN-FIX, makerplane-data and the configurator

| ID | Failure | Effect | Sev. | Mitigation today | Open |
|---|---|---|---|---|---|
| CAN-1 | Node or bus loss | EMS-1, PFD-7 | as those rows | CAN hardware CRC; node data flags; CFX-COM-008 (node sends a self-identifying frame at least every 2 s; a "should"), CFX-ELE-001, CFX-ELE-002, CFX-ELE-003 (supply range, reverse polarity) | CFX-COM-008 binds the node to send, not the receiver to notice silence: nothing requires fix-gateway's CAN-FIX plugin to flag a node that stops (O6) |
| CAN-2 | Corrupted or wrong-unit frame accepted | EMS-2, PFD-8 | as those rows | CAN hardware CRC; CFX-COM-005 (no data type or unit substitution); CFX-COM-001 (mandatory node messages, sub-items .1 to .6) | CFX-COM-005 is a sender obligation; no receiver-side range or unit check is specified (O6) |
| PKG-1 | Corrupted or tampered pack | TER-2, NAV-2 | as those rows | Ed25519 manifest, verify before trust, per-pack sha256, atomic swap | none |
| PKG-2 | Older valid manifest replayed | DAT-2, TER-2 | Maj | The updater refuses a signed manifest older than its cache (H3) | |
| PKG-3 | Source data wrong at ingest | TER-2, NAV-2 | as those rows | `schema_guard`, publish gate, pack reports bound into the manifest | Data quality requirements per kind (O7) |
| CFG-1 | Wrong V-speeds or engine limits saved | PFD-6, EMS-2 | Haz to Cat | The configurator server rejects an out-of-order or out-of-range profile (H4) | The profile reaches the aircraft by a manual install; the human check against the POH leaves no record (tool inventory, row C1) |
| CFG-2 | Screen config makes a gauge editable | The gauge writes the value it displays: a knob or touch edit sets `VS` or an engine value to the dialled number and sends it to the gateway, shown valid until the source next writes (PFD-10, EMS-2). pyEfis becomes a second writer of a sensed key (A5) | as those rows | No shipped config makes a sensed gauge editable. The write audit fails on a VS readout given an `encoder_order` (`tests/safety/test_core_writes.py`) | The rule holds by config, not by code: `gauges/abstract.py` defaults a gauge's `encoder_set_key` to its own `dbkey`, and `encoder_order` or `touch_edit` makes it an editor. The audit covers the shipped configs only, not an installer's own |

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
   Every M cell on the primary path rests on the data flags being set. H1 and H2 closed two
   known paths by which they were not. A third known path, a hung display (section 3.1.1), is
   open: nothing in pyEfis flags it (O8). That path, and any path nobody has found yet, is
   detected only by the pilot's cross-check against the standby (O2).
2. **The standby is load-bearing.** It is the only thing that lowers the attitude L cell, and the
   only cross-check for an M cell the stack fails to flag. That is why A1 and A2 exist. It is not
   a cross-check for a blocked pitot or static port, which it shares (ADS-1). For that failure,
   the protection is the airframe's heated pitot and alternate static source, and the only
   in-stack detection would be a GPS comparison that does not exist yet (O9).
3. **The instrument specs are a real mitigation record.** Every primary instrument has an
   annunciation requirement (AI-ANN-001, AL-ANN-001, AS-ANN-001, HDG-ANN-001, VSI-ANN-001,
   TC-ANN-001, HSI-ANN-001, HSI-ANN-002, HSI-ANN-003), each with tests. They take a value off
   "valid, without warning", but only once the flag reaches them, and what they leave depends on
   the flag. Under `fail` or `old` the value is removed: an L. Under `bad` the airspeed, altitude
   and VS readouts stay on the glass in amber: an annunciated suspect display, not an L
   (AS-ANN-001, AL-ANN-001 and VSI-ANN-001, cited by PFD-3, PFD-4, PFD-5, PFD-6, PFD-9 and PFD-10).
   That is not an M either, because it carries a warning. The argument holds only while sources
   use `fail` for data they know is invalid (A8).

## 5. Open items

| # | Open item | Rows | Owner, path |
|---|---|---|---|
| O1 | **Closed 2026-11-08.** The standby's scope is attitude, airspeed and altitude (A1, A6); the user documentation carries it | PFD-1, PFD-3, PFD-5, GW-1 | Done |
| O2 | No comparator between pyEfis and the standby; detection of an unflagged M rests on the pilot | PFD-2 | Not proposed now |
| O3 | **Closed 2026-11-21 (edition 5).** PFD-9 to PFD-15 are graded against AC 23.1309-1E Appendix 1; where App. 1 has no row (wind, TAS, trend, altitude alerting) the cell says so | PFD-9 to PFD-15 | Done |
| O4 | Functions with no requirement IDs: engine widgets, moving map, data annunciation, flight-plan engine, fix-gateway; and no requirement for the airspeed trend under a bad input | EMS-1, EMS-2, NAV-2, MAP-1, DAT-1, DAT-2, GW-4, PFD-14 | Owners of each spec |
| O5 | No interlock against two sources on one key | GW-3 | Source selection on the fix-gateway roadmap |
| O6 | CAN-FIX requirements bind senders only: nothing specifies that a receiver flags a silent node or an out-of-range frame | CAN-1, CAN-2 | fix-gateway CAN-FIX plugin |
| O7 | No data quality requirements per pack kind (accuracy, resolution, completeness, timeliness) | TER-2, PKG-3 | makerplane-data check catalogue |
| O8 | A hung GUI thread freezes every PFD value with valid flags, and the client watchdog cannot trip because it runs on that thread (section 3.1.1). Candidate remedy: a frame-liveness check off the GUI thread, for example a separate thread or a service-manager watchdog fed from the paint loop, that blanks or flags the display after N seconds without a repaint. N is a safety-cue threshold and is the project owner's decision. Also held here: an assumption A9, that the primary-flight code is separable from the rest, is entered in section 2 only once the import check that enforces it has no exceptions left; until then it would be false | PFD-2, PFD-4, PFD-6, PFD-8, GW-2 | pyEfis maintainers, with Safety and Compliance |
| O9 | A blocked pitot or static port, shared with the standby, gives both the same wrong air data with valid flags (section 3.1.2). Candidate cue: a GPS plausibility check, `GPS_ELLIPSOID_ALT` against `ALT` and `GS` against `IAS`. Its thresholds and presentation are safety-cue choices and are the project owner's decision | ADS-1, PFD-4, PFD-6, PFD-10 | pyEfis maintainers, with Safety and Compliance |
| O10 | A pitch offset set on a gateway encoder biases `PITCH` with valid flags, and the same knob sets `BARO` when pushed (GW-5). Candidates: a bound far narrower than -180 to +180 deg, a display of a non-zero offset, or taking the offset off the baro knob. Each is a safety-cue or control choice and is the project owner's decision | GW-5, PFD-2 | fix-gateway maintainers, with Safety and Compliance |
| O11 | **Narrowed 2026-11-23 (CAS4).** Warnings and cautions now sound a tone on every display host with an audio output (brief section 7; CASW-AUR-001), so the second sense no longer rests on where the window is placed. The visual condition stands for reading the message. The window is on its own screen or absent on the benches and the shipped panel, by the project owner's ruling that placement is the builder's, so the placement condition is restated around the marker: a `cas_marker` or `cas_window`, and any warning or caution `annunciator` lamp, in the primary field of view of every screen the pilot flies from (Safety and Compliance review of CAS3). It is discharged as a stated **installation requirement on the builder, not a pyEfis check** (project owner's ruling, 2026-11-23): wiki *Designing Your Panel*, section **Installation requirement: crew alerts in your primary field of view**; `cas_widget_spec.md` §7; `annunciator_widget_spec.md` §8; basis in `avionics_reference.md` §14.5. Still open: (a) a display host with no audio output (the Pi 5 bench today: its monitor has no speakers) stays one sense; (b) loss of the tone is not annunciated (CAS-8): a missing device or adapter is logged, but a muted mixer or a pulled cable is not detected at all. Candidates: a power-up tone test (a tone on `CAS TEST`, or a boot chime), which proves the whole audio chain by ear; and a local `AURAL FAIL` advisory, which covers only the logged cases. Both are safety cues and are the project owner's decision; (c) `HDG FAIL` and `NAV FAIL` should rise above caution when that source is coupled to the autopilot on an approach (phase-of-flight re-levelling, R2), which the first slice leaves out | CAS-1, CAS-2, CAS-8 | pyEfis maintainers, with Safety and Compliance; the project owner for the tone sounds and for audio hardware |

## 6. Keeping it current

- **A change that adds a display function adds or updates a row here.** A row needs the function,
  both modes, a severity or TBD, the mechanism, and the requirement IDs, written in full. A
  contributor who cannot assign a severity writes TBD and asks Safety and Compliance; the row is
  what is required, not the classification.
- A change that weakens an assumption in section 2 is raised before it is built.
- This file is the one copy. Other repositories link here rather than copying it.

## 7. Sources

- FAA AC 23.1309-1E, Appendix 1 (severity by function; pages A1-1 to A1-3, A1-6 and A1-11 for
  the rows used here) and Figure 2. Read.
- FAA AC 25-11B Table 4-6, as cited by `docs/vsi_widget_spec.md`. Edition 4 graded PFD-10 from it;
  it is transport-category guidance, and edition 5 grades PFD-10 from AC 23.1309-1E instead.
- 14 CFR 91.175 (IFR approach minimums and navigation).
- AIM, effective 2026-07-09, 1-1-2 (NDB frequency range and disturbances), and FAA-H-8083-15B
  Instrument Flying Handbook, chapter 9 (ADF relative and magnetic bearing; operational errors of
  ADF, p. 9-8), for NAV-5 and NAV-6.
- This repository's `docs/ai_widget_spec.md`, `airspeed_widget_spec.md`, `altimeter_widget_spec.md`,
  `annunciator_widget_spec.md`,
  `heading_widget_spec.md`, `hsi_widget_spec.md`, `tc_widget_spec.md`, `vsi_widget_spec.md`,
  `requirements.md`, `instrument_verification_status.md`, `README.rst`.
- canfix-spec `src/requirements.rst` (32 IDs).
- fix-gateway `src/fixgw/config/database/ahrs.yaml` (`ALT`, `IAS`, `GS`, `GPS_ELLIPSOID_ALT`,
  `PITCHSET`), `src/fixgw/plugins/rpi_bno055/__init__.py`, `src/fixgw/plugins/rpi_rotary_encoder/__init__.py`
  and `src/fixgw/config/connections/baro_rpi_rotary_encoder.yaml`.
- FAA-H-8083-25, Pilot's Handbook of Aeronautical Knowledge, chapter on flight instruments
  (pitot-static blockage behaviour).
- The fix pull requests in section 3.5.
- **Not read:** SAE ARP4761A and ARP4754B (paywalled). The shape here is from FAA public guidance
  and the SAE abstract.

## 8. Edition notes

Evidence added since the current edition. A note changes no row, severity or open item unless it
says so.

### 2026-11-25: display timing under sustained load on the bench Pi 5 (CERT20b)

**Record:** [`docs/evidence/cert20b_hot_soak/README.md`](../evidence/cert20b_hot_soak/README.md),
with the commands, scripts and raw logs beside it. The run is pyEfis#571; the pass line, verdict
and scope were added to the record by pyEfis#577.

- **Result.** The PFD keeps its rate on the bench Pi 5 at room ambient. The run was 32 min of
  the full stack (fix-gateway and pyEfis on eglfs, cycling every screen), compared over a cool
  window (the first 10 min) and a hot window (the last 10 min). The SoC was never throttled: the
  `get_throttled` bits were 0 in every sample. It plateaued at 62-68 C, about 12 C under the
  Pi 5's 80 C soft limit.
- **Pass line (project owner, 2026-11-25),** for every SVS screen (PFD, PFD_AI_ONLY,
  MAP_CTL_TEST) in both windows:

  | Limit | Worst measured | Verdict |
  |---|---|---|
  | Median frame interval 66.7 ms or less | 44.1 ms | pass |
  | p99 frame interval 100 ms or less | 70.8 ms | pass |
  | Longest gap 150 ms or less, outside a screen switch | 96.5 ms | pass |
  | Roll data-to-glass p99 120 ms or less | 104.2 ms | pass |
  | Hot at most 10% worse than cool (median interval, p99 interval, roll p99) | +5.8% | pass |

  Every limit passes. The tightest is roll data-to-glass p99: 104.2 ms against 120.
- **The latency line covers the display only.** The 120 ms is data-to-glass inside the display:
  from the gateway's input to the buffer swap. No sensor latency is in it, and the panel's
  scanout is not in it either. Whether the full sensor-to-glass path meets the 100 ms in
  AC 25-11B section 5.9 is unverified until a source's own latency is measured. A source can
  exceed that budget on its own: CERT13h2's late OnSpeed altitude is one. "Passes the latency
  line" is not a statement about the whole path.
- **Hot-soak and thermal-limit testing is out of scope now** (project owner's ruling,
  2026-11-25). It comes later in the program as environmental testing on flight-ready hardware,
  not on this bench. This result says nothing about the display with the SoC held at its limit,
  and no follow-on on this bench is planned.
- **What it changes here.** No row. It is evidence that, on this bench, sustained load does not
  slow the PFD past the pass line; it is not a mitigation for a hung display (section 3.1.1, O8),
  which is a stall, not a slow frame. It does not close the CAS-7 measurement either: that asks
  for CAS quiet against 12 unacknowledged messages flashing, and this run did not vary CAS.
