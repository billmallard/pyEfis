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
