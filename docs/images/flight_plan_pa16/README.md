# flight_plan bench captures (PA16, AER-2088)

Real X-session captures from the Beelink pyEfis bench (`bench_deploy.md --ref
aer-2088/fpl-airway-map-only-expansion`), taken directly against the live X
display the same way `../flight_plan_bench/README.md` (AER-805) documents:

```bash
DISPLAY=:0 xdotool mousemove <x> <y> click 1
kill -USR1 <pyefis pid>              # writes /tmp/pyefis_screenshot.png
```

Scenario built live through the UI (ADD WPT KSBA, ADD WPT GVO -- both from
the Recent list -- then GVO's row menu -> Load Airway -> V27 -> AVOLS), the
real bench `procedures-conus` pack, not a synthetic fixture.

- `fpl_page_collapsed_airway_row.png` -- FPL page after inserting V27 from
  GVO to AVOLS (4 published fixes: MZB, REDIN, PACIF, AVOLS). The whole
  segment is one row, "V27 -> AVOLS", the permanent state this PR ships (no
  on-page expansion any more).
- `fpl_page_tap_opens_row_menu.png` -- the same row tapped: it opens the row
  menu (Insert Before/After, Load Airway, Activate Leg, Direct To, WPT Info,
  Set Role, Remove) instead of expanding into its 4 member fixes. This is the
  DoD's "no tap path expands an airway row" proven on the glass, not just in
  the test suite.
- `map_tab_route_unaffected.png` -- the Map tab against the same plan: the
  route line still draws from the FP1 bus independently of the FPL page's
  display grouping, per the DoD's "map rendering is unchanged".
