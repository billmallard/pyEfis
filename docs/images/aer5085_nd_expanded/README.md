# G11a evidence: moving map ND mode, EXPANDED MAP (AER-5085, pyEfis #134)

Real `MovingMap`, real layer workers, the Beelink bench's own data packs
(`/data/makerplane-data`), the mock FIX database seeded per scene, rendered
offscreen by `tools/render_nd_evidence.py`. Font B612, as on the bench's live
map. Every render waited until each enabled layer reported `is_settled`.

These are offscreen renders, not the live glass: at the time the Beelink's
display was staged for another PR's review, so nothing here touched the live
display or the checkout. The map is a plain `QWidget`, so an offscreen grab
draws the same pixels the panel would.

## Pose and scenes

All scenes: 34.380 N 120.000 W, `TRACKM` 072, 2500 ft, range 10 NM, fixes and
airways on, about 8.4 NM west of KSBA tracking toward it. GS 112, TAS 118,
wind 300/14.

| Scene | What is seeded |
|---|---|
| `approach` | Plan active (`FPLSTATE` 1, `FPLPHASE` TERM) to KSBA: `WPDIS` = the great-circle distance, `WPETE` = `WPDIS / GS`. `GSV` 1, `GSI` +0.4. |
| `gsflag` | As `approach`, `GSI` bad: no pointer, red GS flag (the HSI's rule). |
| `noglide` | No plan (`FPLSTATE` 0, the engine's 0 / 0.0 / ""), `GSV` 0: no waypoint block, no deviation scale. |
| `off` | `nd_mode: off`, the plain map, for the dev comparison. |

Each scene is drawn under `map_style` `standard` (terrain) and `nav_only`.

## Directories

- `panel/` -- 650x1000, the bench's map panel (PFD screen, Map tab: 196/200
  of a 69-column tab section on a 1920x1080 display).
- `hw/` -- 800x480, the 7-inch EFIS panel.

The ETA in each image is the render's own clock + `WPETE`, so it differs
between images.

## Off is byte-identical to dev

```sh
# on the Beelink, from scratch clones under ~/bench-scratch/aer-5085/
# branch @ d0b6ad1, dev @ fce470c with tools/render_nd_evidence.py copied in
for sz in "650 1000 panel" "800 480 hw"; do set -- $sz
  (cd branch && QT_QPA_PLATFORM=offscreen ~/pyefis-venv/bin/python \
      tools/render_nd_evidence.py --width $1 --height $2 --font B612 --out out/$3)
  (cd dev && QT_QPA_PLATFORM=offscreen ~/pyefis-venv/bin/python \
      tools/render_nd_evidence.py --width $1 --height $2 --font B612 --scenes off --out out/$3)
  for st in standard nav_only; do
    cmp dev/out/$3/nd_off_$st.png branch/out/$3/nd_off_$st.png && echo "BYTE-IDENTICAL off $3 $st"
  done
done
```

Result: `BYTE-IDENTICAL` for all four (both sizes, both styles). The `off`
images here are the branch's.

The script lives at `/tmp/nd_bench_aer5085.sh` on the bench while the session
runs; the loop above is its body. Each PNG has an evidence sidecar
(`<image>.json`) naming the commit that drew it.
