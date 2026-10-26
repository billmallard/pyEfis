# AER-3865 / pyEfis #304 -- terrain roll, current dev vs screen-space-roll prototype

Captured on the Raspberry Pi 5 bench (V3D, eglfs), 2026-10-26, with
`tools/svs_capture.py --offscreen` running alongside the live pyefis.service.
Left column: `dev` at `f1ef6ae`. Right column: this branch at `a4c1fe4`. Each
frame's `.json` sidecar records the checkout it was rendered from.

## Geometry is the Pi's live screen, not the code defaults

`cap_live.py` applies the `virtual_vfr` options from the screen the Pi actually
serves (`~/makerplane/pyefis/config/screens/managed.yaml`, defaultScreen
MAP_CTL_TEST) to the AI widget before capture: `pitchDegreesShown: 25`,
`horizon_position: 68`, `aircraft_symbol: brackets`, and the rest of that
block, plus its `svs_*` appearance keys (clearance palette, haze 32 nm). The
widget is 1248x1200, which is 130 of 200 columns on the 1920x1200 panel. The
sheets are scaled to 50%.

Pose: 39.75 N, 104.75 W, 8,500 ft, heading 200 (Front Range on the right,
plains on the left), range 30 nm, sim-free: `svs_capture` pins the pose
directly through its mock FIX database, so every frame is repeatable.

## Reproduce

On the Pi, with `dev` and this branch cloned to `~/bench-scratch/aer3865/{dev,proto}`
and a scratch venv `venv` (`python3 -m venv --system-site-packages`):

    ./run_sheet.sh                       # 12 attitudes x 2 builds -> sheet/
    python3 make_sheet.py sheet out.png  # optional "pitch,roll;..." row filter

`guarded_cap.sh` wraps each capture with the AER-1697 safety cutoffs: kill on
V3D BO growth > 400 MB, any BO allocation failure in dmesg, or 90 s. Every
capture in these sheets exited 0, peaked at about 77 MB of BO growth, and left
pyefis.service active.

## Not from this change

The black triangle in some top-right corners is the AI widget's own
background showing past its sky/ground rectangles at horizon_position 68. It
appears on `dev` with SVS off (`--symbology-only`) at the same attitude. On
`dev` the over-tilted terrain sometimes happens to cover it.
