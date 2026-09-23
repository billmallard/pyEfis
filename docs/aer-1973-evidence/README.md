# AER-1973 pitch-up / terrain-HFOV evidence

Proves both halves of the AER-1973 change at the live `horizon_position = 68`
(Bill's AER-1802 ruling): the pitch ladder legitimately spreads out and shows
more range, and the terrain's horizontal extent is unchanged (the
`_TERRAIN_HFOV_PITCH_DEG` pin holds).

Level flight, 3000 ft MSL near Santa Barbara, heading 087, range 15 NM,
`horizon_position = 68` (not a code default -- forced on both captures via a
throwaway `AI.__init__` wrapper, since it is a deliberate deployed value, not
this branch's change). Captured with `tools/svs_capture.py --offscreen` on
the Beelink bench (Intel ADL-N iGPU) against two throwaway checkouts, never
the bench's live `~/src/pyEfis` (which stayed on the branch staged for
review; services were never restarted for these captures).

| File | Checkout | `pitchDegreesShown` (code default) | `pyefis_rev` (sidecar) |
|---|---|---|---|
| `dev_800x480.png` | `dev` | 30 (unmodified) | `80b67fb` |
| `fix_800x480.png` | `aer-1973/pitch-degrees-shown-50` | 50 (this branch) | `0f0aa52` |

Command (per file, `$D` = the checkout dir, `$H` = 68 forced via the wrapper
described above since `svs_capture.py` has no `--horizon-position` flag):

```bash
cd $D
DISPLAY=:0 CAP_HORIZON_POSITION=68 ~/pyefis-venv/bin/python _cap_driver.py \
  --out <name>.png \
  --lat 34.4275 --lon -119.8546 --alt 3000 --heading 87 --pitch 0 --roll 0 \
  --range 15 --width 800 --height 480 --offscreen \
  --tiles /data/makerplane-data/terrain/tiles \
  --water /data/makerplane-data/water/current/water.sqlite \
  --nasr /data/makerplane-data/navdata/current/airports.sqlite \
  --dof /data/makerplane-data/obstacles/current/obstacles.sqlite \
  --highways /data/makerplane-data/highways/current/highways.sqlite \
  --timeout 25 --verbose
```

`_cap_driver.py` is a thin, uncommitted wrapper used only to force
`horizon_position` (it monkeypatches `AI.__init__` to set the attribute
after construction, then `runpy`s the real `tools/svs_capture.py` unmodified
with the original CLI). It carries no code change and was not committed --
`pitchDegreesShown` itself is each checkout's real, unmodified default.

## Result

```
$ sha256sum dev_800x480.png fix_800x480.png
c74c1743e738ef0d67fae8b197c49ebfd56ec4e8d5749223424101abdb5e8379  dev_800x480.png
f6ed1e3a0c17a16060a9df336a5cd6036d8413c47e4f2b405f1f82c86898c9ef  fix_800x480.png
```

Different, as expected -- this is not a no-op change (contrast
`docs/aer-1806-evidence`, which proves the opposite for that refactor).
Visually: the pitch-ladder numbers/ticks are coarser and the "10" and "-20"
labels that were clipped or absent in `dev_800x480.png` are fully visible in
`fix_800x480.png` (the +9.6/-15 -> +16.0/-25 deg range from AER-1973's
issue table). The terrain silhouette (mountain ridge line, the diagonal
river/road, the water/land boundary), the horizon line's screen position,
and the runway/obstacle markers sit at byte-for-byte identical screen
coordinates in both frames -- the horizontal extent of the terrain picture
is unaffected by the `pitchDegreesShown` change, which is the whole point of
the `_TERRAIN_HFOV_PITCH_DEG` pin this issue wires up
(`tests/instruments/ai/test_camera.py::TestTerrainHFOVPinnedAcrossPitchDegreesShown`
pins the same invariant as pure arithmetic, with no rendered frame involved).
