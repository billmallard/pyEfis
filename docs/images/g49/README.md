# G49 evidence: alert at the MAP auto-suspend (pyEfis #330, AER-4323)

The FPL page at 800x480, painted by the real `FlightPlan` widget against an
in-process FIX database (approach plan AP0, AP1 IAF, AP2 FAF, AP3 MAP,
AP4 MAHP; `FPLSTATE = 3` throughout).

The banner and label follow the engine's `FPLSUSPMAP` (fix-gateway #91),
not the other keys.

| File | Bus state | What it shows |
|------|-----------|---------------|
| `map_auto_susp.png` | `FPLSUSPMAP = 1`, `FPLACTLEG = 4` (MAP), `FPLTF = 2` (FROM) | The engine's auto-suspend past the MAP: "SUSP AT MAP" banner with a "Fly the missed" button above the soft keys |
| `map_auto_susp_menu.png` | same, MENU open | The menu item reads "Fly the missed"; the banner is dimmed and not tappable under the overlay |
| `pilot_susp_final.png` | `FPLSUSPMAP = 0`, `FPLACTLEG = 4`, `FPLTF = 1` (TO) | A pilot SUSP on final, short of the MAP: no banner, the menu keeps "Resume" |
| `pilot_susp_past_map.png` | `FPLSUSPMAP = 0`, `FPLACTLEG = 4`, `FPLTF = 2` (FROM) | A pilot SUSP held past the MAP, where RESUME only un-suspends: no banner, "Resume". Same position keys as the auto-suspend; only the engine's key tells them apart |

Regenerate from the repo root (`FONT_FILE` only if Qt has no system fonts):

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. FONT_FILE=/path/to/DejaVuSans.ttf \
    python -m pytest --no-cov -p no:cacheprovider docs/images/g49/render_g49.py
```
