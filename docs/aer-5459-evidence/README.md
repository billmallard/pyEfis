# AER-5459 (P3g) evidence: the map turns by true track, the ND rose reads magnetic

Before = `dev` @ `ab870309`, plus `tools/render_track_evidence.py` copied in
from the branch. After = `aer-5459/p3g-map-true-track` @ `f73c162e`. Both
trees were `git archive` exports, so each sidecar says `commit: unknown`;
these are the commits that drew them.

Rendered offscreen on the Beelink bench, 2026-11-12, under
`~/bench-scratch/aer-5459`. This is the real `MovingMap` with its real layer
workers, the bench's own data packs (`/data/makerplane-data`) and font
B612, fed from the in-memory mock FIX database (no fix-gateway). It is not
an x11grab of the live glass: the Beelink's display was held by another
staged review (AER-5418), so its display, checkout and config were not
touched. The map is a plain `QWidget`, so the grab draws the pixels the
panel would.

## The pose

Ownship is 2 NM before the KSBA runway 7 threshold, on the extended
centreline, at 1,500 ft, range 5 NM. The runway ends come from the bench's
NASR pack (`runway_ends`). `TRACK` is the runway's true bearing, 088.5.
`MAGVAR` is -14, KSBA's NASR variation (14 E; FIX `MAGVAR` is west-positive),
so `TRACKM` is 074.5.

Runway 7/25 is the long magenta runway. The short pair crossing it is 15L/15R.

## What to see

In each `cmp_*` image, dev is on the left and the branch is on the right.

| Image | dev (left) | branch (right) |
|---|---|---|
| `cmp_*_track_up.png` | runway 7/25 leans 14 deg left of straight ahead | runway 7/25 runs straight up from the arrow |
| `cmp_*_north_up.png` | the arrow points 075, 14 deg left of the runway | the arrow is parallel to the runway, 088 |
| `cmp_*_nd.png` | the rose reads 075 under the lubber, but the runway leans 14 deg | the rose still reads 075 under the lubber, matching `TRK 075 MAG`, and the runway runs straight up |

The wind arrow (`WINDDIR` 260, magnetic) is the same in both: it was
already drawn against a magnetic up, and still is.

`panel` = 650x1000, the bench's map panel (PFD screen, Map tab).
`hw` = 800x480, the 7-inch EFIS panel. `<size>/before/` and
`<size>/after/` hold the single frames, each with its sidecar.

## Commands

```sh
# local: export the two trees and copy them to the bench
git archive -o before.tar origin/dev src tools tests/mock_db tests/__init__.py
git archive -o after.tar f73c162e src tools tests/mock_db tests/__init__.py
# on the Beelink, with before/ and after/ extracted under ~/bench-scratch/aer-5459
# (tools/render_track_evidence.py copied into before/tools/):
for d in before after; do for sz in "650 1000 panel" "800 480 hw"; do set -- $sz
  (cd $d && QT_QPA_PLATFORM=offscreen nice ~/pyefis-venv/bin/python \
      tools/render_track_evidence.py --width $1 --height $2 --font B612 --out out/$3)
done; done
```

The side-by-side images were joined with PIL, dev on the left, with a
10 px white gap between the two frames.
