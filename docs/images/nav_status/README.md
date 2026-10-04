# nav_status chip renders (FP7, billmallard/pyEfis#189)

`contact_sheet_3x.png` (3x nearest-neighbour), top to bottom: no plan;
LEG/TERM; DIRECT/ENR (no FROM ident on a direct-to); SUSP at the MAP, LNAV, no
NEXT; LOI with WPETE bad (`--:--`); position fail (red `XXX`). The individual
`<state>_600x48.png` / `<state>_300x32.png` files are 1:1.

Synthetic engine outputs on the in-memory mock FIX database; no gateway needed.
For the chip reading a real gateway, see `../fp7_hsi/`.

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=src python3 docs/images/nav_status/render_states.py
# on a host with no system fonts, also: RENDER_FONT_DIR=<dir of .ttf files>
```
