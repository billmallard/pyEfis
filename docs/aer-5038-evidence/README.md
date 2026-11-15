# AER-5038 / pyEfis #399 evidence: vertical bar normalize-mode indicator

Each image is one bare `VerticalBar` (EGT-style, 1000-1600 range,
`normalize_range = 400`) rendered twice: left in Normal mode, right after
`setNormalizeMode(True)`. Scaled 3x nearest-neighbour.

- `normalize_before.png` -- code before the fix: the Normalize indicator
  stays white; only its outline changes from dark grey to grey.
- `normalize_after.png` -- with the fix: the indicator fills with
  `normalizePenColor` (blue).

The text glyphs are empty boxes because the render sandbox had no fonts
installed; the light-grey background is the bare widget with no parent
screen. Neither affects the indicator.

Regenerate from the repo root:

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=src python docs/aer-5038-evidence/render.py
git checkout d9028b7e^ -- src/pyefis/instruments/gauges/verticalBar.py
OUT=normalize_before.png QT_QPA_PLATFORM=offscreen PYTHONPATH=src python docs/aer-5038-evidence/render.py
git checkout HEAD -- src/pyefis/instruments/gauges/verticalBar.py
```
