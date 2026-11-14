# AER-5670 (FPLWRITE2): FixBridge._notify on the Beelink GUI thread

pyEfis #480. The question: after #481, what share of the GUI thread does
`FixBridge._notify` (the bus write callback, every listener under it) still
take, and is it under 2% with this branch?

## Result

Share of GUI-thread wall samples inside `FixBridge._notify` (py-spy, 250 Hz,
30 s, `--idle`). A = `dev` 1c39a1fc, B = this branch at the head shown.
Runs are in time order, all on 2026-11-14 between 21:59Z and 22:28Z.

| run | build | `_notify` | ms per second |
|-----|-------|----------:|--------------:|
| A_1 | dev 1c39a1fc | 9.97% | 99.7 |
| B_1 | 088b324d (lazy engine, keyed listeners, map skip) | 2.00% | 20.0 |
| B_2 | cb71c93f (+ item cache, relay pre-check) | 1.84% | 18.4 |
| A_2 | dev 1c39a1fc | 11.40% | 114.0 |
| B_3 | b52ab61f (+ cached slot rows, whole check before the signal) | 1.59% | 15.9 |
| A_3 | dev 1c39a1fc | 12.71% | 127.1 |
| B_4 | 053ee2cd (+ FPLCRS compared to 0.1 deg) | 1.23% | 12.3 |
| A_4 | dev 1c39a1fc | 12.15% | 121.5 |
| B_5 | 053ee2cd | 1.17% | 11.7 |

Two independent counts agree on every run: `timeline.py` (the FPLWRITE1
script on the Beelink, `~/perf/2026-11-14-svs-slow/`, md5 in `summary.txt`)
and `under_notify.py` here. `summary.txt` has both for all nine runs.

## How it was measured, and how it differs from FPLWRITE1's A/B

The bench was held by another run's staged review (`aer-5671/boot1-ground-data-status`,
from 21:53Z), so nothing here restarted or restaged the kiosk. The kiosk ran
throughout. Instead:

- **Gateway:** a private fixgw (`stack.sh gw-up`) on 127.0.0.1:3492, from the
  bench's own fix-gateway checkout (`dev` 6a0adc6) with the live config copied
  and XPLANE, KNOBSTER, DEMO, CANFIX and the other source plugins off. Its
  flight plan engine restored the bench's own route from the copied
  `flightplan_state.json`: KSBA-KSMO, 18 slots, LEG, active leg 11, loaded.
- **Aircraft:** synthetic, not X-Plane (no session was available; the queue only
  flies 23:00-06:00 Central). `fly.py` writes the keys of the bench's standing
  X-Plane RREF block at 10 Hz. It flies the first 80% of the active leg
  (DARTS -> MOVVE) at 120 kt, 4500 ft, wings level, over and over. The engine computed
  throughout: WPDIS counted down, XTK about 0, and FPLCRS moved in the
  fourth decimal each cycle, as it does in flight.
- **Display:** pyEfis from a clone of A or B on Xvfb `:57` (1920x1080), with the live
  pyEfis config copied (FixPort moved to 3492), so the panel is the same:
  the map and SVS paint, and both `flight_plan` widgets stay hidden as on the
  bench. The SVS renders through llvmpipe there, not the Intel GPU, so the
  paint shares are not comparable with the kiosk's. The `_notify` share is
  the callback's own wall time.
- **Measure:** `measure_pid.sh` is `measure.sh` aimed at an explicit pid and
  port 3492, with a 30 s capture instead of 15 s. Each pyEfis was 75 s old when
  measured, and each run started a fresh process.

Box load (the convention in `docs/bench_measurement_convention.md`): load
average 4.8-5.6 on 4 cores during the runs. The live kiosk pyEfis and fixgw
were up and active, with the A/B instance, llvmpipe and other agents' idle followers
beside them. A and B paid the same load, interleaved.

## Reproduce

On the Beelink, in `~/bench-scratch/aer5670/` with these files:

```sh
sh stack.sh setup        # clones A (1c39a1fc) and B (the branch); copies configs
sh stack.sh gw-up
sh ab.sh 1 A B           # starts fly.py on 3492 if needed; measures each variant
python3 under_notify.py out/B_1.json
kill $(cat fly.pid); sh stack.sh gw-down; kill $(cat stack/xvfb.pid)
```

`ab.sh` needs `~/bench-scratch/aer4464/nfx.py` (netfix client) and
`~/perf/2026-11-14-svs-slow/timeline.py` on the box.
