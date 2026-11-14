# AER-5481 bench look: pack list under the panel-change banner

Rendered on the Beelink bench (offscreen Qt, the bench's real fonts) from a
copy of its live `~/.makerplane/pyefis/status.json` (12 packs), with a pending
`panel_change` block injected into the copy. The live file and the live
display were not touched.

- `before_pending_1920x1080.png`: pyEfis `dev` at f9e51206 (#462 merged). The
  last five pack rows paint behind Continue/About/Update.
- `after_*`: this branch. The rows shrink to fit above the buttons.

Regenerate on the bench:

    ~/pyefis-venv/bin/python bench_render.py   # writes ~/bench-scratch/aer5481/*.png

`bench_render.py` imports pyEfis from `~/pyEfis/src`; point `sys.path` at
another checkout to render a branch.
