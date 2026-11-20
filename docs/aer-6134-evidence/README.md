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
