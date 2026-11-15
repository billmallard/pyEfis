# AER-4339 startup notice: bench evidence

Captured on the Beelink bench (X11, 1920x1080) on 2026-10-31 with
`aer-4339/startup-notice-banner` @ 5b8523e staged by `bench-deploy.sh --ref`.
The bench has no `~/.makerplane/pyefis/acknowledgments.jsonl`, so this is the
missing-record path: the long (20 s) banner, plus a WARNING in the journal.

| File | What it shows |
|------|---------------|
| `beelink_banner_8s.png` | First x11grab frame with pyEfis up, 8 s after restart: the PFD, not the DataStatus page, with the notice banner across the bottom. |
| `beelink_dismissed_27s.png` | 27 s after restart: the banner has cleared itself with no input. The PFD is unchanged underneath. |

Frames from 8 s to 25 s are byte-identical, and so are frames from 27 s to 43 s.
The bench had no moving data, so the only change on the glass is the banner going
away. The attitude panel reads `SVS UNAVAIL` on this bench, so these frames show
the banner over the GL attitude view, not over rendered terrain.

Journal lines from the same restart:

```
INFO  pyefis.gui - data-status: booting PFD (data status reachable from the annunciation)
WARNING pyefis.startup_notice - startup notice: acknowledgment record /home/pyefis/.makerplane/pyefis/acknowledgments.jsonl is missing; showing the non-blocking banner
```

## Regenerate

```bash
S=makerplane/processes/paperclip/scripts/bench-deploy.sh   # maos-workspace
ssh -i <key> pyefis@10.110.10.241 'sh -s' < $S -- --ref aer-4339/startup-notice-banner --owner AVIONICS --issue AER-4339
scp grab.sh pyefis@10.110.10.241:bench-scratch/aer4339-grab.sh
ssh -i <key> pyefis@10.110.10.241 'flock -o -w 900 /tmp/pyefis-bench.lock sh bench-scratch/aer4339-grab.sh'
# frames land in ~/bench-scratch/aer4339/fNN_<seconds>s.png
ssh -i <key> pyefis@10.110.10.241 'sh -s' < $S -- --restore --owner AVIONICS --issue AER-4339
```

`grab.sh` restarts pyEfis and takes an x11grab every 2 s for about 40 s.
