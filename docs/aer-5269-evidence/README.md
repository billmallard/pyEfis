# AER-5269 (CERT1b): an expired or suspect tape no longer looks live

The likeliest field failure is one sensor going quiet while fix-gateway keeps
running. Its key goes `old` when its TOL runs out, not `fail`, so CERT1's link
watchdog never trips. On `dev` an `old` (or `bad`) airspeed or altitude tape
blanked only its readout digits and kept drawing its scale, bands, trend and
alt bug at the frozen value, and `VSI_PFD` left a grey dot at the frozen rate.

Bill's ruling (2026-11-09): `old` gets CERT1a's look (scale blanked, red X,
the same as `fail`); `bad` gets an amber suspect cue, not the red X; the TAS
box blanks whenever IAS is failed or old.

## 1. Bench check: the expiry reaches pyEfis (Beelink, dev `ce55802`)

`cert1b_capture.sh before`, under the bench lock. `cert1_writer.py` feeds
PITCH, ROLL, ALT, IAS, HEAD, VS, ALAT and TAS over netfix at 10 Hz, then the
**feed is killed with fix-gateway still running**. `fixflags.py` reads each
key's value and flags (`a o b f s`) from the gateway over netfix `@r`, and its
TOL over `@q`. Grabs are full-framebuffer `ffmpeg -f x11grab`, twice 1 s
apart; the second is kept. Log: `before_info.txt`.

- IAS, ALT, VS and TAS all have TOL 2000 ms. The gateway set `old` (flags
  `01000`) between 1.6 and 2.1 s after the feed stopped, on all four.
- The link watchdog did not trip (no watchdog line in the journal).
- pyEfis received it: by the 5 s grab the attitude indicator had greyed and
  the IAS and ALT readouts had blanked. The airspeed scale and bands, the
  altitude scale and the VSI tape scale were still drawn at 110 kt / 4537 ft
  (`before_stopped_5s.png`, byte-identical to the 11 s grab). So no
  fix-gateway change is needed; the defect is pyEfis's alone.

## 2. The looks (offscreen widget renders, Beelink fonts)

`looks_sheet.png`, left to right: live, `old` on dev, `old` on the branch,
`bad` on dev, `bad` on the branch, `fail` (CERT1a, unchanged). Each panel is
the airspeed tape with its TAS box, the altimeter tape, the VSI trend tape and
`VSI_PFD`, at Beelink PFD sizes. IAS, ALT and VS carry the flag; TAS stays
live in every panel, so the TAS box shows the new rule.

- `strip_branch_old.png` and `strip_branch_fail.png` are byte-identical:
  `old` now draws exactly the failed look.
- `strip_dev_old.png` and `strip_dev_bad.png` are byte-identical: on dev the
  two states drew the same thing, and neither carried a cue on the tapes.

```sh
# from a dev tree (before) and from the branch (after)
export QT_QPA_PLATFORM=offscreen PYTHONPATH=src:.
python render_tapes.py strip live strip_branch_live.png   # also old, bad, fail
python render_tapes.py sheet looks_sheet.png strip_branch_live.png Live \
  strip_dev_old.png "old, dev" strip_branch_old.png "old, CERT1b" \
  strip_dev_bad.png "bad, dev" strip_branch_bad.png "bad, CERT1b" \
  strip_branch_fail.png "fail (CERT1a)"
```

## 3. On the Beelink glass, branch `a83a4d8`

`cert1b_after_job.sh`: stage the branch with `bench-deploy.sh --ref`, run
`cert1b_capture.sh after`. Log: `after_info.txt`.

| Image | What it shows |
|---|---|
| `after_boot_keys_old.png` | Just after the restart, no feed: every key is `old` at the gateway. Red X on the airspeed, altitude and VSI tapes. |
| `after_stopped_11s.png` | 11 s after the feed stopped, gateway `old` on all four keys, watchdog not tripped (the journal has only its startup line): red X, scales blanked, readouts XXX. |
| `after_resumed_5s.png` | 5 s after the feed restarted: every tape back. |
| `after_live_frozen.png` | Not evidence of the look: see below. |
| `contact_sheet.png` | PFD column, 0.5x. Left dev, right branch; top live, bottom feed stopped. |

**What the after capture does not show.** Its `1_live` and `2_stopped_5s`
grabs are byte-identical to each other, and so are the two grabs of `1_live`
taken 1 s apart, while the feed was swinging roll +-20 deg. The glass was not
repainting yet, about 90 s after the restart. So the after run does not
measure how soon the X appears after expiry; the 11 s frame shows only that
it does. The before run shows the client receiving `old` within 5 s.

The `after` run ran over a sibling run's staging (AER-5266, same owner name,
so `bench-deploy.sh` read it as my own claim). It was live on the bench from
21:53:17Z to 21:55:08Z and was not restored over the sibling's re-stage.
