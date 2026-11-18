# SVSCEIL1 bench evidence (AER-5934)

Beelink bench, 2026-11-18 03:07-03:45 UTC. pyEfis `dev` b38df57c, which
already carries MAPPAINT1 (pyEfis #484). Live panel `managed.yaml`: SVS on the
left, the tab section on the right. X-Plane was not running; every run drives
the same synthetic flight, `docs/aer-5668-evidence/feed.py` (the X-Plane
plugin's 14 keys at 7.6 Hz), started at 20 s of uptime.

## Result

The SVS is not capped at 18.8 paints a second. It paints at its 30 Hz frame
clock, with the map showing or hidden. The 18.8 came from the measuring method:
`timeline.py` counts runs of AI-paint samples in a 250 Hz py-spy recording, and
that count reads about a third low. The A/B is in the same 15 s window: the
timeline and an in-process counter, both running during one py-spy recording.

| run | map | instrument | SVS paints/s | frame ticks that repainted /s | window repaints (UpdateRequest) /s | time in window repaint + flush |
|---|---|---|---|---|---|---|
| u_engine_1 | hidden | counter only | **30.6** | 30.3 | 49.5 | 37.8% |
| u_map_1 | showing | counter only | **30.7** | 30.2 | 51.9 | 44.5% |
| s_engine_2 | hidden | counter + py-spy | 31.3 (counter) / **21.1** (timeline) | 29.9 | 48.7 | 49.1% |
| s_map_2 | showing | counter + py-spy | 29.6 (counter) / **18.1** (timeline) | 28.7 | 50.5 | 58.5% |
| g_map_1 | showing | DRM scanout only | 35.1 patch changes/s | - | - | - |
| g_engine_1 | hidden | DRM scanout only | 34.7 patch changes/s | - | - | - |

- **Counter vs timeline, same window:** 31.3 vs 21.1 (map hidden), 29.6 vs 18.1
  (map showing). The timeline also reads the paint 12 ms long (median), where
  the counter's wall clock reads 6.5 ms, and the start-to-start gap 44-48 ms
  where the counter reads 33. I have not pinned down why py-spy's sample stream
  distorts it this way. `timeline.py` assumes evenly spaced 4 ms samples. Its
  count is not a paint rate, whatever the reason.
- **py-spy's own cost is small.** Under py-spy the counter reads 31.3 (map
  hidden) and 29.6 (map showing), against 30.6 and 30.7 without it. With the
  map showing, the frame-clock gaps stretch a little (p90 34.9 ms, max 81 ms,
  against 33.2 and 60).
- **Glass, with no instrument in the process at all:** a 10 s DRM scanout grab
  at 60 fps (`kmsgrab`) of a 480x360 terrain patch. The patch changed 35.1
  times a second with the map showing, 34.7 hidden. That is more than the 30 Hz
  clock can produce. On this X11 bench the window is blitted into the scanout
  buffer, not page-flipped, so a capture can catch a half-written frame and
  count one paint twice. Read the glass number as "well above 25", not as an
  exact rate.
- **"Half idle" GUI thread:** the window's UpdateRequest (every widget's paint,
  the GL composite and the flush) takes 38-45% of the GUI thread unprofiled.
  py-spy books the C++ part of that as idle. The frame clock is not starved:
  its p90 tick gap is 33.2 ms.
- The panel builds four `AI` widgets (one per screen). The three hidden ones
  tick at 30 Hz and return at once (median tick cost 0.0 ms), so they are not
  a factor.

So the definition of done's first branch holds without a code change: the SVS
paints at about 30 a second with the map showing, above the 25 target, on the
same panel and feed.

## Runs that did not complete

- `s_engine_1`: the first py-spy run used a 60 s recording. py-spy hung at
  98% CPU and held pyEfis stopped (`t` state) for about 15 minutes, freezing
  the display, until I killed it. Its reports stop at the hang; they are kept
  in `raw/` but not used. Later runs use 15 s, as `measure.sh` does, under a
  45 s `timeout`.
- `s_map_1` was aborted along with it (`raw/s_map_1.jsonl`, not used).

## Instruments

- `probe_launch.py` starts pyEfis's `main()` with counters wrapped around
  `AI._frame_tick`, `AI.update` and `AI.paintEvent`, plus an event filter on
  the top-level window that delivers `UpdateRequest` itself and times it. It
  writes one JSON line every 5 s. No source file in the checkout changes.
- `run_probe.sh LABEL map|engine [PROBE_SPY=1]` copies `~/start-pyefis.sh` to a
  backup, points its last line at the probe, restarts pyEfis, starts the feed,
  clicks the Engine tab (1385,10) when asked, samples from 75 s of uptime, and
  restores the launcher byte-identical (`cmp`). With `PROBE_SPY=1` it records
  15 s of py-spy at 250 Hz, as `measure.sh` does, and runs `timeline.py` on it.
- `glass.sh LABEL map|engine` runs with the stock launcher and grabs the
  scanout.
- `summ.py raw/<run>.jsonl` gives the per-run means above. `timeline.py` is the
  investigation's script (pyEfis #480), copied unchanged from the bench.

Every run was taken under the bench lock (`flock /tmp/pyefis-bench.lock`).
Load before and after each run was 0.4-1.0. A sibling follower (AER-5806
`sim_follow.py`) was idle throughout, waiting for X-Plane. The bench was left
on `dev` b38df57c with the stock launcher, after a plain restart.
