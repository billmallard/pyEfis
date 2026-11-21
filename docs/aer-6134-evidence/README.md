# AER-6134 (CERT1f): the HSI's compass numerals follow HEAD alone

On `dev` the HSI hid its compass numerals whenever `isFail()` was true. That
covers a failed CDI, a failed GSI and a bad COURSE as well as an invalid
heading. With a valid heading, the card then showed ticks and no numbers. The
Beelink PFD's COURSE is invalid (`---`), so its HSI has never shown a numeral
(pyEfis #508, `docs/aer-5894-evidence/bench_hsi_sheet.png`).

Bill's ruling (2026-11-20): the numerals follow HEAD alone. They show whenever
HEAD is valid, whatever the nav state. A nav fault drops only its own symbols.
Those symbols already have their own gates: `_course_valid()` for the course
pointer, `_cdi_shown()` for the deviation bar, and the NAV and GS flags.

## Bench: Beelink, the live PFD (`cert1f_job.sh`)

`bench_hsi_sheet.png` crops the HSI from the two live frames and is upscaled 2x
nearest-neighbour. The left frame is `dev` at `ea09204f`, the bench checkout.
The right frame is the branch at `fd48221a`. Both frames come from the same
panel, with HEAD valid (`00000`, fed at 090) and COURSE bad (`00010`, the
bench's own state: no course source). `bench_*_info.txt` logs the flags read
around each grab.

- `dev`: MAG `090°`, CRS `---°`, NAV flag, and a ticked card with no numerals.
  This is how the bench HSI has looked in every frame (#508).
- Branch: the same, plus the numerals. The NAV flag stays up.

`cert1f_job.sh` ran on the Beelink on 2026-11-21, after the DEMO6 soak hold
ended. It grabbed the `dev` frame under the bench lock, then staged the branch
with `bench-deploy.sh --ref ... --owner AVIONICS --issue AER-6134`. It grabbed
the branch frame under the lock, then restored `dev` (`restore RC=0`).
`cert1f_capture.sh` feeds the primary keys with CERT1b's `cert1_writer.py`
(`docs/aer-5269-evidence/`). It leaves COURSE, CDI and GSI as the bench has
them. Grabs are full-framebuffer `ffmpeg -f x11grab` captures, taken twice
1 s apart; the second one is kept (`bench_*_live.png`). The LINK MON OFF
banner in the `dev` frame belongs to a separate bench check and is not part of
this change.

## The looks: offscreen widget renders with Beelink fonts (`render_hsi.py`)

`looks_dev.png` (before) and `looks_branch.png` (after) share a layout. The top
row is the rose and the bottom row is the arc. Left to right: all valid, CDI
fail, GSI fail, COURSE bad, COURSE fail, HEAD fail. CDI and GSI are enabled,
the heading is 090 and the course is 120. No gateway is used; the renders come
from `tests/mock_db`.

```
QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. \
  ~/pyefis-venv/bin/python docs/aer-6134-evidence/render_hsi.py strip looks.png
```

Run it from a `dev` tree for the before and from the branch for the after. The
script prints the path of the widget module it imported. Both sheets were
rendered on the Beelink, in `~/bench-scratch/aer-6134`, with the bench's own
venv and fonts. The live display and the checkout were not touched.

- `dev`: CDI fail, GSI fail and COURSE bad have no numerals. COURSE fail
  already kept them, because `isFail()` tests `_CourseBad` but not
  `_CourseFail`.
- Branch: every nav-fault column keeps its numerals. HEAD fail still removes
  them, along with the bug, as CERT1e ruled.

## Tests

`tests/instruments/hsi/test_hsi_heading_quality.py` adds three tests, under the
CERT1f heading:

- A nav fault alone keeps the numerals: CDI fail, GSI fail, COURSE bad and
  COURSE fail, each on the rose and the arc. The 6 CDI-fail, GSI-fail and
  COURSE-bad cases fail on `dev`. The 2 COURSE-fail cases pass there.
- The fault still drops the deviation bar (CDI fail, COURSE bad, COURSE fail).
- An invalid heading still hides the numerals with every nav input valid.

A mutation pass put `isFail()` back into each of the three gates in turn: the
rose numerals, the arc numerals and the rose label opacity in `changeFail()`.
Each mutant failed 3 or 4 tests.
