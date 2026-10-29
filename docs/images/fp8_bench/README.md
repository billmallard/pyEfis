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
