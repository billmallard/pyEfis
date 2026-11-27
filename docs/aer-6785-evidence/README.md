# RTE1b bench evidence (AER-6785)

Live captures from the Beelink bench (X11 kiosk, 1920x1080), 2026-11-27. pyEfis
was at `aer-6785/rte1b-route-entry` (c828e2e6), staged with `bench-deploy.sh --ref`.
fix-gateway was at `aer-6754/efb5b-vfom` (1a25926), another staged review left
as it was. Each PNG is the right-hand Flight Plan pane (x 1248-1920), cropped
from a whole-display x11grab (`shot.sh` below). No scaling.

Every route was typed on the on-screen keypad, one tap per character
(`keys.py` turns a string into `xdotool` taps on the keypad).

| File | What it shows |
|---|---|
| `1_before.png` | The bench's standing route (KSBA-KSMO, FPLSEQ 70) |
| `2_route_entry.png` | MENU, then Route: `ENTER ROUTE`, the keypad with SPACE and `.` |
| `3_kpmd_typed.png` | `KSBA FLOUT VTU V485 OHIGH TTE V459 LOPES PAIDD JEFFY V459 LHS KPMD` typed |
| `4_kpmd_pending.png` | ENT: the route on EFB4b's sheet, `ROUTE: KSBA-KPMD`, 13 fixes. The bus still holds KSBA-KSMO |
| `5_kpmd_loaded.png` | Accept: KSBA-KPMD is the plan, airways kept as V485 / V459 segments |
| `6_reject_pending.png` | `KSBA VTU KPMD` typed and offered |
| `7_after_reject.png` | Reject: byte-identical to `5_kpmd_loaded.png` (md5 8cc9f33e on the full frame) |
| `8_kphx_typed.png` | `KSBA FLOUT VTU V485 OHIGH TTE V459 LOPES PAIDD JEFFY V459 LHS WAYVE DARTS MOVVE MIPTE KPHX` typed |
| `9_kphx_pending.png` | ENT: `ROUTE: KSBA-KPHX` on the sheet, 17 fixes (scrolls) |
| `10_kphx_loaded.png` | Accept: KSBA-KPHX is the plan |

Bus readings (`bus.sh`, fixgw netfix), after each step:

    before:          KSBA-KSMO FPLSEQ 70 FPLLDSEQ 70 FPLCOUNT 24 FPLSEGCNT 7
    KPMD pending:    KSBA-KSMO FPLSEQ 70 FPLLDSEQ 70 FPLCOUNT 24 FPLSEGCNT 7
    KPMD accepted:   KSBA-KPMD FPLSEQ 71 FPLLDSEQ 71 FPLCOUNT 13 FPLSEGCNT 7
                     ids KSBA FLOUT VTU HENER OHIGH TTE WRING AMONT LOPES PAIDD JEFFY LHS KPMD
    short route rejected:
                     KSBA-KPMD FPLSEQ 71 FPLLDSEQ 71 FPLCOUNT 13 FPLSEGCNT 7
    KPHX pending:    KSBA-KPMD FPLSEQ 71 FPLLDSEQ 71 FPLCOUNT 13 FPLSEGCNT 7
    KPHX accepted:   KSBA-KPHX FPLSEQ 72 FPLLDSEQ 72 FPLCOUNT 17 FPLSEGCNT 11
                     ids KSBA FLOUT VTU HENER OHIGH TTE WRING AMONT LOPES PAIDD JEFFY LHS
                         WAYVE DARTS MOVVE MIPTE KPHX

Both accepted routes are the ForeFlight exports' fixes, in order
(`tests/flightplan/test_route_string.py`, `KSBA_KPMD_FPL` and `KSBA_KPHX_FPL`).

## How it was made

1. `bench-deploy.sh --ref aer-6785/rte1b-route-entry --owner AVIONICS --issue AER-6785`,
   then a plain `systemctl --user restart pyefis.service` under the bench lock.
2. `cp -p ~/makerplane/fixgw/config/flightplan_state.json` to
   `~/bench-scratch/aer6785/flightplan_state.pre-AER-6785.json`, because Accept commits.
3. Taps (`xdotool mousemove X Y click 1`): Flight Plan tab (1326, 10), MENU
   (1844, 1005), Route (1584, 180), the keypad (`keys.py`), ENT (1757, 899),
   Accept (1385, 972), Reject (1584, 972). Each step ran `shot.sh` and `bus.sh`.
4. Restore: stop fixgw, remove the state file, copy the pre-AER-6785 one back
   (`cmp` identical), start fixgw, restart pyEfis. The bus read back
   KSBA-KSMO FPLSEQ 70 FPLLDSEQ 70 FPLCOUNT 24. Then
   `bench-deploy.sh --restore=pyEfis` to `dev` (b933a2f6), and a plain restart.

`shot.sh`:

    ffmpeg -hide_banner -loglevel error -y -f x11grab -draw_mouse 0 \
      -video_size 1920x1080 -i :0 -frames:v 1 ~/bench-scratch/aer6785/$1.png

`bus.sh`:

    from fixgw import netfix
    c = netfix.Client("127.0.0.1", 3490); c.connect()
    r = lambda k: c.read(k)[1]
    n = int(r("FPLCOUNT"))
    print(r("FPLNAME"), r("FPLSEQ"), r("FPLLDSEQ"), n, r("FPLSEGCNT"),
          " ".join(r("FPL%dID" % i) for i in range(1, n + 1)))
