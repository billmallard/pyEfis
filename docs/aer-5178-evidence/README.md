# AER-5178 (CERT1a): a failed tape carries a red X and no scale

pyEfis #411's "fixgw stopped 6 s" frame showed the attitude indicator grey under
a large red XXX, but the airspeed, altitude and VSI tapes showed their failure
only as a small red XXX in the readout box, and kept drawing scale numbers,
coloured bands and trend vectors that can still be read as live.

## The two looks (offscreen widget renders, Beelink fonts)

`variants_sheet.png`, left to right: the tapes live, the tapes failed on `dev`
today, look A (red X over the scale), look B (scale blanked + red X; the
branch default). Each panel is airspeed, altitude, VSI trend tape at their
Beelink PFD sizes (120x590, 115x590, 65x400). The single strips are
`live.png`, `dev_failed.png`, `x_over_scale.png` and `blanked.png`.

In both looks the readout boxes keep their red XXX, the VSI tape keeps its
"VSI / XXX" header, and the TAS and baro boxes keep drawing, because those are
their own data (TAS, BARO). Look B also drops the trend vectors, the altitude
bug and the VSI moving dot. `helpers.FAILED_TAPE_BLANK_SCALE` selects between
them.

Regenerate (from a pyEfis tree; a `dev` tree for `live` and `dev`, the branch
for the two looks):

```sh
export QT_QPA_PLATFORM=offscreen PYTHONPATH=src:.
python docs/aer-5178-evidence/render_tape_variants.py strip live live.png
python docs/aer-5178-evidence/render_tape_variants.py strip dev dev_failed.png
python docs/aer-5178-evidence/render_tape_variants.py strip x_over_scale x_over_scale.png
python docs/aer-5178-evidence/render_tape_variants.py strip blanked blanked.png
python docs/aer-5178-evidence/render_tape_variants.py sheet variants_sheet.png \
  live.png "Live (reference)" dev_failed.png "Failed today (dev)" \
  x_over_scale.png "A: red X over scale" blanked.png "B: scale blanked + red X"
```

The Beelink has no DejaVu Sans Condensed, so text falls back to DejaVu Sans, as
it does on the glass.

## On the Beelink glass, fixgw stopped

Beelink bench (X11/xcb, 1920x1080), 2026-11-08, CERT1's method (#411):
`cert1_writer.py` feeds PITCH, ROLL, ALT, IAS, HEAD, VS, ALAT and TAS over
netfix at 10 Hz, and `cert1a_capture.sh` SIGSTOPs the fix-gateway process,
grabs, SIGCONTs and grabs again. Every frame is a full-framebuffer
`ffmpeg -f x11grab` grab, taken twice 1 s apart; the second is kept.

| Image | pyEfis | What it shows |
|---|---|---|
| `before_live.png` | dev `b5eb3dd` | Live feed. |
| `before_stopped_6s.png` | dev `b5eb3dd` | 6 s after SIGSTOP: small red XXX in each readout box, every scale still drawn. Byte-identical to the 12 s frame. |
| `before_resumed_4s.png` | dev `b5eb3dd` | 4 s after SIGCONT. The VSI readout is still a red XXX (see below). |
| `after_live.png` | branch `5854923` | Live feed on the fix. |
| `after_stopped_6s.png` | branch `5854923` | 6 s after SIGSTOP: red X across the airspeed, altitude and VSI tapes, scales blanked. Byte-identical to the 12 s frame. |
| `after_resumed_4s.png` | branch `5854923` | 4 s after SIGCONT: every tape back, VSI reads 0. |
| `contact_sheet.png` | - | PFD column, 0.5x: before stopped, after live (top); after stopped, after resumed (bottom). |
| `vsi_header_resumed_4x.png` | - | VSI header 4 s after SIGCONT, 4x nearest: dev (stuck XXX) left, branch right. |

`before_info.txt` and `after_info.txt` are the capture logs. The watchdog
tripped 2.0-2.5 s after each SIGSTOP and recovered at the SIGCONT.

The stuck VSI XXX on dev is a race: `Alt_Trend_Tape` routed flag changes
through its rate-limited `redraw()`, so a change landing inside
`update_period` was dropped, and with VS steady nothing redrew afterwards.
CERT1's own capture did not hit it; today's dev capture did. One clean
branch capture does not prove a race gone; the unit test
`test_vsi_tape_flag_change_is_not_rate_limited` does, deterministically.

The after captures ran unattended on the box (`cert1a_after_job.sh`): wait for
the bench lock, stage the branch with `bench-deploy.sh --ref`, capture,
`--restore` to dev.
