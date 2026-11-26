# SVSFLOOR1: X-Plane runway heights against NASR and GLO-30

Three sim-bench sessions on 2026-11-26 (X-Plane 12, default scenery), each an
RNAV approach and the missed approach out over the runway. A KAST RNAV 26
session also ran; it ended in a driver error before the approach ("autopilot
did not couple") and logged no runway crossing.

| Session | Profile |
|---|---|
| `8c204d34b5ca` | `profile-ksmx-r30.yaml` |
| `720386699308` | `profile-kded-r30.yaml` |
| `c0a68c707b21` | `profile-kssf-r28.yaml` |

`agl_log.py` ran on the Beelink during each session (armed by `sim_follow.py`)
and polled fix-gateway at 5 Hz for LAT, LONG, ALT and AGL. The bench maps ALT to
`sim/flightmodel/position/elevation` and AGL to `sim/flightmodel/position/y_agl`,
so ALT - AGL is X-Plane's own ground under the aircraft. The logs are
`agl-*.csv.gz`. The columns are time, then each key's value and flags.

`analyze.py` keeps the samples inside a NASR runway polygon (the threshold-to-threshold
rectangle at the published width, as the SVS draws it). For each sample it compares
X-Plane's ground with the NASR surface interpolated between the thresholds, and with
GLO-30 at the same point. Run it from a pyEfis checkout on the Beelink, with `xp/`
holding one directory per session:

    ~/pyefis-venv/bin/python analyze.py ksmx-r30 kded-r30 kssf-r28

The output is in `survey.txt`. `f` is the fraction along the runway from its first threshold.
