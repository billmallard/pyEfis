# AER-5626 (DEMO4): demo kiosk on the Beelink's live panel

One full loop of the demo source on the bench's 1920x1080 panel, kiosk on,
2026-11-14 16:06 to 16:27Z. pyEfis at cc1d9da9 (this branch); fix-gateway
at d3bf964 (`aer-5626/demo-kiosk-keys`, billmallard/fix-gateway#177).

How it ran (`capture.sh`, run on the Beelink by path under the bench lock):

- A scratch demo gateway, the shipped fix-gateway config with netfix moved to
  :3491, ran beside the bench's own fixgw, which was not touched. Its demo
  flew `fp8-ksmx-rnav30-missed` (1172 s) with this page schedule:
  0 s PFD/Map, 150 PFD/Flight Plan, 420 PFD/Map, 780 PFD/Engine, 960 PFD/Map.
- pyEfis's live config was pointed at :3491 with `kiosk: {enabled: true,
  idle_return_s: 30}` for the run, then restored byte-identical (`cmp`), with
  its mtimes, by the script's exit trap.
- `ffmpeg -f x11grab` grabbed the panel every 10 s. `xdotool` made two taps
  as a visitor would: the Map tab at t=200 s, the Engine tab at t=408 s.
- `capture.log` has the DEMOLIVE, DEMOPAGE and FPLSEQ values read over netfix
  at each grab.

Files:

- `panel_t0040.png`: the whole panel at t=40 s, half size.
- `marking_4x.png`: the marking, cropped from that frame, 4x nearest-neighbour.
- `touch_hold_idle_return.png`: the right half of the panel around both taps.
- `loop_pages.png`: the right half of the panel across the loop, with the
  script's page at each frame.

The engine page reads 0.0 throughout: the demo writes no engine keys until
DEMO3. The HSI shows NAV flagged because the bench's NAVSRC is not GPS; that
is the bench config, not this change.
