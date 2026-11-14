# PA14 bench validation: SID, airway, STAR, approach (AER-1613)

The procedures-and-airways join (billmallard/pyEfis#242), in the shape of FP8
(`../fp8_bench/`). One IFR route is built on the Beelink's Flight Plan tab
with the PROC page and the airway picker, the way a pilot would enter it, and
then flown against X-Plane.

**Route:** KSBA, FLOUT5 departure (runway 15B, VTU transition), V485 VTU to
OHIGH, FERN7 arrival (OHIGH transition), KSMO RNAV (GPS) RWY 21 (vectors to
final), missed approach to the SADDE hold.

**Data:** AIRAC cycle **2611** (effective 2026-10-29 to 2026-11-26), the
bench's procedures pack `/data/makerplane-data/procedures/2611`
(`FPLDBCYC 2611` on the bus). Software: pyEfis `c445c000` (dev), fix-gateway
`9aede5d` (dev), deployed with `bench-deploy.sh --owner AVIONICS --issue
AER-1613` at 13:36Z on 2026-11-14.

Frames are `x11grab` on the 1920x1080 kiosk. `d*` are the Flight Plan pane
cropped from x = 1256 at full resolution; `g*` are whole frames scaled to
1280 wide.

## Why this route

The brief's route opens at KSBA. Two candidate destinations failed on the
PROC page before anything was flown, and those failures are findings
(below), not reasons to avoid the test:

- **KBUR via FERN7** cannot be loaded: FERN7's only KBUR runway transition
  ends in a `VM` leg whose fix is the airport, and the pack carries no
  position for it (`d07`).
- **KVNY** has FERN7 but no RNAV approach, so the CDI ramp could not be
  checked there.

KSMO has FERN7 and an RNAV approach. FERN7 at KSMO also shows the third
data finding: its common route (FIM, VNY, DARTS) is filed in the pack as a
transition named `ALL`, so choosing OHIGH loads OHIGH, CANYN, FIM and
silently drops the common route (`d08`, `d09`). The route was loaded as a
pilot would load it, with that defect, and flown that way.

## Day 1, on the ground (2026-11-14, no X-Plane)

Built by synthetic taps and keystrokes (`bench_scripts/t.sh`) on the
Flight Plan tab, each step read back on the bus (`data/load_keys.txt`).

| Frame | What it shows |
|---|---|
| `d01` | FLOUT5 from runway 25 carries a `CI` leg. The load is refused whole: "EDIT REFUSED: CAN'T FLY CI LEG AT WAYPOINT 3", `FPLMSG = UNSUPP CI SLOT3`, the plan unchanged (guardrail 1). |
| `d02`, `d03` | FLOUT5 from runway 15B (`VA` 152 to 413 ft, `CF` FLOUT 197, `TF` VTU) loads. |
| `d04` | There is no "Load Airway" on a procedure row, so VTU is inserted as a waypoint after the SID to start V485 from. The page shows VTU at DIS 0, DTK 043: the bus has VTU in slots 4 and 5, a zero-length leg. |
| `d05`, `d06` | V485 from VTU, exit OHIGH: three fixes, MEA 9000. |
| `d07` | FERN7 at KBUR, runway 08: "NO POSITION FOR KBUR". |
| `d08` | FERN7 at KSMO offers `ALL` as a transition, and no common route. |
| `d09`, `d10` | FERN7.OHIGH previews and loads as OHIGH, CANYN, FIM. |
| `d11`, `d12` | RNAV 21 with the `VECTORS` transition. The whole route: 18 slots, 7 segments, `FPLAPRTYPE RNAV`. |
| `g1` | `ACT 2` with the aircraft on the runway: the `VA` leg. `FPLSTATE 3` (SUSP), `FPLPHASE VECTORS`, `FPLCRS`/`FPLXTK`/`WPDIS` 0. The FPL header reads SUSP; the HSI course reads 000. |
| `g2` | After a 2 nm climb-out on heading 152, `RESUME`: `FPLMSG RESUME NAV -> FLOUT`. The engine flies the `CF`'s coded course 197 (XTK -1.12 nm, needle full scale), an intercept, not a direct. |

`data/route_ksba_ksmo.json` is the route block pyEfis published, read back
off the bus with `bench_scripts/snap.py`. The overnight follower republishes
it only if the bus no longer holds it. `data/ground_keys.txt` is the
`ground.py` key log for `g1`/`g2`.

Regenerate the ground check (Beelink, under the bench lock, X-Plane idle):

```sh
cd ~/bench-scratch/aer1613        # bench_scripts/* and data/route_ksba_ksmo.json
flock -w 300 /tmp/pyefis-bench.lock python3 ground.py
```

## The X-Plane flight (queued for the night of 2026-11-14, 23:00-06:00 Central)

X-Plane's driver flies en-route fixes and one approach from an air start,
with no departure and no STAR by name, so the route is flown in three
slices (profiles in `data/`):

| Slice | Session | From | To |
|---|---|---|---|
| A | `1242bb63442d` | 3 nm before FLOUT, 6,000 ft | after HENER |
| B | `11d33a5b4857` | 4 nm before HENER, 9,000 ft | after VNY |
| C | `2c89084d9ebf` | 4 nm before VNY, 4,500 ft | RNAV 21, missed approach, 3 min in the SADDE hold |

X-Plane flies the STAR's fixes as waypoints, as published (FIM, VNY,
DARTS); the box flies what it loaded (FIM, DARTS). On the Beelink,
`bench_scripts/pa14_follow.py` recognises each session, ACTs the slice's
leg (slice A: the `VA`, then RESUME), logs the bus at 2 Hz and grabs the
panel on each event. Its start actions were rehearsed against the live
engine with a synthetic position (`--dry A|B|C`) before arming.
