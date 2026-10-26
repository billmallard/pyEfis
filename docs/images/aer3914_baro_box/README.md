# Altimeter tape baro setting box (pyEfis #311, AER-3914)

| File | What it shows |
|---|---|
| `sheet_zoom3x.png` | **Pi 5 render, nearest-neighbour 3x.** The bottom 220 px of the stock ALT tape (144 x 1200 px, the `svs.yaml` tape on the Pi's 1920x1200 / 200 x 110 grid), over a sky colour standing in for the SVS. Left to right: inHg at rest with the dim edit icon; inHg focused by a real synthetic touch; hPa focused after 3 inner-knob steps (1013 -> 1016); the knob-walk highlight; BARO failed. |
| `sheet_1x.png` | The same, actual size. |
| `tape_full_1x.png` | One whole tape, focused, actual size (the mock ALT value is 100). |
| `beelink_live_half.png` | **Live Beelink PFD** (the bench's served `screens/managed.yaml`, X11), this branch at `2d14982`, 50%. The box is at the bottom of the altimeter tape; it is the only baro readout on the screen. |
| `beelink_live_box_1x.png` | The box from that frame, 1:1. |
| `beelink_live_touch_3x.png` | Live Beelink, 3x crops of the box: at rest; about 1.5 s after an `xdotool` click on it (ring + icon); the next frame, about 12.5 s after the click (see the PR: still focused, an open anomaly). |

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
