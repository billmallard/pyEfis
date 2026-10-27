# Altimeter tape baro setting box (pyEfis #311, AER-3914)

| File | What it shows |
|---|---|
| `sheet_zoom3x.png` | **Pi 5 render, nearest-neighbour 3x.** The bottom 220 px of the stock ALT tape (144 x 1200 px, the `svs.yaml` tape on the Pi's 1920x1200 / 200 x 110 grid), over a sky colour standing in for the SVS. Left to right: inHg at rest with the dim edit icon; inHg focused by a real synthetic touch; hPa focused after 3 inner-knob steps (1013 -> 1016); the knob-walk highlight; BARO failed. |
| `sheet_1x.png` | The same, actual size. |
| `tape_full_1x.png` | One whole tape, focused, actual size (the mock ALT value is 100). |
| `beelink_live_half.png` | **Live Beelink PFD** (the bench's served `screens/managed.yaml`, X11), this branch at `2d14982`, 50%. The box is at the bottom of the altimeter tape; it is the only baro readout on the screen. |
| `beelink_live_box_1x.png` | The box from that frame, 1:1. |
| `beelink_live_touch_3x.png` | Live Beelink at `2d14982` (before the repaint fix), 3x crops of the box: at rest; about 1.5 s after an `xdotool` click on it (ring + icon); about 12.5 s after the click, where the ring should already have cleared. That stale frame is the defect the timeline below pins down. |
| `live_focus_timeline.png` | **Live Beelink, the focus ring on glass over time**, recorded continuously at 4 fps (one row per touch, cyan = ring visible; white line = touch, red line = the 10.5 s timeout). BEFORE (`f7b4d3d`, queued `update()`): the ring appears up to 3.5 s late and stays up past the timeout. CONTROL: TK1's `touch_edit` numeric_display on the same screen, on time 8/8. AFTER (`ee532a0`, synchronous `repaint()`): on time 10/10. |

The Pi renders are QPainter, not GL: the tape is a `QGraphicsView`, so an
offscreen render is the pixels the panel draws. They were made on the Pi 5
(`wpballard@10.110.10.199`, its own DejaVu fonts and PyQt6 from
`~/pyEfis/.venv`) from a throwaway clone of this branch in
`~/bench-scratch/aer-3914`. The Pi's live display was not touched (there is
no screenshot on the Pi, AER-2002).

Regenerate the renders:

```sh
QT_QPA_PLATFORM=offscreen PYTHONPATH=src python3 tools/render_baro_box_evidence.py OUTDIR
```

The bench round trip against the Pi's live fix-gateway (BARO restored after):

```sh
cd <clone> && QT_QPA_PLATFORM=offscreen ~/pyEfis/.venv/bin/python tools/bench_baro_roundtrip.py
```

The Beelink frames came from `bench-deploy.sh --ref aer-3914/tk3-baro-box`
(its flight frame), and from `xdotool mousemove 1064 629 click 1` followed by
`ffmpeg -f x11grab` on `:0`, under `flock /tmp/pyefis-bench.lock`.

The live focus timeline (Beelink, `flock` held, pyEfis restarted only by the
deploy before each series; one row per touch):

```sh
export DISPLAY=:0
xdotool mousemove 1900 1070; sleep 1
ffmpeg -loglevel error -f x11grab -framerate 4 -video_size 150x40 -i :0+990,600 -t 13.5 run/f%03d.png &
sleep 0.8; xdotool mousemove 1064 629 click 1; wait
```

A frame counts as "ring on" when it has more than 200 pure-cyan pixels (the
at-rest box with its dim icon has 96, the focused box 259). For the CONTROL
series a `touch_edit` numeric_display on `BARO` was added to the live
`managed.yaml` temporarily and the file was restored from backup afterwards.
That widget also turned the tape box off, which is the one-readout rule
working on the live screen.
