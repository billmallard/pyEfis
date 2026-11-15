# CERT2c evidence: bar highlight with an old highlight key (AER-5319)

`before.png` is rendered from `dev`, `after.png` from this branch. Each image
shows one VerticalBar (EGT1, highlight key EGTMAX1, both at the same value),
upscaled 2x nearest-neighbour. On the left, EGTMAX1 is valid. On the right,
EGTMAX1 is old.

- before: the magenta ball stays on its last pick while EGTMAX1 is old.
- after: the ball is dropped while EGTMAX1 is old (Bill, 2026-11-09: drop it,
  do not grey it).

These are sandbox renders without fontconfig, so text draws as boxes. The ball
geometry and colour are what the evidence covers.

Regenerate from the repo root:

    git worktree add --detach /tmp/dev-wt origin/dev
    QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. python3 docs/images/cert2c/render.py docs/images/cert2c/after.png
    QT_QPA_PLATFORM=offscreen PYTHONPATH=/tmp/dev-wt/src:. python3 docs/images/cert2c/render.py docs/images/cert2c/before.png
