# CERT1c evidence: a suspect (bad) readout shows its value in amber (AER-5893)

Left to right in every image: `Airspeed_Tape` (IAS 112), `Altimeter_Tape`
(ALT 4520), `Alt_Trend_Tape` (VS 500), 100x400 each on a black panel, scaled 2x
nearest-neighbour.

| File | State | Code |
|------|-------|------|
| `before_live.png` | all keys valid | `dev` at `ba86f94a` (byte-identical to the branch's live render) |
| `before_bad.png` | IAS, ALT, VS flagged `bad` | `dev` at `ba86f94a`: amber frames (CERT1b), readout boxes empty |
| `after_bad.png` | IAS, ALT, VS flagged `bad` | this branch: amber frames, the value in amber in each readout |

The live render is unchanged: the branch's `live.png` has the same md5 as
`before_live.png` (`858a581b9a252de5d436b325857c99c5`), so only a `bad` readout
looks different.

## Regenerate

From the repo root, once on the branch and once on `dev` (copy the script over):

```bash
OUT=/tmp/cert1c QT_QPA_PLATFORM=offscreen PYTHONPATH=src \
  python3 -m pytest -p no:cacheprovider --no-cov -q \
  docs/aer-5893-evidence/render_readouts.py
```

It writes `live.png` and `bad.png` to `$OUT`. The renders here were made in the
agent sandbox with DejaVu fonts via fontconfig, not on bench hardware.
