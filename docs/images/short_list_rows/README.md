# One-row list renders (pyEfis #400, AER-5039)

Offscreen renders of the Catalog page with one stored route and the Direct-To
FPL tab with one waypoint, 672x1080 pane, Beelink display metrics (1920x1080,
21.5 in). Left: `dev` before the fix. Right: with the fix.

- `catalog_one_route_before_after.png`
- `dto_fpl_one_waypoint_before_after.png`

These are QPainter renders of the widget's own paint methods, not bench
captures; text uses the sandbox's fonts.

## Regenerate

Save the script below as `tests/instruments/flight_plan/_render_short_list_tmp.py`
(it uses the `fix` and `qtbot` fixtures), then run once per tree:

```bash
OUT=docs/images/short_list_rows TAG=after QT_QPA_PLATFORM=offscreen PYTHONPATH=src \
  python -m pytest tests/instruments/flight_plan/_render_short_list_tmp.py --no-cov -q
git stash -- src
OUT=docs/images/short_list_rows TAG=before QT_QPA_PLATFORM=offscreen PYTHONPATH=src \
  python -m pytest tests/instruments/flight_plan/_render_short_list_tmp.py --no-cov -q
git stash pop
```

and paste each before/after pair side by side with a 10 px gap (PIL).

```python
import os
from types import SimpleNamespace
from PyQt6.QtGui import QImage, QPainter, QColor
from pyefis.flightplan import model as fp_model
from pyefis.instruments import flight_plan

BEELINK = SimpleNamespace(screenWidth=1920, screenHeight=1080, screenDiagonalInches=21.5)

def _render(w, paint, path):
    img = QImage(w.width(), w.height(), QImage.Format.Format_RGB32)
    img.fill(QColor("black"))
    p = QPainter(img)
    paint(p)
    p.end()
    img.save(path)

def test_render(fix, qtbot, monkeypatch):
    out, tag = os.environ["OUT"], os.environ["TAG"]
    w = flight_plan.FlightPlan(None)
    qtbot.addWidget(w)
    w.parent = SimpleNamespace(parent=BEELINK)
    w.resize(672, 1080)
    entry = SimpleNamespace(slug="kgpm-kgpm", name="KGPM-KGPM", count=2,
                            comment="1182N7WF", mtime=1.0)
    monkeypatch.setattr(w, "_catalog_entries", lambda: [entry])
    monkeypatch.setattr(w, "_catalog_entry_distance_nm", lambda *a: 0.0)
    _render(w, lambda p: w._paint_catalog(p, w.width(), w.height()),
            f"{out}/catalog_one_route_{tag}.png")
    w._plan = fp_model.FlightPlan(name="T", waypoints=[
        fp_model.Waypoint(id="KGPM", type="airport", lat=32.7, lon=-97.0)])
    _render(w, lambda p: w._paint_dto_fpl_tab(p, w.width(), 0, w.height()),
            f"{out}/dto_fpl_one_waypoint_{tag}.png")
```
