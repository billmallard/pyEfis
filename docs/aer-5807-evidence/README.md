# AER-5807 (AFC3) evidence: the `autopilot_panel` instrument

## Capture sheets (Pi 5)

`sheet_full.png` (640x260) and `sheet_compact.png` (900x110) show the real
widget in nine reported states, rendered on the Pi 5 test unit from this
branch. The panel is a plain QWidget, not a GL widget, so it is rendered with
`QT_QPA_PLATFORM=offscreen` beside the running display; nothing live was
touched. The font is DejaVu Sans. Each sheet's header stamps the host and the
revision.

```sh
QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. python3 \
    docs/aer-5807-evidence/make_sheet.py --out docs/aer-5807-evidence
```

## Bench run (scripted state source)

AFC2 (the X-Plane adapter, AER-5806) has not landed, so the bench run uses a
scripted source, `bench/ap_source.py`. It speaks the AFC1 contract over
netfix: it baselines `APCMDSEQ` on connect, answers each later change after
0.4 s, rewrites every state key twice a tol, refuses NAV ("NO NAV SOURCE")
and VNAV (not in `APCAPS`), arms and then captures APR, and stops writing
after 40 s.

`bench/run.sh` starts a private fix-gateway (`dev`, netfix only, on
127.0.0.1:3492, `bench/bench.yaml`), then the source, then `bench/drive.py`.
The driver puts the real panel in a screen stand-in with a real
`EncoderController`, connects it through pyEfis's own FIX client, clicks keys
and boxes with synthetic mouse presses, and checks each step:

| Step | Pass condition |
|---|---|
| 01 source up | data fresh, every key off or greyed, VNAV greyed |
| 02 AP | pending at 100 ms, active once the source answers |
| 03 HDG | active |
| 04 NAV | pending, then amber with the source's APMSG; never active |
| 05 / 06 APR | APR and NAV armed (GS, LOC), then both active on capture |
| 07 VS | active, VS box accented, ALT armed |
| 08 LVL | ALT SEL box focused and knob-edited, then LVL pressed: LVL active, focus released |
| 09 VNAV | greyed key pressed: request sent, refused, amber with APMSG |
| 10 source stops | NO AUTOPILOT DATA, every key in the no-data state |

```sh
sh docs/aer-5807-evidence/bench/run.sh <fix-gateway clone> <pyEfis clone> \
    <out dir> full 640x260
```

`bench-pi5-full.jsonl` and `bench-pi5-compact.jsonl` are the driver logs from
the Pi 5, one line per step. The frames themselves are not committed; the
sheets show the same states.
