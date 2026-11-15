# AER-5388 bench evidence: the ND button cycles MAPNDMODE

Beelink bench (X11), 2026-11-11, with fix-gateway `aer-5388/mapndmode` @ 1f93fb9
and pyEfis `aer-5388/mapndmode` @ 4f4ee4a6 staged by `bench-deploy.sh --ref`.
fixgw's own updater delivered `MAPNDMODE` through the stock (stamped)
`database/custom.yaml`; pyEfis's updater did the same for
`screens/map-controls-test.yaml`.

The screen was shown by a temporary edit, reverted byte-identical afterwards:
`preferences.yaml.custom` gained `SCREENS_CONFIG: screens/aer5388_list.yaml`
(the stock `default_list.yaml` plus `SCREEN_MAP_CTL_TEST`) and
`SCREEN_MAP_CTL_TEST: screens/map-controls-test.yaml`; `main/default.yaml` had
`defaultScreen: MAP_CTL_TEST`. Then pyEfis was restarted.

| File | State |
|---|---|
| `0-off-before.png` | after the restart, before any tap: MAPNDMODE 0, off |
| `1-expanded.png` | after tap 1: MAPNDMODE 1, expanded |
| `2-ctr.png` | after tap 2: MAPNDMODE 2, ctr |
| `3-off-again.png` | after tap 3: MAPNDMODE 0, off |
| `cycle-strip.png` | the four above at 1/3 scale, left to right then top to bottom |

Each tap, on the bench under the bench lock:

```sh
export DISPLAY=:0
xdotool mousemove 1776 950 click 1        # centre of the ND button at 1920x1080
sleep 2
~/pyefis-venv/bin/fixgwc --execute "read MAPNDMODE"
kill -USR1 <pyefis pid>                    # -> /tmp/pyefis_screenshot.png
```

Six taps read back 1, 2, 0, 1, 2, 0, and the SIGUSR1 frames of the second
pass were byte-identical to the first pass for each state. The map is a plain
QWidget, so the SIGUSR1 grab shows it (only GL panels come back blank).
`0-off-before.png` is an x11grab of the root window. "NO POS": the bench had
no position source at the time, which does not affect the mode geometry.
