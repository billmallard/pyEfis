---
name: Visual / SVS Test Case
about: A repeatable manual test case for a visual or rendering behavior (SVS terrain/water/obstacles/airports, HSI, tapes). Log one whenever a visual edge case is found.
title: "[TEST] <area>: <short description>"
labels: ["test-case"]
---

<!--
Log a test case every time a visual edge case is found in flight or the harness,
so it can be re-checked after changes. Keep it concrete enough that someone else
can reproduce it from the steps alone.
-->

## Area

<!-- one: SVS terrain | SVS water | SVS obstacles | SVS airports/runways | HSI | altimeter/VSI tape | other -->

## Related issue / bug

<!-- e.g. #40 — leave blank if this case isn't tied to a known defect -->

## Origin

<!-- flight test (X-Plane / live) | visual harness | unit/headless -->

## Preconditions

- **Data:** <!-- nav-data cycle, terrain tiles, water/obstacle pack versions -->
- **Scenario / position:** <!-- lat, lon, MSL alt, heading; or airport / route -->
- **Config:** <!-- SVS enabled, range / auto-range, source, anything non-default -->

## Steps

1.
2.
3.

## Expected result

-

## Actual result (only when failing)

-

## Evidence

<!-- screenshot, X-Plane side-by-side, DB query output, perf numbers -->

## Notes

-
