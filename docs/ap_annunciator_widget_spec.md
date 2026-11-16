# Autopilot Mode Annunciation and Target Cues: Widget Specification

Standards-grounded spec for the autopilot cues on the PFD (AFC4): the **mode
annunciation strip** (`ap_annunciator`, `ModeAnnunciator` in
`instruments/autopilot/fma.py`) and the **target cues** the autopilot state gates
on the tapes: the `IASSEL` bug and box on `Airspeed_Tape`, the `VSSEL` bug on a VS
`Altimeter_Tape` and on `VSI_PFD`, and the `ALTSEL` box's capture look on the ALT
`Altimeter_Tape`. Companion to [`avionics_reference.md`](avionics_reference.md) §12,
which holds the page-cited standards basis, and to the makerplane brief
`briefs/autopilot_control_head_plan.md` (maos-workspace), sections 3, 5.5 and 5.7.

Out of scope here: the flight director bars (AFC5), the control head and its button
states (AFC3), and the autopilot itself (AFC2 answers requests on the X-Plane bench).

## 1. Purpose

The strip is how a pilot knows what the autopilot is doing, so it is required, not
optional (brief §5.5 item 1). AC 25.1329-1C §44.c (p.41): "Mode annunciation must
indicate the state of the system ... Mode selector switch position or status is not
acceptable as the sole means of mode annunciation." The biggest risk the brief names
is an annunciation that lies (§8), so the strip shows only what the autopilot source
reports and removes it when the source goes quiet.

## 2. Current state (implemented, AFC4)

- **Strip.** Three groups, lateral | AP YD | vertical by default (`ap_position:
  left` puts AP YD first). Each mode group has its active mode (green) and its armed
  modes (white) in separate places. The active vertical mode carries its target where
  the contract names one (`VS +500`, `IAS 90`). A new active mode is boxed and flashes
  for `mode_flash_s` (10 s). `APDISC` shows a red, boxed, flashing `AP` while the
  source holds it; a tap sends `APCMD` `DISC` to acknowledge, only while the alert is
  set and the autopilot reads disengaged. Any state key old, bad or failed: `NO AP
  DATA`, amber if the autopilot was engaged at the last fresh reading, grey if not.
  Before a source is seen, or on a gateway without the AFC1 keys: empty.
- **Airspeed tape.** While IAS is the active or an armed vertical mode: an `IASSEL`
  box at the top of the tape (green border when active, white when armed; value in the
  bug colour; dashes when `IASSEL` is 0, "not set") and the `IASSEL` bug on the label
  edge, pegged at the box or the TAS box when off scale. Display only: the value is set
  on the control head (AFC3).
- **VS tape and PFD VSI.** While VS is the active vertical mode: the `VSSEL` bug.
- **Altimeter tape.** While `APALTCAP` is set: the `ALTSEL` box border turns green and
  thickens. The gateway's deviation alert (EFIS-ALTSEL-006, amber) outranks it.

## 3. Data contract

AFC1, fix-gateway `src/fixgw/config/database/autopilot.yaml` and
`doc/autopilot_keys.md`. The strip reads only; its one write is the acknowledgement.

| Key | Use | Writer | tol |
|---|---|---|---|
| `APENG`, `YDENG` | `AP`, `YD` cells | autopilot source | 2000 ms |
| `APLAT`, `APLATARM` | lateral active / armed | autopilot source | 2000 ms |
| `APVERT`, `APVERTARM` | vertical active / armed; gates the IAS and VS cues | autopilot source | 2000 ms |
| `APALTCAP` | `ALT CAP`; the ALTSEL box capture look | autopilot source | 2000 ms |
| `APDISC` | the disconnect alert; latched by the source until `DISC` | autopilot source | 2000 ms |
| `VSSEL`, `IASSEL` | targets (strip text, bugs, box) | pilot (several writers) | 0 |
| `APCMD`, `APCMDSEQ` | `DISC` acknowledgement: command, then counter | pilot | 0 |

Freshness: all eight state keys are read as one reading. One key old, bad or failed
blanks the whole strip and every gated cue. A target key with no usable value shows the
mode name with no number.

## 4. Requirements

| ID | Requirement | Cite | Status |
|---|---|---|---|
| **AP-SRC-001** | Show only the state the autopilot source reports, never a press or a request. A refused request leaves the strip unchanged. | AC 25.1329-1C §44.c p.41; brief §3, §8 | shipped |
| **AP-ENG-001** | Annunciate autopilot engagement (`AP`) and yaw damper (`YD`) from `APENG`/`YDENG`. | AC 25.1329-1C §27.a(2) p.30 | shipped |
| **AP-ANN-001** | Active and armed modes in different locations; armed lists in the order the source gives. | AC 25.1329-1C §44.c(1)-(2) p.41 | shipped |
| **AP-COLOR-001** | Active modes green, armed modes white. | AC 25.1329-1C §44.c(4) p.42; AC 25-11B Table 5-1 p.43 | shipped |
| **AP-ANN-002** | The active vertical mode carries its target (`VS` with `VSSEL`, `IAS` with `IASSEL`). No number where the contract has no reference key. | AC 25.1329-1C §44.c(1) p.41 ("target information") | shipped; **ALT hold reference: gap** (no key, see §7) |
| **AP-ANN-003** | A change of active mode (armed to active, a reversion, a mode that changed while the strip was blank) is boxed and flashes for `mode_flash_s`, default 10 s. The first reading is a baseline. | AC 25.1329-1C §44.d(1)-(2) p.42 | shipped |
| **AP-ANN-004** | Altitude capture is annunciated (`ALT CAP`). | AC 25.1329-1C §44.d(1) p.42 | shipped |
| **AP-DISC-001** | A disconnect (`APDISC`) is a warning: red, boxed, flashing `AP`, held with no display time limit while the source holds the flag. | AC 25.1329-1C §27.b(2)(a) p.32; AC 25-11B Table 5-1 p.43; brief §5.7 | shipped (visual) |
| **AP-DISC-002** | A tap acknowledges with `APCMD` `DISC` then `APCMDSEQ`+1, only while `APDISC` is set, fresh, and `APENG` is false, so the tap cannot disconnect anything. | AC 25.1329-1C §27.b(2)(b) p.32 ("another acceptable means"); AFC1 `DISC` semantics | shipped |
| **AP-DISC-003** | The disconnect warning has an aural part. | AC 25.1329-1C §27.b(2)(a)-(b) p.32 | **deviation-accepted**: no audio exists in pyEfis yet (brief §5.5 item 1, "when audio exists") |
| **AP-STALE-001** | Any state key old, bad or failed: `NO AP DATA`, never the last reading. | AC 25.1329-1C §28.a(2)(c) p.35 (by analogy: invalid guidance removed); AC 25-11B §4.2 p.21-22; brief §5.7 | shipped |
| **AP-STALE-002** | `NO AP DATA` is amber when the autopilot was engaged at the last fresh reading, grey otherwise. | AC 25-11B Table 5-1 p.43 (amber: caution) | shipped |
| **AP-STALE-003** | Nothing is drawn before any source has been seen, or on a gateway without the AFC1 keys; construction never raises. | pyEfis graceful FIX-key init | shipped |
| **AP-LAYOUT-001** | Groups ordered like the control head's (lateral, AP/YD, vertical); `ap_position: left` for AP/YD first. | AC 25.1329-1C §43.b(4) p.41 | shipped |
| **TGT-IAS-001** | `IASSEL` bug and target box on the airspeed tape while IAS is active or armed; dashes and no bug when not set; pegged off scale. | AC 25-11B App. A A.4.2 p.71; brief §5.5 item 4 | shipped |
| **TGT-IAS-002** | The box border says active (green) or armed (white). | AC 25.1329-1C §44.c(4) p.42; brief §5.3 | shipped |
| **TGT-IAS-003** | Box and bug removed when the autopilot state goes old, bad or failed. | brief §5.7 | shipped |
| **TGT-VS-001** | `VSSEL` bug on a VS tape and on the PFD VSI while VS is the active mode; removed on stale state. | brief §5.5 item 5 | shipped |
| **AL-CAP-001** | The `ALTSEL` box changes look while `APALTCAP` is set; the deviation alert outranks it. | AC 25.1329-1C §44.d(1) p.42; brief §5.5 item 3 | shipped |

Altitude **deviation** alerting (EFIS-ALTSEL-005/-006/-009/-010) was already shipped by
fix-gateway #90 and pyEfis #362 (`requirements.md`); AFC4 adds only the capture look.

## 5. Test cases

`tests/instruments/autopilot/test_fma.py` (strip) and `test_tape_cues.py` (tapes). Every
test docstring names its IDs. Writes are asserted on the bytes queued to fix-gateway.

| Requirement | Tests |
|---|---|
| AP-SRC-001 | `test_strip_shows_reported_state`, `test_a_request_alone_shows_nothing`, `test_refused_request_never_lights_the_mode`, `test_nothing_engaged_is_an_empty_strip` |
| AP-ENG-001, AP-COLOR-001 | `test_strip_shows_reported_state` |
| AP-ANN-001 | `test_strip_shows_reported_state`, `test_armed_list_in_source_order` |
| AP-ANN-002 | `test_vertical_target_from_its_key`, `test_target_follows_the_key`, `test_target_without_a_usable_value_is_the_mode_alone`, `test_alt_hold_shows_no_number` |
| AP-ANN-003 | `test_mode_change_flashes_for_the_flash_time`, `test_flash_time_is_configurable`, `test_reversion_flashes_too`, `test_first_reading_is_a_baseline`, `test_recovery_flashes_only_what_changed_while_blank`, `test_blink_hides_text_on_the_off_phase` |
| AP-ANN-004 | `test_capture_is_annunciated` |
| AP-DISC-001 | `test_disconnect_flashes_red_ap_until_the_source_clears_it`, `test_disconnect_latch_is_the_sources` |
| AP-DISC-002 | `test_tap_acknowledges_with_disc`, `test_tap_never_sends_disc_otherwise`, `test_seq_wraps_at_its_max` |
| AP-STALE-001 | `test_any_stale_key_blanks_to_no_data` (8 keys x old/bad/fail), `test_no_data_paints_no_mode_text`, `test_recovery_restores_the_reading` |
| AP-STALE-002 | `test_no_data_is_amber_after_engaged_grey_otherwise` |
| AP-STALE-003 | `test_never_seen_source_draws_nothing`, `test_missing_keys_build_and_draw_nothing` |
| AP-LAYOUT-001 | `test_groups_follow_the_control_head_order`, `test_template_fits_every_slot` |
| TGT-IAS-001..003 | `test_ias_target_*` |
| TGT-VS-001 | `test_vs_tape_bug_*`, `test_vs_bug_defaults_follow_the_key`, `test_vsi_pfd_bug_only_while_vs_active` |
| AL-CAP-001 | `test_altsel_box_changes_look_while_capturing`, `test_deviation_alert_outranks_the_capture_look` |

Mutation check (AER-5808): each of these guards was broken in the source and the suite
went red: the freshness test, the engaged guard on the acknowledgement, the VS and IAS
mode gates, the alert-outranks-capture rule, the seen-live latch, and the baseline on
recovery.

## 6. Conventions and standards basis

Page-cited in [`avionics_reference.md`](avionics_reference.md) §12. Colours follow AC
25-11B Table 5-1 (green engaged modes, white armed, red warning, amber caution); cyan
bugs follow `instrument_bugs_design.md` (pilot-selected). Mode names are the source's
own strings (AFC1), drawn as given: no vendor naming or trade dress.

## 7. Open items

- **ALT hold reference.** AC 25.1329-1C §44.c(1) asks for target information, and the
  brief's example is `ALT 8500`. AFC1 has no key for the altitude being held, and
  `ALTSEL` is not it: after a capture the pilot may already have set the next altitude.
  The strip shows `ALT` alone. A source-published reference (for example an
  `APALTREF` key, fed in AFC2 from the sim's altitude-hold dataref once its name is
  checked against the X-Plane 12 list) would close it. That is a new FIX key, so it is Bill's call.
- **Aural disconnect warning** (AP-DISC-003): when pyEfis has audio.
- **Failure to engage or arm** (AC 25.1329-1C §44.e p.42) is the control head's
  (AFC3: request pending, then amber and `APMSG`). The strip does not show `APMSG`.
- **FD de-selection** (§28.b p.35) is AFC5's.
- **Display crowding**: one combined capture-sheet review of the attitude display with
  AFC5 before either merges (brief §8).
- `VSI_Dial` carries no `VSSEL` bug; the shipped screens use `vsi_pfd` and the VS tape.
