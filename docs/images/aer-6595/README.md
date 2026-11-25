# SVSFLOOR1: the SVS camera floor, KSBA runway 07

Offscreen SVS captures on the Beelink bench (X11, Intel ADL-N), dev against
this branch, at one pose: KSBA runway 07, on the centreline 1,000 ft past the
threshold, heading 088.6 true (magnetic variation 0), pitch 0, range 15 NM,
1024 x 600. NASR puts the runway surface there at 11.5 ft.

Three camera height inputs:

| Case | Height input | What it stands for |
|---|---|---|
| `ok` | 16.5 ft | the input agrees with NASR: runway plus the 5 ft eye height |
| `under20` | -8.5 ft | a sim runway 20 ft lower than NASR's (inside the 30 ft band) |
| `under40` | -28.5 ft | a sim runway 40 ft lower than NASR's (past the band) |

`svs_floor_strip.png`: top row dev, bottom row this branch, left to right
`ok`, `under20`, `under40`, each scaled to 512 x 300.

- dev draws `under20` and `under40` from under the runway: the runway is the
  grey wedge above the horizon and the surrounding field paints as conflict.
- The branch draws both from the runway surface. `under40` adds the amber
  `SVS HGT` tag; `under20` has none.
- `ok` is pixel-identical between dev and the branch (0 of 614,400 pixels
  differ): a correct height is not moved.
- On the branch, `under20` differs from `ok` in 206 pixels. The floor is
  11.4994 + 5 = 16.4994 ft, not 16.5, a sub-pixel change at the horizon.
  `under40` differs in 1,808 pixels, the tag and the same horizon pixels.

Each PNG has its `.png.json` sidecar with `pyefis_rev` (dev `48ac6d7`,
branch `f3573a6`), the size and the exact command.

## Regenerate

On the Beelink, with a throwaway clone of each tree beside the script
(never the live `~/src/pyEfis` checkout):

```sh
mkdir -p ~/bench-scratch/aer6595 && cd ~/bench-scratch/aer6595
git clone --depth 1 --branch dev https://github.com/billmallard/pyEfis.git dev
git clone --depth 1 --branch aer-6595/svs-floor https://github.com/billmallard/pyEfis.git branch
flock -w 900 /tmp/pyefis-bench.lock sh ./capture.sh
```

`capture.sh` is in this directory. It runs `tools/svs_capture.py --offscreen`
from each tree against the bench data under `/data/makerplane-data`.
