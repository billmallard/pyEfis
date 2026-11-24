# Crew Alerting (CAS) Window and Marker: Widget Specification

Standards-grounded spec for the crew alerting display (CAS3, CAP-119): the **window**
(`cas_window`, `CASWindow`), the **compact marker** (`cas_marker`, `CASMarker`), the **full
list** they open (`CASList`) and the **CAS NOT SHOWN** cue (`CASNotShownCue`), all in
`instruments/cas/`. Companion to [`avionics_reference.md`](avionics_reference.md) §14, which
holds the page-cited standards basis, and to the makerplane brief `briefs/crew_alerting.md`
(maos-workspace), sections 5.3, 6 and 11, which this implements. The hazard rows are CAS-1 to
CAS-7 in [`safety/fha_avionics_stack.md`](safety/fha_avionics_stack.md) §3.2.1.

Out of scope here (brief 12.1): sound (slice 3), engine limits (slice 2), recall and clear,
phase-of-flight re-levelling, crew-set inhibits, and the shared acknowledge with the
autopilot disconnect cue (an AFC4 follow-up, brief 6.5).

## 1. Purpose

Today a pilot learns of a failure only from the instrument that failed, if they are looking
at it. CAS puts every alert in one fixed place, sorted by urgency, with a cue on every other
screen (brief section 1). It is **supplementary** (FHA assumption A3): every instrument keeps
its own flags and colours, and CAS only adds a message. Because pilots come to rely on the
window, the design's first concern is that a quiet window can never be a failed one (brief
11, C2, C4).

## 2. Current state (implemented, CAS3)

- **Window.** One line per message, warnings red, cautions amber, advisories white, sorted
  as the gateway sorts them. An unacknowledged line flashes, swapping between a filled box
  with dark text and an outlined box with coloured text every 0.5 s, so its text reads in
  both phases. An acknowledged line is steady. With more messages than `lines` (default 4),
  the last row is `+k` in the colour of the most urgent hidden line; k counts messages
  beyond the gateway's twelve slots too. With no message the window draws nothing and is
  transparent to touch.
- **Marker.** One tile naming the highest active level (`WARNING`, `CAUTION`,
  `ADVISORY`) in its colour, flashing while anything is unacknowledged. Empty when quiet.
- **Touch.** Window: acknowledge while anything shown is unacknowledged, otherwise open the
  full list; the `+k` row always opens it. Marker: open the full list (never
  acknowledges). Full list: acknowledge, then close; it closes itself after 20 s.
- **Local alerts.** `GATEWAY LINK LOST` (warning), `CAS FAIL` (caution), `CATALOG
  REFUSED` (advisory), and the `CAS NOT SHOWN` cue (advisory) when no screen carries a
  window or marker.
- **Stale is never current.** During link loss or `CAS FAIL`, and for 2 s after they
  clear, only local alerts are drawn.
- **Shipped config.** No shipped screen carries the window: where it goes is the builder's
  choice in the configurator, on its own screen or beside the attitude display (project
  owner, 2026-11-23). Every shipped screen but data status and About carries a marker, so
  the shipped panel raises no `CAS NOT SHOWN` and the full list opens from any screen.

## 3. Data contract

CAS2, fix-gateway `src/fixgw/config/database/cas.yaml`. The widgets read only; their one
write is the acknowledgement.

| Key | Use | Writer | tol |
|---|---|---|---|
| `CASMSG1`..`CASMSG12` | Slots of the sorted list, `LEVEL\|ACK\|ID\|TEXT\|DETAIL` | `cas` plugin | 3000 ms |
| `CASCNT` | Active messages, including beyond slot 12 | `cas` plugin | 3000 ms |
| `CASTOP` | Highest unacknowledged level | `cas` plugin | 3000 ms |
| `CASSEQ` | List sequence, written after the slots | `cas` plugin | 3000 ms |
| `CASACK` | The `CASSEQ` a display acknowledges up to | every display (this widget on a touch) | 0 |

The plugin rewrites every list key each second. Local inputs: the CERT1 link watchdog
(`fix_watchdog.link_lost()`) and the updater's `status.json` (`status_path`, default
`~/.makerplane/pyefis/status.json`, re-read every 10 s).

## 4. Requirements

Status: **shipped** (implemented and tested), **deviation** (documented, accepted for this
slice), **gap** (planned elsewhere).

| ID | Requirement | Source | Status |
|---|---|---|---|
| CASW-SRC-001 | A slot is parsed exactly as `LEVEL\|ACK\|ID\|TEXT\|DETAIL` (level 1-3, ack 0/1, text non-empty). An empty slot is no message; a malformed one is dropped and logged, never repaired | brief 5.3; fix-gateway `cas.yaml` | shipped |
| CASW-SRC-002 | The list is read in one piece: `CASSEQ` before and after the slots must agree, else the last whole list stays. `CASCNT` counts messages beyond the slots | brief 5.3 ("a reader never sees half an update") | shipped |
| CASW-ORD-001 | Lines are ordered warning, caution, advisory; within a level unacknowledged first; the gateway's newest-first order kept. A local alert leads its level | AC 25.1322-1 §8c (PDF p.10-11); AC 23.1311-1C §18.4 (p.46); brief 5.2 | shipped |
| CASW-WIN-001 | With no message the window draws nothing | brief 6.2 | shipped |
| CASW-WIN-002 | Warning red, caution amber, advisory white, each overridable per widget | AC 25.1322-1 §11a (p.12), App. 1 (p.23); AC 23.1311-1C §22 (p.47); G3X p.106 | shipped |
| CASW-WIN-003 | An unacknowledged line flashes; an acknowledged one is steady; every CAS widget flashes in one phase; the text is readable in both phases | AC 25.1322-1 §12c (p.14), App. 1 (p.18, p.20); brief 6.2 | shipped |
| CASW-WIN-004 | Past `lines` messages the last row is `+k`, coloured as the most urgent hidden line, k counting every active message | AC 25.1322-1 §9 (p.12), App. 1 (p.22, "overflow indication ... number and urgency"); brief 6.3 | shipped |
| CASW-WIN-005 | Window touch acknowledges while anything shown is unacknowledged, else opens the full list; `+k` opens it; the full list acknowledges then closes; a quiet window passes the touch through | brief 6.1, 6.3, 6.5 | shipped |
| CASW-MRK-001 | The marker shows the highest active level as a word and a colour, flashes while anything is unacknowledged, is empty when quiet, and a touch opens the list without acknowledging | brief 6.1; G3X p.373; AC 23.1311-1C §22.6 (colour not the sole cue) | shipped |
| CASW-ACK-001 | A touch writes `CASACK` = the `CASSEQ` of the list drawn, never a newer one; local alerts are acknowledged on this display; nothing is written during link loss, `CAS FAIL`, or with every gateway line acknowledged | brief 5.3, 6.5 (C3) | shipped |
| CASW-LOC-001 | `GATEWAY LINK LOST` (warning) while the CERT1 link watchdog has tripped | brief 6.4 | shipped |
| CASW-LOC-002 | `CAS FAIL` (caution) when the gateway answers but a list key is missing, old, bad or failed, or `CASSEQ` was not rewritten for 4.5 s, or reading the list raises; not during link loss (the link alert replaces it at once); not in the first 5 s after start | AC 25.1322-1 §7d(1) (p.9, loss of the alerting function); brief 6.4, R12 | shipped |
| CASW-LOC-003 | `CATALOG REFUSED` (advisory) while `status.json` carries the CERT3 rollback row | brief 6.4 | shipped |
| CASW-LOC-004 | `CAS NOT SHOWN`: with the `CAS*` keys live and no window or marker on any screen, a cue over every screen and an error in the log; a screen lacking one while another has one is logged as a warning | brief 6.4, R13, C2 | shipped |
| CASW-LOC-005 | `GATEWAY LINK LOST` and `CAS FAIL` stay 2 s after their condition clears | brief C6 | shipped |
| CASW-STALE-001 | During link loss or `CAS FAIL`, and while they clear, only local alerts are drawn: no gateway slot is ever shown as current | brief 6.4, C4; FHA CAS-4 | shipped |
| CASW-REG-001 | `cas_window` and `cas_marker` are registered instruments that build in isolation and take their options through the screen-build path | CAS3 amendment (Bill, 2026-11-22) | shipped |
| CASW-AUR-001 | Warnings and cautions reach a second sense (a tone) | AC 25.1322-1 §6 (two senses for warnings and cautions); brief 7 | deviation: no audio output exists; one-sense limit recorded as FHA open item O11 |
| CASW-RCL-001 | Acknowledged messages can be cleared from view and recalled, with a stored indication | AC 25.1322-1 §9 (p.12) | gap: slice 1 has no clear; every active message stays listed (brief 5.2). Planned with recall, brief 12.1 |

## 5. Notes and deviations

- **CAS TEST timing (found on the private bench, AER-6346).** The gateway raises `CAS TEST`
  for about 5 s from plugin start. A display that is still starting, or that boots the
  data-status screen on the ground, may never draw it, so the power-up test is not
  reliably seen. It is a gateway behaviour (CAS2); the remedy is a follow-up, recorded in
  the CAS3 PR.
- **Flash style.** The tile swaps reverse video and outline rather than blanking, so a
  flashing line is always legible. The look (sizes, flash style, fill) is the project
  owner's call, with the placement.
- **Advisory white.** AC 25.1322-1 App. 1 (p.23) allows any colour but red, amber, yellow or
  green for advisories; white matches G3X and SkyView.

## 6. Tests

`tests/instruments/cas/test_model.py` (the Qt-free model) and
`tests/instruments/cas/test_widgets.py` (paint per row on a real grab, touch writes on the
queued bytes, the coverage watch, the registry build path). Every requirement ID above
except the deviation and the gap appears in at least one test docstring. The bench run on a
private gateway is `docs/aer-6346-evidence/`.

## 7. Installation requirement

**On every screen the pilot flies from, a `cas_marker` or `cas_window` must sit in the
pilot's primary field of view.** This is a requirement on the builder's installation, not
something pyEfis checks (project owner's ruling, 2026-11-23, AER-6355). Placement is the
builder's choice in the configurator, and only the builder knows where each display is
mounted and where the pilot's eyes are.

- **Why.** Warnings and cautions are visual only in this slice (CASW-AUR-001, FHA O11): no
  tone exists. The flashing marker or window is the only attention-getter, so it has to be
  where the pilot's eye already is. The window itself may sit on its own screen: the marker
  carries the attention, and a touch opens the list (CASW-MRK-001).
- **A screen the pilot flies from** is any screen up on a display in front of the pilot in
  flight, including one switched to (engine, map, radios).
- **Primary field of view:** what the pilot sees by eye movement alone from the normal
  seated eye position; within 15 degrees of the normal line of sight, about 8 inches from
  the centre of the basic T at a 30-inch viewing distance. Warnings and cautions belong
  there (AC 23.1311-1C §15.2, Table 3 and its Note 4; AC 25.1322-1 Appendix 5; quoted in
  [`avionics_reference.md`](avionics_reference.md) §14.5).

The builder-facing text, with how to check it from the seat, is the wiki page *Designing
Your Panel*, section **Installation requirement: crew alerts in your primary field of view**
(`docs/wiki/Designing-Your-Panel.md`). FHA rows CAS-1 and O11 cite that section as the
discharge of the one-sense condition. The same requirement covers warning and caution
`annunciator` lamps ([`annunciator_widget_spec.md`](annunciator_widget_spec.md) §8).
