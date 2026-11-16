# AFC4 evidence: autopilot mode strip and tape cues (AER-5808)

Offscreen renders of the real widgets, driven from an in-memory FIX database
(`tests/mock_db`), one autopilot state per row. Not a Pi 5 GL capture: that sheet
and the X-Plane bench run are separate steps of AFC4's definition of done.

- `strip.png`: `ap_annunciator` at 640x40 over a sky-blue ground, nine states
  (captions on the left). Row 3 is the same moment as row 2, half a second later: the
  flash's off phase, box kept.
- `tapes.png`: the IASSEL box and bug (IAS active, then armed), the VSSEL bug on a VS
  tape and on `VSI_PFD`, and the ALTSEL box while capturing (green border) beside the
  plain box.

Regenerate from the repo root:

```bash
QT_QPA_PLATFORM=offscreen python3 docs/aer-5808-evidence/render.py
```

In the agent sandbox the Qt libraries come from a deb-extracted prefix
(`LD_LIBRARY_PATH=<prefix>/usr/lib/x86_64-linux-gnu`, `FONTCONFIG_FILE=<prefix>/fonts.conf`);
on a normal install neither is needed.
