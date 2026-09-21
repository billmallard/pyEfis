# AER-1806 no-op evidence

Proves the AER-1806 refactor (camera.py's optional `pixels_per_deg_h`,
defaulted `None` at every call site; `visiblePitchAngle` derived from
`pitchDegreesShown / 2` instead of an independent literal) renders
identically to `dev` at the shipped config (`pitchDegreesShown = 30`).

Same pose as the AER-1799 evidence capture -- level flight, 1 NM final
RWY 7 KSBA, 611 ft MSL, heading 089, range 5 NM -- captured with
`tools/svs_capture.py --offscreen` on the Beelink bench (Intel ADL-N
iGPU) against two throwaway checkouts, never the bench's live
`~/src/pyEfis` (which stayed on `dev`, untouched, services never
restarted).

| File | Checkout | `pyefis_rev` (sidecar) |
|---|---|---|
| `dev_800x480.png` | `dev` | `1e7db42` |
| `fix_800x480.png` | `aer-1806/pitch-hfov-decouple` | `59f29ed` |

Command (per file, `$D` = the checkout dir):

```bash
cd $D
DISPLAY=:0 PYTHONPATH=$PWD/src ~/pyefis-venv/bin/python tools/svs_capture.py \
  --out <name>.png \
  --lat 34.42721 --lon -119.87481 --alt 611.0 --heading 89 --pitch 0 --roll 0 \
  --range 5 --width 800 --height 480 --offscreen \
  --tiles /data/makerplane-data/terrain/tiles \
  --water /data/makerplane-data/water/current/water.sqlite \
  --nasr /data/makerplane-data/navdata/current/airports.sqlite \
  --dof /data/makerplane-data/obstacles/current/obstacles.sqlite \
  --timeout 60 --verbose
```

## Result

```
$ sha256sum dev_800x480.png fix_800x480.png
8112a1136a7e3b00b7a540e37766c1a80cdf466858f2009c381ca74255c2863d  dev_800x480.png
8112a1136a7e3b00b7a540e37766c1a80cdf466858f2009c381ca74255c2863d  fix_800x480.png
```

Byte-for-byte identical -- not just visually indistinguishable. Expected:
neither code change is reachable at these values. `view_projection`'s new
`pixels_per_deg_h` parameter only changes `sx` when a caller passes a
non-`None` value, and no call site (`svs_gl.py`'s single `view_projection`
call) does; `visiblePitchAngle` computes to `int(30 / 2) == 15`, the exact
`int` the old hardcoded literal was.

`horizon_position` is untouched by this PR (stays the widget default, 50,
in `svs_capture.py`, which has no CLI flag for it) -- irrelevant here since
the changed code paths are no-ops regardless of horizon_position.
