# EFB4b bench evidence (AER-6706)

Live captures from the Beelink bench (X11 kiosk, 1920x1080), pyEfis at
`aer-6706/efb4b-accept-import` staged with `bench-deploy.sh --ref`, fix-gateway
at `dev` (e185502). Each PNG is the right-hand Flight Plan pane (x 1248-1920)
cropped from a full SIGUSR1 grab (`shot.sh`); no scaling.

| File | What it shows |
|---|---|
| `1_before_upload.png` | The FPL page with the bench's standing route (KSBA-KSMO, FPLSEQ 70) |
| `2_offered.png` | After the upload: the route is unchanged, the strip offers `KSBA TO KPMD`, 13 waypoints |
| `3_review_sheet.png` | Review: every fix, leg and running distance, the note, Accept / Reject / Later |
| `4_after_accept.png` | After Accept: the imported route is the plan (FPLSEQ 71, loaded by the engine) |

Bus readings (`bus.sh`, fixgw netfix):

    upload 1: FPLIMPSEQ 1 FPLIMPDONE 0, route KSBA-KSMO FPLSEQ 70 FPLLDSEQ 70 FPLCOUNT 24
    Reject:   FPLIMPSEQ 1 FPLIMPDONE 1, route KSBA-KSMO FPLSEQ 70 FPLLDSEQ 70 FPLCOUNT 24
              (the frame after Reject is byte-identical to 1_before_upload.png, md5 c5c8108e)
    upload 2: FPLIMPSEQ 2 FPLIMPDONE 1
    Accept:   FPLIMPSEQ 2 FPLIMPDONE 2, route KSBA TO KPMD FPLSEQ 71 FPLLDSEQ 71 FPLCOUNT 13
              ids KSBA FLOUT VTU HENER OHIGH TTE WRING AMONT LOPES PAIDD JEFFY LHS KPMD

## How it was made

1. `bench-deploy.sh --ref aer-6706/efb4b-accept-import --owner AVIONICS --issue AER-6706`.
2. `enable.sh`: turns `FPL_EXCHANGE` on with `allow: ["127.0.0.0/8"]` (the box
   only; no hotspot), restarts fixgw and pyEfis under the bench lock. The
   configs it edits were copied to `~/bench-scratch/efb4b/*.pre-AER-6706` first.
3. `xdotool mousemove 1326 10 click 1` (the Flight Plan tab), `shot.sh 1_before_upload`.
4. `curl -s -X POST --data-binary @tests/plugins/fpl_exchange/data/foreflight/ksba_kpmd.fpl
   http://127.0.0.1:8080/upload` (fix-gateway's fixture: Bill's iPad export from
   2026-11-22). The plugin answered `Sent to the panel: KSBA TO KPMD, 13 waypoints.`
5. Review at (1795, 932), Reject at (1584, 972), Accept at (1385, 972), each
   followed by `shot.sh` and `bus.sh`. The second upload repeated step 4.
6. `revert.sh`: fixgw config back to the pre-AER-6706 copies (`cmp` clean), the
   standing KSBA-KSMO route put back from a `flightplan_state.json` with the
   same 24 idents and FPLSEQ 70, then `bench-deploy.sh --restore` to `dev`.
