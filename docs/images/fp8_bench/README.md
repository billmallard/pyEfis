# FP8 bench flight evidence

Screens from the Beelink bench (pyEfis `49628ed`, fix-gateway `2666bc4`,
1920x1080 kiosk, `x11grab`), scaled to 1280 wide and saved as JPEG.

- `s1_*`: session 1, 2026-10-28, hand-flown in X-Plane by Bill.
- `s2_*`: session 2, 2026-10-29, pilotless sim bench session `cbbeafe57646`.
- `r1_*`: session 2's aborted first attempt, `33758e63080f`.

## How session 2 was run

On the Beelink, `bench_scripts/fp8_s2.py` (with `nfx.py`, `session2.sh`,
`fp8_proc_route.py`, `fp8_logger2.py`, `shot.sh`, `rref_block.txt`) waited
for X-Plane data on the bus inside the sim bench's flying window. Then it:
- turned on the session-only RREF position feed and `DATA_RECORDER`;
- started the 1 Hz logger;
- published the profile's procedure route and activated it at PAMJI;
- drove the checks off the engine's own state: the GPSSRC swap at LNAV, a
  screenshot at the ramp, RESUME 8 s after the MAP auto-SUSP, SUSP 1 nm
  before HANNU and RESUME once FROM past it, SCALE 0.3/AUTO, the
  `GPS_ACCURACY_HORIZ` write, and the pyEfis restart in the hold.

It reverted both flags when the session ended. The session was queued with:

```sh
curl -s -X POST -H "Authorization: Bearer $XPBENCH_TOKEN" -H "Content-Type: application/json" \
  http://10.110.10.167:8770/sessions -d '{"profile": "fp8-ksmx-rnav30-missed", "issue": "AER-809"}'
```

Every action, with UTC stamps, is in `data/fp8_s2_events.log`.

**Bench quirk (fix-gateway#51).** The `xplane` plugin subscribes to RREF only
at startup. After the sim bench launched X-Plane, fixgw had to be restarted
before any X-Plane data arrived. That was done by hand at 05:33Z.

## Regenerating the section 2 numbers

```sh
gunzip -k data/fp8_s2_bus_1hz.csv.gz && mkdir -p run && mv data/fp8_s2_bus_1hz.csv run/fp8_s2.csv
curl -s -H "Authorization: Bearer $XPBENCH_TOKEN" \
  http://10.110.10.167:8770/sessions/cbbeafe57646/truth > run/truth.jsonl
python3 data/analyze_bus_ab.py run data/fixes.json
```

The bus log carries `FPLCRS`/`FPLCDI` (ours) and `EXTCRS`/`EXTCDI`
(X-Plane's) on the same 1 Hz row. `truth.jsonl` is X-Plane's own 5 Hz
navigator. The same trace, trimmed, is the playback fixture in fix-gateway:
`tests/sim/fixtures/fp8_xplane_2026-10-29.csv.gz`, replayed by
`tests/sim/test_fp8_xplane_replay.py`.

## G42: FPL page DTK beside the HSI (pyEfis #325, AER-4237)

Session 1 found the FPL page's DTK column in true course while the HSI's CRS
box was magnetic: `s1_dto_rzs_active_fplpage.jpg` (built before #324) shows
RZS at 295 on the page. #324 (AER-3792, `49628ed`) made the column the
magnetic course into each fix, `dtk_true + MAGVAR`, the conversion the
engine applies to `FPLCRS`. These two frames show it on the bench.

- `g42_leg1_ksba_gvo.jpg`: active leg KSBA-GVO. Page DTK 285, HSI CRS 285
  (`FPLCRS` 285.19).
- `g42_leg2_gvo_rzs.jpg`: after sequencing GVO. Page DTK 083, HSI CRS 083
  (`FPLCRS` 82.79).

Bench: Beelink, pyEfis `b73d836` (dev), fix-gateway `15e9baf`, 2026-10-30,
1920x1080 `x11grab` scaled to 1280 wide. X-Plane was idle, so the position
is synthetic: `bench_scripts/g42_dtk_mag.py` writes a static
LAT/LONG/GS/HEAD/TRACK with `MAGVAR` -11.9 over netfix at 2 Hz, on each leg
in turn. That is why the altitude, attitude and terrain colours do not
match the place. The plan is published as plain TF legs (no coded course),
so the page has to derive DTK itself. The script snapshots the bench's
route block first and republishes it afterwards, then re-activates the
leg that was active. On this run an earlier attempt had already left the
old plan loaded but inactive, so leg 11 was re-activated by hand with the
script's `act(11)`. The bus values at each grab are in `data/g42_keys.log`.

Run on the bench, under the lock:

```sh
cd ~/bench-scratch/aer4237   # g42_dtk_mag.py + nfx.py
flock -o -w 900 /tmp/pyefis-bench.lock python3 g42_dtk_mag.py shots
```
