# Instrument description -- `makerplane.instrument/1`

Status: **contract, version 1.** INS8 (AER-6685), from the study
`briefs/instrument_description_study.md` (maos-workspace, INS7). Nothing in pyEfis or the
configurator draws a description yet: the evaluators and painters are INS9 (pyEfis) and
INS10 (makerplane-data). This document, the two schemas and the corpus are what both build
to.

A description is one YAML file that draws one instrument. It is **draw-only**: no field takes an
expression, and nothing in it can write a key, take input or fetch a resource. Every rule below
is checked without running the file.

| Part | Where |
|---|---|
| Description schema (JSON Schema 2020-12) | `src/pyefis/editor/instrument_description.schema.json` |
| Display-list schema | `src/pyefis/editor/instrument_display_list.schema.json` |
| Validator and CLI | `src/pyefis/editor/instrument_description.py` |
| Conformance corpus | `conformance/instrument_description/` (`manifest.json` lists every case) |
| Tests | `tests/editor/test_instrument_description.py` |

The first valid case is the study's worked example,
`conformance/instrument_description/valid/oil_pressure_dial.yaml`, commented line by line.

## 1. Why the file only draws

Every popular declarative graphics format grew an expression language, and then it was no
longer declarative (study section 3). Draw-only holds only if the schema has no field that
takes an expression. The split follows ARINC 661: fix-gateway is the user application and owns
all logic, the interpreter is the display system and draws, and the description is the
definition file. A fact the drawing needs that an engine computes is a FIX key, never a field
here (the engine-state-on-bus rule).

## 2. The file

Fields at the top level, all closed (`additionalProperties: false` at every level):

| Field | Required | Meaning |
|---|---|---|
| `format` | yes | `makerplane.instrument/1`, exactly (B9) |
| `type` | yes | `user.<name>`, lower case, digits and `_`. The local name may not equal a shipped type's, ignoring case (B9) |
| `label` | yes | the palette label, literal text, at most 48 characters (B8) |
| `category` | no | the palette group, a name |
| `family` | yes | `scale_gauge`, the only family of version 1. The family owns the quality look (section 6) |
| `author`, `license` | no | literal text; `license` an SPDX-style id |
| `options` | no | at most 32 option declarations (below) |
| `inputs` | yes | 1 to 8 named inputs, each `{option: <fixkey option>}` (B3) |
| `canvas` | yes | `{width, height}`, the file's coordinate space, each up to 2000 |
| `scale` | yes | the value mapping (below) |
| `draw` | yes | 1 to 256 elements, back to front |
| `on_fail` | no | up to 32 static elements, drawn in addition to the family's fail look (B7) |

**Options** use the `InstrumentSpec` `Prop` vocabulary, so the configurator builds the
properties panel as it does for a shipped type. Version 1 has three kinds; each needs `name`,
`kind` and `default`, and may carry `label`:

- `fixkey`: a FIX key name (`OILP1`). The only way a file names a key, and only as a default
  the installer can rebind.
- `boolean`: a static switch for `visible_if`.
- `color`: a token or `#rrggbb` default, plus an optional `token` (the theme token it reads,
  as `Prop.token`).

Other `Prop` kinds (number, enum, string, aircraft_ref) are not in version 1; nothing in the
drawing could read them. An option may not be named `font_family` or `font_percent` (the
screen builder's common options, S1), nor `touch_edit` or `encoder_*` (they make the instrument
an input target, B2).

**Scale.** `input` names an input. `range: {from, to}`, each a number or `aux.Min` / `aux.Max`
(the key's own limits from fix-gateway). Exactly one of:
- `angle: {start, sweep, center}` -- a round scale, degrees clockwise from 12 o'clock, about
  `center` (default: the canvas centre);
- `axis: {x1, y1, x2, y2}` -- a bar, `from` at the first point and `to` at the second.

`clamp: true` pins a value past the range at the end stop.

**Elements.** Each element is an object with exactly one key, the primitive's name.

| Primitive | Fields (required in bold) | Notes |
|---|---|---|
| `circle` | **cx, cy, r**, fill, stroke, width | |
| `rect` | **x, y, w, h**, rx, fill, stroke, width | |
| `line` | **x1, y1, x2, y2, stroke**, width, dash | |
| `polyline` | **points, stroke**, width, dash | 2 to 64 points |
| `polygon` | **points**, fill, stroke, width | 3 to 64 points |
| `arc` | **cx, cy, r, start, sweep, stroke**, width, dash | a stroked arc, angles as `scale.angle` |
| `text` | **x, y, text, size**, font, fill, anchor, box, role | `box` draws a frame round it; `role: label` marks the caption the family turns red on annunciate |
| `group` | **draw**, translate, rotate | at most 4 groups deep |
| `bands` | **width**, r or offset | the limit arcs or bars (section 6) |
| `ticks` | **every, length, stroke**, r or offset, width | graduations every `every` value units |
| `tick_labels` | **every, size**, r or offset, decimals, font, fill | |
| `pointer` | **shape**, pivot, input, fill, stroke, width | value-bound |
| `fill_bar` | **width**, input, fill | value-bound, axis scales only |
| `readout` | **x, y, mask, size**, input, decimals, font, fill, anchor | value-bound; `mask` is the `value_text` digit mask |

- On an angle scale, `bands`, `ticks` and `tick_labels` are placed by `r`, the radius about
  the scale's `center`, and a `pointer` needs `pivot`. On an axis scale they are placed by
  `offset`, the perpendicular distance from the axis, and the pointer moves along it. The wrong
  one is refused (S1).
- `pointer`, `fill_bar` and `readout` read `scale.input` unless they name another `input`.
- Any element may carry `visible_if: <boolean option>`: a static option name, nothing else (B1).
- `font` is one of the shipped font families (`DejaVu Sans Condensed`, `DejaVu Sans`,
  `DejaVu Sans Mono`, `B612`, `Inter`, `Roboto`, `Open Sans`). No font files (B4). Absent, the
  instrument's `font_family` applies.
- `text` is a literal string of at most 32 characters, with no `<`, `>`, `&` or control
  characters (B8). Quote `"OFF"`, `"ON"`, `"YES"` and `"NO"`: unquoted, YAML reads them as
  booleans and the file is refused (S1).
- All numbers are literals. A string where a number belongs is refused as an expression (B1).

## 3. Colours

A colour field (`fill`, `stroke`) takes one of:
- a style-contract token (`ink.primary`, `line.border`; `pyefis.screens.color_tokens.TOKENS`);
- the name of one of the file's own `color` options;
- a literal `#rrggbb`;
- `band`, the family's value colour (section 6), on `pointer`, `fill_bar` and `readout` only.

Anything else is refused (B1). **Red and amber are the key's, not the file's** (B6, Bill,
2026-11-26, packet AER-6670). Outside `on_fail`, a colour is refused when it is
`state.warning` or `state.caution`, a colour option whose default or token is one of those, or a
literal in the red-to-amber window: hue at or below 50 degrees or at or above 335, saturation
at least 0.5, value at least 0.35. `#ff0000` and `#ffaa00` are inside, and so are browns and
dark oranges (`#a0522d`, `#cc6600`). `#ffff00` (yellow, hue 60), magenta, pale pink and
near-black red are outside. The `on_fail` layer is drawn only when the key is failed or old, so
it may use any colour.

## 4. The rules

Every refusal names one rule id. A file is valid when it has no refusal.

| Id | Rule | Enforced by | Cases (`invalid/`) |
|---|---|---|---|
| S1 | **Well-formed.** Required fields, types, value sets, one document, UTF-8, no duplicate field, placement that fits the scale kind. A shape check, not a safety rule | schema keywords not attributed elsewhere; `_check_s1`; the parser's duplicate-field check | `s1_*` |
| B1 | **No expressions.** Every string is a literal, a token, a closed source name (`aux.Min`, `aux.Max`) or a declared option of the right kind | the closure (`additionalProperties: false`); `x-rule: B1` keywords; `_check_b1` | `b1_*` |
| B2 | **No command.** No action, event, write or knob vocabulary | the closure, named by `CLOSURE_VOCABULARY["B2"]`; `_check_b2` (knob options) | `b2_*` |
| B3 | **No input but declared keys.** Every input reads a `fixkey` option; every `input` names a declared input | `_check_b3` | `b3_*` |
| B4 | **No external resources.** No URL, include, image or font file | the closure, named by `CLOSURE_VOCABULARY["B4"]`; the font list (`x-rule: B4`) | `b4_*` |
| B5 | **Bounded cost.** At most 64 KiB, 256 elements in all, 64 points per shape, 32 characters per text, 4 levels of grouping; no YAML aliases | every `max*` keyword; `_check_b5`; the parser's size and alias checks | `b5_*` |
| B6 | **Red and amber come only from the key** (section 3) | `_check_b6` | `b6_*` |
| B7 | **Quality is not authorable.** No field addresses quality; `on_fail` holds static elements only, so it cannot draw a failed value | the closure, named by `CLOSURE_VOCABULARY["B7"]`; `x-rule: B7` on `on_fail` elements | `b7_*` |
| B8 | **Text is text.** Literal strings, never markup | `x-rule: B8` patterns. Painters must also create text as text: `textContent` in the DOM, never parsed markup | `b8_*` |
| B9 | **Versioned.** Known `format` and `family`; a `user.` type that shadows no shipped type | `x-rule: B9` keywords; `_check_b9` against `screenbuilder_factory.REGISTRY` | `b9_*` |

`x-rule` is a schema annotation the validator reads to name the rule a failing keyword belongs
to. A JSON Schema validator ignores it, so the schema is usable on its own: it accepts exactly
what the validator's schema pass accepts (`test_walker_agrees_with_jsonschema`). An unknown
field is refused under the rule whose vocabulary names it (`on_click` under B2, `url` under
B4, `on_old` under B7) and under B1 otherwise.

**Refuse, do not warn-and-apply.** A half-applied drawing can mislead. The editor refuses an
invalid file on upload, naming the rule. On the device a file that fails validation builds a
placeholder reading `INVALID INSTRUMENT` in its span and logs the refusals, never a partial
drawing (INS9).

What the rules cannot catch is installer configuration: a correct dial with the wrong
caption, or a scale that disagrees with its painted numbers (FHA CFG-2, ANN-1).

## 5. The validator

```bash
python -m pyefis.editor.instrument_description FILE [FILE ...]
python -m pyefis.editor.instrument_description --json FILE
python -m pyefis.editor.instrument_description --shipped-types-from schema.json FILE
```

Exit 0 when every file is valid, 1 when any is refused (each refusal printed as
`REFUSED <rule> <path>: <reason>`), 2 when the check cannot run. B9's shadowing check reads
`REGISTRY`, which imports PyQt6; without it, pass an exported editor `schema.json`
(`python -m pyefis.editor.schema -o schema.json`).

The schema pass is a small walker over the JSON Schema keywords the schema uses, so the device
gains no dependency. It refuses a schema that uses any other keyword
(`check_schema_keywords`), so a constraint added later is never silently skipped. In Python,
`validate_text`, `validate_file` and `validate(doc)` return the refusals; `rules=` runs a
subset, which the tests use.

## 6. The quality look (the family's rule, not the file's)

Bill's ruling, 2026-11-26 (packet AER-6670): described gauges take the IFLAG reference look,
the airspeed and altitude tapes' (Bill, 2026-11-25). The file cannot change any row; it can
only add to fail and old through `on_fail`.

| State | `scale_gauge` draws |
|---|---|
| fail | value-bound elements (`pointer`, `fill_bar`, `readout` digits) are **not drawn**; the readout's place shows `XXX` in `state.warning`; `bands` dimmed; `on_fail` drawn |
| old | as fail |
| bad | last value kept; `readout` and `pointer` drawn in `state.caution`, overriding their declared colour |
| annunciate | `readout`, and `text` with `role: label`, in `state.warning`, unless fail or old |
| never written | waits for IFLAG's bus signal. Until the bus carries it, the display cannot tell, and the value draws as written. When the signal lands: as fail (one interpreter change and one corpus update reach every described gauge) |

The `band` colour, in order: fail or old -- not drawn; annunciate -- `state.warning`; bad --
`state.caution`; past `lowAlarm` or `highAlarm` -- `state.warning`; past `lowWarn` or
`highWarn` -- `state.caution`; otherwise `ink.primary`. These are the comparisons
`AbstractGauge.setColors` makes against the same aux values.

`bands` places one arc or bar per limit region from the key's aux values: `state.warning`
below `lowAlarm` and above `highAlarm`, `state.caution` between alarm and warn, `state.valid`
between `lowWarn` and `highWarn`. A limit the key does not carry draws no region.

The exact dim is fixed by INS9's first corpus cases, not here: it is a look Bill sees on the
bench before it lands (section 10).

## 7. Evaluation (INS9 and INS10)

Evaluation is `(description, options, state, span) -> display list`, pure and deterministic,
with no Qt and no DOM. Both evaluators must give the same display list for every corpus case,
coordinates rounded to 0.01 px.

- **State**, one entry per input:
  `{value, old, bad, fail, annunciate, aux: {Min, Max, lowWarn, lowAlarm, highWarn, highAlarm}}`,
  `value` and each aux a number or null, the flags booleans.
- **Options**: the file's defaults, overlaid with the instance's options; colour tokens resolved
  with `color_tokens.resolve` (the theme can change mutable tokens, never `state.*`).
- **Span**: the canvas is scaled uniformly to fit the instrument's span and centred, keeping the
  aspect ratio. Text `size` is in canvas units and scales with it.
- **Angles** are degrees clockwise from 12 o'clock. A value maps linearly from `range` to the
  sweep or the axis. The pointer's `shape` is in its own frame, pivot at the origin and
  pointing at 12 o'clock; it is rotated about `pivot` (angle scale) or moved along the axis.
- **Ticks and labels** fall on multiples of `every` within the range, ends included. An
  evaluator draws at most 128 per element, whatever the key's range, so a bad aux range cannot
  make a paint unbounded (B5 at run time).
- **Defaults**: no `fill` -- no fill; no `stroke` -- no outline; `width` 1; `anchor` start;
  `decimals` 0.

## 8. The display list

`instrument_display_list.schema.json`: `{format: makerplane.display_list/1, width, height,
ops}`. Ops are back to front, each one key of seven: `circle`, `rect`, `line`, `polyline`,
`polygon`, `arc`, `text`. Coordinates are absolute span pixels; colours are lower-case
`#rrggbb` or `#rrggbbaa`; fonts are resolved family names; there are no tokens, options or
conditions. A boxed text is a `rect` and a `text`. `from` (optional) names the element that
produced the op (`draw[3]`, `on_fail[0]`), for diffing. A painter is a switch over the seven
kinds with no logic: QPainter in pyEfis, SVG nodes in the configurator.

## 9. The conformance corpus

`conformance/instrument_description/manifest.json` lists every file:
- `descriptions`: `{file, expect, why}`, `expect` either `valid` or the one rule id the file
  must be refused under. Each invalid file is `valid/minimal.yaml` with one change, and its
  header comment says what changed.
- `display_lists`: samples the display-list schema must accept or refuse.

The tests hold four things: every valid case is accepted; each invalid case is refused under
its rule and no other; every rule has a case; and **removing a rule turns its cases red**.
That last test strips a rule's semantic check, its schema keywords, its closure vocabulary and
its parse checks, then requires every case pinned to it to come out wrong. A case still refused
under the removed rule names a check the test does not know about.

INS9 adds `cases/`: a description, options, state and span, with the expected display list.
INS10's evaluator runs against this corpus on pyEfis `dev`, and pyEfis CI runs the
configurator's evaluator against it, as `test_refusal.py` does today (AER-6212). A new rule
lands in the corpus first, so the side that lags goes red.

## 10. Versioning and open items

`format` carries the major version. An interpreter refuses any other (B9). An additive change
inside version 1 (a new optional field, a new primitive) lands in the schema and the corpus
together. An older interpreter then refuses a file that uses it, under the closure (B1), which is
the safe direction.

Not decided here:
- **An installer's colour override.** B6 checks the file. An instance can still set a colour
  option to a literal red at screen level, as it can for any shipped widget ("it is their
  airplane", `color_tokens`). Whether INS9 refuses, ignores or allows that is open.
- **The dim**: section 6.
- **A gauge with no readout.** On fail it loses its pointer and its bands dim; the family draws
  no `XXX` of its own. Whether it should is a look question for INS9's bench check.
- **Distribution.** How a `user.*` file reaches a device (study section 10). INS9 and INS10
  confirm the path before building.
- **Families beyond `scale_gauge`** (a tape, lamps, readouts) and static bezel art: version 2
  at the earliest.

## 11. Requirements

- **INSD-VAL-001:** The validator accepts every valid case in the corpus.
- **INSD-VAL-002:** The validator refuses every invalid case under the rule its manifest entry names, and under no other.
- **INSD-VAL-003:** Removing any rule's enforcement turns every corpus case pinned to that rule red.
- **INSD-COR-001:** Every corpus file is listed in the manifest, and the study's worked example is the first case.
- **INSD-COR-002:** Every rule id has at least one invalid corpus case.
- **INSD-SCH-001:** Both schemas use only keywords the validator's schema pass implements.
- **INSD-SCH-002:** Where the jsonschema package is installed, both schemas are valid JSON Schema 2020-12 and agree with the schema pass on every corpus file.
- **INSD-DL-001:** The display-list schema accepts and refuses its corpus samples.
- **INSD-CLI-001:** The CLI exits 0 on valid files and 1 on a refused file, naming the rule.
