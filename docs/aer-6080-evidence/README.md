# AER-6080 (CERT12b): bench strips, SVS on and off, dev vs branch

The seam must not change a pixel. Each bench renders the attitude widget at
four pinned poses in three modes, once from `dev` and once from the branch,
and the pairs are compared pixel for pixel. The strips below compare `dev`
at ea09204f with the branch at 236b08ea, which has `dev` merged in.

| Mode | What it is |
|---|---|
| `svs` | SVS plugged in, drawing terrain (`tools/svs_capture.py` unchanged) |
| `symbology` | SVS plugged in, disabled (`--symbology-only`) |
| `none` | No renderer: `set_svs_config` never runs. On the branch this AI loads no SVS module |

Poses (lat, lon, ft MSL, heading, pitch, roll, magvar, horizon_position):
coastal 34.4275 -119.8546 2500 0 0 0 -12 50; mountains 39.20 -106.85 12500
150 -5 20 0 68; approach 37.96933 -107.98168 10500 105 -3 -10 0 68; final
34.42721 -119.87481 611 89 -3 0 -12 68. Heading and magvar vary so the true
heading the AI hands the renderer is exercised; horizon_position 68 (the
deployed SVS panels' value) exercises the lens shift and roll pivot.

All frames are 800x480, rendered offscreen (QOffscreenSurface + FBO, no
window, no DRM master) with the bench's own GL stack and the
`/data/makerplane-data` terrain, water, airport and obstacle packs.

## Beelink (X11, Intel ADL-N) -- 2026-11-21

![Beelink strip: rows coastal, mountains, approach, final; columns svs, symbology, none; each cell is the branch frame at half scale, captioned with its dev-vs-branch pixel count](beelink/strip-beelink.png)

24 of 24 pairs are identical. The first Beelink run (2026-11-20, `dev`
4146d4ca against branch 08901ad8) had 23 of 24. In that run `approach/svs`
differed at one pixel, (480, 330), by 1 LSB per channel. Three repeat runs
per tree showed that pixel flipping between the same two values on `dev`
alone (`beelink/repeat-approach-svs.txt`). It is run-to-run variation in the
renderer, and this run happened not to hit it.

## Pi 5 (eglfs, V3D 7.1) -- 2026-11-21

![Pi 5 strip: same layout as the Beelink strip, rendered under eglfs](pi5/strip-pi5.png)

24 of 24 pairs are identical. The frames were rendered under
`QT_QPA_PLATFORM=eglfs` while the bench's live `pyefis.service` held the
display. The service kept the same MainPID (1391040), and its restart count
stayed at 0 before and after (`pi5/run.log`). Its journal showed no
traceback, segfault or GL out-of-memory error. The probe frame ran first,
on its own, to check this before the full set.

## Regenerate

On the bench, with two clones (`dev` at the base, `branch` at the head) side
by side and this directory copied next to them:

```sh
export DISPLAY=:0                       # Beelink; on the Pi instead:
# export QT_QPA_PLATFORM=eglfs QT_QPA_EGLFS_KMS_CONFIG=$HOME/eglfs_hdmi.json
D=/data/makerplane-data
flock -w 900 /tmp/pyefis-bench.lock sh run_strips.sh <venv-python> dev branch out \
  $D/terrain/tiles $D/navdata/current/airports.sqlite \
  $D/obstacles/current/obstacles.sqlite $D/water/current/water.sqlite
QT_QPA_PLATFORM=offscreen <venv-python> compare_strips.py out strip.png <label>
```

`run_strips.sh` writes `out/manifest.txt` with each tree's SHA and every
capture's exit code; `strip_capture.py` is the per-frame driver (it adds the
`none` mode and `--horizon-position` around `tools/svs_capture.py`).
