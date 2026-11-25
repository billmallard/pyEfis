# Adding (or changing) an instrument

A step-by-step for getting a new instrument — or a new option on an existing one
— into pyEfis **and** the web configurator, faithfully and without drift. Read
[instrument_spec.md](instrument_spec.md) first for the model; this is the recipe.

The golden rule: **define the instrument once** in the registry record, let the
schema and (by hand, but tracked) the configurator twin derive from it, and let
the test gate keep them honest.

---

## Where things live

| Thing | File |
|------|------|
| Descriptor types (`InstrumentSpec`, `Prop`, `FixValue`) | `src/pyefis/screens/instrument_spec.py` |
| The registry + builders | `src/pyefis/screens/screenbuilder_factory.py` |
| Option application | `src/pyefis/screens/screenbuilder_options.py` |
| Schema exporter | `src/pyefis/editor/schema.py` |
| Test gate | `tests/editor/test_registry.py` |
| Reference render (real widget) | `tools/render_instrument.py` |
| Asset bundle builder | `tools/build_editor_assets.py` |
| The configurator twin | `makerplane-data/configurator/public/editor.html` (`build*`) |

---

## Step 1 — the widget

Either reuse an existing widget under `src/pyefis/instruments/<x>/` or add one.
Conventions every instrument follows:

- It is a `QWidget` / `QGraphicsView` that consumes one or more FIX keys via
  `fix.db.get_item(KEY)` and the `valueChanged` / `oldChanged` / `badChanged` /
  `failChanged` signals.
- By default it renders **fail** as a red "XXX" and **old/bad** greyed. A
  widget spec under `docs/*_widget_spec.md` can override that on purpose, and
  where one does, the spec wins: the airspeed and altimeter tapes treat old as
  fail and show bad in amber (CERT1b/c, `airspeed_widget_spec.md`), the heading
  readout shows old/bad as blank amber (`heading_widget_spec.md`), and the HSI
  treats old as fail (`hsi_widget_spec.md`, HSI-ANN-001). Read the spec for the
  widget you are touching before you apply the default.
- **Each configurable knob is a plain attribute** set in `__init__` to its
  default (e.g. `self.show_tas = True`). The property `name` in the record maps
  to that attribute, and its `default` must equal the attribute's initial value
  (the defaults rule).
- Decide each knob's **category** (see the spec): panel option (category 1) vs
  FIX value (category 2). Do not add an editor option for something that is
  really aircraft data in fix-gateway.

Sanity-check the real look (this is the twin's target):

```bash
PYTHONPATH="<pylib>;src" python tools/render_instrument.py <type> --safe -o /tmp/<type>.png
```

## Step 2 — the registry record

Add (or extend) an `_register(InstrumentSpec(...))` in
`screenbuilder_factory.py`. Bind the `builder` here (the only Qt-aware part).
Declare category-1 `properties`, document category-2 `fix_values`, and give
category-3 `preview` sample data so the twin can draw something realistic.

The builder names the widget class through the lazy instrument table, never
by importing its package (CERT12c, `briefs/primary_flight_core.md` R2b). Add
one line to `INSTRUMENTS` in `src/pyefis/screens/instrument_table.py`
(class name to package), then call `instrument("ClassName")(...)`. The
package is imported only when a screen places the instrument, so a PFD never
loads the map. `tests/screens/test_instrument_table.py` fails if the factory
imports an instrument package directly.

```python
_register(InstrumentSpec(
    type="arc_gauge",
    label="Arc Gauge",
    category="gauge",
    builder=(lambda screen, config, font_percent=None, font_family=None,
             replace=None: instrument("ArcGauge")(
                 screen, min_size=False, font_family=font_family)),
    keep_aspect=True,
    properties=[
        Prop("dbkey", "fixkey", default="", label="FIX key",
             apply="setter:setDbkey"),
        Prop("name", "string", default="", label="Name"),
        Prop("decimal_places", "integer", default=1, label="Decimal places"),
        Prop("show_units", "boolean", default=False, label="Show units"),
        Prop("segments", "integer", default=0, label="Segments"),
        Prop("name_location", "enum", default="top", enum=["top", "right"]),
    ],
    fix_values=[                      # category 2 -- fix-gateway, NOT the editor
        FixValue("Min", source="min", label="Range minimum"),
        FixValue("Max", source="max", label="Range maximum"),
        FixValue("lowWarn", source="aux", label="Low warning (yellow)"),
        FixValue("highWarn", source="aux", label="High warning (yellow)"),
        FixValue("lowAlarm", source="aux", label="Low alarm (red)"),
        FixValue("highAlarm", source="aux", label="High alarm (red)"),
    ],
    preview={"value": "2350", "fill": 0.72, "green_to": 0.62, "yellow_to": 0.83},
))
```

Rules of thumb:
- Every `Prop` has a `default` matching the widget's `__init__` default (§5 of
  the spec).
- `apply`: plain attributes use `attr` (the default); a gauge key uses
  `setter:setDbkey`; unit-switching / encoder / nested `svs` are `special`.
- Only declare a property you intend the twin to honor (the fidelity rule).
- Don't redeclare `font_family` / `font_percent` — they are common options.
- A runtime control key (`bindable=Binding(...)`) is restated in the widget's
  `_live_binding_specs()`. The gate holds the two together field by field
  (semantics, key option, ladder option, enum), so change both in one commit.
- A generic type with a `dbkey` `fixkey` prop and no default gets a demo key in
  `tools/render_instrument.py` (`_NEEDS_DBKEY`, derived from the records), so its
  palette thumbnail draws a value. Nothing to add there by hand.

## Step 3 — keep the curated tables empty

Every instrument is migrated: the curated dicts in `editor/schema.py`
(`_CATEGORIES`, `_LABELS`, `_OPTIONS`, `_REQUIRED_OPTIONS`, `_KEEP_ASPECT`,
`_SVS_CAPABLE`, `_NOT_OFFSCREEN_RENDERABLE`) and the `INSTRUMENT_FACTORIES` /
`INSTRUMENT_DEFAULTS` / `INSTRUMENT_DEFAULT_OPTIONS` literals in
`screenbuilder_factory.py` are empty, and the fold-back fills
`INSTRUMENT_FACTORIES` and `INSTRUMENT_DEFAULTS` from the records. Do not add a type to them; put it in its record. The gate
fails on a type defined in both places.

## Step 4 — run the gate

```bash
PYTHONPATH="<pylib>;src" python -m pytest tests/editor --no-cov -q
```

It verifies the record is a real factory type, isn't double-defined, matches the
exported schema, that the **real widget exposes every `attr` property** you
declared, and that its live bindings match the record's `bindable` props. Fix
anything red before moving on.

## Step 5 — the configurator twin (fidelity)

In `makerplane-data/configurator/public/editor.html`, the `build*(inst)` function
for your type draws the preview. It must **match the real widget** (render it
first in Step 1) and read from the schema, not hard-code:

- read options from `inst.options`;
- read category-3 sample data from the schema:
  `const meta = state.schema.instruments[inst.type] || {}; const pv = meta.preview || {};`
- honor **every** category-1 option you exposed (a boolean toggle must visibly
  toggle; an enum must switch the drawing). If the twin can't yet honor an
  option, don't expose it in the record.

For a brand-new type also add: a `renderCanvas()` dispatch branch, a palette
entry is automatic (schema-driven), and a palette SVG is generated in Step 6.
If the type carries an `aircraft_ref` prop (the gauges' `tank`), add it to
`AIRCRAFT_REFS` in `configurator/public/aircraft_refs.js` and regenerate
`configurator/test/fixtures/aircraft_refs_pyefis.json`: that table is still
kept by hand, and nothing fails if you miss it.

GL/SVS widgets (`virtual_vfr`) can't render in a browser; the twin uses a
captured `svs/<scene>.webp` instead (see the configurator README).

## Step 6 — regenerate + deploy assets

**Normally automatic.** `.github/workflows/editor-assets.yml` rebuilds
`schema.json`, `groups.json` and every `palette/<type>.svg` that renders for real
offscreen, and uploads them to the branch's R2 prefix on a `dev`/`qa`/`master`
push that touches the editor, the factory or `src/pyefis/instruments/`. Types the
offscreen path cannot draw (GL/SVS/embedded-app) build as placeholders and are
never uploaded by CI. A type whose record says it builds standalone and renders
offscreen, and that is not on `render_instrument.py`'s placeholder list
(`_CONFIG_DRIVEN`), must render: if it placeholders, `build_editor_assets.py`
exits 1 and the job goes red. The manual route below is for the placeholder
types, or for a local check:

```bash
# pyEfis: rebuild schema.json (+ groups.json + palette/<type>.svg)
PYTHONPATH="<pylib>;src" python tools/build_editor_assets.py --out work/editor_assets

# makerplane-data/configurator (wrangler OAuth already set up on the dev machine):
npx wrangler r2 object put makerplane-configs/assets/editor/schema.json \
    --file=../../pyEfis/work/editor_assets/schema.json \
    --content-type application/json --remote
#   ...repeat for groups.json and any new palette/<type>.svg ...
npm run deploy        # publishes public/editor.html
```

Assets are **not committed** to `makerplane-data` (they live in R2, sourced from
pyEfis). After deploy, re-fetch a couple of times when verifying with `curl` —
the edge cache serves the previous file for a few seconds.

## Step 7 — commit (two repos move together)

- pyEfis (branch from `dev`, PR to `dev`): the widget + record + tests.
- makerplane-data (branch from `dev`, PR to `dev`): the twin change, plus
  `aircraft_refs.js` and its fixture if the type carries an `aircraft_ref` prop.

Focused commit per change; note both SHAs when an editor change spans repos. No
emojis in commit messages. Do not push to upstream `makerplane/*` without
explicit authorisation.

---

## Checklist

- [ ] Widget renders fail/old/bad correctly; each knob is an `__init__` attribute.
- [ ] Each knob categorised (1 panel option vs 2 FIX value) — correctly.
- [ ] `InstrumentSpec` registered; `properties` defaults match widget defaults.
- [ ] `fix_values` document the category-2 inputs; `preview` lets the twin draw.
- [ ] Nothing added to the curated dicts or the legacy literals.
- [ ] Bindable props and `_live_binding_specs()` agree (the gate checks).
- [ ] An `aircraft_ref` prop is in `aircraft_refs.js` and its fixture.
- [ ] `pytest tests/editor` green (the gate).
- [ ] If it writes a FIX key: declared in fix-gateway's `writers.yaml` and the pin
      bumped, so `python tools/check_fix_writers.py` passes ([key_writers.md](key_writers.md)).
- [ ] Twin `build*` matches the real widget and honors every exposed option.
- [ ] Assets regenerated + uploaded to R2; Worker deployed; verified at origin.
- [ ] Committed in both repos with focused messages.

---

## Worked example: a new "oil pressure arc" is just config

Most "new instruments" are an existing widget with different FIX wiring and
options — no new widget code. An oil-pressure gauge is just an `arc_gauge` placed
in the editor with `dbkey: OILP`, `name: "OIL"`, and the warn/alarm bands set in
fix-gateway (category 2). Nothing to add here. Reach for a **new widget +
record** only when the *visual form* is genuinely new (a new dial face, a new
tape style); then follow Steps 1-7.
