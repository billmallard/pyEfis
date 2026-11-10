# AER-5149: target-bank bug renders

`sheet.png`: the plain attitude indicator, 480x360 per tile, rendered offscreen
with the bug read from the FIX key `BANKBUG`. The sandbox has no fonts, so no
tile shows text, and the `BANK` readout in the bottom row shows empty boxes
where its digits go.

| | col 1 | col 2 | col 3 | col 4 |
|---|---|---|---|---|
| top | bug 45, bank L45 (on target) | bug 45, bank L48 (in band) | bug 45, bank R38 (under-banked) | bug 45, bank R55 (over-banked) |
| middle | bug 50, bank L50 | bug 50, bank R50 | bug 60, bank R60 | bug 60, bank R66 (caution, de-cluttered) |
| bottom | edit focus, bug 45, wings level | edit focus, bug off | tolerance 10, bug 45, bank R53 | bug 30, bank L30 |

How it reads: a cyan arrow outside the scale marks the target bank on each
side, and a cyan band +/-5 deg wide (`bankBugTolerance`) lies over the scale.
On target, the fixed white roll pointer sits inside the band, under the arrow.
Off target, roll toward the band. While the bank scale has edit focus, the
`BANK` readout sits under the slip ball inside the focus ring; at rest only the
dim edit icon shows there.

Regenerate from the repo root:

    QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. \
        python docs/images/aer5149_bank_bug/render.py
