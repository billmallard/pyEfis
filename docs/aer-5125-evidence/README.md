# AER-5125 evidence: the pitch ladder on the SVS terrain's tangent

`tools/svs_capture.py --offscreen --flat`, 1024x768, on the Beelink (Intel
ADL-N), through `docs/aer-5122-evidence/hp_capture.py` to set
`pitchDegreesShown` 50 and `horizon_position` (50 or 75). Pose: open sea, lat
24.30, lon -81.80, 100 ft, heading 180, roll 0, range 30 NM, **pitch -20 or
+20**.

- `base_*`: #423's branch `aer-5122/svs-horizon-offset-tangent` at 662510c
  (linear ladder, lens-shifted terrain).
- `branch_*`: `aer-5125/svs-tangent-ladder` at a3cf3cd.

The sidecars read `-dirty` only because `hp_capture.py` was copied into
each throwaway clone's root. No source file was modified.

## Measurement

`compose.py` takes the sea's far edge as the first row of the renderer's red
edge band in the `--terrain-only` frame, and the zero-pitch line as the white
attitude line in the composed frame, in 240 columns clear of the centre
symbols.

| Case (hp / pitch) | base: edge below line | branch: edge below line |
|---|---|---|
| 50 / -20 | -9.5 px (-0.62 deg, edge ABOVE the line) | +3.5 px (+0.23 deg) |
| 50 / +20 | +17.5 px (+1.14 deg) | +4.5 px (+0.29 deg) |
| 75 / +20 | +17.5 px (+1.14 deg) | +4.5 px (+0.29 deg) |

Expected on the branch: the physical dip of the sea horizon at 100 ft,
0.18 deg (2.8 px) below the line, at every pitch. Measured: 3.5 to 4.5 px.
Expected on the base: that dip plus the linear-vs-tangent gap of 0.85 deg at
20 deg (13.1 px), up at -20 and down at +20. The line moved 13.0 px between
the two sides in both directions. Both sides carry the same ~1 to 1.5 px
offset from the closed form, which is the edge band's first row.

At horizon_position 75 and pitch -20 the horizon is above the glass, so
that case is not shown.

`--symbology-only` is not used: that mode disables the SVS, so it draws the
no-SVS linear ladder on both sides, which is correct and unchanged.

- `horizon_crops_4x.png`: one row per case (50/-20, 50/+20, 75/+20), base
  left, branch right. Rows +-24 around the sea edge, columns 40-295 of the
  composed frame, 4x nearest-neighbour. White = zero-pitch line; red = far
  edge of the sea.
- `composite_pairs.png`: whole composed frames at 50%, base left, branch
  right. Top: hp 50, pitch -20. Bottom: hp 75, pitch +20.

## Regenerate

```bash
# on the Beelink, under the bench lock
flock -w 900 /tmp/pyefis-bench.lock sh capture.sh
# then, with Pillow, from a checkout of this branch:
python3 docs/aer-5125-evidence/compose.py ~/bench-scratch/aer5125/out docs/aer-5125-evidence
```
