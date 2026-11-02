# RWY1 (AER-4631): true-size runways on the moving map

Offscreen renders of the real `MovingMap` widget on the Beelink bench
(`10.110.10.241`), with the bench's installed data packs under
`/data/makerplane-data` (terrain, water, highways, NASR `airports.sqlite`,
navaids) and the bench's fonts. The mock FIX database stands in for
fix-gateway. These are not grabs of the live kiosk display.

Pose: track 0 (track-up, so north-up), ownship a quarter of the range
south of the airport reference point, 800 x 480.

| File | What it shows |
|------|---------------|
| `<IDENT>_<R>nm.png` | this branch at 1, 2, 5 and 10 NM |
| `before_<IDENT>_2nm.png` | `dev` at 28534bb, same pose, 2 NM |
| `sheet_after.png` | the twelve branch renders, rows KSBA / KDFW / 0C0, columns 1 / 2 / 5 / 10 NM, at half scale |

Airports: KSBA (three hard runways), KDFW (seven long hard runways,
close parallels, a 627 ft displaced threshold on 13L), 0C0 Dacy, IL
(three turf runways).

1 NM is below the default range ladder (`2,5,10,...`); a pilot reaches it
only with a ladder that includes 1.

## Regenerate

From a checkout of the branch copied to the bench (no lock needed: the
render is offscreen and never touches the live display or checkout):

```sh
tar czf - src tools tests/mock_db tests/__init__.py | \
  ssh pyefis@10.110.10.241 'mkdir -p ~/bench-scratch/aer-4631 && tar xzf - -C ~/bench-scratch/aer-4631'
scp docs/images/rwy1_true_size_runways/render.sh pyefis@10.110.10.241:bench-scratch/rwy1-render.sh
ssh pyefis@10.110.10.241 'sh bench-scratch/rwy1-render.sh ~/bench-scratch/aer-4631 ~/bench-scratch/rwy1-after'
```

`render.sh` calls `tools/render_map_style_evidence.py --styles standard`
once per airport and range.
