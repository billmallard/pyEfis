# AER-5481 bench look: the pack list under the panel-change banner

Rendered on the Beelink bench (offscreen Qt, the bench's real fonts) from a
copy of its live `~/.makerplane/pyefis/status.json`: 12 packs, six of them
terrain regions. The pending `panel_change` in these renders is the bench's
real one (config v50, a manual pull at 2026-11-14 01:49Z). The live file and
the live display were not touched.

- `before_pending_1920x1080.png`: pyEfis `dev` at f9e51206 (#462 merged). The
  last five pack rows paint behind Continue/About/Update.
- `collapsed_*.png`: this branch. The six terrain regions are one row,
  "Terrain (6 regions)", at full row height (Bill, 2026-11-14).
  - `collapsed_800x480.png`, `collapsed_1920x1080.png`: as the bench is.
  - `collapsed_800x480_message.png`: with a transient message showing. It sits
    below the last row.
  - `collapsed_800x480_region_expired.png`: `terrain-us-west` set to EXPIRED in
    the copy. The row turns amber and names the region.

Regenerate on the bench, after unpacking this branch's `src` to
`~/bench-scratch/aer5481/collapse/src`:

    ~/pyefis-venv/bin/python collapse_render.py
