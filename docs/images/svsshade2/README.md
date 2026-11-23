# SVSSHADE2 bench evidence (AER-6401)

Captures of the four preview poses (`tools/export_svs_preview_patch.py`
`SCENES`) in both views, on the Beelink (Intel ADL-N, X11) and, for the KSBA
final pose, on the Pi 5 (V3D, eglfs, alongside the live pyEfis). Taken on
2026-11-23 from throwaway clones under `~/bench-scratch/aer6401`, never the
live checkout; pyEfis was not restarted. Revisions are in `*/revs.txt`
(dev `de10421e`, branch `23ea61e8`). The sidecars read `-dirty` for dev
because `tools/map_terrain_capture.py` was copied into the dev clone, so the
"today" map runs dev's own map code at the same pose.

Each `strip_<scene>.png` is, left to right: the SVS on dev, the SVS on this
branch (`terrain_shading: relief`, the new default), the moving map in
`caution` mode on dev, and the map in `caution` mode on this branch. SVS
800x480 scaled to 640x384, map 480x480 scaled to 384x384.

## Render equality: `terrain_shading: clearance` against dev

The SVS was captured four times per pose: dev, dev again (the base
repeated), the branch with `--terrain-shading clearance`, and the branch
with the default. The sidecars' `sha256` (first 16 hex digits):

| Box | Pose | dev | dev again | branch, clearance | branch, relief |
|---|---|---|---|---|---|
| Beelink | approach | 7471ea1de108a561 | 7471ea1de108a561 | 7471ea1de108a561 | 67863b95b0f52706 |
| Beelink | coastal | 846d5651f5be7395 | 846d5651f5be7395 | 846d5651f5be7395 | b85c5bfc2313e117 |
| Beelink | final | ee2f0fc217a25aca | ee2f0fc217a25aca | ee2f0fc217a25aca | 127de7af4ca85571 |
| Beelink | mountains | 01c1786621125e9d | 01c1786621125e9d | 01c1786621125e9d | 8cb4760641c06960 |
| Pi 5 | final | a3543cfc8e5812b6 | a3543cfc8e5812b6 | a3543cfc8e5812b6 | 579723bcab899b82 |

The repeat and the clearance capture are byte-identical to dev, so only the
dev and relief PNGs are kept; the other two sidecars remain.

## Regenerating

On the Beelink (pyEfis holding the display; offscreen GL on its X server):

    scp bench6401.sh pyefis@10.110.10.241:/tmp/
    ssh pyefis@10.110.10.241 'DISPLAY=:0 QT_QPA_PLATFORM=xcb \
      flock -w 900 /tmp/pyefis-bench.lock sh /tmp/bench6401.sh <sha> \
      /home/pyefis/pyefis-venv/bin/python /data/makerplane-data'

On the Pi 5 (the service's own interpreter and eglfs config):

    scp pi6401.sh wpballard@10.110.10.199:/tmp/
    ssh wpballard@10.110.10.199 'flock -w 900 /tmp/pyefis-bench.lock \
      sh /tmp/pi6401.sh <sha> /home/wpballard/pyEfis/.venv/bin/python \
      /data/makerplane-data'

Data: the installed packs under `/data/makerplane-data` (GLO-30 terrain,
NASR airports, water). The strips are composed from the captures with PIL
(640x384 / 384x384 Lanczos, labelled).
