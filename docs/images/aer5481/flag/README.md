# AER-5481: the PFD DATA flag for a pending panel change

Rendered on the Beelink bench (offscreen Qt, the bench's fonts) at the size
the stock PFD gives the flag: 18x5 cells of a 200x110 grid on 1920x1080, which
is 173x49 px. The images are upscaled 2x, nearest. The data is a copy of the
bench's live status.json (12 packs, all current).

- `flag_pending.png`: a panel change is pending, so the flag is amber.
- `flag_no_change.png`: no change is pending and the packs are current, so
  nothing is drawn (the frame is empty on purpose).
- `bench_live_glass_pending_no_flag.png`: an x11grab of the live bench glass
  on `dev` f9e51206, taken while a real manual config pull (config v50,
  2026-11-14 01:49Z) was pending. The live panel is a configurator-managed
  screen with no `data_annunciation` placed, so no flag appears there,
  before or after this change.

Regenerate on the bench: `~/pyefis-venv/bin/python flag_render.py` (the
script imports pyEfis from `~/bench-scratch/aer5481/flag/src`).
