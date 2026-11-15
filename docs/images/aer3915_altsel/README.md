# Selected-altitude box and bug (pyEfis #310, AER-3915)

Rendered **on the Pi 5 test unit** (`wpballard@10.110.10.199`, the Pi's own
B612 font and PyQt6 from `~/pyEfis/.venv`) from a throwaway clone of branch
`aer-3915/tk5-altsel` at `3619be6` (after TK3's baro box was merged in), with `QT_QPA_PLATFORM=offscreen`. The tape
is a QPainter-drawn `QGraphicsView`, not GL, so an offscreen render is the same
pixels the panel draws. The Pi's live display was not touched. There is no
SIGUSR1 screenshot on the Pi (AER-2002).

Size is the live panel's: the `altimeter_tape` in `managed_MAP_CTL_TEST.yaml`
is 12 x 60 cells of the 200 x 110 grid at 1920 x 1200, i.e. **115 x 655 px**.
ALT is 4130 ft and BARO 29.92 in every frame; the baro box (#311) is the strip at the bottom.

| File | What it shows |
|---|---|
| `sheet_1x.png` | **Actual size**, left to right: at rest (ALTSEL 4500, dim edit icon on), focused by a real touch through `EncoderController`, ALTSEL 9000 (bug pegged half-visible under the box), ALTSEL 1000 (bug pegged at the bottom of the scale, above the baro box), ALTSEL failed (dashes, no bug). |
| `box_zoom4x.png` | The box at rest, focused and with no value, nearest-neighbour **4x**. |
| `{rest,focused,above,below,novalue}_1x.png` | The individual frames. |

Regenerate:

```sh
QT_QPA_PLATFORM=offscreen PYTHONPATH=src python3 tools/render_altsel_evidence.py OUTDIR
```

Bus check against a running fix-gateway (restores ALTSEL afterwards):

```sh
QT_QPA_PLATFORM=offscreen PYTHONPATH=src python3 tools/render_altsel_evidence.py --live 127.0.0.1:3490
```

Run on the Pi on 2026-10-27 against the live gateway, at `3619be6` (output identical to the first run on 2026-10-26 at `e4beb35`). Every netfix connect is retried: the gateway's netfix server can refuse a back-to-back connect (billmallard/fix-gateway#43), which once left ALTSEL unrestored before the retry was added.

```
gateway ALTSEL before: 3000   ALT: 2013.5
focused by touch: True
inner +1  gateway ALTSEL = 3100  (want 3100)
outer +1  gateway ALTSEL = 4100  (want 4100)
push      gateway ALTSEL = 2000  (ALT 2013.5, want 2000)
focus cleared after push: True
restored ALTSEL: 3000
LIVE CHECK PASS
```
