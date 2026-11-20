# AER-6139 (SVSTFC1) evidence: ADS-B traffic in the synthetic vision

Real GL renders of the SVS with traffic, through the production draw path
(`SVSGLRenderer._render_overlays`), captured with `tools/svs_capture.py`
at pyEfis `ce118355` (each PNG's `.json` sidecar names the commit and the
exact command).

**These are sandbox renders, not the benches.** The GL is Mesa llvmpipe
(software) under Xvfb, 800x480, no MSAA. Both benches were held by the
72 h show-unit soak (AER-5995) when this was made. The bench run the
definition of done asks for (Pi 5 GL capture, Beelink screenshot, frame
budget) is added to this directory when the hold ends.

| File | What it is |
|---|---|
| `sandbox_svs6.png` | Over Santa Barbara at 4,500 ft, heading 034: the six P3b states inside the forward fan |
| `sandbox_svs6_zoom2x.png` | the target band of that frame, 2x nearest-neighbour |
| `sandbox_ridge20.png` | 2,000 ft, heading 000, the Santa Ynez ridge (about 2,600 ft at 4.5 NM) ahead: the six states plus 14 more targets, 20 in all |
| `sandbox_ridge20_zoom2x.png` | the target band of that frame, 2x nearest-neighbour |
| `sandbox_ridge_none.png` | the same pose with no traffic, to show where the ridge is |

The six states (relative to ownship's pressure altitude, `PALT` = the
commanded altitude):

| Tag | State | What to see |
|---|---|---|
| `+05` | normal, 2.5 NM, 12 deg left | filled white arrowhead, pointing along its track relative to our heading |
| `-03` | traffic alert (`ALRT = 1`), climbing 1,000 fpm | yellow; flashes filled/open (the frame caught one phase); up arrow |
| `+15` | degraded (NIC 3, NACp 3) | open outline |
| `+08` | stale (`TFCkTGT` `old`) | grey dashed outline; down arrow (descending 600 fpm) |
| `--` | altitude invalid (`TFCkALT` `bad`) | tag dashed; drawn at ownship level (the co-altitude assumption) |
| `-12` | no track (`TTYP = 0`) | diamond, non-directional |

In `sandbox_ridge20.png` the ridge (magenta: terrain above us, see
`sandbox_ridge_none.png`) crosses the whole view at about 4.5 NM. The
three `-20` targets, 4.9 to 6.0 NM out, are at sea level and the `-08`
ones at 1,200 ft, beyond and below the ridge line from 2,000 ft: terrain
would hide them, and they are drawn over it.

## Reproduce

Terrain is public Copernicus GLO-30, fetched and converted with the repo's
own tools:

```sh
python tools/fetch_glo30.py --dest glo30raw --tiles N33W120 N34W120 N34W121 N35W120 N35W121
python tools/convert_glo30.py --src glo30raw --dest tiles
```

Then, on any display with GL (the sandbox used Xvfb + `QT_QPA_PLATFORM=xcb`):

```sh
python tools/svs_capture.py --out sandbox_svs6.png --lat 34.4258 --lon -119.8415 \
    --alt 4500 --heading 34 --traffic svs --tiles tiles --nasr "" --dof "" --water "" \
    --offscreen --width 800 --height 480 --range 20
python tools/svs_capture.py --out sandbox_ridge20.png --lat 34.4258 --lon -119.8415 \
    --alt 2000 --heading 0 --traffic svs --traffic-extra 14 --tiles tiles \
    --nasr "" --dof "" --water "" --offscreen --width 800 --height 480 --range 20
```

`--traffic svs` seeds the mock FIX db with the bench injector's scenario
(`tools/bench_traffic_inject.py --layout svs`), written the way the
gateway's traffic writer writes it. On a bench, the same scene over the
real path is `bench_traffic_inject.py --layout svs --extra 14 --ownship`
into fix-gateway's stratux plugin (see `docs/aer-5266-evidence/README.md`
for enabling it).
