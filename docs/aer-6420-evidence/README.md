# AER-6420 (FPA3): map Insert on a route the engine refused

The scene: the engine flies a four-fix route, then refuses a second commit
(`FPLLDSEQ` stays at the flown `FPLSEQ`). The slots on the bus hold the
refused route, so the map draws no route. The pilot taps a bare map point
beside the second leg and presses INSERT. 800x480 map pane, 40 NM, north up.

| File | What it shows |
|---|---|
| `dev.png` | `dev` at `origin/dev` (the base of pyEfis #566): `INSERTED MAPWPT`, the pointer cleared, and the refused route plus MAPWPT republished to the engine |
| `branch.png` | the branch: `ROUTE NOT LOADED: SEE FPL`, nothing published, the pointer and banner kept |
| `sheet_1x.png` | left `dev`, right branch, 1:1 |
| `toast_zoom3x.png` | the toast only, top `dev`, bottom branch, nearest-neighbour 3x |

The toast's size, colour and position are unchanged (`_paint_toast`, 16 px at
this pane size, same 12 px cap height in both frames). Only the text differs.

## Regenerate

`render_toast.py` drives the real `MovingMap.banner_insert()` through the
in-memory FIX database from the root `conftest.py`, so it runs under pytest.
From the repo root, for each tree (`dev` and the branch), with offscreen Qt:

```bash
cp docs/aer-6420-evidence/render_toast.py tests/_aer6420_render.py
QT_QPA_PLATFORM=offscreen PYTHONPATH=src AER6420_OUT=$PWD/out.png \
  python3 -m pytest -p no:cacheprovider --no-cov -q tests/_aer6420_render.py
rm tests/_aer6420_render.py
```

The sheet and zoom are PIL crops of the two frames (crop box
`(240, 50, 560, 95)`, `Image.NEAREST`).
