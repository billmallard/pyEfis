# G95a digit-entry frames (pyEfis #547)

A numeric_display built through the real `Screen` path from the knob options
of `includes/mgl/v16/square-active-radio-display.yaml` (mask `000.000`,
step 0.025, enforce multiplier), on a 118.000-136.975 key set to 121.500.
Basic style: DejaVu Sans Mono, blank character a space. Offscreen Qt, the
blink phase driven by hand. `strip-2x.png` is the five states top to bottom,
nearest-neighbour 2x.

1. at rest, 121.500
2. push: digit entry starts from the lowest valid digits, 110.000, digit 2 (blink on)
3. same, blink off: the digit being set shows the blank character
4. turn +1: 120.000
5. push: digit 2 taken, digit 3 blinking

Regenerate from the repo root, on the #547 branch:

    QT_QPA_PLATFORM=offscreen PYTHONPATH=src python3 docs/images/g95a/render.py
