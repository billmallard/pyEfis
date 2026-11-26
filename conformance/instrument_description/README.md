# Conformance corpus -- `makerplane.instrument/1`

The cases both instrument-description evaluators are held to (pyEfis INS9, the
configurator INS10). The contract is `docs/instrument_description_spec.md`; the schemas are
`src/pyefis/editor/instrument_description.schema.json` and
`src/pyefis/editor/instrument_display_list.schema.json`.

- `manifest.json` lists every file and what it must do: `valid`, or the one rule id it must
  be refused under. The tests refuse a file that is not listed.
- `valid/` -- accepted. `oil_pressure_dial.yaml` is the study's worked example and the first
  case. `limits.yaml` and `max_elements.yaml` sit exactly at each bound.
- `invalid/` -- each is `valid/minimal.yaml` with one change, named in its header comment and
  prefixed by its rule id.
- `display_list/` -- samples for the display-list schema.
- `cases/` (INS9) -- a description, options, state and span with the expected display list.

Check a file by hand:

```bash
PYTHONPATH=src python -m pyefis.editor.instrument_description conformance/instrument_description/valid/*.yaml
```

Run the corpus and the mutation check:

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=src python -m pytest tests/editor/test_instrument_description.py --no-cov -q
```

Add a rule's case here before the rule's code: the side that lags goes red.
