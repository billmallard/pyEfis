# AER-5894 (CERT1e): a failed or expired heading no longer reads as live on the HSI

On `dev`, under a failed HEAD, the HSI raised its red HDG flag. Beside the flag
it kept the MAG readout in white at the frozen heading, and the rose kept the
heading bug on the frozen card. `isFail()` tested `_HeadBad` but not
`_HeadFail`, so an HSI with no CDI and no GSI also kept its compass numerals.
Under an expired (`old`) HEAD, nothing changed at all: there was no flag, and
the card, numerals, bug and MAG all looked live. That is the likelier field
failure: one heading source stops while fix-gateway runs.

The look on the branch follows Bill's CERT1b ruling for the tapes
(2026-11-09). `old` gets the failed look, and `bad` gets an amber cue.

| HEAD | HDG flag | MAG readout | numerals, heading bug, track diamond, bearing needles |
|------|----------|-------------|--------------------------------------------------------|
| valid | no | white value | drawn |
| `fail` | red | red `XXX` | removed |
| `old` | red | red `XXX` | removed |
| `bad` | red (unchanged) | blank, amber `MAG` label | removed |

The compass ticks stay on the stopped card. The course pointer and the CDI stay
as well: the deviation does not depend on heading, and both stay on the stopped
card, as on an electromechanical HSI with its HDG flag in view.

## 1. Bench: Beelink, the live PFD (`cert1e_capture.sh`)

`cert1e_capture.sh <label>` ran under the bench lock. CERT1b's
`cert1_writer.py` (`docs/aer-5269-evidence/`) fed HEAD = 090 and the other
primary keys over netfix at 10 Hz. The script then did the following:

- **old:** it killed the feed with fix-gateway still running. HEAD (TOL
  2000 ms) went `old`, flags `01000`, by the 5 s read. The grab followed.
- **fail:** it restarted the feed, then sent `SIGSTOP` to fix-gateway, which
  is a hung gateway. CERT1's watchdog marked every key `fail`. The script
  grabbed at 6 s, then sent `SIGCONT`.

Grabs are full-framebuffer `ffmpeg -f x11grab` captures, taken twice 1 s apart.
The second one is kept. The value and flag log is `bench_*_info.txt`.

- Before: `dev` at `9205cb47`, the bench checkout.
- After: the branch at `11d6f523`, staged with
  `bench-deploy.sh --ref ... --owner AVIONICS --issue AER-5894` and restored to
  `dev` afterwards (`cert1e_after_job.sh`).

`bench_hsi_sheet.png` crops the HSI from each frame. The top row is `dev` and
the bottom row is the branch. Left to right: live, `old`, `fail`, resumed.

- `dev` `old`: no flag, white `090°`, and the cyan bug still on the card.
- `dev` `fail`: HDG flag, but still a white `090°` and the bug.
- Branch `old` and `fail`: HDG flag, red `XXX`, and no bug. The display
  recovers on resume.

The bench panel's COURSE is invalid (`---°`), and the bench drives no CDI.
`isFail()` folds both into the numeral gate, so the numerals are hidden in
every bench frame, both before and after. Section 2 shows them with COURSE
valid.

## 2. The looks: offscreen widget renders with Beelink fonts (`render_hsi.py`)

`looks_dev.png` (before) and `looks_branch.png` (after) are laid out the same
way. The top row is the rose and the bottom row is the arc. Left to right:
HEAD live, `old`, `bad`, `fail`. CDI and GSI are absent and COURSE is valid,
with heading 090. The bug is at 000 on the rose and at 120 on the arc. No
gateway is used; the renders come from `tests/mock_db`.

```
QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. \
  ~/pyefis-venv/bin/python docs/aer-5894-evidence/render_hsi.py strip looks.png
```

Run it from a `dev` tree for the before and from the branch for the after. The
script prints the path of the widget module it imported.

## 3. Tests

`tests/instruments/hsi/test_hsi_heading_quality.py` covers the following:

- `fail`, `old` and `bad`, each on the rose and the arc, with CDI and GSI
  absent.
- The `top_panel` and `split` readout layouts.
- The `isFail()` HEAD fix.
- A repaint on a quality change with no value change.
- The HDG sync push being refused.

20 of the 25 fail on `dev`. The 5 that pass there are the 2 controls and 3
cases `dev` already handled: `isFail()` under `bad`, and the sync push under
`fail` and `bad`. The `dev` run also has 6 teardown errors, from paints that
had raised; the branch run has none. A mutation pass removed
each gate in turn (rose bug, rose track, arc bug, arc track, `old` in validity,
the repaint, the `isFail()` fix, the `bad` blank and both value pens). Every
one of those mutants was killed.
