# Moving map / SVS gesture performance plan (pyEfis #98)

**Note on this file's history:** this brief is cited by name in roughly a
dozen commit messages going back through the MP1-MP7 series (`git log --all
--grep map_gesture_perf_plan`) and in the module docstrings of
`tools/bench_map_gestures.py` and `src/pyefis/instruments/map/perf.py`, but
the file itself was never actually committed to any branch -- it lived
outside the repo (planning doc, not code) and the references to it outlived
it. Sections 1-4 below are reconstructed pointers to where that content
actually lives today (the shipped code, its tests, and the commits that
built it) rather than a verbatim recovery of the original text, which no
longer exists anywhere this session could check. Section 5 is new
(AER-679) and is the authoritative source for its own content.

## 1-3. GIL-starvation probe, root causes (R1-R4), GuiProbe

Implemented in `src/pyefis/instruments/map/perf.py`: `GuiProbe` (a 10 ms
QTimer measuring its own tick-to-tick gap on the GUI thread -- an objective
"is anything holding the GIL" signal independent of what's holding it) and
`MapPerfStats` (frames painted, paint-ms ring, per-layer job lifecycle
counters, water rasterization counters, settle latency). See that file's own
module docstring and the `AER-585`..`AER-588` / MP1-MP6 commits
(`git log --oneline -- src/pyefis/instruments/map/`) for the root causes
these counters were built to diagnose (gesture-phase gating, newest-wins
worker publication, the frame clock, render-discard races).

## 4. MP7 offscreen gesture benchmark harness

`tools/bench_map_gestures.py` (pyEfis #98) -- see that file's module
docstring and `docs/moving_map_spec.md` section 9.1 for the full schema.
Builds a real `MovingMap` under the Qt `offscreen` platform against the
same mock FIX db the unit tests use, and drives it through named gesture
scenarios (`pinch_out`, `pinch_in`, `rotate`, `pan`, `ladder`) by calling
the widget's own `zoom_by`/`rotate_by`/`pan_by`/`range_up` entry points.

**Known gap this section left standing (the reason section 5 exists):**
every one of the MP7 scenarios pins LAT/LONG and only varies range/
rotation/pan offsets. That is a regime the aircraft is never actually in --
AER-677 (2026-09-06) found that driving *real* position motion collapses
the SVS frame gap from ~25 ms (40 fps) to ~699 ms (1.4 fps) even though
SVS's own internal render time (`frame.svs_total`) barely moved. The
static MP7 pattern could not have caught this and didn't; it kept
reporting green while the regression shipped.

## 5. Moving-position mode (AER-679)

`tools/bench_map_gestures.py --moving-position` closes the gap section 4
left: instead of a static scenario, it drives LAT/LONG continuously at a
configurable ground speed / heading / update rate for a configurable
duration, against the moving map, the AI/SVS widget, or both (`--target`).
Promotes AER-677's ad hoc `fixgw.netfix` reproduction script (130 kt,
heading 280, 20 Hz -- now the harness's own defaults) rather than
reinventing the drive mechanics; drives LAT/LONG directly against the same
in-process mock FIX db the gesture scenarios already use (no live
fix-gateway needed), which is FIX-bus-equivalent to what the ad hoc script
did against a real gateway, since the two widgets subscribe to FIX keys
the same way regardless of what wrote them.

Reports frame-**gap** percentiles (p50/p95/p99/max, not a mean -- "a mean
hides a lurch") for whichever widget(s) are in play, plus a hit/miss tally
for the SVS water/highway/obstacle/airport collector caches, so a result
can be read as "renderer slow" (`frame_total_ms` high) vs "renderer
starved" (`frame_gap_ms` high while `frame_total_ms` stays low and
collector `miss` counts are high) -- the exact distinction that diagnosed
AER-677 (SVS's own render time stayed 6.49 ms while the gap it experienced
was 699 ms; the difference was collector work starving the render thread,
not the renderer doing more drawing). Full JSON schema, the sourced 50 ms
`frame_gap_ms.p95` pass threshold, and its provenance:
`docs/moving_map_spec.md` section 9.2. Ready-to-use budget file:
`tools/budgets/moving_position.json`.

**Gating going forward:** SVS/map perf work (this brief, issue #98, and any
follow-on collector-cache/starvation fix such as AER-678) should be
evaluated against `--moving-position`, not against the static MP7 gesture
pattern alone -- the static pattern cannot see position-triggered collector
starvation by construction, and AER-677 is the proof that it missed a real,
user-visible regression for weeks. A before/after run of
`--moving-position` (dev at the commit before a fix, then after) is the
expected evidence attached to any PR claiming to improve moving-aircraft
SVS/map performance.

**Honest caveat, carried through in every moving-position result's
`"caveat"` field:** the position-update writer is itself Python load
running in the same process/thread model pyEfis uses, at a rate (20 Hz
default) comparable to what X-Plane drives in practice. A number measured
this way is "pyEfis under motion comparable to X-Plane," not a pure-pyEfis
figure -- don't quote it as the latter (AER-677).
