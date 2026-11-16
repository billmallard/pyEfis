# AER-4339 startup notice: bench evidence

Two captures on the Beelink bench (X11, 1920x1080).

| File | Captured | What it shows |
|------|----------|---------------|
| `beelink_banner_8s.png` | 2026-11-16, dev `2f6bc38d` | First x11grab frame with pyEfis up, 7 s after restart (the file keeps its old name so the wiki link holds): the PFD, not the DataStatus page, with the notice banner across the bottom. |
| `beelink_dismissed_27s.png` | 2026-10-31, `aer-4339/startup-notice-banner` @ 5b8523e | 27 s after restart: the banner has cleared itself with no input. The PFD is unchanged underneath. |

### 2026-11-16 re-take (`beelink_banner_8s.png`)

Taken by `grab_aer5805.sh` on pyEfis dev `2f6bc38d` and fix-gateway dev
`382856a`, with X-Plane not sending, so LAT/LONG read `Old` at the gateway
before and after the restart. The bench now holds an accept record in
`~/.local/state/makerplane/acknowledgments.jsonl`, so this is the accepted
path: the short (8 s) banner. Frames at 0 s to 5 s are black, 7 s to 13 s are
byte-identical with the banner, and from 16 s the banner is gone. The
airspeed, altitude and vertical-speed keys are old on this bench too, so those
tapes show a red X, the map is TRK UP with NO POS, and the HSI shows `BRG1 OFF / BRG2 OFF`
with no bearing pointers.

Journal line from the same restart:

```
INFO  pyefis.startup_notice - startup notice: this notice is accepted for pyEfis 2.2.1 in /home/pyefis/.local/state/makerplane/acknowledgments.jsonl
```

Regenerate: `scp grab_aer5805.sh` to the bench and run it under the bench lock
(`flock -o -w 900 /tmp/pyefis-bench.lock sh grab_aer5805.sh`). It restarts
pyEfis, grabs every 2 s for about 40 s into `~/bench-scratch/aer5805/`, then
takes three grabs 4 s apart with the position aged out (the `aer4243` frame).

### 2026-10-31 capture (`beelink_dismissed_27s.png`)

Staged by `bench-deploy.sh --ref` with `aer-4339/startup-notice-banner` @
5b8523e. The bench then had no acknowledgment record, so this was the
missing-record path: the long (20 s) banner, plus a WARNING in the journal.
Frames from 8 s to 25 s were byte-identical, and so were frames from 27 s to 43 s.
The bench had no moving data, so the only change on the glass is the banner going
away. The attitude panel reads `SVS UNAVAIL` on this bench, so these frames show
the banner over the GL attitude view, not over rendered terrain.

Journal lines from that restart:

```
INFO  pyefis.gui - data-status: booting PFD (data status reachable from the annunciation)
WARNING pyefis.startup_notice - startup notice: acknowledgment record /home/pyefis/.makerplane/pyefis/acknowledgments.jsonl is missing; showing the non-blocking banner
```

## Regenerate the 2026-10-31 capture

```bash
S=makerplane/processes/paperclip/scripts/bench-deploy.sh   # maos-workspace
ssh -i <key> pyefis@10.110.10.241 'sh -s' < $S -- --ref aer-4339/startup-notice-banner --owner AVIONICS --issue AER-4339
scp grab.sh pyefis@10.110.10.241:bench-scratch/aer4339-grab.sh
ssh -i <key> pyefis@10.110.10.241 'flock -o -w 900 /tmp/pyefis-bench.lock sh bench-scratch/aer4339-grab.sh'
# frames land in ~/bench-scratch/aer4339/fNN_<seconds>s.png
ssh -i <key> pyefis@10.110.10.241 'sh -s' < $S -- --restore --owner AVIONICS --issue AER-4339
```

`grab.sh` restarts pyEfis and takes an x11grab every 2 s for about 40 s.
