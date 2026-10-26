# FP7 on-glass captures (AER-808, AER-3036)

Real X-session captures from the Beelink bench (1920x1080, `DISPLAY=:0`,
`ffmpeg -f x11grab`), with pyEfis #285 (`aer-808/fp7-nav-status` @ `71b499a`)
staged by `bench-deploy.sh --ref`. Captured 2026-10-11 13:11-13:12Z.

The plan and the position are synthetic, written over netfix to the bench's
real fix-gateway (`dev` @ `0abda9d`, `flightplan` + `compute` + `netfix`).
X-Plane was not feeding the bench (`LAT`/`LONG` flagged old beforehand). The
route is the FP7 HSI check's KSBA > GVO > RZS > KSMX (`../fp7_hsi/hsi_chain_points.py`),
with leg 2 (KSBA-GVO) active. The aircraft sits 0.5 nm RIGHT of the leg midpoint,
with `MAGVAR 0`, `GS 120`, `GPSSRC 0` and `NAVSRC 2`. The `*.keys.txt` files are the
bus values read back at the moment of each capture.

- `fp7_pfd_hsi_gps.png` is the live `managed.yaml` PFD. The HSI is on GPS (`CRS 297°`,
  `COURSE 296.98`). The deviation bar is LEFT of the course line, which is
  correct for a position right of track (`CDI -0.49`). TO is shown, and the map
  tab shows the magenta KSBA-GVO leg. `HDG 000°` and the north-up rose are
  there only because nothing drives `HEAD` on the bench. They are not a defect.
- `fp7_pfd_hsi_gps_zoom2x.png` is the HSI from that frame, enlarged 2x with
  nearest-neighbour scaling.
- `fp7_flightplan_nav_status.png` is #285's stock FLIGHTPLAN screen with
  the `nav_status` chip under the map: `LEG  KSBA > GVO > RZS  7.0 NM  0:03  TERM`.
  It agrees with the bus (`WPFROM KSBA`, `WPNAME GVO`, `WPNEXT RZS`,
  `WPDIS 6.98`, `WPETE 209` s).
- `fp7_nav_status_chip_zoom2x.png` is the chip strip from that frame, enlarged 2x
  with nearest-neighbour scaling.

## Regenerate

`fp7_glass.sh` is the exact script that ran. On the bench, with #285 staged:

```bash
cd ~/bench-scratch/aer3036
timeout 900 flock -o -w 900 /tmp/pyefis-bench.lock sh fp7_glass.sh
```

The script snapshots and puts back everything it changes:
- the live `main/default.yaml` (`defaultScreen` is switched per shot),
- `screens/flightplan.yaml` (#285's copy, which carries the chip, is swapped in),
- the stored flight plan (re-published, so the engine returns to mode `NONE`),
- the scalar keys it writes.

pyEfis boots onto the NAVIGATION DATA status screen, so the script taps
Continue (`xdotool`) before each capture.
