# Airspeed tape green band from Vs1 (pyEfis #396, AER-5143)

V-speeds: Vs1 (`Vs`) 56, Vs0 48, Vfe 85, Vno 140, Vne 180 kt; IAS 65 kt; tape 140x480.

- `before_vs.png`: `dev` before the fix, `Vs` set. Green runs down to Vs0 (48).
- `after_vs.png`: the fix, `Vs` set. Green stops at Vs1 (56); only the white flap arc
  continues down to Vs0.
- `after_novs.png`: the fix, `Vs` unset. Green falls back to Vs0, byte-identical to
  `before_vs.png`.
- `compare.png`: the three side by side, left to right, 1:1.

Rendered on the Beelink bench (for its fonts) in a scratch copy, offscreen, from the repo root:

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. python docs/images/aer5143/render_tape.py after_vs.png
QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. python docs/images/aer5143/render_tape.py after_novs.png --no-vs
# before: the same command with src/pyefis/instruments/airspeed/__init__.py from origin/dev
```
