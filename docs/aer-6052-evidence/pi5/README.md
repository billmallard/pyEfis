# AFC5 Pi 5 GL capture sheet (AER-6052)

Real GL terrain under the flight director, rendered on the Pi 5 bench
(Broadcom V3D 7.1, eglfs) by `tools/svs_capture.py --offscreen` at commit
501a7137, concurrently with the live `pyefis.service`. The live service had 0
restarts during or after the sheet. Each PNG has a `.png.json` sidecar giving
the commit, the device and the full argv.

The geometry is the bench's live screen: `MAP_CTL_TEST` from
`~/makerplane/pyefis/config/screens/managed.yaml` (the file
`SCREEN_MAP_CTL_TEST` maps to). That is a 1248x1200 `virtual_vfr` with
`pitchDegreesShown 25`, `horizon_position 68` and the bracket symbol.
`cap_live.py` applies those options to the widget the same way the screen
builder does. `svs_capture.py` itself is unchanged.

`contact.png` is at half scale. Columns: single_cue, cross_pointer. Rows:

| Scene | Pose | FD command | What it shows |
|---|---|---|---|
| `ksba_final` | KSBA, about 1.5 NM west of RWY 7 at 700 ft, hdg 75, pitch -2, wings level | pitch -4, roll 8 | near-airport terrain colouring, with the magenta ridge behind the bars |
| `mtn_climb` | east of the Front Range at 8500 ft, hdg 270, pitch 4, wings level | pitch 8, roll -15 | a climb with a left turn; the cue sits above the symbol, in the sky |
| `bank_turn` | same spot, hdg 200, pitch 2, roll 25 right | pitch 0, roll 10 | a shallow-out command while banked: the cue shows -15 of bank error |

Regenerate on the Pi (the scripts expect `~/bench-scratch/aer6052`, with `pr`
a checkout of the branch and `venv` a Python with PyQt6, numpy and PyOpenGL):

```sh
./sheet.sh
```

`guarded_cap.sh` kills a capture on more than 400 MB of V3D buffer growth, on
a BO allocation failure in dmesg, or after 90 s. Every capture here peaked at
74 to 77 MB of growth.
