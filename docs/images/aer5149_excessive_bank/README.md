# AER-5149: excessive-bank caution default 45 -> 60

`sheet.png`: the plain attitude indicator, 360x270 per tile, rendered offscreen
from the real widget. Columns left to right: bank -55, -45, +45, +55 deg.
Top row: `excessiveBankDeg: 45` (the old default). Bottom row: the new default
(60).

Before, the bank scale and pointer turn amber at 55 deg, inside both ACS
steep-turn bands (Private 45 +/-5, Commercial 50 +/-5). After, they stay white
through all four.

Tile text is absent: the sandbox that produced the sheet has no fonts. The
bank cluster draws no text, so that does not affect what the sheet shows.

Regenerate from the repo root:

    QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. \
        python docs/images/aer5149_excessive_bank/render.py
