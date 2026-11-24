# CERT1g evidence: the round dials follow the tapes' flag convention (AER-6399)

Columns left to right in both images: `live`, `bad`, `old`, `fail`. In each
column the round `Airspeed` dial (IAS 112) is above the round `Altimeter` dial
(ALT 4520). Each dial is 240x240 on a black panel, at 1:1.

| File | Code |
|------|------|
| `before.png` | `dev` at `de10421e`: `bad` and `old` both draw grey, and `old` keeps its frozen needle. Only `fail` shows the XXX |
| `after.png` | this branch: `bad` draws needle and markings in the tapes' suspect amber; `old` draws the red XXX with no needle, the same as `fail` |

The airspeed dial's coloured arcs keep their colours under `bad`, as the tapes
keep their bands under the amber frame.

Only the `bad` and `old` columns changed. The `live` and `fail` columns of the
two images are pixel-identical (compared with `QImage ==` on each column crop).

## Regenerate

From the repo root, once on the branch and once on `dev` (copy the script over):

```bash
OUT=/tmp/cert1g QT_QPA_PLATFORM=offscreen PYTHONPATH=src \
  python3 -m pytest -p no:cacheprovider --no-cov -q \
  docs/aer-6399-evidence/render_dials.py
```

It writes `dials.png` to `$OUT`. The renders here were made in the agent
sandbox with DejaVu fonts via fontconfig, not on bench hardware.
