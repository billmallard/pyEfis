# G59 evidence: a route waypoint draws once (pyEfis #375, AER-5088)

Each image: **left = `dev` (fce470c1), right = this branch**, the real
`MovingMap` rendered offscreen on the Beelink with the bench's data packs and
fonts, route KSBA RZS GVO KSMX loaded, leg RZS -> GVO active. Bottom row:
the scene's route point, cropped 100x80 px and scaled 4x nearest-neighbour.

| Image | What to look at |
|---|---|
| `ksba_2nm.png` | dev: a grey route ring and a grey `KSBA` under the true-size runways, plus the airport's own `KSBA`. Branch: the airport's label only. |
| `ksba_20nm.png` | dev: two rings and two `KSBA` labels 1-2 px apart. Branch: one. |
| `gvo_2nm.png`, `gvo_20nm.png` | dev: a magenta route hexagon over the blue VOR hexagon, and a magenta `GVO` over `GVO 113.8`. Branch: the blue VOR and its label, with the magenta TO ring. |

The visible change on the active waypoint: its label is now the database
layer's white (or the navaid's), not route-state magenta. The TO waypoint
stays marked by the magenta ring and the magenta leg.

## Regenerate

On the Beelink, one scratch tree per side (neither touches the live display
or the checkout):

```bash
# in ~/bench-scratch/aer-5088/{dev,branch}, each a tar of src tools tests/mock_db tests/__init__.py
QT_QPA_PLATFORM=offscreen ~/pyefis-venv/bin/python \
    tools/render_route_drawn_once_evidence.py --data /data/makerplane-data --out out
# then, anywhere with Pillow:
python3 docs/aer-5088-evidence/compose_pairs.py dev/out branch/out docs/aer-5088-evidence
```

`render_route_drawn_once_evidence.py` was copied into the dev tree unchanged;
it does not depend on the fix.
