# Flight plan pictures

For [Flight Plan](../../wiki/Flight-Plan.md). All are the right-hand tab column
cropped out of a 1920 x 1080 frame of the simulator bench (the Beelink, X11),
box (1248, 0, 1920, 1080).

| File | How |
|---|---|
| `bench_fpl_tab_hold.png` | x11grab frame `110127_hold_fpl_tab_2.png` from sim-bench session `a9055711e732` (2026-11-07, in the WINCH hold), taken by [`../hsi/bench_flight/docs_flight.py`](../hsi/bench_flight/docs_flight.py) after it touched the Flight Plan tab. |
| `bench_fpl_empty.png` | Ground capture, 2026-11-07 14:0x UTC, no flight and no plan: touch the Flight Plan tab. |
| `bench_add_wpt.png` | Then touch ADD WPT. |
| `bench_direct_to.png` | Then X, then DIRECT TO. |
| `bench_catalog_one_route.png` | Then X, then CATALOG (one stored route on the bench). |
| `bench_fpl_menu.png` | Then X, then MENU. Closed with Cancel, then the Map tab touched again. |

The ground captures were taken outside sim-bench flying hours with the bench
lock held, on pyEFIS `dev` (the bench checkout read `5abf28d`; `src/` is identical from `980497e` to `c8d7ede`). Each step was a
touch (`xdotool mousemove X Y click 1`) followed by pyEFIS's own screenshot
(`kill -USR1 <pyefis pid>`, written to `/tmp/pyefis_screenshot.png`). That
grab draws the synthetic-vision area white, which is outside these crops. The
bench was left on the Map tab with an empty plan; its final grab is
byte-identical to the one taken before the first touch.

The nav status line on the page is `../nav_status/contact_sheet_3x.png`, a
render with its own README.
