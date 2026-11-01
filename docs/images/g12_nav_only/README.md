# G12 evidence: moving map `map_style: nav_only` (AER-4462, pyEfis #135)

## Files

| File | What it is |
|---|---|
| `offscreen_standard.png` | Real `MovingMap`, real Beelink data packs, rendered offscreen at 34.30 N 119.80 W, track 000, range 20 NM, 1280x720, fixes and airways on. `map_style` unset. |
| `offscreen_nav_only.png` | Same pose and options, `map_style: nav_only`. |
| `glass_*.png` | The live Beelink screen with the branch staged by `bench-deploy.sh --ref`, captured by pyEfis's own SIGUSR1 grab. See "On the glass" below. |
| `contrast_table.py` / `contrast_table.md` | WCAG contrast of every retained layer, read from the palette tables in the source. A computed bound, not the device check. |
| `bench_scripts/g12_glass.py` | Feeds a static position over netfix, publishes and activates a KSBA-GVO-RZS plan, opens the Map tab and grabs the screen. It republishes the bench's own plan at the end. |

## Offscreen renders, and the byte-identity check

Run on the Beelink (it has real fonts and the data packs), from scratch copies
of the tree under `~/bench-scratch/aer-4462/`. Neither copy touches the live
display or the checkout:

```sh
A="--lat 34.30 --lon -119.80 --track 0 --range 20 --width 1280 --height 720 --fixes --airways"
# dev @ 01559b1 (after the merge of dev into this branch), with tools/render_map_style_evidence.py copied in
cd ~/bench-scratch/aer-4462/dev && QT_QPA_PLATFORM=offscreen ~/pyefis-venv/bin/python \
    tools/render_map_style_evidence.py $A --styles standard --out out
# this branch
cd ../branch && QT_QPA_PLATFORM=offscreen ~/pyefis-venv/bin/python \
    tools/render_map_style_evidence.py $A --styles standard nav_only --out out
cmp ../dev/out/map_standard.png out/map_standard.png && echo BYTE-IDENTICAL
```

Result: `BYTE-IDENTICAL`. Both standard renders hash
`499dc8da5c89b764d816b7643dc33cfcbacab35d44c22bcf8aea41c33ac628cc`
(an earlier pass against dev @ eed5e72, before the merge, also matched:
`d0fc35c1...e3015af`). The tool
waits until every enabled layer reports `is_settled` before it grabs. The
Beelink has no rivers pack, so the rivers layer draws nothing in these renders.

## Contrast table

```sh
PYTHONPATH=src python docs/images/g12_nav_only/contrast_table.py > docs/images/g12_nav_only/contrast_table.md
```

## On the glass

`bench_scripts/g12_glass.py` runs on the Beelink under
`flock -w 900 /tmp/pyefis-bench.lock`, once with the live screen as it is,
and once after adding `map_style: nav_only` to the Map tab's `moving_map`
options in `~/makerplane/pyefis/config/screens/managed.yaml` and restarting
pyEfis. `managed.yaml` was backed up first and restored afterwards. The
exact steps and the SHAs are in the PR body.

### Glass capture, 2026-11-01

- Staged with `bench-deploy.sh --ref aer-4462/map-nav-only-preset --owner AVIONICS --issue AER-4462`: pyEfis @ 3368282, fix-gateway dev @ 666c3d7, makerplane-data dev @ 3aec02a.
- `glass_standard.png`: the live screen as served (`screens/managed.yaml`, Map tab, no `map_style`). This is the second of two grabs taken 3 s apart. The first was still settling (it differed across the map and the HSI), so the settled one is used.
- `glass_nav_only.png`: after one change on the device. `map_style: nav_only` was added as the first option of the Map tab's `moving_map` block in `~/makerplane/pyefis/config/screens/managed.yaml` (line 132), then pyEfis was restarted. Both grabs were byte-identical.
- `map_panel_*.png`: the right-hand map panel cropped from each frame (x 1248-1920).
- `glass_keys.log`: the FIX values read back at each grab.
- Afterwards: `managed.yaml` was copied back from the backup (`cmp` clean) and pyEfis restarted. The script republished the bench's own plan (PA15, 25 slots) and re-ACTed leg 2. Then `--restore`.
- The PFD's white left area is the GL SVS panel, which is blank in a SIGUSR1 grab on this box. That is expected.

## After merging dev with #369 (RD2 road casing), AER-4590

The merge of dev 8024da26 into this branch (088f2a27) was A-B'd against the
accepted head 515e0b62 with `tools/render_map_style_evidence.py` on the
Beelink. Each tree was a `git archive` copy under `~/bench-scratch/aer-4590/`,
and dev got a copy of the tool:

```sh
D="--data /data/makerplane-data --width 1280 --height 720 --fixes --airways"
# accepted pose (above), and close in over KSBA
tools/render_map_style_evidence.py $D --lat 34.30 --lon -119.80 --track 0 --range 20 --styles standard nav_only --out out_r20
tools/render_map_style_evidence.py $D --lat 34.4262 --lon -119.8404 --track 250 --range R --styles standard nav_only --out ksba_rR   # R = 2, 1, 0.5, 0.25
```

- At 20 NM (the accepted pose), and at 2 NM and 1 NM over KSBA, both styles are
  byte-identical between 515e0b62 and the merge. The standard renders also
  match dev.
- Below 1 NM (0.5 and 0.25 NM over KSBA), standard on the merge is
  byte-identical to dev, so it is #369's picture. nav_only differs from
  515e0b62. #369 draws roads at true width with a `#5a5a5a` casing, and the
  merge swaps only the fill colour to the nav_only palette, so the casing stays
  `#5a5a5a` in every style.
- `merge369_nav_only_0p5nm_ab.png`: nav_only at 0.5 NM over KSBA. Top is
  515e0b62, bottom is the merge. 1:1.

The default `range_ladder` (2..160 NM) also clamps pinch zoom, so this change
only appears on a screen whose ladder goes below about 1 NM.

## nav_only road casing, AER-4607

The follow-up to the section above. `road_casing` was added to both palettes:
standard `#5a5a5a` (unchanged), nav_only `#3c3c3c`. The standard casing is
0.47 of its `#c0c0c0` fill, and `#3c3c3c` is the same fraction of `#808080`.
Rendered on the Beelink from `git archive` copies under
`~/bench-scratch/aer-4607/`: `dev` (41cda11, with the tool copied in),
`before` (#366 head 84d4f93), `after` (this branch), and `alt` (this branch
with the nav_only casing hand-edited to `#282828`, for comparison only):

```sh
D="--data /data/makerplane-data --width 1280 --height 720 --fixes --airways"
for R in 20 1 0.5; do
  tools/render_map_style_evidence.py $D --lat 34.4262 --lon -119.8404 --track 250 --range $R --styles standard nav_only --out ksba_r$R
done
tools/render_map_style_evidence.py $D --lat 34.30 --lon -119.80 --track 0 --range 20 --styles standard nav_only --out acc_r20
```

- Standard is byte-identical to dev at 20, 1 and 0.5 NM over KSBA and at
  the accepted 20 NM pose (`499dc8da...c628cc`, as above).
- nav_only is byte-identical to the #366 head at 20 and 1 NM over KSBA and
  at the accepted pose. It differs only at 0.5 NM, where RD2 draws the casing.
- `casing_nav_only_0p5nm_ab.png`: nav_only at 0.5 NM over KSBA, track 250.
  Top is the #366 head (`#5a5a5a` casing), bottom is this branch. 1:1.
- `casing_nav_only_0p5nm_zoom3x.png`: the top right of the same frame
  (x 1080-1280, y 0-240), 3x nearest-neighbour. Left to right: `#5a5a5a`
  (before), `#3c3c3c` (this branch), `#282828` (the darker alternative).
