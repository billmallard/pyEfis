# AFC4 live X-Plane session: the mode strip on a running screen (AER-6288)

AER-5808 proved `ap_annunciator` by replaying a recorded AFC2 session into an
offscreen render. This run puts it on a running pyEfis `dev` screen, fed live
by X-Plane through the AFC2 adapter, and scores every frame against the bus.

**Status:** rig built and rehearsed. Sim-bench session `16dfbb9a74a7` is
queued for the 2026-11-23 05:00Z window. The results section is added after
the flight.

## The rig (`rig/`)

On the Beelink, in `~/bench-scratch/aer6288`. Nothing touches the live
gateway, `pyefis.service`, display `:0` or the live config trees.

- A **private fix-gateway** (`dev`, the AFC2 adapter with `APALTREF`) on its
  own `udp_in` 49104 and netfix port 3594. It reads X-Plane over its own RREF
  subscriptions. `mkconfig_fgw.py` is AER-6052's builder, unchanged.
- A **private pyEfis `dev`** on Xvfb `:7`, 1920x1080. `mkconfig_pyefis.py`
  takes the bench's live PFD screen (`managed.yaml` PFD) with its options
  unchanged, drops the tab section, and adds `ap_annunciator` across the top
  of the attitude display, a `vsi_pfd` (the VSSEL bug) and the AFC3 autopilot
  panel. The airspeed and altimeter tapes keep their shipped cue defaults
  (IASSEL box and bug, ALTSEL box with the capture look). It also writes
  `strip_geometry.json`, the strip's pixel rectangle from pyEfis's own layout
  code.
- **`seq.py`** presses the autopilot through the private gateway the way the
  control head does: HDG, a 40 deg offset, a 30 deg intercept and NAV, then
  VS to ALT, then an IAS climb to a second ALT capture, then DISC. It grabs
  the screen once a second on average and logs every bus update with its
  flags (`bus.jsonl`). Each frame record carries the bus values and the
  grab's start and end times (`frames.jsonl`).
- `session.sh start|stop` are the hooks `sim_follow.py` runs around the
  session. `setup.sh` clones both `dev` trees and builds the configs.

Re-fly: run `setup.sh`, then `rehearse.sh` (no sim), then submit
`profile.yaml` with `sim-session.sh` and arm
`sim_follow.py --sid <id> --dir run1 --on-start "sh session.sh start" --on-end "sh session.sh stop"`
from a `run1/` directory holding a copy of `session.sh`.

## Scoring (`score.py`)

```sh
cd <pyEfis checkout>
QT_QPA_PLATFORM=offscreen python3 <this dir>/score.py <run dir> [strip_geometry.json]
```

- **Expected**, from the bus log alone. The strip text follows the spec,
  written out in the scorer, not taken from the widget's model.
- **Seen**, from the pixels, slot by slot. Each slot is compared with the
  expected text and with every plausible alternative, painted by the real
  widget: every mode name, the expected number's neighbours, both colours,
  every flash look, and the empty slot. The whole strip is also compared
  with NO AP DATA in both colours.
- **Verdicts:** `match`, `edge` (a frame on a state change that shows a state
  the bus held within the grab's window), and `MISMATCH`. Frames where a
  flash's off phase hides a slot's text are counted separately, because they
  prove only where the box is.

## Rehearsal (no sim)

`rehearse.sh` feeds a scripted state sequence (HDG with GPS armed, VS +500
with ALT armed, ALT CAP, ALT 8000, IAS 90 with ALT armed, YD, a disconnect)
and then stops writing, so the keys go old. 110 frames: 108 `match`, 2 `edge`,
0 `MISMATCH`. The NO AP DATA frames scored 0.929 against their own look and
at most 0.002 against any rival.

**Mutation check.** The same frames were scored against a corrupted bus log:
HDG renamed ROL, IASSEL 90 changed to 80, APALTREF 8500 changed to 8400. All
three corrupted states were flagged (`MISMATCH`), except in frames where a
flash's off phase hid the text, and those frames are reported. Three faults
in the rig were found and fixed on the way:

1. The bus log lost its last seconds, which is the stale tail. The process
   exits on STOP without joining the logger thread, so the log is now
   line-buffered. AER-6052's `seq.py` has the same exposure.
2. A whole-strip classifier that chose only among states the bus had visited
   passed most of the corrupted frames, because the true glass state was not
   a candidate. Hence the per-slot open lexicon.
3. A steady 1.0 s grab is two half-periods of the 0.5 s flash, so every grab
   during a flash landed in the same phase, the text hidden. Grabs now
   alternate 1.25 s and 0.75 s apart, which is still once a second on
   average.
