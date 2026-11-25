# AER-6415 (CAS4) evidence: the alert tones

## The recordings (for the project owner's ear)

What the player writes to the audio device, byte for byte, at the default volume
(`AuralVolume` 0.8), 48 kHz 16-bit mono. BACKLOG CAS4 leaves the sounds to the
project owner; these are the proposal.

| File | What it is |
|---|---|
| `disconnect.wav` | Autopilot disconnect: three falling sweeps, 1600 to 800 Hz, every 1.1 s. Four cycles |
| `warning.wav` | Warning: three 1000 Hz beeps, every 1.2 s. Four cycles |
| `caution.wav` | Caution: a falling two-note chime, 1100 then 880 Hz, every 5 s. Two cycles |
| `r9_sequence.wav` | R9 in one take: a caution chimes; at 0.5 s a warning cuts it off; at 2.9 s an autopilot disconnect arrives and takes turns with the warning; at 7.5 s the disconnect is acknowledged; at 8.7 s the warning is, and the caution comes back; at 14.2 s the caution is, mid-chime |
| `r9_sequence_spectrogram.png` | The spectrogram of `r9_sequence.wav`, phases marked |

Regenerate:

    PYTHONPATH=src python3 docs/aer-6415-evidence/make_recordings.py docs/aer-6415-evidence
    python3 docs/aer-6415-evidence/spectrogram.py docs/aer-6415-evidence

(`make_recordings.py` imports the Qt package, so on a headless box set
`QT_QPA_PLATFORM=offscreen`.)

## The Beelink bench (2026-11-23, X11 kiosk, HDA Intel PCH / Realtek ALC897, headphone jack)

Branch `aer-6415/cas4-aural-tone` staged with `bench-deploy.sh --ref`, the real
fix-gateway `dev` with the `cas` plugin on. `bench_tones.py` runs on the bench and
drives the alert states over netfix; `beelink/run_*/` holds what it logged:
`phases.log` (each phase, with `CASTOP`, `CASSEQ`, `APDISC` read back from the
gateway), `aural.log` (pyEfis's own `aural:` lines from the journal) and
`pcm_status.log`.

Install steps the bench needed, now in the wiki ("Alert tones"):

- `pyefis` was not in the `audio` group. pyEfis runs as a systemd **user** unit, so
  the group took effect only after `systemctl restart user@1000.service`. Before that
  the log read `aural: cannot open ALSA device 'default': No such file or directory`.
- alsa-utils was not installed, and the `Master` control was muted at 0%. It is now
  at 80%, unmuted, and stored with `alsactl store`.

**Run 1** (`beelink/run1/`, on `default`): a standing `HDG FAIL` caution sounds. An
autopilot disconnect (`APDISC`, with every AFC1 key written at 2 Hz the way a source
writes them) cuts it off at 16:06:27.69. The caution returns at 16:06:33.71 when the
disconnect is acknowledged, and `CASACK` silences it at 16:06:39.71. Each change came
within about 0.1 s of the bus write that caused it.

**Runs 2 and 3** went through a temporary ALSA `file` tee in front of `default`
(`~/.asoundrc` `pcm.aer6415tap`, `AuralDevice: aer6415tap`, both reverted after).
The tee kept the jack playing and also recorded every byte pyEfis wrote:

- `run_disconnect`: the disconnect tone cuts an `AP LINK LOST` caution and plays
  until it is acknowledged.
- `run_warning`: every alert here was raised by the real plugin or by pyEfis:
  - `AP LINK LOST` as a caution, then as a **warning** (the autopilot was engaged
    when the link stopped), silenced by `CASACK`.
  - fix-gateway stopped for 8 s: `CAS FAIL` (a local caution), then
    `GATEWAY LINK LOST` (a local warning), which interrupted it. With no bus at all,
    the warning still sounded from pyEfis.
  - The link came back, and `CAS FAIL` sounded until it cleared.

`tap_tones.py` labels every 10 ms of the tee's bytes against the shipped tone cycles
(`tap_labels.txt`). **0 of 1235 and 0 of 3168 chunks match no tone.** So the
recordings above are exactly what the bench played, in this order:

    run_disconnect: caution, disconnect
    run_warning:    caution, warning, caution, warning, caution

A note on `pcm_status.log`: `default` on this box goes through dmix, which keeps the
hardware clocking while any client holds it open. A `RUNNING` state there means the
device is driven; it cannot show silence. The silences come from the `aural:` log
lines and the tee.

## The Pi 5 bench (eglfs)

Staged with `bench-deploy.sh --bench pi5 --ref`: pyefis.service active, no
traceback. Its monitor (Dell 2407WFP) reports no audio support over HDMI
(`sad_count 0`), and the Pi 5 has no headphone jack. ALSA `default` therefore refuses
to open (`Unknown error 524`). pyEfis logs it once and retries every 5 s. The visual
CAS is unchanged. That is the no-device path (CASW-AUR-006). It is not a tone on the
Pi; that needs a USB audio adapter (the project owner's purchase, asked on AER-6415).

### The Pi 5 with a USB audio adapter (2026-11-25)

The project owner plugged in a USB audio adapter (`0c76:1203` JMTek "USB PnP Audio
Device", ALSA card 2) and speakers. The Pi runs `dev` at `89282f8d`, which carries
#567, so nothing was deployed. Install facts:

- PipeWire takes the adapter as its default sink, but the Pi has no PipeWire ALSA
  plugin, so ALSA `default` still means HDMI. The live `main/default.yaml` now sets
  `AuralDevice: plughw:CARD=Device`. pyEfis logged
  `aural: playing on ALSA device 'plughw:CARD=Device'`.
- The level is unchanged. `plughw` bypasses PipeWire, so the adapter's hardware
  `Speaker` control sets the loudness. It sits at 626/1008 (62%, -23.9 dB), where
  PipeWire put its 0.40, and `AuralVolume` is the default 0.8.

`bench_tones.py` ran on the Pi with two substitutions: the status path is `card2`,
and fix-gateway is the user unit (`systemctl --user stop|start fixgw.service`, not
sudo). `pi5/` holds the same three logs as the Beelink runs. The `aural.log` times
are Pi local time (CST); `phases.log` uses epoch seconds (14:21:10 CST is 1795638070).

    14:20:52 caution    a standing caution, which cleared at 14:21:08 before the run
    14:21:16 disconnect APDISC raised; silent at 14:21:22 when it is acknowledged
    14:21:33 caution    AP LINK LOST (disengaged at the loss); silent when the link returns
    14:21:48 warning    AP LINK LOST (engaged at the loss); silent at 14:21:53 on CASACK
    14:21:56 caution    fix-gateway stopped: CAS FAIL, then
    14:21:58 warning    GATEWAY LINK LOST interrupts it, with no bus at all
    14:22:10 caution    the link is back, and CAS FAIL sounds until it clears at 14:22:12

The card 2 PCM state agrees: it was `RUNNING` for 6.0 s in the disconnect run, and
for 10.4, 4.4 and 16.2 s in the warning run, matching the spans above. It was
`PREPARED` (open, silent) between them. Here `plughw` is not dmix, so `RUNNING`
does mean samples were reaching the adapter. Whether they were loud enough at the
speakers is for the ear at the bench. No tee was used, so this run has no byte match.
