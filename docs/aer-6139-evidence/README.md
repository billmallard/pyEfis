# AER-6139 (SVSTFC1) evidence: ADS-B traffic in the synthetic vision

Real GL renders of the SVS with traffic, through the production draw path
(`SVSGLRenderer._render_overlays`), captured with `tools/svs_capture.py`
at pyEfis `ce118355` (each PNG's `.json` sidecar names the commit and the
exact command).

The first set (`sandbox_*`) is sandbox GL: Mesa llvmpipe (software) under
Xvfb, 800x480, no MSAA, made while both benches were held by the 72 h
show-unit soak (AER-5995). The second set (`bench_*`, below) is the bench run
the definition of done asks for, made on 2026-11-21 once the soak passed.

| File | What it is |
|---|---|
| `sandbox_svs6.png` | Over Santa Barbara at 4,500 ft, heading 034: the six P3b states inside the forward fan |
| `sandbox_svs6_zoom2x.png` | the target band of that frame, 2x nearest-neighbour |
| `sandbox_ridge20.png` | 2,000 ft, heading 000, the Santa Ynez ridge (about 2,600 ft at 4.5 NM) ahead: the six states plus 14 more targets, 20 in all |
| `sandbox_ridge20_zoom2x.png` | the target band of that frame, 2x nearest-neighbour |
| `sandbox_ridge_none.png` | the same pose with no traffic, to show where the ridge is |

The six states (relative to ownship's pressure altitude, `PALT` = the
commanded altitude):

| Tag | State | What to see |
|---|---|---|
| `+05` | normal, 2.5 NM, 12 deg left | filled white arrowhead, pointing along its track relative to our heading |
| `-03` | traffic alert (`ALRT = 1`), climbing 1,000 fpm | yellow; flashes filled/open (the frame caught one phase); up arrow |
| `+15` | degraded (NIC 3, NACp 3) | open outline |
| `+08` | stale (`TFCkTGT` `old`) | grey dashed outline; down arrow (descending 600 fpm) |
| `--` | altitude invalid (`TFCkALT` `bad`) | tag dashed; drawn at ownship level (the co-altitude assumption) |
| `-12` | no track (`TTYP = 0`) | diamond, non-directional |

In `sandbox_ridge20.png` the ridge (magenta: terrain above us, see
`sandbox_ridge_none.png`) crosses the whole view at about 4.5 NM. The
three `-20` targets, 4.9 to 6.0 NM out, are at sea level and the `-08`
ones at 1,200 ft, beyond and below the ridge line from 2,000 ft: terrain
would hide them, and they are drawn over it.

## Reproduce

Terrain is public Copernicus GLO-30, fetched and converted with the repo's
own tools:

```sh
python tools/fetch_glo30.py --dest glo30raw --tiles N33W120 N34W120 N34W121 N35W120 N35W121
python tools/convert_glo30.py --src glo30raw --dest tiles
```

Then, on any display with GL (the sandbox used Xvfb + `QT_QPA_PLATFORM=xcb`):

```sh
python tools/svs_capture.py --out sandbox_svs6.png --lat 34.4258 --lon -119.8415 \
    --alt 4500 --heading 34 --traffic svs --tiles tiles --nasr "" --dof "" --water "" \
    --offscreen --width 800 --height 480 --range 20
python tools/svs_capture.py --out sandbox_ridge20.png --lat 34.4258 --lon -119.8415 \
    --alt 2000 --heading 0 --traffic svs --traffic-extra 14 --tiles tiles \
    --nasr "" --dof "" --water "" --offscreen --width 800 --height 480 --range 20
```

`--traffic svs` seeds the mock FIX db with the bench injector's scenario
(`tools/bench_traffic_inject.py --layout svs`), written the way the
gateway's traffic writer writes it. On a bench, the same scene over the
real path is `bench_traffic_inject.py --layout svs --extra 14 --ownship`
into fix-gateway's stratux plugin (see `docs/aer-5266-evidence/README.md`
for enabling it).

## Bench run, 2026-11-21 (DoD 2 and 3)

pyEfis `aer-6139/svs-traffic` @ `dbdc299` on both boxes; fix-gateway `dev`
@ `16282cd`. The traffic path is the real one: GDL90 over UDP from
`tools/bench_traffic_inject.py` into fix-gateway's stratux plugin, whose
traffic writer fills the `TFC` block, read by pyEfis over netfix. Nothing
wrote a `TFC` key by hand. STRATUX was enabled for the session only and
reverted by it (`preferences.yaml.custom` byte-identical to its backup
afterwards). The scripts that ran are in `bench/`.

| File | What it is |
|---|---|
| `bench_beelink_t12.png` | Beelink glass (x11grab, 1920x1080), live PFD screen, 12 s into the P3b fixture (`--layout svs`) |
| `bench_beelink_t22.png` | 22 s: the stale target's reports stopped at 18 s; `TFC4TGT` is `old` (`bench/glass_t22.txt`) |
| `bench_beelink_t12_t22_zoom2x.png` | the AI band of the two frames (top t=12, bottom t=22), 2x nearest-neighbour |
| `bench_beelink_20targets.png` | Beelink glass during a frame-rate run with 20 targets |
| `bench_pi5_six_states.png`, `bench_pi5_20targets.png`, `bench_pi5_no_traffic.png` | Pi 5 GL captures (V3D, eglfs, `svs_capture --offscreen --traffic svs`, 800x480) at the Beelink run's position, 4,500 ft, true heading 320 |
| `bench/glass_t12.txt`, `glass_t22.txt`, `glass_end.txt` | netfix reads of the block and ownship keys at each grab (third field: `o` old) |
| `bench/A0_*.jsonl`, `bench/B20_*.jsonl`, `bench/session.log` | the frame-rate runs, one record per 5 s |

**The Beelink glass.** Ownship flies the MAPPAINT1 feed (Smokies, 4,500 ft,
track 308, 136 kt; `PALT` follows `ALT` at 29.92). At t=12, three of the six
targets are in the SVS's view: `+08` filled white (still reporting), `-03`
yellow with its climb arrow (alerted, inside 2 NM so drawn larger), and `--`
(altitude invalid, at our level, partly under the airspeed tape). At t=22
`+08` is grey and dashed, and `-03` has flashed to its open phase. The map
on the right shows the same targets. The other three are outside this
panel's view: the AI is about 1248x1080, so its terrain field of view is
about 35 deg, and the feed's `HEAD` and `MAGVAR` put the nose 12 deg right
of track. The Pi 5 frames, at a 5:3 aspect, show all six.

**Frame budget (DoD 3).** The AER-5934 in-process probe (no profiler),
which counts AI paints and frame-clock ticks, was given a counter of targets
drawn per frame (`bench/mkprobe.py`). Each run: restart, MAPPAINT1 feed from
20 s, 60 s window from 75 s of uptime, the live PFD/map panel. Arms
interleaved A, B, A, B on a quiet box (load 0.5 to 0.7). B adds
`bench_traffic_inject.py --layout svs --extra 14` ahead along the track.

| Run | Targets drawn (median per frame) | SVS paints/s | AI paint p90 | GUI thread CPU |
|---|---|---|---|---|
| A0_1 | 0 | 30.69 | 8.5 ms | 43.3 % |
| B20_1 | 20 | 30.33 | 10.2 ms | 48.9 % |
| A0_2 | 0 | 30.58 | 8.5 ms | 44.5 % |
| B20_2 | 20 | 30.42 | 10.2 ms | 47.7 % |

20 targets cost 0.26 paints/s (30.64 to 30.38), within the 1 fps limit. The
SVS runs at its 30 Hz frame clock with headroom in both arms, so the rate
alone understates the cost. The cost is 1.7 ms on the AI paint's p90 and
about 4.4 points of GUI-thread CPU.

Reproduce: stage the branch (`bench-deploy.sh --ref aer-6139/svs-traffic`),
copy `bench/` to `~/bench-scratch/aer6139/` on the Beelink, build the probe
with `python3 mkprobe.py ../aer5934/probe_launch.py probe_launch.py`, then
`flock -w 900 /tmp/pyefis-bench.lock sh session6139.sh`. On the Pi 5:
`flock -w 300 /tmp/pyefis-bench.lock sh pi6139.sh`.

