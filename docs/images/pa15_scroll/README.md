# PA15 (AER-2087): FPL list finger scrolling, Beelink bench frames

Beelink kiosk (1920x1080, X11/xcb), PFD screen, right-hand tab section on
its **Flight Plan** tab. Each image is the panel cropped at 1:1 from a full
x11grab (`x = 1250..1920`), so the row geometry is what the glass shows at
the real tab width.

Captured 2026-11-01 03:09:59-03:10:24Z on pyEfis **`f7b39d4`** (this branch
with `dev` merged). `provenance.txt` holds the checkout SHA and pyEfis PID
read at the start and end of the run. They match, so no other agent restaged
the bench mid-run, which happened twice on this shared box during the session.

The route is a 24-fix test route the driver publishes. Someone else's
session inserted **KGPM** as the fourth row while it was loaded. That is the
reason for the 1153 NM leg. It is not part of the test and does not affect it.

| File | What it shows |
|------|---------------|
| `1_top.png` | 25 rows, 14 at the physical row height, scroll bar on the right edge with the thumb at the top. Active leg PA001 magenta. |
| `2_dragged.png` | From the end of the list, a slow 400 px drag down (pointer held 0.6 s, so no fling). The list moved back about 7 rows to PA003. No row was selected. |
| `3_flung_to_end.png` | A 300 px flick released while moving. The fling carried to the end and stopped there: PA023 is the bottom row and the thumb is at the bottom. |
| `4_dragged_after_tab_switch.png` | Map tab, back to Flight Plan, then a slow drag. The first drag after a tab switch scrolls too. |
| `5_tap_opens_row_menu.png` | A plain tap on a row still opens its row menu. |
| `6_cancel_selects_nothing.png` | Cancel closes it, with nothing selected. |
| `strip.png` | The six side by side. |

## Repaint latency (measured, and present without PA15)

In `capture.sh`, two frames grabbed 0.8 s after release still showed the
list where it was **before** that drag. The next frame showed the drag
applied, so the input was handled and the paint was late. Measured with
frames at 0.1/0.3/0.6/1.0/2.0 s after each action:

| Build | Action | Late (> 0.1 s) | Worst |
|-------|--------|----------------|-------|
| `f7b39d4` (PA15) | 12 slow drags (`drag_latency.sh`) | 3 of 12 | 1.0 s |
| `f7b39d4` (PA15) | 12 switches back to the Flight Plan tab (`tab_latency.sh`) | 4 of 12 | 1.0 s |
| `3368282` (`dev` + a map preset, no PA15 code) | the same 12 tab switches | 3 of 12 | 1.0 s |

Switching to the Engine tab was on time 24 of 24 on both builds. In the late
frames the tab bar already shows Flight Plan selected while the page under it
is still the Engine page. So the Flight Plan widget's paint is intermittently
delayed by up to about 1 s on this bench, and that delay exists without the
PA15 code.

## How they were made

The route goes on the bus with no sim, and the drags are real X11 pointer
input (xdotool), which reaches the widget through the same Qt mouse path a
touchscreen's synthesised mouse events take. Run on the bench, with
`bench_scripts/*` and `../fp8_bench/bench_scripts/nfx.py` in one directory:

```sh
P="python3 pa15_bench.py"; D=out3
flock -w 300 /tmp/pyefis-bench.lock $P snapshot $D     # save the bench's route
setsid nohup $P feed 600 >feed.log 2>&1 </dev/null &   # OUTSIDE the lock
flock -w 300 /tmp/pyefis-bench.lock $P publish $D 24
flock -w 300 /tmp/pyefis-bench.lock bash capture.sh    # frames above (+ provenance guard)
flock -w 300 /tmp/pyefis-bench.lock bash drag_latency.sh
flock -w 300 /tmp/pyefis-bench.lock bash tab_latency.sh
flock -w 300 /tmp/pyefis-bench.lock $P restore $D      # put the bench's route back
```

Do not start the feeder inside `flock ... sh -c`. A background child inherits
the lock's file descriptor and holds the bench lock until it exits.

Crops: `Image.open(f).crop((1250, 0, 1920, 1080))` (PIL). Latency: compare
the list region `(0, 180, 640, 960)` of each frame to the last one.
