# AER-4243: SVS with a dead position, on the Beelink bench

Full-screen x11grab frames of the live Beelink kiosk (X11, managed screen,
`virtual_vfr` attitude instrument with SVS on), 2026-10-30. X-Plane was not
running, so nothing was writing position and the gateway aged LAT/LONG out on
their 20 s bench tol. PITCH/ROLL were old too, which is why the sky is grey in
every frame (AI-FAIL-001).

| File | Build | LAT at the gateway | What it shows |
|---|---|---|---|
| `1_before_dev_lat_old.png` | dev `68fc968` | `Old` | The defect. The map says NO POS with a grey ownship, and the SVS draws terrain at the dead position. |
| `2_after_lat_old.png` | branch `73078f4` | `Old` | Same state. The terrain is gone, the ground is the attitude fill, and SVS UNAVAIL shows. |
| `3_after_lat_fresh.png` | branch `73078f4` | fresh (rewritten 5 s earlier) | The terrain is back, the map ownship is yellow, no annunciation. |
| `4_after_lat_aged_out.png` | branch `73078f4` | `Old` (36 s after the write) | It aged out live. SVS UNAVAIL and the map's NO POS appear together. |

Frames 1 and 2 were taken after a pyEfis restart with LAT already old, so pyEfis
learned the flag from its initial read. Each was accepted only when three grabs
4 s apart had the same hash.

## How they were made

```sh
# stage the build (restarts pyEfis); --restore for the dev frame
ssh pyefis@10.110.10.241 'sh -s' < bench-deploy.sh -- --ref aer-4243/svs-stale-position --owner AVIONICS --issue AER-4243

# on the bench, under the bench lock
F=~/pyefis-venv/bin/fixgwc
DISPLAY=:0 xdotool mousemove 402 971 click 1          # boot nav-data screen: Continue
sleep 25; $F --execute "read LAT"                     # -> "34.392858 Old"
DISPLAY=:0 ffmpeg -f x11grab -i :0 -frames:v 1 frame.png

# frames 3 and 4
$F --execute "write LAT 34.392858"; $F --execute "write LONG -119.841493"
sleep 5;  DISPLAY=:0 ffmpeg -f x11grab -i :0 -frames:v 1 fresh.png
sleep 30; DISPLAY=:0 ffmpeg -f x11grab -i :0 -frames:v 1 aged.png
```
