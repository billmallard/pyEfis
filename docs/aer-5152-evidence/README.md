# AER-5152 -- safety advisories on the About/System screen (BACKLOG L5)

The About/System screen at 1024 x 600 (the Pi 5 panel), rendered offscreen
from the `AboutSystem` widget (a plain QWidget, so these are the pixels the
screen draws). Each case feeds the widget a `status.json` with an
`advisories` block in the shape documented by makerplane-data
`docs/advisories.md` (PR #172), and pins `pyefis.__version__` to 2.2.1.
Fonts: DejaVu Sans (the sandbox has no DejaVu Sans Condensed).

| Image | What it shows |
|---|---|
| `about_empty.png` | channel on, `active: []`: nothing at all -- the screen is the pre-L5 About screen |
| `about_applicable.png` | a WARNING whose only target is `software: pyefis` 2.2.0 to 2.2.2, which the updater wrote as `unknown` and pyEfis settled as applying to 2.2.1; and a CAUTION the updater matched on a pack cycle |
| `about_off.png` | channel off (`{"enabled": false}`): one quiet grey line |

Each image has a `.json` sidecar (docs/evidence.md) naming the commit that drew it.

## Regenerate

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=src:tools \
    python3 docs/aer-5152-evidence/render_about_advisories.py docs/aer-5152-evidence
```
