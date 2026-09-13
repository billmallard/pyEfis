# Per-host timing baselines for the moving-map perf budgets

MP8b-2 (AER-1135), `briefs/map_gesture_perf_plan.md` section 5, pyEfis #98.

A baseline in this directory is what the timing rows of
`tests/perf/test_map_pack_budgets.py` assert against, at the DoD's 1.5x
tolerance. `tools/map_perf_baseline.py` owns both minting and comparison.

## Why per-host at all

Section 5's timing numbers — worker render <= 0.6 s at 160 and 300 NM,
settle latency <= 600 ms, paint p95 <= 15 ms, roads worker <= 0.3 s,
GUI-thread max gap <= 50 ms — were measured on one machine, a Beelink
N150. They are a statement about that machine. Asserted directly on
arbitrary hardware they fail on a slow box with no defect present and
pass on a fast box hiding a 3x regression. So each host carries its own
recorded numbers and the budget is "no worse than 1.5x of what this
machine did when it was known-healthy".

The count-based budgets in `tests/perf/test_map_gestures.py` need none of
this — they are pipeline properties and read the same everywhere. Prefer
a count budget to a timing budget whenever the question admits one.

## Host identity is not `gethostname()`

The brief says `tests/perf/baselines/<hostname>.json`. That does not work
where CI runs: a GitHub-hosted runner's hostname is a per-job random
string (`fv-az###-###`), and a container's is its container id, which
changes on every recreate. Keyed that way, no baseline is ever found on
those hosts, every timing row warns, and the tier gates nothing while
looking green.

So the key is `PYEFIS_PERF_HOST` when set, and `socket.gethostname()`
only as a fallback for a workstation or the bench, where the hostname is
a real and stable name. Setting `PYEFIS_PERF_HOST` is a host opting in:
"this is a machine I intend to keep, and I am willing to maintain a
baseline for it".

Committed baselines today:

| file | host | notes |
|---|---|---|
| _(none yet)_ | | see "Status" below |

## Minting

Run on the machine being minted for, against real packs, with the tree
clean:

```
PYEFIS_PERF_HOST=beelink QT_QPA_PLATFORM=offscreen PYTHONPATH=src \
  python tools/map_perf_baseline.py mint \
    --tile-path  /data/makerplane-data/terrain/tiles \
    --water-db   /data/makerplane-data/water/current/water.sqlite \
    --highway-db /data/makerplane-data/highways/current/highways.sqlite \
    --repeats 3 \
    --out tests/perf/baselines/beelink.json
```

Commit the resulting file. Read it before you do — it is short, and every
field in it is a claim.

## What stops a bad baseline being blessed

This is the part with no analogue in the count budgets, and it is worth
being explicit about, because a wrong baseline does not look wrong.

A count budget's falsifier is a mutant: break MP1's gesture gating and
"1 terrain render per pinch" goes red. A timing budget has no such
falsifier. The mutation that makes it worthless is not in the code under
test at all — it is **a baseline captured while the tree was degraded**.
Mint while the terrain worker is rendering twice per pinch and the slow
number is recorded as normal; every later run then passes at 1.5x of a
defect, forever, green. No clock can detect this, because
slow-because-broken and slow-because-this-box-is-slow are the same
measurement.

Five guards stand in for the missing falsifier. All of them establish
tree health *by means other than the clock*:

1. **Clean tree at a named commit.** `git status --porcelain` must be
   empty; the SHA and `git describe` go into the file. Untracked files
   count as dirty — a stray `conftest.py` changes what runs.
   `--allow-dirty` exists for experimentation and records `tree_clean:
   false`; never commit one.

2. **The MP8a count budgets must pass in the same minting run.** The
   load-bearing guard, and the only one with no override.
   `tests/perf/test_map_gestures.py` is hardware-independent, so a
   failure there is a pipeline defect rather than a slow machine — and
   those are exactly the defects that would inflate a timing baseline.
   Minting shells out to pytest (a separate process, so its answer is
   independent of the timing run it is vouching for) and refuses on a
   single failure.

3. **Reproducibility.** `--repeats` (default 3); if any metric's
   max/min exceeds 1.25x the tool refuses. A box that cannot reproduce
   itself within 25% cannot support a 1.5x gate — the noise would eat
   most of the tolerance. The recorded value is the **median**, and
   every sample is kept in the file: a baseline from the fastest run can
   never be met again, one from the slowest hides a regression the size
   of the noise.

4. **Recorded data-pack identity.** Every timing row is a function of
   how much geometry the scene holds, so the water pack's `pack_meta`
   (id + cycle) is recorded. A different pack cycle moves the numbers
   for reasons that have nothing to do with the code.

5. **A calibration probe, re-run at check time.** `calibration_ms` times
   a fixed, pack-free numpy workload. It is recorded at mint and
   re-measured on every comparison; a drift beyond 1.3x means the host is
   no longer the host the baseline describes (thermal throttling, a
   noisy neighbour, different silicon behind the same name) and the row
   downgrades to a warning. This cuts both ways, and the second
   direction is the important one: it stops a baseline minted on a
   loaded box from silently passing a real regression once the box is
   quiet again.

None of this makes a bad baseline impossible. It makes one require a
clean tree at a named SHA on which the count budgets passed, three
reproducible repeats, and a recorded pack cycle — a much smaller target
than "somebody ran the tool once".

## Status: no baseline is committed yet, and what that means

**Every timing row is currently warn-only, on every host.** That is
stated plainly rather than left to be discovered:

- No baseline file exists here, so `load_baseline()` returns `None`,
  `check()` returns `gated=False`, and the test emits a `UserWarning`
  naming the metric and the measured value instead of asserting. The
  warning is deliberate — a skipped timing test and a passing one look
  identical in `pytest -q`, which is how a tier comes to measure nothing
  without anyone noticing.
- Minting a Beelink baseline needs the bench, real packs and a clean
  tree at a known-good SHA. That is an AVIONICS/bench task, not
  something that can be produced from a checkout.
- Minting a CI baseline is **not** recommended even once the mechanism
  is available: a shared GitHub runner has no stable identity and its
  noise routinely exceeds the 1.25x minting spread limit. The timing
  tier is a bench and workstation gate. CI's perf gate is the count
  tier, which needs none of this.

What *is* gated everywhere, today, with no baseline and no pack: the
comparator's own behaviour, the minting guards, the footprint guard, the
GUI-probe starvation falsifier, and the injected-stall proof that the
measurements read the real render path. Those are the tests that keep
this file honest, and they run on every PR.
