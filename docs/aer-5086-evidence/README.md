# AER-5086 evidence: pitch-limit indicator (AI-LIM-001)

Composed-screen renders of the pitch-limit marker on the Beelink bench's served
PFD (`screens/managed.yaml`: SVS, garmin symbol, `horizon_position` 68,
`pitchDegreesShown` 40), 1920x1080. They are x11grab frames of the live glass,
so the GL terrain is in them. pyEfis was the branch at `ef48024`, staged with
`bench-deploy.sh --ref`. The bench was restored to `dev` afterwards.

`AOA` and `AOA.Warn` come from fix-gateway's `onspeed` plugin (fix-gateway#121,
on the bench's `dev` checkout). The plugin reads a pty fed with
`tools/onspeed_sim.py`'s own profile (`state_at`) and the plugin's own sentence
encoder. `feeder.py` adds one thing: a clock you can hold. "hold <t>" freezes
the simulator's profile at t seconds, so a frame isn't smeared by a 3 deg/s
sweep. "live" runs the simulator's own real-time sweep. The bench has no
simulator, so `driver.py` writes attitude and position over netfix: 1 NM final
RWY 7 KSBA, 611 ft. It sets `PITCH` = bus `AOA` - 3, which is the simulator's
constant -3 deg flight path. At that flight path the limit should hold one ladder
pitch, `AOA.Warn - 3`.

`frames.json` has the bus values read just before and just after each grab
(`AOA`, its old/bad/fail flags, `AOA.Warn`, `PITCH`). `live_sweep.json` is one
full simulator period read off the bus at 5 Hz. It shows `AOA` sweeping, being
published bad during the taxi phase, and `AOA.Warn` stepping 13.5 -> 12.4 ->
11.5 with flaps.

## Frames

`sheet.png` crops the attitude area out of every frame below and captions each crop with its bus values.

| File | AOA / Warn | Margin | What it shows |
|---|---|---|---|
| `1-taxi.png` | 0.0 (bad) / 13.5 | none | No marker. Below `min_ias` the plugin publishes AOA bad. |
| `2-cruise.png` | 3.5 / 13.5 | +10.0 | No marker. The margin is outside `pitchLimitShowMarginDeg` (8). |
| `3-amber6.png` | 7.5 / 13.5 | +6.0 | Amber marker 6 deg above the symbol, at 10.5 on the ladder. |
| `4-amber3.png` | 10.5 / 13.5 | +3.0 | Amber marker 3 deg above the symbol, also at 10.5. |
| `5-red.png` | 15.0 / 13.5 | -1.5 | Red: past the warning AOA, the marker sits below the symbol. |
| `6-flaps40.png` | 8.5 / 11.5 | +3.0 | Flaps 40 lowers the warning AOA. The marker is at 8.5. |
| `7-amber3-bank20.png` | 10.5 / 13.5 | +3.0 | Banked 20 deg: the marker stays upright, in the aircraft's frame. |

`zoom_2x.png`: frames 4 and 5, 2x nearest-neighbour, the left bar and the symbol.

`live_strip.png` (from `live/`) shows six frames across the simulator's real-time
flaps-40 sweep, read left to right and top to bottom. The nose rises through the
limit and comes back down. The marker stays at 8.5 on the ladder while the pitch
moves under it, and it turns red once AOA passes 11.5.

## Two harness notes

- **Stale first grab.** After a step change in an otherwise static scene, the
  first grab could come back byte-identical to the previous state. The bus
  already held the new values. A grab 1 s later showed them. Real flight data
  is never static, so the frames here are the second grabs. This looks like the
  glass staying one paint behind until something else repaints. It is not
  specific to this marker.
- **pyEfis keeps values across a fix-gateway restart.** After the gateway
  restarted, writing a value equal to the gateway's initial value sent no update.
  So pyEfis kept the old one, and a re-shoot came out banked 20 deg. The final
  `6-flaps40.png` is from a run that wrote a real ROLL change first.

## How to regenerate

On the Beelink, with this branch staged and nothing else using the bench:

    mkdir -p ~/bench-scratch/aer5086 && cp feeder.py driver.py session.sh ~/bench-scratch/aer5086/
    flock -w 900 /tmp/pyefis-bench.lock sh ~/bench-scratch/aer5086/session.sh

`session.sh` backs up the three fix-gateway config files it touches:
`default.yaml` (adds `ONSPEED_CONFIG`), `preferences.yaml.custom` (adds the
include) and `connections/onspeed.yaml` (sets `load: yes` and the pty). It
starts the feeder and restarts fixgw, then runs `driver.py`. On exit it puts the
three files back and restarts fixgw again. The hold list is `HOLDS` in
`driver.py`. The committed frames come from three runs of it with different
hold lists (see "Two harness notes"). Then compose locally:

    python3 docs/aer-5086-evidence/compose.py
