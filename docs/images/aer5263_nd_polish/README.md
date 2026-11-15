# G11c evidence: ND EXPANDED polish (AER-5263, pyEfis #134)

Before = `dev` @ `77882f6`, after = the G11c branch @ `51ec454`. Same tool,
pose and scenes as the G11a evidence (`../aer5085_nd_expanded/README.md`):
the real `MovingMap`, real layer workers and the Beelink bench's own data
packs (`/data/makerplane-data`), the mock FIX database seeded per scene,
rendered offscreen by `tools/render_nd_evidence.py` in font B612. Every
render waited until each enabled layer reported `is_settled`. Offscreen, not
the live glass: the map is a plain `QWidget`, so the grab draws the pixels
the panel would. The bench's display, checkout and config were not touched.

Pose: 34.380 N 120.000 W, `TRACKM` 072, 2500 ft, range 10 NM, fixes and
airways on, about 8.4 NM west of KSBA tracking toward it.

## Files

- `cmp_<size>_<style>.png` -- `approach` scene, before (left) and after
  (right) side by side.
- `<size>/before/` -- `dev`'s `approach` scene, both styles.
- `<size>/after/` -- the branch, every scene (`approach`, `gsflag`,
  `noglide`, `off`) in both styles.
- `hw` = 800x480, the 7-inch EFIS panel; `panel` = 650x1000, the bench's
  map panel (PFD screen, Map tab).

Each PNG has an evidence sidecar (`<image>.json`) naming the commit that
drew it. The ETA in each image is the render's own clock + `WPETE`.

## Commands, and off is byte-identical to dev

```sh
# on the Beelink: /tmp/nd_bench_aer5263.sh, scratch clones under
# ~/bench-scratch/aer-5263/ (branch @ 51ec454, dev @ 77882f6)
for sz in "650 1000 panel" "800 480 hw"; do set -- $sz
  for d in branch dev; do
    (cd $d && QT_QPA_PLATFORM=offscreen nice ~/pyefis-venv/bin/python \
        tools/render_nd_evidence.py --width $1 --height $2 --font B612 --out out/$3)
  done
  for st in standard nav_only; do
    cmp dev/out/$3/nd_off_$st.png branch/out/$3/nd_off_$st.png && echo "BYTE-IDENTICAL off $3 $st"
  done
done
```

Result: `BYTE-IDENTICAL` for all four (both sizes, both styles).
