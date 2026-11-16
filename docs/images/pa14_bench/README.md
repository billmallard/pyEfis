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

## Night 1 (2026-11-15 05:00-06:30Z): what flew

All three sessions finished `complete`. The follower recognised each one,
found the PROC-page route still on the bus, and ACTed the slice's leg
(`data/night1_events.txt`). The playback fixture is in fix-gateway
`tests/sim/fixtures/pa14_*` and its replay test is
`tests/sim/test_pa14_xplane_replay.py`.

| Frame | What it shows |
|---|---|
| `n1a_va_*` | Slice A, live X-Plane: `ACT 2` puts the box on FLOUT5's `VA`. SUSP, VECTORS, course 000. |
| `n1a_resume_cf_flout_map` | RESUME 6 s later: `RESUME NAV -> FLOUT`, course 197.0 against X-Plane's 196.96. |
| `n1a_seq_vtu` | FLOUT -> VTU. In the replay of the same trajectory the engine switches 0.2 s from X-Plane. |
| `n1a_end_still_to_vtu` | **pyEfis #474 in flight.** Taken as the session ended, after X-Plane quit (SVS unavailable): the box is still TO VTU. X-Plane flew the 135-degree turn at VTU and switched to HENER at t = 1484 s. The engine never sequenced, because the route carries VTU twice. With the duplicate removed, the same trajectory sequences 5 s after X-Plane (fix-gateway replay). |
| `n1b_seq_ohigh`, `n1b_seq_canyn_star` | Slice B: V485 into FERN7. Each sequence comes 5-6 s after X-Plane's (X-Plane switches about 0.2 nm early, XPB-001). |
| `n1b_apr_armed_fim` | APR ARM as the box nears FIM, 30 nm from KSMO. |
| `n1b_seq_darts_approach` | The STAR hands into the approach: FIM -> DARTS (RNAV21.VECTORS active). X-Plane went to VNY, the STAR's common route the pack dropped (AER-5611). The box is up to 0.74 nm off X-Plane's path on this leg. |

**Slice C's approach frames are not used.** Between 06:01 and 06:17Z, two
other agents' followers took this session for their own and restarted fixgw
six times (thread comment, 2026-11-15 10:35Z). The engine's ramp, MAP
suspend and missed approach are proven on X-Plane's truth through the
replay test. Slice C is queued again (session `400e386d7193`, night of
2026-11-15) for clean frames on the glass.

## Night 2 (2026-11-16 05:15-05:45Z): slice C again, clean

Session `400e386d7193`, `complete`, with no other follower on the bench
(`data/night2_events.txt`). At the start the bus held another route, so the
follower republished the PROC-page route (`match True`), then ACTed DARTS.

| Frame | What it shows |
|---|---|
| `n2c_lnav_active_faf_fpl` | LNAV, approach active, 1.99 nm before MOVVE (the FAF). |
| `n2c_final_mipte_fpl` | MOVVE -> MIPTE, 0.30 nm scale. |
| `n2c_susp_at_map_fpl` | Suspended at the MAP (RW21): "SUSP AT MAP", "Fly the missed". No auto-sequence. |
| `n2c_missed_fpl` | RESUME 8 s later: MISSED, `SEQ ALT -> CAPOB` (the `CA` to +600 was already met), course 237 to CAPOB. |
| `n2c_sadde_hold_fpl` | SADDE, the missed approach hold. |

The follower's ramp-threshold grabs (`C_scale_*`) fired at the slice's start,
on the other route still on the bus, so they are not used. The same
one-shot-on-stale-state trap as night 1's MAP trigger. The ramp is pinned
numerically in fix-gateway's `test_pa14_xplane_replay.py`.

## Map frames: slice C's trajectory replayed into the bench (2026-11-16 12:31Z)

The follower grabs only the Flight Plan tab, so the map during the approach
comes from `bench_scripts/c_replay.py`. It writes X-Plane's own truth for
session `2c89084d9ebf` (t = 530-1000 s, 2x) into the live gateway over
netfix, with the Map tab up and no X-Plane running. It sends ACT 10, then
RESUME 8 s after the MAP suspend, as the follower did. This is a replay,
not the live sim feed. Keys at each grab: `data/c_replay_keys.txt`.

| Frame | Bus at the grab |
|---|---|
| `r2c_map_apr_active` | LNAV, APR 2, scale 0.997, 1.99 nm to MOVVE |
| `r2c_map_ramp_1nm` | scale 0.647, 0.99 nm to MOVVE |
| `r2c_map_final` | scale 0.30, 1.49 nm to RW21 |
| `r2c_map_susp_at_map` | SUSP at RW21, 0.01 nm |
| `r2c_map_missed` | missed, APR 3, scale 1.0, to CAPOB |
