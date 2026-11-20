# AER-5983: proposed LINK MON OFF cue

The cue pyEfis would show, over every screen, when the FIX link watchdog is
not running (it failed to start, `FixLinkTimeout <= 0`, or no ping key is in
the FIX database). The wording and look are a proposal awaiting Bill's call.

- `pfd_800x480.png`, `pfd_1024x600.png`: real non-GL attitude indicator and
  tapes on the mock FIX database, with the real cue widget over them.
- `pfd_800x480_with_demo.png`: the same with the DEMO strip lit, to show the
  cue sits below it.
- `cue_crop_3x.png`: the top centre of the 800x480 frame, nearest-neighbour 3x.

The SVS terrain is GL and does not render offscreen; the cue is a normal
child of the main window, stacked last, as the DEMO strip and the startup
notice are.

Regenerate from the repo root:

    QT_QPA_PLATFORM=offscreen python docs/images/aer5983_link_mon_off/render_cue.py
