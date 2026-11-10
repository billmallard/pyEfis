# AER-5266 (P3b) bench evidence: ADS-B traffic on the moving map

Beelink bench, 2026-11-09, pyEfis `aer-5266/p3b-traffic-layer` @ `2ae9954`,
fix-gateway `dev` @ `0b7425a`. Live PFD screen (`managed_PFD.yaml`), map
panel cropped from a full-screen x11grab of the glass, 10 NM north-up.

The path is the real one end to end: synthetic GDL90 over UDP into
fix-gateway's stratux plugin, whose traffic writer fills the `TFC` block,
which pyEfis reads over netfix. Nothing was written to a `TFC` key by hand.

| File | What it is |
|---|---|
| `live_t12_map.png` | 12 s into the injection: every target live |
| `stale_t22_map.png` | 22 s: the stale target's reports stopped at 18 s; its `TFC4TGT` is `old` (see `bus_t22.txt`) |
| `traffic_zoom_2x.png` | the two frames side by side (left t=12, right t=22), cropped round the traffic and scaled 2x nearest-neighbour |
| `bus_t12.txt`, `bus_t22.txt`, `bus_end.txt` | netfix reads of the block at each grab and after the run (third field = flags: `o` old, `b` bad) |
| `inject.log` | the injector's own output |

The targets (relative to ownship at 34.4258, -119.8415, true track 034,
`PALT` 4,500 ft):

| Tag on glass | State | What to see |
|---|---|---|
| `+05` | normal | filled white arrowhead |
| `-03` | traffic alert (`ALRT = 1`), climbing 1,000 fpm | yellow, flashing: filled at t=12, open at t=22; up arrow |
| `+15` | degraded (NIC 3, NACp 3) | open outline |
| `+08` | stale (reports stopped) | filled white at t=12; grey dashed outline at t=22; down arrow (-576 fpm) |
| `--` | altitude invalid (`ddd = 0xFFF`, `TFC5ALT` bad) | tag dashed |
| `-12` | track not valid (`m` = 00, `TTYP = 0`) | diamond, non-directional |

Not part of this change: the ownship arrow points along `TRACKM` (022) on a
true-north map, while targets use true track. The 12 deg difference is the
bench's `MAGVAR`.

## Reproduce

On the Beelink, with the branch staged (`bench-deploy.sh --ref ...`), under
the bench lock:

1. Back up `~/makerplane/fixgw/config/preferences.yaml.custom` and add
   `STRATUX: true` under `enabled:`. Then `sudo systemctl restart fixgw` and
   `systemctl --user restart pyefis`. Wait for the startup banner to clear
   (about 30 s).
2. Run the injector. It also writes ownship position over netfix, because
   no simulator is running:
   `~/pyefis-venv/bin/python ~/src/pyEfis/tools/bench_traffic_inject.py --ownship --lat 34.4258 --lon -119.8415 --alt 4500 --track 34 --seconds 34 --warmup 18`
3. Grab the glass at t=12 and t=22:
   `ffmpeg -f x11grab -draw_mouse 0 -video_size 1920x1080 -i :0 -frames:v 1 out.png`.
   Crop the map with `(1255, 0, 1920, 1080)`.
4. Restore the backup and restart fixgw and pyefis.

The stale window is about 3 s to 10 s after the target's last report. It
goes `old` at the 3 s `tol` and is evicted at the writer's `evict_s`.
`python3 tools/bench_traffic_inject.py --selftest` checks the encoder against
the GDL90 ICD vectors (G§2.2.4, G§3.5.2).

The session script that ran this is `aer5266_session.sh` beside this file.
