# AER-6639: the attitude goes black after a SIGUSR1 screenshot and a touch

2026-11-26, Beelink simulator bench (xcb, Intel ADL-N). X-Plane was off, so
LAT, LONG and TALT are old and the AI shows its SVS UNAVAIL fallback. The
served PFD is `screens/managed.yaml`.

## What causes it

A `kill -USR1` screenshot runs `mainWindow.grab()`. On xcb that takes the AI's
`QOpenGLWidget` viewport through Qt's own grab path. Nothing changes on the
glass at that point. The next repaint of any widget over the AI composes the
AI black: a touch on the HSI's HDG readout, or on the altimeter's baro box.
The AI repaints only when its data changes. On a static bus it never
repaints, so the attitude stayed black until restart.

The touch is not needed, and neither is the HSI:

| pyEfis | Screenshot first? | Touch | Sky mean after the touch (x 300-950, y 100-330) |
|---|---|---|---|
| `dev` 5143414f | no | HDG | 144.6 (two runs, one 30 s after a restart) |
| `dev` 5143414f | yes | HDG | **0.0**, still 0.0 at the timeout |
| `dev` 5143414f | yes | baro | **0.0**, still 0.0 at the timeout |
| fix c974be0f | yes | HDG | 144.6 throughout |
| fix c974be0f | yes | baro | 144.6 throughout |

On `dev`, one `PITCH` write after the black frame brought the AI back
(142.7 at PITCH 1, then 144.6 at PITCH 0), with no restart.

The issue's control run (a baro touch that stayed drawn) ran in a pyEfis
process that had taken no screenshot. Both failing runs in AER-6630 had: the
deploy's own screenshot at 02:42:23 and 02:45:59 (journal), then the press
or the touch.

## The fix

`main.save_screenshot()` grabs as before, then calls `update()` on every
`QOpenGLWidget` in the grabbed window, so the AI redraws its viewport before
it can be composed black. The saved image is unchanged: the SVS/AI panel is
still blank in it.

## Frames

`hdg_touch_dev_vs_fix.png`: top row `dev`, bottom row the fix. Left to
right: after the screenshot, 1.5 s after the HDG touch (cyan focus ring on
HDG), and 13.5 s after it, past the 10 s focus timeout. Each 1920x1080
frame is scaled to 640x360.

`baro_touch_dev_vs_fix.png`: the same for a touch on the baro box.

## Commands

On the bench, as `pyefis`, with the branch staged by `bench-deploy.sh`:

```
flock -w 300 /tmp/pyefis-bench.lock sh touch_after_screenshot.sh out/fix-hdg 566 678
flock -w 300 /tmp/pyefis-bench.lock sh touch_after_screenshot.sh out/fix-baro 1065 630
```

The script restarts `pyefis.service`, waits 30 s, sends SIGUSR1, touches
`x y` with xdotool and takes x11grab frames. It then writes `PITCH` 1.0 and
0.0 to the gateway over netfix, to show one AI repaint recovers.

The strips were made from the copied frames with:

```
QT_QPA_PLATFORM=offscreen python3 make_strip.py <frames-dir> .
```
