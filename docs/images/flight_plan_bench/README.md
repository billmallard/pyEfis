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

## USB keyboard evidence (AER-807, 2026-10-03, follow-up, recaptured 2026-10-03 for AER-2592)

**Recapture note.** The first version of this evidence (`entry_page_virtual_usb_keyboard.png`,
PR #277) was wrong: INTEGRATOR found the committed PNG was the *FPL* page carrying a stale
`SELECT A WAYPOINT` toast, not the DTO Waypoint tab, and nothing in it showed a typed ident
reaching the instrument -- see
[the PR #277 review comment](https://github.com/billmallard/pyEfis/pull/277#issuecomment-5974565721)
for the full finding. Root cause: typing `KSBA` + Enter on the DTO Waypoint tab resolves to a
single exact match, so `_select_waypoint` fires with `kind="direct_to"` and the page immediately
closes back to `fpl` (`_close_dto`/`_close_entry` in
`src/pyefis/instruments/flight_plan/__init__.py`) -- there is no stable on-glass state after
Enter that still shows the DTO page. Worse, `_close_dto` never clears `self._message`, so a
`SELECT A WAYPOINT` toast set by an earlier, unrelated activate-with-no-target click survives
onto the FPL page and reads as if it belongs to the typed sequence. This recapture types the
ident but deliberately stops short of Enter, so the DTO Waypoint tab itself -- not its aftermath
-- is what the image shows.

`dto_waypoint_tab_virtual_usb_keyboard.png` -- DTO page, **Waypoint tab**, after typing `K` `S`
`B` `A` (no Enter) via a **uinput virtual HID keyboard**, not a literal physical dongle: this
agent has no hands at the bench, so a literal USB keyboard is still untested. What this does
prove: `python3-evdev` (`sudo apt-get install -y python3-evdev`) opened `/dev/uinput` (root-only;
`sudo -n python3 ...`) and registered a device (`UInput(capabilities,
name="pyefis-bench-virtual-usb-kbd", ...)`) that the kernel, udev and X11 enumerated identically
to a physical keyboard -- confirmed from the logs of this exact capture, not pasted from a
different run:

```
Xorg.0.log: (II) config/udev: Adding input device pyefis-bench-virtual-usb-kbd (/dev/input/event18)
Xorg.0.log: (II) Using input driver 'libinput' for 'pyefis-bench-virtual-usb-kbd'
Xorg.0.log: event18 - pyefis-bench-virtual-usb-kbd: is tagged by udev as: Keyboard
Xorg.0.log: (II) XINPUT: Adding extended input device "pyefis-bench-virtual-usb-kbd" (type: KEYBOARD, id 16)
Xorg.0.log: event18 - pyefis-bench-virtual-usb-kbd: device removed
Xorg.0.log: (II) config/udev: removing device pyefis-bench-virtual-usb-kbd
```
(the add/remove pair brackets the ~3s the device existed for this one capture: created, `K`/`S`/
`B`/`A` sent with a short delay between each, then closed.)

So the keystrokes crossed the same kernel evdev -> libinput -> X11/xkb -> Qt `keyPressEvent` path
a real USB keyboard would use -- this is not an XTestFakeKeyEvent/`xdotool key` software
injection, which bypasses the evdev layer entirely. `K`/`S`/`B`/`A` all resolved via the default
US xkb layout already on the box; no keymap tweak was needed. The image shows the on-glass result
directly: the entry field reads `KSBA` and the suggestion strip's first slot shows the matched
`KSBA` candidate -- that population is the on-glass signal that the keystrokes reached the
instrument's input handling (`_entry_key`/`_entry_candidates`), not just the X server. Enter was
deliberately not sent, so the direct-to was never committed and the page never navigated away --
unlike the first attempt, there is no ambiguity here about which page produced the image.

This is still not the literal DoD line ("a USB keyboard ... types") -- it is the strongest remote
substitute available, and the gap between the two is a question of whether kernel-level
HID-identical input satisfies that line, not a question of whether the code path works. Flagging
that distinction rather than quietly claiming the literal hardware check as done.

**Repaint lag, noted for whoever captures here next.** On this bench, a key event sent via the
uinput device does not reliably show up in an `x11grab` frame for several seconds afterward (the
Qt repaint + compositor lag outlasted a 0.5-1s wait more than once during this session, producing
a screenshot that looked like nothing had happened even though the keystroke had landed). Wait
at least 5s after the last synthetic keystroke before grabbing the frame, and if a screenshot
looks like a no-op, recheck after a longer wait before concluding the input didn't register.

**DIRECT badge / magenta line -- not re-attempted here.** The prior FP5b session (same date,
before this recapture) reported a magenta ring/crosshair glyph on the Map tab after a direct-to
interaction that did commit (typed + Enter), while the `FPLSTATE` DIRECT badge itself never
appeared -- attributed there to the bench's map showing `NO POS` throughout (X-Plane not feeding
position). That observation stands as reported in that session; it is not re-verified by this
recapture, since this recapture deliberately never commits the direct-to (no Enter sent). Forcing
a synthetic `LAT`/`LONG` to retest it would mean enabling `fix-gateway`'s `COMMAND` connection and
restarting the shared fix-gateway service -- deferred to AER-809 (FP8, bench validation flight
against X-Plane), as before.

**Cleanup.** No Catalog/stored-route state was changed this session. The bench's `pyefis.service`
was restarted twice to get a clean widget state (no stale toast) before capturing; the working
plan reloaded as `TEST` (KSBA only -- the `KDFW` row seen in the pre-recapture, stale-toast
screenshot was in-memory and did not survive the restart, so it was never a persisted part of
`TEST`). Only the DTO Waypoint-entry field was exercised (typed then the page closed via Escape,
also sent through the same uinput device), not Activate/Store/Delete. Left on the Flight Plan
tab, FPL page, matching the state this session started from.
