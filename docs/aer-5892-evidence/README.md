# MENU1 evidence: the system menu on the Beelink (AER-5892)

Taken 2026-11-17 on the Beelink bench (X11/xcb, 1920x1080), branch
`aer-5892/menu1-system-menu` staged with `bench-deploy.sh --ref`, then
restored to `dev`. pyEfis logged the gesture zone it computed on that panel:

    system menu: corner swipe on (start x >= 1819, y <= 32 px; 4.0 px/mm)

Input was driven with `xdotool` through X (mouse events, the same path a
single-finger touch takes once Qt synthesizes it). A real finger and a pinch
were not used; the pinch and touch-stream cases are covered by
`tests/test_system_menu.py`, which sends real `QTouchEvent`s to the window.

| Image | What it shows |
|---|---|
| `before_after_pfd.png` | Left: `dev`, no menu. Right: the branch, after the corner swipe. |
| `menu_on_every_screen.png` | The menu opened by the swipe on every stock screen the bench loads (PFD, PFD_AI_ONLY, RADIO, EMS, EMS2, FLIGHTPLAN), on DataStatus, and the Screens page. |
| `return_route.png` | From PFD_AI_ONLY (not the default flight screen): Data Status, then Continue lands back on PFD_AI_ONLY; About, then Back lands back on PFD_AI_ONLY. |
| `rejects.png` | Gestures that must not open the menu, then the swipe that does. The journal's count of `opened by the corner swipe` stayed at 15 across the six map cases and at 17 across the four FPL cases, and went up by one for each swipe after them. |
| `card_main_1to1.png`, `card_screens_1to1.png` | The card at 1:1, for the look. |

Two frames come from the first staging, `cad66e01`, before the card-sizing fix
(`511b4410`): the PFD and DataStatus tiles of `menu_on_every_screen.png`, and the
right half of `before_after_pfd.png`. The fix changed only the Screens page; the
main page is drawn by the same code in both. The sidecars say which.

What this run found and fixed: the Screens page first came up as a 20 px bar on
the glass (widgets added to a visible card were left out of its height). The
tests had checked the buttons existed but not where they were; the fix
(`511b4410`) adds a test that every button sits on the card at full row height.

What it ruled out: after `bench-deploy.sh`'s own SIGUSR1 screenshot the
attitude panel went black as soon as the menu opened, and stayed black after it
closed. After a plain `systemctl --user restart pyefis` (no grab) the menu dims
the panel by exactly the scrim's alpha (grey 136 to 72) and it returns to 136
when the menu closes. The black panel is the existing SIGUSR1-grab defect on
this bench, made visible by the first full recomposition, not the menu.

## The bus key over the real wire

`wire_test.py` runs a real pyavtools client (not the test mock) in a pyEfis
process against a real fixgw netfix server from the fix-gateway branch
`aer-5892/sysmenu-key` on 127.0.0.1:3499, and writes `SYSMENU` from a second
netfix connection the way a control head would. `wire_test.out` is its output:
true opens the menu, false leaves it as it is, and the next true opens it
again. The slot runs on the GUI thread. The bench's live gateway was not used:
it does not define `SYSMENU` until the fix-gateway change is deployed, and it
was running under another session.

## Regenerate

On the bench, with the branch staged and pyEfis restarted plainly:

    sh drive.sh swipe 1905 10 1845 220      # the swipe
    sh drive.sh tap X Y                     # a tap
    sh drive.sh drag X0 Y0 X1 Y1 SECONDS    # a slow drag
    sh drive.sh grab NAME                   # an x11grab to NAME.png, logged in grabs.txt

`grabs.txt` lists every frame with its time, checkout HEAD and pyEfis PID.
Compose with:

    python3 compose.py <frames dir> docs/aer-5892-evidence <DejaVuSans.ttf>
