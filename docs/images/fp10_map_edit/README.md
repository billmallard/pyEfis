# FP10 bench evidence: tap to select, map pointer, banner (AER-812)

Beelink bench (X11 kiosk, 1920x1080, Map tab of the PFD's tab section, 10 NM
north-up), 2026-10-29 13:05-13:10Z. Revisions on the box for every image:
**pyEfis `712c531`** (`aer-812/fp10-map-graphical-edit`) and **fix-gateway
`356d22a`** (`aer-812/netfix-ack-echo`, which makes the ack reach the
display). No X-Plane was running, so position is stale (`NO POS`) except
where a synthetic 50 s position feed was on (below).

| File | What it shows |
|------|---------------|
| `01_tap_rzs_banner.png` | Tap on RZS: pointer on it, banner `RZS VOR`, `012° 7.8 NM ELEV 3596 FT 114.9`, five soft keys |
| `02_direct_to_rejected_no_position.png` | DIRECT TO with no position: the engine rejects it and the toast says so (`REJECTED: NO POSITION`) |
| `03_direct_to_rzs_accepted.png` | Same, position fed: `DIRECT TO RZS`, the magenta direct-to line, RZS ringed |
| `03_direct_to_rzs_accepted_full.png` | The full frame of 03: HSI CRS 012° matches the banner's 012° |
| `04_stacked_chooser.png` | Tap between two overlapping fix symbols east of KSBA: chooser lists all three in reach + CANCEL |
| `05_bare_map_point.png` | Tap on open water: `MAP POINT` with its position, bearing/distance, no elevation over water |
| `06_info_opens_fpl_tab.png` | INFO on the map point: the Flight Plan tab comes forward with WPT Info for `MAPWPT` |

The images are the map pane cropped out of the SIGUSR1 screenshot (x 1248-1920
of the 1920x1080 frame), except `_full`.

Bus side, read off the gateway at the same time (netfix subscription on a
second connection): DIRECT TO wrote `DTOID=RZS`, `DTOTYPE=2`, `FPLCMD "<n> DTO"`;
without position `FPLMSG=NO POSITION` then `FPLCMDACK=-n`; with position
`FPLCMDACK=n`, `FPLSTATE=2`, `FPLACTLEG=0`, `WPNAME=RZS`, `WPDIS=7.83`.

## Regenerate

On the bench, staged with `bench-deploy.sh --ref aer-812/fp10-map-graphical-edit`
and `--ref fix-gateway=aer-812/netfix-ack-echo`, under the bench lock:

```sh
# tap.sh X Y NAME SETTLE: xdotool click, then SIGUSR1 screenshot
DISPLAY=:0 xdotool mousemove 1762 178 click 1        # RZS
DISPLAY=:0 xdotool mousemove 1347 998 click 1        # DIRECT TO
kill -USR1 $(pgrep -f pyefis-venv/bin/pyefis)        # -> /tmp/pyefis_screenshot.png
```

Position feed for 03 (netfix, pyavtools client wire format, stops on its own;
`LAT` goes old 20 s later):

```python
s = socket.create_connection(("127.0.0.1", 3490))
# every 0.5 s for 50 s:
s.sendall(b"LAT;34.392858;0000\nLONG;-119.841493;0000\nALT;3000.0;0000\n"
          b"GS;110.0;0000\nTRACK;20.0;0000\nTRACKM;8.0;0000\n")
```

Crop: `Image.open(f).crop((1248, 0, 1920, 1080))` (Pillow).
