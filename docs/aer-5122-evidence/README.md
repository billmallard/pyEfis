# AER-5122 evidence: the SVS sea horizon on the raised zero-pitch line

`tools/svs_capture.py --offscreen --flat`, 1024x768, on the Beelink (Intel
ADL-N). AI widget at `pitchDegreesShown` 50, `horizon_position` 75. Pose: open
sea, lat 24.30, lon -81.80, 100 ft, heading 180, **pitch -10**, roll 0, range
30 NM. Each side is a `--terrain-only` and a `--symbology-only` frame.

- `dev_*`: `dev` at 1523b45 (the `.png.json` sidecars carry `pyefis_rev`).
  Nothing under `src/pyefis/instruments/ai` changed between this branch's base
  and 1523b45.
- `branch_*`: this branch at d96f61f.

`horizon_crop_4x.png`: **left = dev, right = this branch.** Rows 0-79, columns
128-383 of the terrain frame, with the symbology frame's zero-pitch line drawn
in magenta, scaled 4x nearest-neighbour. The red band is the far edge of the
sea.

| Side | Sea edge vs zero-pitch line |
|---|---|
| dev | 14.5 px (0.94 deg) **above** |
| branch | 0.5 px (0.03 deg) below |

Expected after the fix: the centred screen's `tan(pitch) - pitch` residual
(0.10 deg up at pitch -10) less the sea's dip at 100 ft (0.18 deg down), so
0.08 deg (1.2 px) below. The testcase measured dev at 15.0 px on the Pi.

## Regenerate

`hp_capture.py` runs the stock capture tool with the widget's
`horizon_position` and `pitchDegreesShown` set from `HP` and `PDS` (defaults
75 and 50); `svs_capture.py` has no flag for them. On the Beelink, one
throwaway clone per side:

```bash
git clone --depth 1 --branch <ref> https://github.com/billmallard/pyEfis.git x && cd x
for mode in terrain-only symbology-only; do
  DISPLAY=:0 PYTHONPATH=$PWD/src ~/pyefis-venv/bin/python hp_capture.py \
    --offscreen --flat --$mode --width 1024 --height 768 \
    --lat 24.30 --lon -81.80 --alt 100 --heading 180 --pitch -10 --roll 0 \
    --range 30 --tiles /data/makerplane-data/terrain/tiles \
    --water /data/makerplane-data/water/current/water.sqlite \
    --out <side>_$mode.png
done
# then, with Pillow:
python3 docs/aer-5122-evidence/compose.py docs/aer-5122-evidence
```

`compose.py` prints the measurement table above.
