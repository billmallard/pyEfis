# INS6 (AER-6684): flag-state render comparison

INS6 moves ten hand-rolled "any flag, repaint" subscriptions onto
`helpers.bugs.BugBinding.qualityChanged`. The definition of done is no
behaviour change. `flag_render_compare.py` checks that for every migrated
widget:

| Widget | Keys walked |
|---|---|
| `airspeed.Airspeed` | IAS |
| `airspeed.Airspeed_Tape` | IAS, TAS |
| `airspeed.Airspeed_Box` | TAS, GS, IAS |
| `altimeter.Altimeter` | ALT |
| `altimeter.Altimeter_Tape` | ALT, BARO |
| `vsi.VSI_Dial`, `vsi.VSI_PFD` | VS |
| `tc.TurnCoordinator` | ALAT, ROT |
| `nav_status.NavStatus` | the seven NAV_KEYS |

Each key goes through old, bad and fail (on, then off), old+bad together,
a clear, and annunciate on and off: 200 steps in all. After each step the
harness records the paint events delivered synchronously (a `repaint()` slot),
the paint events delivered by the next `processEvents` (an `update()` slot),
and an md5 of `grab()`.

- `dev.json`: `dev` at `3bd405d4` with only the harness added.
- `ins6.json`: the INS6 branch.

The two files are byte-identical (`cmp` exits 0). The same paint counts in the
same phase also show that no `repaint()` became an `update()` or the other way
round.

## The harness catches a broken migration

Each mutant below drops one migrated connection. Every one changed the output:

| Mutant (connection removed) | Steps that differ |
|---|---|
| `VSI_Dial` `qualityChanged -> repaint` | 8 |
| `NavStatus` `qualityChanged -> _changed` | 56 |
| `TurnCoordinator` ROT `qualityChanged -> quality_change` | 8 |
| `Airspeed_Box` `qualityChanged -> _on_flag` | 24 |
| `Altimeter_Tape` BARO `qualityChanged -> _baro_repaint` | 8 |

## Regenerate

From the repo root, with the Qt offscreen platform:

```bash
export QT_QPA_PLATFORM=offscreen PYTHONPATH=src
git worktree add /tmp/ins6-base 3bd405d4
cp docs/aer-6684-evidence/flag_render_compare.py /tmp/ins6-base/docs/
(cd /tmp/ins6-base && PYTHONPATH=src INS6_OUT=/tmp/dev.json \
  python3 -m pytest docs/flag_render_compare.py --no-cov -q)
INS6_OUT=/tmp/ins6.json \
  python3 -m pytest docs/aer-6684-evidence/flag_render_compare.py --no-cov -q
cmp /tmp/dev.json /tmp/ins6.json && echo identical
```

The file name matches no pytest pattern, so a normal run does not collect it;
pass the path explicitly. The md5s depend on the fonts installed, so compare
two runs on the same machine. Do not compare against the committed files.
