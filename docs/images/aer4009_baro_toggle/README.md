# Baro box: second push restores the replaced setting (AER-4009)

| File | What it shows |
|---|---|
| `beelink_live_toggle_2x.png` | **Live Beelink PFD** (X11, the bench's served `screens/managed.yaml`), branch `aer-4009/baro-push-toggle`, the baro box cropped from `:0` and scaled 2x nearest-neighbour. Top row: BARO set to 30.05 from another client, a touch selects the box, then four knob pushes alternate standard / 30.05. Bottom row: a push saves 30.05, an inner-knob step up and back clears it, so the next push at 29.92 does nothing; then a push saves 30.05, another client writes 29.80 (clears), and the next two pushes go standard / 29.80, never back to 30.05. |

Every frame's caption matches the value read back from the live fix-gateway
(`@rBARO`, an independent socket) after that step.

Regenerate on the Beelink (pyEfis on the PFD, past the boot navdata page):

```sh
flock -w 900 /tmp/pyefis-bench.lock sh tools/bench_baro_push_toggle.sh OUTDIR
```

The script touches the box with `xdotool`, pushes and turns the knob by
writing the bench Knobster's FIX keys (`BTN3`, `ENC3`, from
`hmi/encoder_input.yaml`) to the gateway, grabs the box with `ffmpeg -f x11grab`
after each step, and puts BARO back to its starting value at the end. The
sheet is the 14 step frames cropped to the box (x 40-150, y 48-88 of each
200x120 grab) and scaled 2x.
