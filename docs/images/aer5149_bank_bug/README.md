# AER-5149: target-bank bug, design-pass renders

`sheet.png`: the plain attitude indicator, 480x360 per tile, rendered offscreen
from the prototype on branch `aer-5149/bank-bug`. The sandbox has no fonts, so
no tile shows text. The bank cluster draws none.

| | col 1 | col 2 | col 3 | col 4 |
|---|---|---|---|---|
| top | bug 45, bank L45 (on target) | bug 45, bank L48 (in band) | bug 45, bank R38 (under-banked) | bug 45, bank R55 (over-banked) |
| bottom | bug 50, bank L50 | bug 50, bank R50 | bug 60, bank R60 | bug 60, bank R66 (caution, de-cluttered) |

How it reads: a cyan arrow outside the scale marks the target bank on each
side, and a cyan band +/-5 deg wide lies over the scale. On target, the fixed
white roll pointer sits inside the band, under the arrow. Off target, roll
toward the band.

Regenerate from the repo root:

    QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. \
        python docs/images/aer5149_bank_bug/render.py
