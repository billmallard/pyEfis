# AER-6590 (DSP2) evidence: panel presses act with the EMS screen up

The TESS1 spike page (fix-gateway `config/tessera/page.yaml`) pulses six
pyEfis touchscreen-button keys. Before DSP2 a pulse acted only while that
button showed, and none of those six buttons is on a stock screen, so every
press did nothing. With the stock data bindings each press changes its key on
any screen.

Run on the Beelink bench, 2026-11-25, beside the live kiosk (not restarted,
not written). Stock configs from each checkout. The only edits were the
netfix/FixPort port (3495) and `defaultScreen: EMS`. The private
fix-gateway is `dev` at `bfb7e0a`, and pyEfis runs offscreen. Each side's log
shows `data-status: booting EMS`. The probe writes each key `True` then
`False` back to back over netfix, which are the writes the Tessera plugin's
`{pulse: KEY}` makes, and reads the target 1.5 s later.

| Panel key | Press | Key pulsed | dev `48ac6d7b` | branch `09bf8430` |
|---|---|---|---|---|
| 2 | BARO - | `TSBTN11` | 29.92 -> 29.92 | 29.92 -> 29.91 |
| 3 | BARO + | `TSBTN12` | 29.92 -> 29.92 | 29.91 -> 29.92 |
| 5 | HDG - | `TSBTN129` | 0.00 -> 0.00 | 0.00 -> 358.90 |
| 6 | HDG + | `TSBTN131` | 0.00 -> 0.00 | 358.90 -> 0.00 |
| 7 | HDG SYNC | `TSBTN130` | 125.00 -> 125.00 (HEAD 75.0) | 125.00 -> 75.01 (HEAD 75.0) |
| 9 | CDI SRC | `TSBTN133` | NAVSRC 2 -> 2 | NAVSRC 2 -> 0 (GPS -> NAV1) |
| | | | **0 of 6 changed** | **6 of 6 changed** |

Full output: `bench/dev.txt`, `bench/branch.txt` (provenance line, boot
screen, probe output).

Not covered here:

- **No real panel.** The TESS2 board is not here yet. These are the panel's
  writes made over netfix, not a finger on a Tessera key.
- **HDG - from 000 lands on 358.9, not 359.** That is the heading-bug-down
  button's own `change value wrap`, whose span is `HEADBUG` max - min
  (359.9). This change makes it reachable from a panel key; it does not
  change it. It is filed separately.

## Reproduce

On the bench, as the bench user:

```sh
mkdir -p ~/bench-scratch/aer6590
cp dsp2_bench.sh probe.py ~/bench-scratch/aer6590/
sh ~/bench-scratch/aer6590/dsp2_bench.sh
```

`dsp2_bench.sh` clones fix-gateway `dev` and pyEfis `dev` and the branch
under `~/bench-scratch/aer6590`, copies each one's stock config, sets the port
and the boot screen, runs one side at a time and stops its stack after.
