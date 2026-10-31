# G49 evidence: alert at the MAP auto-suspend (pyEfis #330, AER-4323)

The FPL page at 800x480, painted by the real `FlightPlan` widget against an
in-process FIX database (approach plan AP0, AP1 IAF, AP2 FAF, AP3 MAP,
AP4 MAHP; `FPLSTATE = 3` throughout).

| File | Bus state | What it shows |
|------|-----------|---------------|
| `map_auto_susp.png` | `FPLACTLEG = 4` (MAP), `FPLTF = 2` (FROM) | The engine's auto-suspend past the MAP: "SUSP AT MAP" banner with a "Fly the missed" button above the soft keys |
| `map_auto_susp_menu.png` | same, MENU open | The menu item reads "Fly the missed"; the banner is dimmed and not tappable under the overlay |
| `pilot_susp_final.png` | `FPLACTLEG = 4`, `FPLTF = 1` (TO) | A pilot SUSP on final, short of the MAP: no banner, the menu keeps "Resume" |

Regenerate from the repo root (`FONT_FILE` only if Qt has no system fonts):

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. FONT_FILE=/path/to/DejaVuSans.ttf \
    python -m pytest --no-cov -p no:cacheprovider docs/images/g49/render_g49.py
```
