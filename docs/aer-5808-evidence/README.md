# AFC4 evidence: autopilot mode strip and tape cues (AER-5808)

Offscreen renders of the real widgets, driven from an in-memory FIX database
(`tests/mock_db`), one autopilot state per row. Not a Pi 5 GL capture: that sheet
and the X-Plane bench run are separate steps of AFC4's definition of done.

- `strip.png`: `ap_annunciator` at 640x40 over a sky-blue ground, ten states
  (captions on the left), AP YD first (the default since Bill's ruling on AER-5808).
  Row 3 is the same moment as row 2, half a second later: the flash's off phase, box
  kept. Rows 5 and 5b: ALT hold with `APALTREF` 8500 while `ALTSEL` is 10500, then the
  same with `APALTREF` old.
- `tapes.png`: the IASSEL box and bug (IAS active, then armed, then holding the edit
  focus after a touch: ring and edit icon), the VSSEL bug on a VS
  tape and on `VSI_PFD`, and the ALTSEL box while capturing (green border) beside the
  plain box.

- `replay.png`: a real X-Plane flight through the real adapter into the real strip.
  `replay.py` replays fix-gateway's AFC2 fixture
  (`tests/plugins/xplane/data/afc2_c172_bf3a33402db4_raw.jsonl`: sim-bench session
  bf3a33402db4, X-Plane 12.4.3, Laminar C172 G1000, 2026-11-18) through
  `fixgw.plugins.xplane.autopilot` on fix-gateway's shipped database. It feeds every key
  change the adapter published, in order and on the session's clock, to
  `ap_annunciator`. One row per mode change (on the flash's ON phase) and one after
  each flash ends; the caption has the session time and the target keys. What it
  shows:
  - ALT engages at the current altitude, `ALT 7510`, then captures `ALT 8000` and
    `ALT 8500`. While PIT is active, the 7900 in `APALTREF` is not shown.
  - Pressing VS shows `VS 0` for about 0.5 s, then `VS +500`. X-Plane engages VS at
    the current rate, and the AFC2 adapter writes the pilot's target 0.5 s later
    (`TARGET_DELAY_S`). That is adapter timing, not the strip.
  - LVL shows as `ROL`/`PIT`, then `ALT`: X-Plane has no LVL state.
  - The disconnect latches a red `AP`. GPS and ALT stay up because the flight
    director stays on.

  This is a replay into an offscreen render, not the live glass or a Pi 5 GL capture.
  Staleness is not replayed: the replay runs faster than real time, so no key goes
  old.

Regenerate from the repo root:

```bash
QT_QPA_PLATFORM=offscreen python3 docs/aer-5808-evidence/render.py
QT_QPA_PLATFORM=offscreen python3 docs/aer-5808-evidence/replay.py <fix-gateway checkout at 85d4fd2 or later>
```

In the agent sandbox the Qt libraries come from a deb-extracted prefix
(`LD_LIBRARY_PATH=<prefix>/usr/lib/x86_64-linux-gnu`, `FONTCONFIG_FILE=<prefix>/fonts.conf`);
on a normal install neither is needed.
