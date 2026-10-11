# AER-3042: bench-deploy.sh flight-frame proof on the Beelink

Evidence for billmallard/maos-workspace#95 (head `372a40f`), run 2026-10-11T13:20Z
on the Beelink (`beelinkpyefis`, 1920x1080, X11).

- `bench-deploy-shot.png` -- SIGUSR1 "app started" grab (boot NAVIGATION DATA page).
- `bench-deploy-boot.png` -- x11grab before the Continue tap (boot page; cursor visible).
- `bench-deploy-flight.png` -- x11grab 8 s after the tap at (403, 972): configured
  flight screen with the SVS panel drawn.

pyEfis was staged on `aer-2088/fpl-airway-map-only-expansion` @ `90b44b7` (a live
review), so the run re-staged that same branch rather than restoring dev.

Regenerate:

```sh
S=makerplane/processes/paperclip/scripts/bench-deploy.sh   # from maos-workspace@372a40f
ssh -i <BEELINK_SSH_KEY> pyefis@10.110.10.241 'sh -s' < $S -- \
    --ref aer-2088/fpl-airway-map-only-expansion --owner AVIONICS --issue AER-2088
scp -i <BEELINK_SSH_KEY> pyefis@10.110.10.241:bench-deploy-flight.png .
```
