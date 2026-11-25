# CERT20b: one hot-soak, full-load timing run on the bench Pi 5

Measured 2026-11-24 on the Pi 5 hardware bench (`pyefis`, 10.110.10.199), board issue
AER-6451, BACKLOG `CERT20b`. Platform records come from CERT20a's `describe_platform()`
(`tools/evidence_sidecar.py`, AER-6324).

## Result

**Verdict: the PFD keeps its rate on the bench Pi 5 at room ambient.** All SVS screens pass
the pass line Bill set on 2026-11-25 (see "Pass line"). Throttling was not reached, and testing
at the thermal limit is out of scope for this bench. It belongs to environmental testing on
flight-ready hardware, later in the program.

- **The SoC never reached its thermal limit, and never throttled.** Under the full stack the
  SoC rose from 54.6 C to a plateau of about 62-66 C (one-minute means), with a highest single
  sample of 68.3 C. The run stopped on the plateau rule after 32 min. The `get_throttled` "now"
  bits were 0 in all 997 samples, every 2 s from launch to stop. The Pi 5 starts reducing its
  clock at a soft limit of about 80 C and drops to its lowest clock at 85 C (Raspberry Pi,
  "Heating and cooling Raspberry Pi 5", raspberrypi.com/news/heating-and-cooling-raspberry-pi-5). So this run answers "does the stack heat its own SoC into throttling on this bench?":
  **no**. It does not answer the hot-cockpit case, an SoC held at its limit (see "Scope").
- **Cool and hot windows are the same within noise.** Frame intervals, paint times and ROLL
  data-to-glass agree between the first 10 min and the last 10 min to about 1 ms at the median,
  and to a few ms at p99 (table below). Nothing in the numbers moves with temperature over this
  range.
- **The SVS screens run at about 23-24 frames/s, not 30.** PFD, PFD_AI_ONLY and MAP_CTL_TEST
  (the three screens with SVS) have a median frame interval of 41-44 ms in both windows, p99
  60-71 ms, worst gap 73-97 ms outside a screen switch. The screens without SVS hold the 30 Hz
  frame clock (median 32.8-33.1 ms).
- **ROLL data-to-glass on the SVS screens: median 61-66 ms, p99 96-104 ms, max 123-145 ms.**
  This is measured from the feed's timestamp just before it sent the value to fix-gateway, to
  the end of the Qt update that composed and swapped the first frame showing it. It includes
  the gateway hop and pyEfis, and it does not include a sensor or the panel's scanout (up to
  16.7 ms more at 60 Hz). On the screens without SVS it is 26-45 ms at the median.
- **A screen switch costs one long frame.** The first 2 s after a switch to an SVS screen hold
  gaps up to 455-652 ms on its first visits (the SVS GL renderer and heightmap are built again
  each time the screen is shown, `SVSGLRenderer initialised ... heightmap built` in the journal
  at each visit), and 115-204 ms on later visits. These are reported separately, not hidden.

Two reference points. Neither is the pass line, which is Bill's (see "Pass line"). AC 25-11B section 5.9: "Data update rates for information elements
used in direct airplane or powerplant manual control tasks (such as attitude ...) equal to or
greater than 15 Hertz have been found to be acceptable", and "display system lag (including the
sensor) for attitude that does not exceed a first order equivalent time constant of 100
milliseconds ... is generally acceptable." AC 23.1311-1C (page 44) asks for attitude, heading
and air data "at a rate of at least 15 Hz". The 100 ms in AC 25-11B is a first-order time
constant that includes the sensor. It is not a p99 latency and cannot be compared directly with
the p99 numbers here.

## The stack under test

| | |
|---|---|
| Board | Raspberry Pi 5 Model B Rev 1.1 (BCM2712, 4x Cortex-A76), revision d04171 |
| Cooling as fitted | **No fan or active cooler.** There is no `cooling_fan` device and no thermal `cooling_device`. Whether a passive heatsink or a case is fitted cannot be seen from software. Bill can say. |
| Ambient | Not measured. The NVMe drive read 32.9-33.9 C throughout, the only other temperature on the box. |
| CPU state (start and end) | 4 cores online, affinity 0-3, `cpufreq-dt`, governor `ondemand`, 1500-2400 MHz. Identical in all three platform records (`run_soak2/platform_*.json`). |
| Throttle state going in | `get_throttled=0xe0000`: ARM frequency capping, throttling and the soft temperature limit have all occurred since the last boot (30 days earlier), none of them now. Only the "now" bits are judged here. |
| pyEfis | `~/pyEfis` as it was on the bench, `4d3c6d10` (branch `aer-6415/cas4-aural-tone`, AER-6415's staging, which is dev plus CAS3 and CAS4), `QT_QPA_PLATFORM=eglfs`, the bench's own config (`~/makerplane/pyefis/config`, unchanged). |
| fix-gateway | `66dc8eb7` (dev), `fixgw.service` as running, not restarted. Plugins enabled: NETFIX, SYSTEM, ANNUNCIATE, COMPUTE, CAS, FLIGHTPLAN. No attitude or position source is enabled on this bench, so the feed below supplied them. |
| Screens | All 9 in the bench's list, 15 s each, in order: DataStatus, SIXPACK, PFD, PFD_AI_ONLY, RADIO, EMS, EMS2, MAP_CTL_TEST, About. An AI paints on six of them. SVS range as configured: 30 NM. |
| Load | A synthetic 3 NM orbit at 120 kt and 5500 ft about KSBA through the bench gateway: ROLL and PITCH at 25 Hz, LAT, LONG, ALT, HEAD, TRACK, GS, IAS, TAS, VS at 5 Hz. pyEfis used 40-42% of one core, fix-gateway 1.6%, the whole box 11% of four cores. |

## Results

Cool = the first 600 s after the feed started (SoC 54.6-67.8 C, mean 61.7 C). Hot = the last
600 s before the stop (58.4-68.3 C, mean 64.5 C). The SoC temperature swings about 3 C with
the screen cycle, because the SVS screens load the SoC more than the others. All times are ms.

| Screen | Window | Interval median | p99 | max gap | max in first 2 s after switch | Paint median / p99 | ROLL data-to-glass median | p99 | max |
|---|---|---|---|---|---|---|---|---|---|
| PFD | cool | 44.1 | 60.2 | 76.0 | 455.1 | 7.4 / 15.0 | 65.9 | 96.8 | 114.4 |
| PFD | hot | 43.9 | 63.7 | 73.1 | 114.6 | 7.5 / 14.7 | 65.6 | 100.5 | 145.0 |
| PFD_AI_ONLY | cool | 41.8 | 69.2 | 87.9 | 547.6 | 5.5 / 37.1 | 63.3 | 104.2 | 132.6 |
| PFD_AI_ONLY | hot | 42.3 | 65.6 | 95.5 | 166.4 | 5.4 / 36.1 | 63.0 | 95.8 | 125.0 |
| MAP_CTL_TEST | cool | 40.7 | 67.3 | 85.7 | 651.8 | 5.3 / 36.0 | 61.6 | 98.9 | 123.0 |
| MAP_CTL_TEST | hot | 41.7 | 70.8 | 96.5 | 203.7 | 5.4 / 36.2 | 63.2 | 103.3 | 123.0 |
| SIXPACK | cool | 33.1 | 98.8 | 100.2 | 99.7 | 5.7 / 6.4 | 25.8 | 42.2 | 48.2 |
| SIXPACK | hot | 33.1 | 98.5 | 99.7 | 99.1 | 5.7 / 6.2 | 25.6 | 42.0 | 47.2 |
| RADIO | cool | 32.8 | 47.4 | 91.9 | 563.0 | 7.3 / 13.6 | 44.3 | 68.8 | 90.8 |
| RADIO | hot | 32.8 | 47.6 | 62.8 | 140.8 | 7.1 / 14.0 | 45.2 | 71.3 | 89.2 |
| EMS | cool | 32.8 | 46.1 | 84.7 | 176.9 | 7.1 / 12.0 | 43.1 | 66.8 | 86.9 |
| EMS | hot | 32.8 | 47.4 | 54.6 | 115.1 | 7.0 / 13.0 | 44.6 | 69.6 | 99.0 |

All AI screens together, outside switches: interval median 35.8 / 36.7 ms (cool / hot),
p99 66.9 / 66.7 ms, max 100.2 / 99.7 ms. ROLL data-to-glass median 49.7 / 50.8 ms, p99
92.9 / 92.6 ms, max 132.6 / 145.0 ms, over 7,840 / 8,110 timed values. 927 of 8,768 and 996 of
9,106 written values were never shown because a newer value arrived before the next frame, as
expected with a 25 Hz feed into a 23-30 Hz display.

How to read three columns:

- **SIXPACK's p99 of 99 ms is not render cost.** Its AI has no SVS, and it repaints only when
  the pose changed. Its intervals cluster at 33, 66 and 99 ms: frame-clock ticks that had no new
  attitude, because the feed is 25 Hz against a 30 Hz clock. The SVS screens repaint every tick,
  because the interpolated position changes every tick.
- **Data-to-glass is higher on the SVS screens by about one frame,** because those frames take
  longer and the swap waits for the display.
- **Paint p99 of about 36 ms on PFD_AI_ONLY and MAP_CTL_TEST** is the occasional paint that
  waits on the GPU. On those screens, between 26% and 58% of paints are composed by the *next*
  Qt update rather than inside their own (`composed_in` in `results.json`). The latency
  measure follows the frame to whichever update composed it.

Temperature, one-minute means from the feed start (C):

```
min  0-9 : 56.1 57.4 62.2 60.0 64.0 60.7 63.1 63.2 62.4 65.1
min 10-19: 61.4 64.9 61.6 65.5 62.6 64.7 64.6 63.7 65.8 62.1
min 20-29: 65.3 62.5 66.5 63.2 65.3 64.4 63.6 65.7 62.1 65.7
min 30-32: 62.4 66.1 64.8
```

## Pass line

Set by Bill on 2026-11-25 (AER-6451, the pass-line card accepted, with his notes on the issue).
It applies to every SVS screen, PFD, PFD_AI_ONLY and MAP_CTL_TEST, in both windows:

| Limit | Worst measured (screen, window) | Verdict |
|---|---|---|
| Median frame interval 66.7 ms or less (15 Hz) | 44.1 ms (PFD, cool) | pass |
| p99 frame interval 100 ms or less | 70.8 ms (MAP_CTL_TEST, hot) | pass |
| Longest gap 150 ms or less, outside a screen switch | 96.5 ms (MAP_CTL_TEST, hot) | pass |
| ROLL data-to-glass p99 120 ms or less | 104.2 ms (PFD_AI_ONLY, cool) | pass |
| Hot window at most 10% worse than cool | +5.8% (PFD, p99 frame interval) | pass |

The 10% rule applies to three metrics on each SVS screen: median frame interval, p99 frame
interval and ROLL data-to-glass p99. Hot against cool, in percent:

| Screen | Median interval | p99 interval | ROLL p99 |
|---|---|---|---|
| PFD | -0.6 | +5.8 | +3.8 |
| PFD_AI_ONLY | +1.2 | -5.3 | -8.0 |
| MAP_CTL_TEST | +2.5 | +5.2 | +4.4 |

The longest gap and the maximum latency are held to their absolute limits only. A single
worst sample in a 10 min window is too noisy for a relative rule.

Three things the line does not say:

- **The latency line covers the display only.** The 120 ms is data-to-glass inside pyEfis and
  the gateway hop, from the gateway's input to the buffer swap. No sensor latency is in it.
  Whether the full sensor-to-glass path meets AC 25-11B's 100 ms is unverified until a
  source's own latency is measured. A source can exceed that budget on its own: CERT13h2's
  late OnSpeed altitude is one. "Passes the latency line" is not a statement about the whole
  path.
- **It is a room-ambient result.** The SoC plateaued at 62-68 C, about 12 C under the 80 C soft
  limit, and never throttled. The record says "keeps its rate on the bench Pi 5 at room
  ambient". It does not say "keeps its rate at the thermal limit".
- **It changes nothing installed.** Whether an installed configuration should fix a governor,
  pin cores or require a cooler is a separate decision of Bill's, not taken here.

## Scope and not covered

- **The SoC at its thermal limit is out of scope now** (Bill, 2026-11-25). This bench, as fitted
  and at room ambient, plateaus 12 C below where the Pi 5 starts throttling. Hot-soak and
  thermal-limit testing comes later in the program, as environmental testing on flight-ready
  hardware, not on this bench.
- **Sensor and scanout.** Data-to-glass starts at the gateway's input and ends at the buffer
  swap. A real AHRS adds its own filter and link delay before the gateway, and the panel adds up
  to one 60 Hz refresh. The Pi has no root access for `kmsgrab`, so the scanout was not read.
- **Other attitude keys.** PITCH and the rest arrive on the same path, but only ROLL was timed.
- **A sustained single screen.** Each screen showed for 15 s per cycle, so the SVS screens
  carried about a third of the run. A PFD left up for the whole flight would heat the SoC a
  little more than this cycle did (the SVS screens are the hot part of the 3 C swing).

## How it was run

Everything runs on the Pi under `~/bench-scratch/aer6451/` from the scripts in `tools/`. The
pyEfis checkout, its config and the gateway config are not touched. The orchestrator stops
`pyefis.service`, runs the same checkout under the probe as a transient user unit, and starts
`pyefis.service` again however the probe ends (an `ExecStopPost`, and its own exit trap).

```sh
# on the Pi; the run needs about 35 min to 3 h
systemd-run --user --unit=cert20b-orch -p RuntimeMaxSec=12600 \
  -E MIN_S=1800 -E MAX_S=10800 -E HOT_S=600 -E PLATEAU_C=0.5 -E WARM_S=90 \
  /bin/sh $HOME/bench-scratch/aer6451/tools/run_soak.sh soak2
# anywhere, on the copied run directory
python3 tools/analyze_soak.py run_soak2 --json run_soak2/results.json
```

- `tools/soak_probe.py` runs the real `pyefis.main.main()` with timestamps on every AI
  `paintEvent` (with the roll it painted), every `UpdateRequest` in the application, and
  `setRollAngle`, plus the 15 s screen cycler. It changes no pyEfis source.
- `tools/soak_feed.py` writes the orbit over netfix and logs each ROLL value with its send time.
- `tools/soak_thermal.py` samples temperature, the firmware ARM clock, `get_throttled`, load
  and process CPU every 2 s.
- `tools/run_soak.sh` sequences the run and applies the stop rule: throttled for 10 min, or no
  new one-minute temperature high above +0.5 C for 10 min, not before 30 min, and at 3 h
  regardless. This run stopped on the plateau rule at 1,924 s.
- `tools/analyze_soak.py` produces `run_soak2/results.json`, which every number above comes
  from. Every timestamp in the three logs is `CLOCK_MONOTONIC`, so they join with no alignment.

`run_soak2/` holds the raw logs (`probe.csv.gz`, `roll_writes.csv.gz`, `thermal.jsonl`), the
three platform records, the orchestrator log and the results. Two earlier dry runs (4 min each)
checked the pipeline. One aborted run (65 s) was stopped by hand to widen the UpdateRequest hook
from the Main widget to the whole application. None of them is used here.
