# PA7 PROC page (pyEfis #238, AER-1606)

Two sets, both at the Beelink's Flight Plan tab size (the `flight_plan`
widget is 649 x 993 px on its 21.5 in 1920 x 1080 panel, `font_percent: 0.8`
as served by the bench's `managed.yaml`).

## Live bench screenshots (`live_*.png`)

pyEfis's own SIGUSR1 screenshots of the live Beelink panel, 2026-11-13,
running branch `aer-1606/pa7-proc-page` @ `bdc2ca2c` (staged with
`bench-deploy.sh --ref`, restored to `dev` afterwards). Each is the right-hand
tab section cropped at 1:1 (x 1256-1920 of the 1920 x 1080 frame), so the tab
strip shows. The pilot's taps were synthetic `xdotool` clicks on the X11
display, each verified by its own SIGUSR1 grab before the next. The
procedures are from the bench's installed pack,
`/data/makerplane-data/procedures/current/procedures.sqlite`, AIRAC 2611.
The engine is the bench's running fix-gateway `dev` @ `7194a0f`.

| File | State |
|---|---|
| `live_1_pick_transition.png` | KSBA RNAV07 chosen; the transition picker (AFOXY, GOLET, VECTORS) |
| `live_2_ready.png` | RNAV07 via GOLET: every leg in the preview, the missed approach in cyan |
| `live_3_loaded.png` | after LOAD APPROACH: the FPL page with the approach and the missed approach as two named rows. The engine loaded it: `FPLLDSEQ` = `FPLSEQ` = 47, `FPLMSG` empty |
| `live_4_refused.png` | ILS07 via GVO, which codes an `FC` leg: the engine refused it whole (`FPLMSG` = `UNSUPP FC YONNI`, `FPLLDSEQ` left at 47) and the FPL page says why; the RNAV07 plan it flies stays on the page |
| `live_5_proc_shows_refusal.png` | the PROC page reopened: what is loaded, and the same refusal |
| `live_sheet.png` | 2, 3 and 4 side by side, 1:1 |

The bench's served `managed.yaml` (written by a configurator panel apply,
v48, at 00:48Z that day) has no `procedures_db_path` for this instrument, so
the page answered `NO PROCEDURES DATABASE` until the line was added for the
test. The file was backed up first and restored byte-identical afterwards.

## Renders (`1_*.png` .. `7_*.png`, `sheet.png`)

The real widget's own paint path offscreen, produced on the Beelink (bench
fonts) from the same AIRAC 2611 pack, with the engine played by hand:

    QT_QPA_PLATFORM=offscreen PYTHONPATH=src python3 tools/render_proc_page.py OUTDIR \
        --procedures /data/makerplane-data/procedures/current/procedures.sqlite \
        --approach R07 --transition GOLET --sid FLOUT5 RW07 VTU

| File | State |
|---|---|
| `1_proc_empty.png` | the PROC page on Approach, KSBA offered |
| `2_pick_transition.png` | the transition picker |
| `3_ready.png` | the selection complete, with the leg preview |
| `4_fpl_loaded.png` | the FPL page after Load |
| `5_fpl_active.png` | flying to the FAF: the approach opens into its working rows |
| `7_departure.png` | the Departure tab: FLOUT5, RW07, VTU, with vector legs named by heading |
| `sheet.png` | all six, 1:1 |
