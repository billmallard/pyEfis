# PA15 (AER-2087): FPL list finger scrolling, Beelink bench frames

Beelink kiosk (1920x1080, X11/xcb), PFD screen, right-hand tab section on
its **Flight Plan** tab. Each image is the panel cropped at 1:1 from a full
x11grab (`x = 1250..1920`), so the row geometry is exactly what the glass
shows at the real tab width.

Captured 2026-10-31 23:27-23:29Z on pyEfis `2f3a8b2` (this branch before
`46c3be9`, the drag-anchor fix). `46c3be9` only changes how a drag anchors
at the threshold. Recapture on the fixed head is tracked on AER-2087.

| File | What it shows |
|------|---------------|
| `1_top.png` | 24-fix route, 14 rows at the physical row height, scroll bar on the right edge with the thumb at the top. Active leg (PA001) magenta. |
| `2_dragged.png` | After a slow drag up 400 px (pointer held 0.6 s before release, so no fling). The list moved about 6.5 rows and the partial top row is clipped under the column header. No row menu opened. |
| `3_flung_to_end.png` | After a 300 px flick released while moving. The fling carried to the end and stopped there: PA023, the last fix, is the bottom row and the thumb is at the bottom. |
| `4_tap_opens_row_menu.png` | A plain tap on a row still opens its row menu. |
| `strip.png` | The four side by side. |

## How they were made

The route goes on the bus with no sim, and the drags are real X11 pointer
input (xdotool), which reaches the widget through the same Qt mouse path a
touchscreen's synthesised mouse events take. Run on the bench, under the
lock, with `bench_scripts/pa15_bench.py` and
`../fp8_bench/bench_scripts/nfx.py` side by side in one directory:

```sh
P="python3 pa15_bench.py"; D=out
$P snapshot $D                          # save the bench's route block first
setsid nohup $P feed 900 >feed.log 2>&1 </dev/null &   # outside the lock
$P publish $D 24; $P act 2
xdotool mousemove 1345 14 mousedown 1 sleep 0.15 mouseup 1   # Flight Plan tab
$P shot $D top
$P drag 1550 820 420 20 0.02 0.6; $P shot $D dragged     # slow drag, no fling
$P drag 1550 820 520 6 0.01 0;  sleep 2.5; $P shot $D flung
$P click 1550 373; $P shot $D tap                        # opens the row menu
$P restore $D                           # put the bench's route back
```

Do not start the feeder inside `flock ... sh -c`: a background child inherits
the lock's file descriptor and holds the bench lock until it exits.

Crops: `Image.open(f).crop((1250, 0, 1920, 1080))` (PIL).
