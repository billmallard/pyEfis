# AER-707 -- `--symbology-only` capture evidence

Both frames were captured on the Beelink pyEfis bench (Mesa software GL under
`xvfb-run`) with the deployed terrain tiles and water pack, at the same
commanded pose: lat 34.4275, lon -119.8546, alt 1500 ft MSL, heading 87,
pitch 5, roll -12, range 15 NM.

```
xvfb-run -a -s "-screen 0 1024x768x24" <venv>/bin/python tools/svs_capture.py \
  --lat 34.4275 --lon -119.8546 --alt 1500 --heading 87 --pitch 5 --roll -12 \
  --range 15 \
  --water /data/makerplane-data/water/current/water.sqlite \
  --tiles /data/makerplane-data/terrain/tiles \
  --water-max-vertices 1000000 \
  --symbology-only --out symbology_only.png
```

`terrain_only.png` is the same pose with `--terrain-only` in place of
`--symbology-only` -- unchanged by this PR, included as the before/after
counterpart.
