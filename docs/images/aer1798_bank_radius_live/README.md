# AER-1798: bank-arc radius on the live Beelink display

Diagnostic evidence for AER-1798's step 1 -- whether the live kiosk display
was already affected by the AER-1785 `bankAngleRadius` first-resize latch
bug (fixed on open PR #251, not yet merged to `dev` at capture time), or
whether that defect was confined to the capture harness as originally
scoped.

Captured 2026-09-20 against the Beelink bench (`10.110.10.241`), X11 kiosk
session, `pyefis.service` freshly restarted onto `dev`@`4838942` (clean
tree, PR #251 not yet merged -- this is the exact pre-fix window the
question needs). Live screen: `PFD` (`managed.yaml`), `virtual_vfr`
spanning the full grid (rows 0-110/110, columns 0-130/200) against a
1920x1080 panel with no window chrome, giving an AI widget of
1250x1080px (boundary and full-bleed top/bottom verified from the raw
pixel data -- no letterboxing). The screen's `bank_radius` option is set
explicitly to `25` (not the code's classic 33.3 default), so the correct,
non-buggy radius for this config is `0.25 * 1080 = 270px`, not `height/3`.

## Files

- `beelink_pfd_live.png` -- full 1920x1080 X11 grab of the live display,
  taken via `DISPLAY=:0 scrot` (bypasses the app's SIGUSR1 handler, known
  broken for the SVS/AI widget -- see repo CLAUDE.md).
- `beelink_bank_cluster_zoom_3x.png` -- 3x nearest-neighbour crop of the
  bank-angle cluster at the top of the AI (the region the radius
  measurement is taken from).

## Measurement

Three independent geometric readings from the raw screenshot pixels (each
using `ai_widget.py`'s own placement formulas so the isolated unknown is
`r` = `self.bankAngleRadius`), all converging on the same value:

1. **Fixed datum triangle** (drawn once per resize in `draw()`, always at
   `x = w/2`, `y = anchor_y - r + [m/2 .. 2m]`): apex row measured at
   y=137, triangle height gives `m` (bankMarkSize) ~7.3px -> `r` ~266px.
2. **Slip/skid ball** (`drawEllipse` at `y = anchor_y - r + 3m`): centroid
   measured at y=159 -> `r` ~262.5px.
3. **Symmetric 30 deg long tick pair** (mirrored either side of the
   vertical through the pivot, midpoint at radius `r`): measured centroids
   at y~=164-167 either side of x~=624-626 -> `r` ~270.3px via
   `r = (anchor_y - y_offset) / cos(30deg)`.

`anchor_y` (`_bank_anchor_y`, `bank_position: 63`, `h=1080`) = `1080 *
(1 - 0.63)` = `399.6px` for all three.

All three methods land at **r ~ 262-270px**, matching the predicted
correct **270px** (25% of 1080) to within measurement/antialiasing noise.
None land anywhere near half that (~135px, which is what the AER-1785 bug
would have produced had the widget's first-ever resize reported roughly
half the final height).

## Conclusion

The live Beelink kiosk display is **not** exhibiting the AER-1785
half-radius defect at this resolution/config. This matches the code-read
finding already on this issue: the shipped default config sizes the
window from the real screen resolution *before* `showFullScreen()`
(`gui.py` `Main.__init__`), so the widget's first-ever `resizeEvent`
already reports the final 1080px height -- the same value a second,
fullscreen-forced resize would report -- so the latch coincidentally
freezes on the correct number. AER-1785 stays scoped as a capture-harness
defect (`tools/svs_capture.py`'s CLI-size-then-eglfs-fullscreen sequence
triggers a *mismatched* first/second resize that this kiosk path does
not); no correction to AER-1793's record is needed. PR #251 still lands
the documented default and closes the general latch bug regardless of
whether any specific deployed config currently reproduces it.

## Commands

```
ssh pyefis@10.110.10.241 'DISPLAY=:0 scrot -z /tmp/aer1798_live.png'
scp pyefis@10.110.10.241:/tmp/aer1798_live.png beelink_pfd_live.png
```

Measurement (run locally against the pulled screenshot):

```python
from PIL import Image
import numpy as np
from scipy import ndimage

im = Image.open("beelink_pfd_live.png").convert("RGB")
arr = np.array(im)
x0, x1, y0, y1 = 400, 850, 80, 320
sub = arr[y0:y1, x0:x1]
mask = (sub[:, :, 0] > 210) & (sub[:, :, 1] > 210) & (sub[:, :, 2] > 210)
lbl, n = ndimage.label(mask)
for i in range(1, n + 1):
    ys, xs = np.where(lbl == i)
    if len(xs) < 3:
        continue
    print(i, len(xs), xs.mean() + x0, ys.mean() + y0)
```
