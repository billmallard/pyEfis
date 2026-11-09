# AER-5251 / pyEfis #319 evidence

Attitude widget, SVS off, `horizon_position` 68, 1248x1200, pitch 0, on a
black view background. `before_*` is `dev` without the fix, `after_*` is this
branch. `before_after_grid.png` is the six renders at 1/3 scale: rows are bank
+30, -30, +60; left column before, right column after.

Regenerate (repo root, `OUT_TAG` names the output prefix):

    OUT_TAG=after QT_QPA_PLATFORM=offscreen PYTHONPATH=src \
        python -m pytest docs/aer-5251-evidence/render.py --no-cov -q
    git stash -- src
    OUT_TAG=before QT_QPA_PLATFORM=offscreen PYTHONPATH=src \
        python -m pytest docs/aer-5251-evidence/render.py --no-cov -q
    git stash pop

The grid was composed with PIL (each render downscaled 3x, pasted 2x3 with a
10 px white gutter).
