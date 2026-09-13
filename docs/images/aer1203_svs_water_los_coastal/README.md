# AER-1203 / AER-701 / pyEfis#102 -- SVS water LOS masking, coastal re-render

Real, on-device GL captures of the AER-658 coastal scene (Santa Barbara /
SBA), one pair pre-fix and one post-fix, both minted by the actual
`tools/svs_capture.py` renderer against real SRTM3 terrain and a real water
polygon pack -- not a synthetic diagnostic (compare `docs/images/aer701_svs_water_los/`,
which was a top-down synthetic ridge+lake stand-in built when this real
re-render was still pending on AER-659).

## What these are

| File | Commit | What it shows |
|---|---|---|
| `before_frame0000_water_through_ridge.png` | `6a47472` (`dev`, 2026-09-06, **before** #173 merged) | The lake/ocean water body draws straight through the foothill ridge in front of it -- issue #102, reported defect. |
| `after_frame0000_water_los_masked.png` | `261bbef` (`aer-701/svs-water-los-masking`, the exact fix commit merged as pyEfis#173) | Same pose, same data, same renderer build. The water band is gone; only the small unoccluded pond in the near foreground remains. |
| `before_frame0000_crop2x.png` / `after_frame0000_crop2x.png` | (same as above) | 2x nearest-neighbour crop of the y=540-660px band where the defect sits, so the ribbon (only a few px tall in the full frame) doesn't get lost in a 1920x1080 embed. |
| `poses_coastal.csv` | -- | All 188 commanded poses for the `coastal` segment (`t, lat, lon, alt, heading, range_nm`), the same file both runs consumed. Frame `idx=0` is the pair shown here. |

Both sides used **identical** poses (frame `idx=0`: lat `34.4234216`, lon
`-119.8544276`, alt `2500 ft`, heading `356.0`, range `15 nm`) and identical
real data -- SRTM3 tiles + water pack under `/data/makerplane-data/` on the
Beelink bench, current at capture time. The only variable between the two
frames is the git SHA the renderer was built from.

The defect and its fix hold across the whole 188-frame sweep, not just this
one pose -- summed per-pixel abs RGB difference between every corresponding
before/after frame pair is nonzero throughout (1,165,261 at `idx=0`, falling
monotonically to 643,382 at `idx=180` as the pose track moves the ridge/water
geometry in frame, but never reaching zero), and spot checks at `idx=90` and
`idx=187` show the same ribbon-through-terrain / ribbon-gone pattern as
`idx=0`.

## Renderer

`tools/svs_capture.py`, the **windowed** GL path (a real Xorg session on the
Beelink bench, `DISPLAY=:0`; **not** `--offscreen`). The bench's
`pyefis.service` (the on-glass display) was live at capture time and holds
its own top-level window; `svs_capture.py`'s windowed path opens a second,
independent `QMainWindow` and does not contend with it (this is X11, not
eglfs -- the eglfs single-screen contention `--offscreen` exists for, per
AER-763, does not apply here). Confidence note per AER-763's own caution: the
`--offscreen` path exists in this tool and was **not** used to produce these
frames, so its still-open validation gap is irrelevant to this evidence.

Driven by a small harness, `~/aer658_capture/driver.py` (pre-fix, full
mountains+coastal sweep) and `~/aer658_capture/driver_coastal_fixed.py`
(post-fix, coastal only), both on the bench, both invoking
`tools/svs_capture.py` once per pose row with no interpolation -- every frame
is an independent, fully-settled capture.

## Commit SHAs and how the two sides were produced

- **Pre-fix**: `~/src/pyEfis` checked out at `6a47472` (`dev` HEAD as of
  2026-09-06, before pyEfis#173/AER-701 merged -- confirmed via
  `git merge-base --is-ancestor 6a47472 261bbef` and that none of the 27
  commits between them touch `svs.py`/`svs_gl.py` water handling).
  Captured 2026-09-06 ~14:25 UTC via `driver.py`.
- **Post-fix**: `~/src/pyEfis` checked out at `261bbef` (the AER-701 fix
  commit itself, `svs: hide water occluded by terrain -- the missing twin of
  #73 (issue #102)`, merged upstream as pyEfis#173/4747970).
  Captured 2026-09-07 ~02:10-02:14 UTC via `driver_coastal_fixed.py`, which
  restricts the same `poses.csv` to `seg=coastal` and writes to a separate
  output tree so the pre-fix frames are preserved as the baseline.

Both runs used the same data:

```
tiles=/data/makerplane-data/terrain/tiles
water=/data/makerplane-data/water/current/water.sqlite
nasr=/data/makerplane-data/navdata/current/airports.sqlite
dof=/data/makerplane-data/obstacles/current/obstacles.sqlite
highways=/data/makerplane-data/highways/current/highways.sqlite
```

## Regenerate

On the Beelink bench (`ssh pyefis@10.110.10.241`, or via `BEELINK_SSH_KEY`
per `makerplane/processes/bench_deploy.md`), with `~/src/pyEfis` checked out
at the SHA of interest:

```bash
cd ~/src/pyEfis
~/pyefis-venv/bin/python tools/svs_capture.py \
    --lat 34.4234216 --lon -119.8544276 --alt 2500 \
    --heading 356.0 --range 15 \
    --width 1920 --height 1080 \
    --tiles /data/makerplane-data/terrain/tiles \
    --water /data/makerplane-data/water/current/water.sqlite \
    --nasr /data/makerplane-data/navdata/current/airports.sqlite \
    --dof /data/makerplane-data/obstacles/current/obstacles.sqlite \
    --highways /data/makerplane-data/highways/current/highways.sqlite \
    --out /tmp/frame_0000.png --timeout 45
```

(Requires `DISPLAY=:0` in the environment -- the tool opens a real window.)

The 2x crops were produced locally with:

```python
from PIL import Image
im = Image.open("frame_0000.png").convert("RGB")
im.crop((0, 540, 900, 660)).resize((1800, 240), Image.NEAREST).save("crop2x.png")
```

## What this does not cover

This is a single hero pose (plus two spot checks) picked for how clearly it
shows the ribbon, not a claim that every pose in every scene is defect-free
post-fix -- see `tests/instruments/ai/test_svs.py::TestWaterOcclusion` for
the unit-level guarantee (all-visible / partial-occlusion / all-occluded
cases on synthetic geometry). On-device visual judgement of whether this
*looks* right belongs to Bill, not to this README.
