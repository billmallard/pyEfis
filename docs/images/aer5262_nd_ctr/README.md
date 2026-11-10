# G11b evidence: moving map ND mode, CTR MAP (AER-5262, pyEfis #134)

Real `MovingMap`, real layer workers, the Beelink bench's own data packs
(`/data/makerplane-data`), the mock FIX database seeded per scene, rendered
offscreen by `tools/render_nd_evidence.py --mode ctr`. Font B612, as on the
bench's live map. Every render waited until each enabled layer reported
`is_settled`.

These are offscreen renders from scratch trees under
`~/bench-scratch/aer-5262/`, not the live glass: nothing here touched the
bench's display or its checkout. The map is a plain `QWidget`, so an offscreen
grab draws the same pixels the panel would.

## Pose and scenes

The pose and scenes are G11a's (`docs/images/aer5085_nd_expanded/README.md`):
34.380 N 120.000 W, `TRACKM` 072, 2500 ft, range 10 NM, fixes and airways on,
about 8.4 NM west of KSBA tracking toward it. GS 112, TAS 118, wind 300/14.

| Scene | What is seeded |
|---|---|
| `approach` | Plan active to KSBA, `GSV` 1, `GSI` +0.4. |
| `gsflag` | As `approach`, `GSI` bad: no pointer, red GS flag. |
| `noglide` | No plan (`FPLSTATE` 0), `GSV` 0: no waypoint block, no deviation scale. |

Each scene is drawn under `map_style` `standard` (terrain) and `nav_only`.

## Directories

- `panel/` -- 650x1000, the bench's map panel.
- `hw/` -- 800x480, the 7-inch EFIS panel.

The ETA in each image is the render's own clock + `WPETE`.

## Commands, and off is byte-identical to dev

```sh
# on the Beelink: branch = git archive 818116eb, dev = git archive 77882f60
# (each: src tools tests/mock_db tests/__init__.py), branch's
# tools/render_nd_evidence.py copied into dev
cd ~/bench-scratch/aer-5262
for sz in "650 1000 panel" "800 480 hw"; do set -- $sz
  (cd branch && QT_QPA_PLATFORM=offscreen ~/pyefis-venv/bin/python \
      tools/render_nd_evidence.py --width $1 --height $2 --font B612 --mode ctr --out out/$3)
  (cd dev && QT_QPA_PLATFORM=offscreen ~/pyefis-venv/bin/python \
      tools/render_nd_evidence.py --width $1 --height $2 --font B612 --scenes off --out out/$3)
  for st in standard nav_only; do
    cmp dev/out/$3/nd_off_$st.png branch/out/$3/nd_off_$st.png && echo "BYTE-IDENTICAL off $3 $st"
  done
done
```

Result: `BYTE-IDENTICAL` for all four (both sizes, both styles). The trees had
no `.git`, so each sidecar's `commit` was stamped `818116eb` by hand afterwards,
with a `commit_note` saying so; each sidecar's `sha256` was re-checked against
its PNG at the time.
