# BOOT1 ground-boot captures (AER-5671)

Beelink bench (X11, 1920x1080), 2026-11-14, pyEfis staged at branch
`aer-5671/boot1-ground-data-status` with `bench-deploy.sh --ref`. fix-gateway
`dev`, `IAS.Vgnd` = 40 kt as served by the bench's `database/ahrs.yaml`.
X-Plane was not running, so the XPLANE plugin wrote no IAS or GS.

| File | What it shows | Journal |
|---|---|---|
| `beelink_ias_old_boot_flight.png` | Boot with IAS flagged old (no feed): flight screen, startup notice banner over it, 9 s after the restart. | `boot: no valid airspeed within 3.0 s; booting the flight screen` |
| `beelink_ground_boot_data_status.png` | Boot with IAS 0.0 and GS 0.0 valid on the bus: Data Status, with the CERT17 PANEL CHANGED notice (config v50 not yet acknowledged on this bench), 12 s after the restart. The 8 s startup banner had cleared. | `boot: on the ground; booting data status` |
| `beelink_after_ias_crossed_vgnd.png` | 11 s after that boot another session's synthetic flight began writing IAS 112 / GS 120. Data Status left for the flight screen without a touch. | `boot: aircraft moving; leaving data status for PFD` |

The first frame is the deploy's own banner frame (`~/bench-deploy-banner.png`).
The other two come from `ground_boot_capture.sh` in this directory, run under
the bench lock:

    scp ground_boot_capture.sh pyefis@10.110.10.241:bench-scratch/aer5671_capture.sh
    ssh pyefis@10.110.10.241 'flock -w 900 /tmp/pyefis-bench.lock sh ~/bench-scratch/aer5671_capture.sh'

It feeds IAS and GS over netfix at 5 Hz, restarts `pyefis.service`, and grabs
the glass with ffmpeg x11grab. Its later steps (IAS 25 kt, then 45 kt) were
overtaken by the other session's flight, so the crossing on the glass is
0 -> 112 kt rather than the scripted 25 -> 45 kt. The scripted crossing is
covered by `tests/test_ground_boot.py`.
