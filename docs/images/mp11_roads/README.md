# MP11 roads layer: batched numpy path (AER-4458, pyEfis #204)

Evidence for the G21 / MP11 change to `map/layers/roads.py` (rivers inherit it).
The scene is Raleigh, 35.8 / -78.8, with a 650x1040 map widget, `cy = 520`, and the
`highways-conus-2026q3r1` pack (403,120,128 bytes on both the Beelink and the sandbox).

## Images

Each image shows **old | new** (pre-MP11 `roads.py` from `origin/dev`, then this
branch). They are composited over a dark background in the default road colour.

- `ab_crop4x_5nm.png`, `ab_crop4x_20nm.png`, `ab_crop4x_80nm.png`: the centre
  160x160 px of the 1024 px worker image, upscaled **4x nearest-neighbour**.
- `ab_full_80nm.png`: the whole 1024x1024 worker image at 80 NM, 1:1.

## Timing and GUI-thread probe (Beelink 10.110.10.241, live pyEfis running, `nice -n 10`)

`gate.py` renders 5 times per range on a worker thread. The MP6 `GuiProbe` (10 ms
QTimer, 50 ms warn) runs on the GUI event loop at the same time.

| range | old median | new median | new probe max gap | new gaps > 50 ms |
|---:|---:|---:|---:|---:|
| 5 NM | 304 ms | 59 ms | 23.3 ms | 0 |
| 20 NM | 564 ms | 86 ms | 24.5 ms | 0 |
| 40 NM | 855 ms | 107 ms | 24.8 ms | 0 |
| 80 NM | 1203 ms | **167 ms** | 25.4 ms | 0 |
| 160 NM | no render | no render | - | - |

The budget in brief section 5 is 80 NM <= 0.3 s. At 160 NM the roads layer is
hidden: its coarsest LOD band ends at 80 NM, and rivers' band ends at 60. So it
posts no job and `is_settled` is True, before and after this change.

## Pixel agreement (`ab.py`, alpha channel; identical on the Beelink's Qt 6.8.1 and the sandbox's Qt 6.11.0)

| range | covered px old / new | IoU (alpha > 0) | solid (alpha >= 128) omitted / invented | px with abs(dA) > 16 | mean abs(dA) |
|---:|---:|---:|---:|---:|---:|
| 5 NM | 83557 / 83511 | 0.9994 | 0 / 0 of 48117 | 8.47 % | 3.31 |
| 20 NM | 61554 / 61511 | 0.9993 | 0 / 0 of 40329 | 16.76 % | 6.95 |
| 40 NM | 61428 / 61416 | 0.9991 | 0 / 0 of 43925 | 16.97 % | 7.60 |
| 80 NM | 40163 / 40177 | 0.9944 | 0 / 0 of 30026 | 18.68 % | 8.51 |

Where the differences come from (sandbox; an ad-hoc `ab.py` variant that
monkeypatches `_LINES_PER_PATH` and the decimator, not committed):

- **Pixel-grid decimation alone moves almost nothing.** With 1 polyline per path,
  0.03 % (20 NM) and 1.02 % (80 NM) of covered pixels differ by more than 16.
- **The rest is batching.** Polylines of one tier stroked as one path cover
  their overlap once. Separate `drawPolyline` calls composited the antialiased
  fringe twice wherever ways overlap: way joints, and dual carriageways that sit
  sub-pixel apart at range.

The solid core is unchanged. Only fringe alpha moves.

## Commands

```bash
# old module = pre-MP11 roads.py with the registration decorator stripped
git show origin/dev:src/pyefis/instruments/map/layers/roads.py \
  | sed 's/^@register_layer$//' > /tmp/roads_old.py
export QT_QPA_PLATFORM=offscreen PYTHONPATH=src
P=~/makerplane-data/highways/current/highways.sqlite      # Beelink path
B=docs/images/mp11_roads/bench_scripts
nice -n 10 python $B/gate.py $P                 # new
nice -n 10 python $B/gate.py $P /tmp/roads_old.py   # old
python $B/ab.py /tmp/roads_old.py 35.8 -78.8 $P
python $B/vis.py /tmp/roads_old.py $P docs/images/mp11_roads
```
