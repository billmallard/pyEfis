# AER-5418 (TURN3) on the bench: the fly-by turn at HENER on the map

The live Beelink bench, staged with `bench-deploy.sh --ref` (owner AVIONICS,
issue AER-5418): fix-gateway `aer-5418/turn3-map-arc` e73d97a and pyEfis
`aer-5418/turn3-map-arc` d96ee1e. The deploy refreshed the bench's
`database/flightplan.yaml`, which now carries `FPLfTA`. The replay is the one
AER-4675 and AER-4715 used: X-Plane's recorded trajectory through the 61 deg
fly-by at HENER on V27 (trace t = 100-200 s of fix-gateway
`tests/sim/fixtures/sim2b_v27_xplane_2026-11-01.csv.gz`, at its recorded
5 Hz). The golden route KSBA GVO V27 AVOLS KSMX goes out through pyEfis's
FixBridge, followed by `ACT 6`, the leg DEANO -> HENER. X-Plane was not
running, so the trajectory is X-Plane's and the engine and the glass are live.

The map is zoomed from 10 nm to 2.1 nm with seven mouse-wheel notches. The
live screen (`managed.yaml`) binds no `MAPRANGE`. The replay holds the
position at four points and grabs the whole screen (x11grab) on the Map tab,
twice, two seconds apart. The second grab is the one used, so the HSI and the
map come from the same frame.

`hsi_map_through_hener.png`: the HSI and the map at each hold, this branch.

`map_before_after_hener.png`: the map at each hold, pyEfis `dev` ab870309
(left) against this branch (right). Same replay, same bench, same gateway
branch. Only the pyEfis checkout was switched (`--restore=pyEfis`, then
`--ref` again).

What the engine published at each hold (`bench/events_branch.log`):

| Point | Trace t | `FPLCRS` | `FPLCDI` | `FPLACTLEG` | `FPL6TA` |
|---|---:|---:|---:|---|---:|
| before turn start | 160.1 | 073 | -0.001 | 6 (HENER) | 0.46 |
| just past turn start | 166.0 | 134 | -0.002 | 6 (HENER) | 0.46 |
| in the turn, before the bisector | 170.7 | 134 | -0.007 | 6 (HENER) | 0.46 |
| past the bisector | 177.2 | 134 | -0.019 | 7 (VTU) | 0.46 |

Full scale is 2 nm (ENR). `FPL6TA` is HENER's turn anticipation: 0.46 nm at
the trace's groundspeed on a 15 deg bank. It was fixed at turn start and held
past the bisector until the arc's end. In every hold the aircraft is on the
magenta arc. The magenta part runs to the arc's apex while HENER is active and
from the apex once VTU is. From the course change to the end of the replay,
`FPLCDI` stayed between -0.028 and -0.001 (`bench/hener_bus_branch.csv`). The
trajectory is X-Plane's, flown at about 17 deg of bank at HENER (XPB-001), so
it is not exactly the engine's arc.

The HSI's `HDG` box reads 000 because it is the heading bug, which the replay
does not set. The replay writes `HEAD` from the trace's track so that the card
turns.

One observation outside this change: in a second run, the HSI grabbed 8 s
after `FPLCRS` flipped to 134 still showed CRS 073 and MAG 085, while the map
in the same frame had moved on. The third run (the one shown) read 134 in all
three grabs at that hold. These are one stale HSI frame in two runs. The bus
was correct throughout.

## Regenerate

On the Beelink, with the SIM2b rig in `~/bench-scratch/aer4464` (`v27_follow.py`,
`nfx.py`, `fp/`) and the AER-4715 rows:

    mkdir -p ~/bench-scratch/aer5418/out && cd ~/bench-scratch/aer5418
    cp ../aer4715/hener_rows.json .
    # replay_hener_turn3.py from this directory
    ~/pyefis-venv/bin/python replay_hener_turn3.py   # not inside flock: it takes the bench lock per grab

then, beside the grabs:

    python3 make_strips.py <branch out/shots> <branch out/events.log>
    python3 make_before_after.py <dev out/shots> <branch out/shots>
