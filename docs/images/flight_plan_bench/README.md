# flight_plan bench captures (AER-805)

Real X-session captures from the Beelink pyEfis bench (`bench_deploy.md --ref
aer-805/flightplan-fpl-entry-keypad`), not the offscreen headless harness.
`SIGUSR1`'s screenshot handler is known-broken on this box (grabs the wrong
window / never writes the file), so these were taken directly against the X
display instead:

```bash
# one-time on the bench (passwordless sudo already available):
sudo apt-get install -y xdotool

# per capture, against the live kiosk window (no window manager, single
# fullscreen 1920x1080 X window named "pyefis"):
DISPLAY=:0 xdotool mousemove <x> <y>
DISPLAY=:0 xdotool click 1
ffmpeg -y -f x11grab -video_size 1920x1080 -i :0 -frames:v 1 /tmp/shot.png
```

`flight_plan` occupies the right half of `config/screens/flightplan.yaml`
(screen x 960-1920); keypad/tab/footer tap-target centers were computed from
the widget's own `_paint_*` layout fractions (e.g. keypad row `y = 540 +
row_index*90 + 45`, key `x = 960 + (col_index+0.5)*(960/7)`).

- `fpl_page_empty.png` -- FPL page, no plan (`NO FLT PLAN`, `NO WAYPOINTS`).
- `entry_page_fastfind.png` -- Entry page mid-FastFind: typed `KSBA` against
  the real bench `airports.sqlite`/`navaids.sqlite` packs (`nasr_db_path`/
  `navaid_db_path` in the stock screen), Recent tab showing the prior commit.
- `fpl_page_two_waypoints.png` -- FPL page after committing KSBA and KSMX by
  keypad: real DTK/DIS/CUM (313°/42 nm to KSMX) from `flightplan.geo` against
  the actual airport coordinates.

Not captured: the HSI showing GPS course. The bench has no live position
(X-Plane wasn't feeding LAT/LONG -- the map shows `NO POS`), so there was no
GPS course for the FP2 engine to compute. See the PR body for what this
means for the DoD's HSI item.

## FP5b captures (AER-807, 2026-10-03)

PR #197 (DTO/Catalog/WPT Info pages + physical keyboard) merged 2026-09-12;
these were captured three weeks later once bench contention from AER-806
cleared. Live `managed.yaml` PFD screen, `Flight Plan` tab
(`flight_plan` instrument has `keyboard: true` there already). `SIGUSR1`
worked fine this time against the correct pid
(`pgrep -f '/pyefis-venv/bin/pyefis$'` -- the stock `pyefis` venv entry
point, not a literal `pyEfis.py`); driven by `xdotool mousemove <x> <y>
click 1` against `DISPLAY=:0`, tap targets read off the tab bar and footer
pixel boundaries in a first screenshot, not computed from the paint-code
grid math (the `_tap()` regions are registered fresh per paint and vary by
page state, so pixel-probing a real frame was more reliable than deriving
coordinates from `_paint_footer`/`_paint_dto_footer` fractions).

- `dto_page_waypoint_tab.png` -- Direct To page, default Waypoint tab: ident
  keypad, Waypoint/FPL/NRST APT tabs, Activate footer.
- `catalog_page_row_menu.png` -- Catalog row's Activate / Invert & Activate /
  Edit / Copy / Delete menu, captured against a route stored for this run
  (`TEST`, deleted again afterward -- see below).
- `fpl_page_row_menu.png` -- FPL page row context menu: Insert Before/After,
  Load Airway, Activate Leg, Direct To, **WPT Info**, Set Role, Remove.
  WPT Info has no HMI verb (`flightplan page` only takes `fpl`/`dto`/
  `catalog`); it's reachable only through this row menu, which is why it's
  a tap sequence rather than a bound key.
- `wpt_info_page.png` -- WPT Info detail for KSBA (resolved via
  `WaypointIndex.lookup` against the bench's real `airports.sqlite`):
  ident/type, name, DD MM.MM lat/lon, elevation, bearing/distance from
  present position.
- `fpl_page_menu_cdi_scale.png` -- FPL page Menu overlay (Invert/Store/
  Clear/Suspend/**CDI Scale (AUTO)**/Delete/Cancel), included because it's
  the on-glass confirmation that the DO-229 CDI-scale menu item from the
  #187 ruling is live, not just the FPL page row list.

**Two anomalies observed, not fixed here** (evidence-gathering only; the
look itself is Bill's call):

- `dto_page_fpl_tab_oversized_text.png` and
  `catalog_page_list_oversized_text.png` -- when a list has exactly one row
  (the DTO page's FPL tab with one waypoint in the plan; the Catalog list
  with one stored route), that row's text renders at a huge fraction of the
  pane height instead of a normal list-row size. Looks like row height (and
  therefore font size) scales as `available_height / row_count` rather than
  a fixed per-row height, so a 1-row list fills the whole list area. Every
  other list screenshot here (the FPL page itself, the row/catalog menus)
  uses a normal fixed row height, so this looks specific to the DTO-FPL-tab
  and Catalog list paint paths.
- The DIRECT badge (`FPLSTATE` = DIRECT next to the route name) never
  appeared after activating direct-to-KSBA from the DTO page's FPL tab, even
  though the page round-tripped correctly (returned to the FPL page, as
  documented). The bench's moving map shows `NO POS` throughout this entire
  capture session (same condition noted above for FP5a/AER-805) -- X-Plane
  isn't feeding position, so the FP2 engine most likely can't resolve
  present position to accept the direct-to command. Not re-investigated via
  the FIX bus directly (a quick `fixgw.netfix.Client` probe from the bench
  didn't connect in the time available); flagging it here as unverified
  rather than claiming either a bug or a known-good no-op.

**Cleanup.** A route named `TEST` already existed as the *working* (unsaved)
plan when this session started (it was not in the Catalog). It was
deliberately Stored via the FPL page Menu to get a non-empty Catalog
screenshot, then Deleted again via Catalog > row menu > Delete > Yes once
the row-menu screenshot was captured, restoring "NO STORED ROUTES". The
screen was left on the `Map` tab (its state when this session began), not
the `Flight Plan` tab used throughout the capture.

## USB keyboard evidence (AER-807, 2026-10-03, follow-up)

`entry_page_virtual_usb_keyboard.png` -- DTO page, Waypoint tab, after typing
`KSBA` + Enter via a **uinput virtual HID keyboard**, not a literal physical
dongle: this agent has no hands at the bench, so a literal USB keyboard is
still untested. What this does prove: `python3-evdev` (`sudo apt-get install
-y python3-evdev`) opened `/dev/uinput` (root-only; `sudo -n python3 ...`) and
registered a device (`UInput(capabilities, name="pyefis-bench-virtual-usb-kbd",
...)`) that the kernel, udev and X11 enumerated identically to a physical
keyboard -- confirmed from the logs, not assumed:

```
kernel: input: pyefis-bench-virtual-usb-kbd as /devices/virtual/input/input20
Xorg.0.log: (II) Using input driver 'libinput' for 'pyefis-bench-virtual-usb-kbd'
Xorg.0.log: event18 - pyefis-bench-virtual-usb-kbd: is tagged by udev as: Keyboard
Xorg.0.log: (II) XINPUT: Adding extended input device "pyefis-bench-virtual-usb-kbd" (type: KEYBOARD, id 16)
```

So the keystrokes crossed the same kernel evdev -> libinput -> X11/xkb -> Qt
`keyPressEvent` path a real USB keyboard would use -- this is not an
XTestFakeKeyEvent/`xdotool key` software injection, which bypasses the evdev
layer entirely. `K`/`S`/`B`/`A`/Enter all resolved via the default US xkb
layout already on the box; no keymap tweak was needed. The ident resolved and
the page reacted (moved off the bare keypad into the matched-waypoint list),
which is the on-glass signal that the keystrokes actually reached the
instrument's input handling, not just the X server.

This is still not the literal DoD line ("a USB keyboard ... types") -- it is
the strongest remote substitute available, and the gap between the two is a
question of whether kernel-level HID-identical input satisfies that line, not
a question of whether the code path works. Flagging that distinction rather
than quietly claiming the literal hardware check as done.

**DIRECT badge / magenta line -- still not captured, and why that's now a
different question than "not tried yet".** The bench's map still shows
`NO POS` (checked again this session). Setting a synthetic `LAT`/`LONG` to
force this would mean enabling `fix-gateway`'s `COMMAND` connection
(`COMMAND_CONFIG`, currently `false` in the bench's live
`~/makerplane/fixgw/config/preferences.yaml`) and restarting the shared
fix-gateway service -- a live-config change and a restart on a box other
agents are using, for a check whose real form is already scoped as its own
item: AER-809 (FP8, "bench validation flight against X-Plane"), explicitly
sequenced after this item and described as needing an actual flight, not a
synthetic position poke. Deferring the DIRECT-badge/magenta-line sub-check to
AER-809 rather than forcing it here. One data point worth recording: KSBA
displayed with a magenta ring/crosshair glyph on the Map tab after this
direct-to interaction, suggesting the map-side target symbol may already be
live independent of the `FPLSTATE` badge -- not confirmed further.

**Cleanup.** No Catalog/stored-route state was changed this session -- the
`TEST` working plan (KSBA, KDFW) was already loaded when this session began
(same residual plan the first capture session left behind), and only the DTO
Waypoint-entry keypad was exercised, not Activate/Store/Delete. Left on the
Flight Plan tab, DTO Waypoint-tab view, matching the state after the keyboard
test.
