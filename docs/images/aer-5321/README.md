# AER-5321 (BACKLOG CERT2e): EMS bar strip, before and after

The first `ganged_vertical_bar_gauge` block of the stock `EMS` screen
(`src/pyefis/config/screens/ems.yaml`), with its `preferences:` references
resolved from `preferences.yaml`, rendered offscreen through screenbuilder at
640x300 over the in-memory mock FIX database.

- `ems_bars_before.png`: `dev` at 4fd2af42. Two MAP bars (BAR22, BAR26, both
  `MAP1`) and the `CAT` bar labelled "IAT".
- `ems_bars_after.png`: this branch. One MAP bar, and the bar labelled "CAT".

Seeded values: `MAP1` 24.1, `CAT` 21, `TACH1` 2350, `THR1` 65. The RPM and
TPS readouts show what the mock database's ranges make of those, so compare
the labels and the bar count, not those two numbers.

`ems-portrait.yaml` and `ems-left-buttons.yaml` carry the same block and the
same change; they are not rendered separately.

## Regenerate

From the repo root, with an offscreen-capable Qt:

```bash
git worktree add /tmp/dev-before 4fd2af42
QT_QPA_PLATFORM=offscreen python3 docs/images/aer-5321/render_bars.py \
    /tmp/dev-before docs/images/aer-5321/ems_bars_before.png
QT_QPA_PLATFORM=offscreen python3 docs/images/aer-5321/render_bars.py \
    "$PWD" docs/images/aer-5321/ems_bars_after.png
```

The first argument is the repo tree whose configs and code are rendered.
