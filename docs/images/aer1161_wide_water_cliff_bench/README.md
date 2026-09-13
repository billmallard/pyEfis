# AER-1161 -- #212 staged on the Beelink bench

`beelink_map_render.png` is a live SIGUSR1 capture of `pyefis.service` on the
Beelink bench (`10.110.10.241`), staged on `aer-1149/wide-water-cliff` @
`0393723da318b4069370859a80ab9357295a2e60` (this PR's head at staging time,
unchanged by the AER-1161 dev-merge -- `terrain.py` is already final on that
head).

This is proof the branch boots and renders, not a demonstration of the
AER-1149 wide-water-cliff behaviour itself: the map is shown at 10 NM over
KSBA, not at the long range / landscape geometry the fix concerns. Whether
the fix *looks right* at range is Bill's call on the touchscreen, per the
issue.

## How it was produced

```bash
S=makerplane/processes/paperclip/scripts/bench-deploy.sh
ssh -i "$BEELINK_SSH_KEY" pyefis@10.110.10.241 'sh -s' < "$S" -- --ref aer-1149/wide-water-cliff
```

`bench-deploy.sh` takes a SIGUSR1 screenshot right after restart, which lands
on the nav-data currency splash screen (the app's normal boot gate, not a
defect). To get a render of the actual map screen:

```bash
export DISPLAY=:0
xdotool mousemove 400 970 click 1   # dismiss the currency splash's Continue button
kill -USR1 <pyefis PID>             # systemctl --user show pyefis.service -p MainPID
```

The second screenshot (`beelink_map_render.png`) is the one embedded in the
PR -- it is what is committed here.
