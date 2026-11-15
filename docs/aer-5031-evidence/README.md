# AER-5031 (CERT1): a hung fix-gateway, before and after the link watchdog

Beelink bench (X11/xcb, 1920x1080), 2026-11-07. Every frame is a full-framebuffer
`ffmpeg -f x11grab` grab. The SIGUSR1 Qt grab leaves the GL attitude panel blank,
and the attitude indicator is the instrument this evidence is about.

The bench had no live source (X-Plane was not running and the primary keys read
`Old`), so `cert1_writer.py` fed PITCH, ROLL, ALT, IAS, HEAD, VS, ALAT and TAS over
netfix at 10 Hz, with roll swinging +-20 deg on an 8 s period. That gives the glass
fresh, good data and makes a frozen frame visible as a frozen bank angle.
`cert1_capture.sh` then sent `SIGSTOP` to the fix-gateway process, so it stayed
connected with its sockets open but stopped answering, grabbed frames, sent
`SIGCONT` and grabbed again.

| Image | pyEfis | What it shows |
|---|---|---|
| `before_live.png` | dev `9a681de` (no watchdog) | Live feed, about 17 deg left bank, 110 kt, 4510 ft. |
| `before_hung_12s.png` | dev `9a681de` | 12 s after SIGSTOP: the same bank, speed and altitude, nothing flagged. It is byte-identical to the 1 s frame: the glass froze. |
| `after_live.png` | branch `d76233e` | Live feed on the fix. |
| `after_hung_1s.png` | branch `d76233e` | 1 s after SIGSTOP, before the 2 s timeout: still live-looking, as designed. |
| `after_hung_6s.png` | branch `d76233e` | 6 s after SIGSTOP: attitude, airspeed, altitude, VSI, baro and the altitude bug all show their existing failed state (red XXX, grey ground). It is byte-identical to the 12 s frame. |
| `after_resumed_4s.png` | branch `d76233e` | 4 s after SIGCONT: every instrument is back with live values. |
| `contact_sheet.png` | - | The two before frames on top and two after frames below, PFD column only, scaled 0.5x. |

fix-gateway was on `dev` for the before run. For the after run it was on
`aer-5029/navtype` (`b121eb1`), staged by a concurrent session two minutes earlier.
That branch adds NAVTYPE keys and does not touch netfix. The watchdog is pyEfis-only
and the stop was a `SIGSTOP` of the whole process, so the gateway's branch does not
bear on what these frames show.

`before_info.txt` and `after_info.txt` are the capture logs. In the after log, the
watchdog trips at 19:31:58, 2.0 s after the 19:31:56 SIGSTOP, and recovers at the
19:32:11 SIGCONT.

What the failed state does not cover, as rendered by each widget's existing fail
look, unchanged by this change: the heading box keeps showing `HDG 000 / MAG 090 /
CRS 000` under a small red `HDG`, the HSI rose and course needle stay drawn, the
airspeed tape keeps its scale numbers, and the moving map is untouched. The map
was already `NO POS` on this bench.

## Regenerate

On the Beelink, with the branch staged (`bench-deploy.sh --ref <branch>`) and pyEfis
restarted:

```sh
mkdir -p ~/bench-scratch/aer-5031
# copy cert1_writer.py and cert1_capture.sh there, then:
flock -w 900 /tmp/pyefis-bench.lock sh ~/bench-scratch/aer-5031/cert1_capture.sh after
```

The script always sends `SIGCONT` to fix-gateway on exit (`trap`), including on
Ctrl-C. Frames land in `~/bench-scratch/aer-5031/<label>/`.
