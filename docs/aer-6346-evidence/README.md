# AER-6346 (CAS3): the CAS window on a private gateway

The CAS1 brief's section 12.2 bench steps that involve a display, run against a private
fix-gateway (`dev` at cf26588, its shipped config tree, netfix on a private port, started
through `fixgw.server:main`) and this branch's pyEfis on an X server (Xvfb with software GL,
llvmpipe). No bench box and no live gateway were touched. Faults are raw netfix writes,
touches are XTEST clicks, frames are grabs of the X root window, and what pyEfis drew is also
read from its own log (`CAS: CASWindow shows ...`).

## Regenerate

With an X server on `$DISPLAY` that has XTEST, `QT_QPA_PLATFORM=xcb`, and a fix-gateway
checkout at `../fgw`:

```sh
# the timed steps (smaller panel: software GL at full size stalls the GUI thread)
python3 docs/aer-6346-evidence/bench.py --fgw ../fgw --out out --placement A --size 1024x600
# step 14, second half: no CAS widget on any screen
python3 docs/aer-6346-evidence/bench.py --fgw ../fgw --out out --no-window --size 1024x600
# the placement renders, 1920 x 1080 (the Beelink panel)
for p in A B C; do
  python3 docs/aer-6346-evidence/bench.py --fgw ../fgw --out out --render-only --placement $p
done
```

`bench.py` prints `PASS` or `FAIL` per check and exits non-zero on any `FAIL`. The images here
are copied from `out/`; the step frames are cropped to the 1024 x 600 panel.

## Results (`bench-steps.log`, `bench-nowindow.log`)

| Step | Result |
|---|---|
| 1 | Quiet: `CASCNT` 0, the window draws nothing, no red or amber in its area |
| 2 | `NAV FAIL` drawn 0.40 s after the CDI fail; amber fill comes and goes over five grabs |
| 3 | A touch acknowledges: `CASACK` = the `CASSEQ` drawn; the line goes steady |
| 4 | `NAV FAIL` gone when the flag clears |
| 5 | `AP LINK LOST` red, 1.9 to 2.0 s after the last `APENG` |
| 6 | `AP LINK LOST` amber when the autopilot was disengaged |
| 7 | `FUEL QTY 3 NO DATA` at 61.8 s, after its 60 s grace and not before |
| 8 | `CAS FAIL` 2.9 s after the `cas` plugin stops (gateway still up) |
| 9 | `GATEWAY LINK LOST` on `SIGSTOP`, only local alerts drawn, no `CAS FAIL` beside it; `SIGCONT` recovers. **End to end 2.87 s, over the brief's 2.5 s**: the watchdog itself logged its trip at 2.51 s (its 2.0 s timeout plus 0.5 s poll, late under software GL), and the CAS window drew 0.36 s after that |
| 10 | `CATALOG REFUSED` white from a `status.json` rollback row |
| 12 | A new alert flashes while the acknowledged one stays steady |
| 14 | **Fails, both halves of the power-up test.** No window or marker anywhere: `CAS NOT SHOWN` cue and an error in the log (passes). But `CAS TEST` never reached the glass: see below |
| 16 | Two messages active, plugin stopped: `CAS FAIL` only, neither old message drawn, no red |
| 18 | Link dropping every 3 s: one `AP LINK LOST`, no gaps; cleared 5.6 s after the link steadied |

Not run here: **11** (fifteen alerts; the shipped catalogue cannot raise fifteen, so it is
covered by CAS2's `test_fifteen_alerts_count_all_and_slot_12_is_the_least_urgent` and this
branch's overflow tests), **13** and **15** (gateway data path and plugin restart: CAS2 unit
tests on the real plugin thread). Steps 5, 6 and 18 write `APENG` from a netfix writer, not
ArduPlane SITL, as CAS2's run did.

### Finding: `CAS TEST` is gone before a display can draw it

The gateway raises `CAS TEST` for about 5 s from plugin start (CAS2). pyEfis waits for the
gateway, then needs about 6 s from connecting to its first frame (`pyefis-steps.log`:
connected 22:10:28, widgets drawing 22:10:34), and on the ground it boots the data-status
screen, which carries no CAS widget. After a gateway restart under a running display the
watchdog recovery re-reads every item (3,717 here) and the window drew again 11 s later. In
every run `CAS TEST` had cleared first. So the power-up test, which the FHA credits against
CAS-1u, does not reach the pilot as built. It is a gateway behaviour; the CAS3 PR records it
and proposes the follow-up.

## Images

- `placements-ABC.png`, `placement-A.png`, `placement-B.png`, `placement-C.png`: the same
  three messages (a warning and a caution unacknowledged, a caution acknowledged) in each
  placement, on the shipped PFD at 1920 x 1080.
- `beelink-placement-A.png`, `-B.png`, `-C.png`: the same renders on the Beelink (Intel GPU,
  its fonts, 1920 x 1080), from `beelink_look.sh`: a private gateway on port 34991 and a
  second pyEfis from this branch, windowed over the live display for about a minute per
  placement under the bench lock. The live gateway (staged for another review) and the live
  pyEfis were not restarted or reconfigured, and both read `active` afterwards. It shows the
  shipped `pfd.yaml`, not the Beelink's own managed panel. The amber DATA flag is the
  Beelink's real navdata state.
- `step-*.png`: the frames the step checks measured.
- Fonts are DejaVu from the sandbox's fontconfig, not the panel's; GL is llvmpipe, not the
  target GPU.
