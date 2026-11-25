# INS5 bench strips: widgets under a stale or bad source (AER-6588)

Each strip is one widget. The top row is the good-source frame: dev and this
branch render it byte for byte the same (`compose.py` asserts the sha256s
match). Each row below sets one FIX flag, dev on the left and the branch on
the right. On dev every one of those stale frames is byte-identical to the
good frame, which is the defect: the source went stale or bad and nothing on
the glass changed.

| Strip | Rows |
|-------|------|
| `wind_strip.png` (3x nearest, black frame added) | `HWIND` old: the HW row draws as bad, amber label and amber `X` (EFIS-WIND-009) |
| `hsi_strip.png` | `HEADBUG` old: grey bug and HDG readout; `HEADBUG` fail: no bug, HDG `---°`; `GS` old: no track diamond |
| `ai_strip.png` | `TRACK` old: FPM amber; `MAGVAR` bad: SVS UNAVAIL, brown ground, FPM amber |
| `map_strip.png` (ND expanded) | `LAT` bad: grey ownship and `NO POS`; `TRACK` fail: grey TRK box and grey ownship |
| `mapcaution_strip.png` | `ALT` old in caution mode: relief instead of the bands, `NO ALT` in the chip |

## How they were made

On the Beelink (`beelinkpyefis`, PyQt 6.8.0 on Qt 6.8.1, the bench venv and
its fonts, the installed `/data/makerplane-data` packs), offscreen, with the
in-memory mock FIX database: no gateway and no change to the live display or
checkout. Two trees were unpacked under `~/bench-scratch/AER-6588`: `dev`
(`git archive origin/dev`) and `branch` (`git archive HEAD`), each with this
branch's `tools/render_ins5_evidence.py` copied in.

```sh
cd ~/bench-scratch/AER-6588
for t in dev branch; do
  (cd $t && QT_QPA_PLATFORM=offscreen ~/pyefis-venv/bin/python -u \
     tools/render_ins5_evidence.py --data /data/makerplane-data --out ../out-$t)
done
# then, anywhere with PyQt6:
python3 docs/images/aer-6588/compose.py out-dev out-branch docs/images/aer-6588
```

The pose is 5 NM south of Aspen (KASE) at 11,500 ft tracking 330, because the
bench's terrain pack covers N39W107 and stops short of KSBA.

## What these frames are not

- **Not the AI's terrain.** There is no GL offscreen, so the AI's SVS is a
  stand-in renderer that reports itself ready and drawing, the one
  `tests/instruments/ai/test_svs_position_quality.py` uses. That is why the
  good frame's land is sky: the AI paints the land as sky when the SVS says it
  drew terrain. What is real is the AI's own overlay pass (FPM, SVS UNAVAIL)
  and its land-brush decision.
- **Not a live source going stale.** The flag is set on the mock FIX item
  after the widget is built, the same edge the pyavtools client raises when
  the gateway flags a key. The widget's own subscription does the rest.
