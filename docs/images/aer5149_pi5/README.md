# AER-5149: target-bank bug and excessive-bank caution, Pi 5 GL frames

Captured on the Raspberry Pi 5 bench (V3D, eglfs), 2026-11-09, with
`tools/svs_capture.py --offscreen` running alongside the live pyefis.service
(SVS terrain on). Every frame's `.png.json` sidecar names the checkout that
drew it: **before** = `dev` at `ce55802a`, **after** = this branch at
`bdf9b447`.

- `sheet.png`: whole frames at 50%. Rows: standard rate (18 deg, the
  standard-rate bank at the capture's 120 KTAS), 45 deg, 60 deg. Columns:
  left bank before, left bank after, right bank before, right bank after.
- `bank_cluster.png`: the same 12 frames, cropped to the bank scale, 1:1.

Bug settings in the "after" frames: off at standard rate (the standard-rate
diamonds already mark it), 45 at 45 deg, 60 at 60 deg. "Before" has no bug,
since `dev` has none, and its caution threshold is the old 45: the 60 deg
frames show the amber scale there and not here.

Geometry is the Pi's live screen: `cap_live.py` applies the `virtual_vfr`
options from `~/makerplane/pyefis/config/screens/managed.yaml` (the
`SCREEN_MAP_CTL_TEST` mapping in `preferences.yaml.custom`, defaultScreen
MAP_CTL_TEST): `bank_position 63`, `bank_radius 25`, `pitchDegreesShown 25`,
`horizon_position 68`, B612 font, a 1248x1200 widget. Pose: 39.75 N, 104.75 W,
8,500 ft, heading 200, range 30 NM (Front Range).

## Reproduce

On the Pi, with `dev` and this branch cloned to `~/bench-scratch/aer5149/{dev,pr}`
and the scratch venv from `~/bench-scratch/aer3865/venv`:

    ./run_sheet.sh          # 6 attitudes x 2 builds -> sheet/
    python make_sheet.py    # here, with the frames copied to frames/

`guarded_cap.sh` wraps each capture with the AER-1697 safety cutoffs (V3D BO
growth > 400 MB, a BO allocation failure in dmesg, or 90 s). All 12 captures
exited 0, peaked at about 77 MB of BO growth, and left pyefis.service active.
