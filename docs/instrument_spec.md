# Instrument Definition Specification

**Status:** active (pilot). **Audience:** anyone adding or changing a pyEfis
instrument or its configurator preview. **Companion:** a step-by-step walkthrough
lives in [adding_an_instrument.md](adding_an_instrument.md).

pyEfis instruments are consumed by **three independent "mirrors"** that used to
drift apart because the same facts were hand-maintained in each:

1. **the screen-builder** — constructs the widget and applies its options
   ([src/pyefis/screens/screenbuilder_factory.py](../src/pyefis/screens/screenbuilder_factory.py),
   [screenbuilder_options.py](../src/pyefis/screens/screenbuilder_options.py));
2. **the editor schema exporter** — emits `schema.json` for the web configurator
   ([src/pyefis/editor/schema.py](../src/pyefis/editor/schema.py));
3. **the configurator "twin"** — draws the live preview in the browser
   (`configurator/public/editor.html` in the `makerplane-data` repo).

This spec defines **one source of truth** they all derive from: a declarative
`InstrumentSpec` record per instrument type. Drift becomes impossible to merge
because a test gate ([tests/editor/test_registry.py](../tests/editor/test_registry.py))
checks the record against the factory, the schema, and the real widget.

---

## 1. The four kinds of instrument input

The central idea. An instrument has **four distinct kinds of input**, and they
must never be conflated:

| # | Kind | Source of truth | In the panel editor? | Drives the twin? | Examples |
|---|------|-----------------|----------------------|------------------|----------|
| 1 | **Config properties** | the registry record (`properties`) | **yes** — the inspector panel | yes | `aircraft_symbol`, `show_tas`, `segments`, `name_location`, `decimal_places` |
| 2 | **FIX-database values** | fix-gateway (item `min`/`max`/`aux`) — described in the record (`fix_values`) | **no** (issue #64) | only as preview | V-speeds (Vne…), gauge warn/alarm bands, range |
| 3 | **Preview hints** | the registry record (`preview`) | no — never written to a device | yes — representative sample data | sample needle value, sample bands, sample pitch/roll |
| 4 | **Container slots** | the registry record (`containers`, list of `ContainerSlot`) | **yes** — a drop-target, not a properties field | yes — recursively | `tab_section`'s `tabs` |

Why it matters:
- **Category 1** is panel *layout/appearance/feature* configuration. It is what
  the configurator edits and writes into the screen YAML.
- **Category 2** is *aircraft/runtime* data that lives in the FIX database
  (fix-gateway), not the panel. V-speeds and gauge warn/alarm bands belong here,
  **not** in the panel editor (issue #64). They are *described* in the record so
  a future **web FIX-database editor** has a contract to build on; the panel
  editor only reads them (as preview).
- **Category 3** lets the browser twin draw a realistic instrument with no live
  FIX connection. It is sample data only.
- **Category 4** is for a property whose *value is a subtree* -- an ordered
  list of named, instrument-holding tabs -- rather than a leaf value.
  `Prop`/`PROP_KINDS` is deliberately scalar-only (`Prop.__post_init__`
  assumes a scalar `default` and, for `enum`, a flat list), so this needed its
  own category rather than a `Prop` special case (pyEfis#131). `tab_section`
  is the only category-4 instrument today.

When you add a configurable knob, decide which category it is **first**. If it is
something a pilot/builder sets for the panel → category 1. If it is aircraft data
read at runtime → category 2 (FIX), not an editor option.

---

## 2. The record: `InstrumentSpec`

Defined in [src/pyefis/screens/instrument_spec.py](../src/pyefis/screens/instrument_spec.py)
(intentionally **Qt-free**, so the schema exports and the contract validates in
CI without a display). One record per instrument type:

```python
InstrumentSpec(
    type:        str,            # registry key == YAML "type", e.g. "arc_gauge"
    label:       str,            # human label (palette + inspector)
    category:    str,            # palette grouping, e.g. "gauge"
    builder:     callable,       # the factory callable, bound in the factory module
    dbkeys:      list[str] = [], # default FIX keys the widget consumes
    properties:  list[Prop] = [],       # category 1
    fix_values:  list[FixValue] = [],   # category 2
    preview:     dict = {},             # category 3 (twin sample data)
    containers:  list[ContainerSlot] = [],  # category 4
    keep_aspect:          bool = False, # round/square -> editor letterboxes it
    offscreen_renderable: bool = True,  # False for GL/compositor widgets
    svs_capable:          bool = False, # can host the GL SVS overlay
)
```

### `Prop` — one category-1 property

```python
Prop(
    name:     str,    # YAML option key AND the widget attribute it maps to
    kind:     str,    # string|number|integer|boolean|enum|color|fixkey
    default:  Any = None,
    label:    str = "",
    enum:     list | None = None,   # required when kind="enum"
    minimum / maximum / step: float | None = None,
    required: bool = False,
    help:     str = "",
    apply:    str = "attr",  # how it reaches the widget (see §6)
)
```

`name` is **both** the YAML option key and the widget attribute, so a property
maps 1:1 to widget state. `kind` selects the editor input control.

### `FixValue` — one category-2 value (documentation + future FIX editor)

```python
FixValue(
    name:   str,            # e.g. "Vne" or "highWarn"
    source: str = "aux",    # aux | min | max  -- where it lives on the FIX item
    label:  str = "",
    dbkey:  str = "",       # which FIX key carries it ("" = the primary key)
    units:  str = "",
    help:   str = "",
)
```

The panel editor does not set these; they are aircraft data in fix-gateway.

### `ContainerSlot` — one category-4 container slot

```python
ContainerSlot(
    name:  str,       # the YAML key holding the subtree, e.g. "tabs"
    label: str = "",
    help:  str = "",
)
```

A container slot describes "this instrument has a property whose value is a
list of named, instrument-holding tabs," not a leaf value -- there is no
`default`, because the value is a subtree the panel editor builds by dragging
instruments into a drop-target, not a scalar the editor seeds. The exporter
emits a `containers: [...]` block per instrument (parallel to, and separate
from, its flat `options:` block) so the editor knows to render a drop-target
instead of a properties field. See `tab_section` (`docs/screenbuilder.md`) for
the one instrument that uses this today, including the `tabs:` wire shape.

---

## 3. How the three mirrors derive from the record

```
                     screenbuilder_factory.REGISTRY  (the single source of truth)
                                     │
        ┌────────────────────────────┼────────────────────────────────┐
        ▼                            ▼                                 ▼
  build the widget            editor/schema.py                  configurator twin
  + apply options             build_schema() ->                 build*(inst) reads
  (factory builder +          schema.json                       schema options +
   screenbuilder_options)     (R2 -> browser)                   preview, never
                                                                hard-codes
```

- **Factory:** `INSTRUMENT_FACTORIES` / `INSTRUMENT_DEFAULTS` are *folded back*
  from `REGISTRY` (see the loop at the bottom of `screenbuilder_factory.py`), so
  migrated instruments are sourced from their record while legacy consumers keep
  working. As instruments migrate, the literal dicts shrink toward empty.
- **Schema:** `build_schema()` uses `_entry_from_spec()` for any type in
  `REGISTRY`, else `_entry_from_curation()` (the transitional curated metadata).
  Every entry carries `options`, `dbkeys`, `required_options`, flags, plus
  `preview`, `fix_values`, and `containers`. `SCHEMA_VERSION` is **3**.
- **Twin:** each `build*(inst)` in `editor.html` reads `inst.options` and the
  instrument's `preview` from the loaded schema. It must not invent appearance.

---

## 4. The fidelity rule (HARD RULE)

**The configurator twin must reproduce what the pyEfis widget actually renders,
as closely as the technology reasonably allows. No freelancing on instrument
appearance in the configurator.**

- pyEfis is the single source of truth for *look*. The twin tracks it; it never
  invents a different style. The target appearance is *whatever pyEfis draws*.
- When a widget's look changes, its twin changes with it (same commit, two repos
  — pyEfis for the widget, `makerplane-data` for the twin).
- **Only expose a category-1 property in the editor if the twin honors it.** An
  option that changes the device but not the preview is a fidelity gap; either
  make the twin honor it or don't expose it yet.
- Build order: render the **real** widget first
  (`python tools/render_instrument.py <type> --safe -o out.png`), then match it.
- pyEfis visuals are themselves a work in progress toward a category-leading
  catalog. "Fidelity" means the twin always tracks the current widget, whatever
  it looks like.

---

## 5. Defaults rule

**Every category-1 `Prop` declares a `default`, and that default must match the
widget's own constructor default.** The record's default is the value the editor
seeds and the value the widget uses when the option is absent — they cannot
disagree. The test gate checks this for `apply="attr"` properties whose widget
attribute is non-`None`. (Free-text keys like `dbkey`/`name` where the widget
default is `None`/empty are exempt.)

This gives every instrument a complete, single-sourced set of starting values —
the basis for the editor's "new instrument" defaults and the planned FIX/property
editor.

---

## 6. Property `apply` — how an option reaches the widget

`screenbuilder_options.apply_options()` runs after the widget is built. `apply`
documents (and, for migrated types, drives) how each option is applied:

| `apply` | Meaning |
|---------|---------|
| `attr` (default) | `setattr(widget, name, value)` — the widget exposes `name` as an attribute |
| `setter:<method>` | `widget.<method>(value)` — e.g. `setter:setDbkey` for gauges |
| `special` | handled explicitly in `apply_options` (unit switching, encoder order, nested `svs` config) |

The gate's widget-attribute check only applies to `attr` props (a `setattr` to a
name the widget never reads is a silent no-op — the check fails it).

---

## 7. Property kinds and editor controls

| `kind` | Editor control | Notes |
|--------|----------------|-------|
| `string` | text input | |
| `number` | number input | `min`/`max`/`step` honored |
| `integer` | number input (int) | |
| `boolean` | checkbox | |
| `enum` | select | `enum=[...]` required; `default` must be in it |
| `color` | colour picker | hex `#rrggbb` |
| `fixkey` | text input (FIX key) | becomes a key-picker once the FIX editor exists |

Common options (`font_family`, `font_percent`) are added to every instrument by
the schema's `common_options` block — do not redeclare them per record.

---

## 8. Flags

- `keep_aspect` — round/square instruments; the editor letterboxes them
  (`object-fit: contain`) instead of stretching. Tapes/bars/text stretch.
- `offscreen_renderable` — `False` for GL/compositor widgets (SVS `virtual_vfr`,
  `weston`) that can't produce a server-side thumbnail; the render service uses a
  placeholder instead.
- `svs_capable` — the instrument can host the GL Synthetic Vision overlay via an
  `svs:` option (attitude / virtual VFR).

---

## 9. The test gate

[tests/editor/test_registry.py](../tests/editor/test_registry.py) makes drift
unmergeable:

- every `REGISTRY` type is a real, buildable factory type, sourced from the
  record;
- a migrated type is **not** also defined in the curated metadata (no double
  definition);
- the exported schema for a migrated type equals its record (label, category,
  dbkeys, options, enums, required, flags, preview);
- the **real widget**, constructed via its builder, exposes every `apply="attr"`
  property the record declares (a renamed/misspelt property fails CI instead of
  silently doing nothing in the cockpit).

Run it: `PYTHONPATH="<pylib>;src" python -m pytest tests/editor --no-cov -q`.

---

## 10. Asset pipeline + deploy

The browser editor reads its data from R2 (it runs no Qt). After a record or
twin change, regenerate and publish:

```bash
# in pyEfis: regenerate schema.json (+ groups.json + palette SVGs)
python tools/build_editor_assets.py --out work/editor_assets

# in makerplane-data/configurator (has wrangler OAuth): upload schema.json
npx wrangler r2 object put makerplane-configs/assets/editor/schema.json \
    --file=../../pyEfis/work/editor_assets/schema.json \
    --content-type application/json --remote
# ...and the Worker (serves public/editor.html):
npm run deploy
```

`schema.json` and palette assets are **not committed** to `makerplane-data` —
they live in R2, generated from pyEfis (the source of truth). Note the edge
cache: re-fetch a couple of times before trusting a "stale" `curl`.

---

## 11. Migration status

The registry coexists with the legacy curated metadata so instruments migrate
one at a time ("pilot, then expand").

- **Migrated** (sourced from `REGISTRY`): `atitude_indicator`, `arc_gauge`,
  `airspeed_tape`, `vsi_dial`.
- **Curated fallback** (still in `editor/schema.py` `_CATEGORIES`/`_LABELS`/
  `_OPTIONS`/…): everything else.

To migrate one, follow [adding_an_instrument.md](adding_an_instrument.md): move
its entries out of the curated dicts into a record, update the twin, run the gate.

### Things the migration has already fixed
- `atitude_indicator`: the editor offered `aircraft_symbol: "delta"` (the widget
  never rendered it) and hid `"garmin"` (it does). The record's enum is now
  `["classic","garmin"]`, gate-enforced.
- `airspeed_tape`: the editor offered an editable `dbkey` that did nothing (the
  widget is hard-wired to `IAS`). Dropped.
