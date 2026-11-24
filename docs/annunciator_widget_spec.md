# Configurable Annunciator Lamps: Widget Specification

Standards-grounded spec for the `annunciator` instrument (ANN1, `Annunciator` in
`instruments/annunciator/__init__.py`) and the shared lamp tile it draws with
(`instruments/tile.py`). Companion to [`avionics_reference.md`](avionics_reference.md)
§13, which holds the page-cited standards basis, and to the makerplane BACKLOG item ANN1
(maos-workspace), which holds Bill's level ruling of 2026-11-22.

Out of scope here: the configurator's tile and binding editor and its twin (ANN2), the CAS
window and marker (CAS3, which draw with the same tile), and `ap_annunciator` and
`data_annunciation`, which are not migrated to the shared tile.

## 1. Purpose

Bill, 2026-11-22: "a configurable annunciator instrument type that can be placed on the
screen in the configurator with the desired size, styling, and bindings to specific
values." A builder places a block of lamps, sizes it, styles it and binds each lamp to a
FIX key, with no code: `GEAR DN`, `PITOT HT`, `FUEL PUMP`, `ALT2 ON`, `TRIM`, or an enum
key shown as text (`NAVSRC` as `GPS`, `VLOC1`).

## 2. Current state (implemented, ANN1)

```yaml
- type: annunciator
  row: 0
  column: 120
  span: {rows: 20, columns: 60}
  options:
    rows: 2
    cols: 3
    tiles:
      - {label: GEAR DN, key: GEARDN, level: status}
      - {label: PITOT HT, key: PITOTHT, level: advisory, flash_on_change: 5}
      - {label: FUEL PUMP, key: FUELPUMP, level: status}
      - {label: OIL PRESS, key: OILP, flag: annunciate, level: warning}
      - {label: OIL LOW, key: OILP, when: "OILP lt 25", level: info}
      - {label: NAV, key: NAVSRC, level: info, enum: {0: VLOC1, 1: VLOC2, 2: GPS}}
```

- **A tile** has a `label` and a `key`, and at most one binding: `when` (a condition in the
  Button grammar, `instruments/conditions.py`, with `condition_keys` for other keys it
  reads), `flag` (`annunciate`, `old`, `bad` or `fail`), or `enum` (value to text). With
  none, the tile is lit while the value is truthy. `on_text` and `off_text` default to the
  label; `off_text: ""` leaves an empty box. `flash_on_change` (seconds, default 0) boxes
  and flashes a change of what the tile shows.
- **Levels.** `warning` red and `caution` amber, reverse video (filled box, black text);
  `status` green, `advisory` white, `info` cyan, caption and outline; `off` dim grey, thin
  outline. Red and amber only for `flag: annunciate`; any other binding asking for them is
  drawn at `advisory` and logged.
- **Stale.** A tile whose key or condition keys are old, bad or failed shows its label in
  grey inside a dashed grey outline, never its last state. A tile bound to `old`, `bad` or
  `fail` shows that flag instead and is not drawn stale by it.
- **Empty.** Before every key a tile reads has once been fresh, and for a key the database
  lacks, the tile draws nothing. With nothing to draw, the block paints no fill either.
- **Layout.** `rows` x `cols`, row-major, equal cells, `gap_px` between and around; `cols: 0`
  is as many as the tiles need. One caption size for the whole block, fitted to the longest
  text any tile can show, so captions do not change size with state.
- **Style.** `font_percent`, `bg_color` and `bg_opacity` (percent), `border_width` (tile
  outline, doubled while flashing), `corner_radius`, and one colour per level, each mapped
  to a style-contract token.

## 3. Data contract

The instrument defines no FIX key and writes none. It reads the keys its tiles name: each
key's value, its `old`, `bad`, `fail` and `annunciate` flags, and its aux values, the same
state dict the Button's conditions use. A key's limit, and so its `annunciate` flag, is
fix-gateway's; pyEfis adds no alert logic.

## 4. Requirements

| ID | Requirement | Cite | Status |
|---|---|---|---|
| **ANN-BIND-001** | A `when` condition in the Button grammar lights the tile; it reads the bound key and its `condition_keys`, their flags and aux values. | ANN1 Architecture (Button grammar, ORG-018) | shipped |
| **ANN-BIND-002** | `flag:` follows one of the key's own flags (`annunciate`, `old`, `bad`, `fail`). | ANN1 Context | shipped |
| **ANN-BIND-003** | `enum:` shows the mapped text for the value; an unmapped value shows itself. | ANN1 Context | shipped |
| **ANN-BIND-004** | With no binding the tile is lit while the value is truthy; `on_text`/`off_text` default to the label. | ANN1 Context | shipped |
| **ANN-BIND-005** | An entry that cannot be used (no key, two bindings, an unknown flag, a malformed condition) is logged and not drawn; construction never raises. | pyEfis graceful FIX-key init | shipped |
| **ANN-LVL-001** | `warning` and `caution` only for `flag: annunciate`; any other binding asking for them is drawn at `advisory` and logged, not refused. | AC 23.1311-1C §22.1 p.47, §22.7 p.49-50, §18.6 p.46; Bill, 2026-11-22 | shipped |
| **ANN-STALE-001** | Any key a tile reads old, bad or failed: the stale look (grey, dashed outline, the label), never the last state, and an alert is not shown on stale data. | AC 23.1311-1C §18.1 p.45 ("not to provide any misleading information") | shipped |
| **ANN-STALE-002** | A tile bound to `old`, `bad` or `fail` shows that flag and is not drawn stale by it. | follows from ANN-BIND-002 | shipped |
| **ANN-EMPTY-001** | Nothing is drawn for a tile before its keys have once been fresh, or for a key the database lacks; the block paints no fill while every tile is empty. | ANN1 Context (as the AFC4 strip, AP-STALE-003) | shipped |
| **ANN-FLASH-001** | A change of what a tile shows is boxed and flashes for `flash_on_change` seconds (0 = never). The first reading is a baseline; back from stale, only a changed reading flashes. | AC 23.1311-1C §18.3 p.45 | shipped |
| **ANN-LAYOUT-001** | Tiles fill a `rows` x `cols` grid row-major in fixed cells; a tile past the grid is not placed. | AC 23.1311-1C §18.1 p.45 (consistent location) | shipped |
| **ANN-RO-001** | The instrument writes no FIX key. | ANN1 Guardrails; FHA A5 | shipped |
| **ANN-CFG-001** | The YAML options reach the widget through `create_instrument` and `apply_options`; re-delivering the same `tiles` keeps the tiles' state. | pyEfis option path (AER-5807 lesson) | shipped |
| **ANN-CFG-002** | The editor schema publishes the tile fields, levels, flags, binding kinds and the level rule (`annunciator` block of `schema.json`), held in lockstep with the instrument, so the configurator lists none by hand (ANN2). | ANN1 Context (schema metadata) | shipped |
| **ANN-TILE-001** | A tile with nothing seen (`None`) paints nothing. | ANN-EMPTY-001 | shipped |
| **ANN-TILE-002** | Each level is drawn in its colour; warning and caution are reverse video; a caller's palette overrides the defaults. | AC 23.1311-1C §22.7 p.49-50, §18.3 p.45; AC 25-11B Table 5-1 p.43 | shipped |
| **ANN-TILE-003** | A stale tile paints only the degraded grey with a dashed outline, whatever its level. | AC 23.1311-1C §18.1 p.45, §22.6 p.49 | shipped |
| **ANN-TILE-004** | A flashing tile keeps its outline and drops caption and fill on the off phase of the shared 0.5 s blink. | AC 23.1311-1C §18.3 p.45 | shipped |
| **BTN-SHARED-001** | The Button evaluates its string conditions through the shared `conditions` module. | ORG-018 (one evaluator) | shipped |

## 5. Test cases

`tests/instruments/annunciator/test_annunciator.py`. Every test docstring names its IDs. The
Button's own suite (`tests/instruments/button/`) runs unchanged on the shared evaluator.

| Requirement | Tests |
|---|---|
| ANN-BIND-001 | `test_condition_in_the_button_grammar`, `test_condition_reads_flags_and_aux_names`, `test_fix_changes_repaint_through_the_widget` |
| ANN-BIND-002 | `test_flag_binding` |
| ANN-BIND-003 | `test_enum_binding_shows_the_mapped_text`, `test_enum_matches_a_whole_float_value` |
| ANN-BIND-004 | `test_bare_key_is_lit_while_truthy`, `test_on_and_off_text` |
| ANN-BIND-005 | `test_unusable_entry_is_not_drawn_and_never_raises` (6 entries) |
| ANN-LVL-001 | `test_red_and_amber_only_from_the_annunciate_flag` (5 bindings x 2 levels), `test_annunciate_flag_may_use_red_and_amber`, `test_status_levels_from_any_condition`, `test_unknown_level_is_advisory` |
| ANN-STALE-001 | `test_stale_key_is_never_drawn_as_its_last_state` (own and condition key x old/bad/fail), `test_stale_overrides_an_alert`, `test_stale_tile_is_grey_and_dashed_whatever_its_level`, `test_fix_changes_repaint_through_the_widget` |
| ANN-STALE-002 | `test_quality_flag_tile_shows_the_flag_itself` |
| ANN-EMPTY-001 | `test_missing_key_builds_and_draws_nothing`, `test_empty_before_first_fresh_reading`, `test_empty_until_every_condition_key_is_fresh`, `test_empty_block_paints_no_background` |
| ANN-FLASH-001 | `test_change_flashes_for_flash_on_change_seconds`, `test_no_flash_by_default`, `test_back_from_stale_flashes_only_a_changed_reading`, `test_enum_text_change_flashes`, `test_flash_timer_runs_only_while_flashing` |
| ANN-LAYOUT-001 | `test_grid_lays_tiles_row_major` |
| ANN-RO-001 | `test_writes_no_fix_key` |
| ANN-CFG-001 | `test_builds_through_apply_options_with_the_yaml_shape`, `test_tiles_set_again_with_the_same_list_keeps_state` |
| ANN-CFG-002 | `test_schema_tile_catalogue_matches_the_instrument` |
| ANN-TILE-001..004 | `test_none_tile_paints_nothing`; `test_each_level_paints_its_colour`, `test_alert_levels_are_reverse_video`, `test_status_levels_are_not_filled`, `test_custom_colours_override_the_defaults`; `test_stale_tile_is_grey_and_dashed_whatever_its_level`; `test_flash_hides_caption_and_fill_on_the_off_phase` |
| BTN-SHARED-001 | `test_button_conditions_use_the_shared_evaluator` |

Mutation check (AER-6347): 13 guards were broken in the source, one at a time, and the
suite went red for each: the level ruling, the stale check, the seen-live latch, the
quality-flag exemption, the flash baseline, the condition-key freshness, the enum's
whole-float match (survived at first; `test_enum_matches_a_whole_float_value` added), the
stale dash, reverse video, the stale colour, the flash off phase, the flag refresh in the
shared state dict, and the empty block's fill.

## 6. Conventions and standards basis

Page-cited in [`avionics_reference.md`](avionics_reference.md) §13. Colours follow AC
23.1311-1C §22.7 and AC 25-11B Table 5-1 (red warning, amber caution, green normal, white
advisory) plus cyan as "another unique color" for `info`. Each colour prop maps to a
style-contract token (`state.warning`, `state.caution`, `state.valid`, `ink.primary`,
`accent`, `ink.muted`, `surface.base`); the stale grey is the house degraded colour
(`helpers/bugs.py`) and is not themeable.

## 7. Open items

- **The look is Bill's.** Reverse video for warning and caution, the dashed stale outline
  and the dim off state are first proposals, shown on the ANN1 card with bench captures.
- **A key with no time-to-live** (`tol` 0, for example a pilot setting) is never old, so a
  tile bound to one reads live from boot and holds its value if the writer dies. The key's
  freshness is the gateway's (FHA H2, ANN-2).
- **CAS message bindings** (the other source Bill's ruling allows red and amber from)
  arrive with CAS3.
- **A binding that is wrong** (an inverted condition, the wrong key) is installer
  configuration, like CFG-2 in the FHA; nothing proves a condition means what its label
  says. FHA rows ANN-1, ANN-2.
- **Aural alerting**: none; a lamp is visual only (AC 23.1311-1C §18.5 p.46 asks for an
  aural warning with visual warnings). The gateway's alerting path owns that.
