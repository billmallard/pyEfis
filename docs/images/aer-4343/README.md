# AER-4343 / CIFP1 -- SVS PAPI evidence

GL SVS frames from the Beelink bench (Intel ADL-N, X11), rendered with
`tools/svs_capture.py --offscreen` from a scratch clone (the live checkout was
not touched), against the bench's installed makerplane-data packs (NASR
airports pack `navdata/2611`). Each PNG has a `.png.json` sidecar naming the
`pyefis_rev` that drew it and the exact argv.

`papi_crops_4x.png` is a crop of x 290-450, y 200-260 from each frame,
upscaled 4x nearest-neighbour (so the light edges are not smoothed), top to
bottom:

| Frame | Runway end (NASR) | Aircraft | Expected | Shows |
|---|---|---|---|---|
| `sba25_3p0` | KSBA 25, `P4L`, 3.00 deg | 2 NM, 3.00 deg path | 2 red / 2 white, left side, red inboard | yes |
| `tex09_3p0` | KTEX 09, `P4L`, 3.55 deg | 2 NM, 3.00 deg path | 4 red (3.00 is below the outboard unit's 3.05) | yes |
| `tex09_3p55` | KTEX 09, `P4L`, 3.55 deg | 2 NM, 3.55 deg path | 2 red / 2 white | yes |
| `sba07_3p0` | KSBA 07, no VGSI | 2 NM, 3.00 deg path | nothing | nothing |
| `sba25_3p0_dev` | KSBA 25 on `dev` | same pose as row 1 | nothing (no SVS PAPI before) | nothing |

The legacy Virtual VFR would have shown 2 red / 2 white in rows 2 and 4 too:
it assumed 3 degrees and drew a PAPI beside every runway.

Pixel check (pure `(r > 230, g < 60, b < 60)` threshold over the full frame):
sba25 120 px (2 lights), tex09 3.00 228 px (4 lights), tex09 3.55 120 px
(2 lights), sba07 0, dev 0.

## Regenerate

Poses put the aircraft 2 NM before the box (landing threshold + displaced
length + 1000 ft) on the runway's true alignment, at
`elev + tan(angle) * distance`.

```sh
M=/data/makerplane-data
DATA="--tiles $M/terrain/tiles --nasr $M/navdata/current/airports.sqlite \
  --water $M/water/current/water.sqlite --dof $M/obstacles/current/obstacles.sqlite"
COMMON="--offscreen --width 800 --height 480 --range 15 --pitch -3"
cd <clone> && export DISPLAY=:0 PYTHONPATH=$PWD/src
python tools/svs_capture.py $COMMON $DATA --lat 34.428452 --lon -119.797490 --alt 649  --heading 269 --out sba25_3p0.png
python tools/svs_capture.py $COMMON $DATA --lat 34.426965 --lon -119.891730 --alt 648  --heading 89  --out sba07_3p0.png
python tools/svs_capture.py $COMMON $DATA --lat 37.964100 --lon -107.957462 --alt 9675 --heading 105 --out tex09_3p0.png
python tools/svs_capture.py $COMMON $DATA --lat 37.964100 --lon -107.957462 --alt 9792 --heading 105 --out tex09_3p55.png
```

The crop composite is built with PIL: `crop((290, 200, 450, 260))`, then
`resize((w * 4, h * 4), Image.NEAREST)`, stacked with a caption bar.
