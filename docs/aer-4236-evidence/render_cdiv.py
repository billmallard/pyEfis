"""Render one HSI scene for the AER-4236 (fix-gateway#20) CDIV evidence.

    python docs/aer-4236-evidence/render_cdiv.py <cdiv> <orientation> <out.png>

<cdiv> is "absent", "0" or "1". Run it once per scene, in its own process, so no
FIX state leaks between scenes. The render tool auto-defines any key a widget asks
for; "absent" makes CDIV lookups raise instead, which is what a pyEfis talking to
an older fix-gateway (no CDIV key) sees.

The flight state is fix-gateway#20's bench case: ILS 1 tuned on a 090 course,
localizer not received, so X-Plane's deflection reads a centred 0.0 and the
glideslope is not valid.
"""

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)

import render_instrument as ri  # noqa: E402

cdiv, orientation, out = sys.argv[1], sys.argv[2], sys.argv[3]

seed = {
    "HEAD": 60.0,      # heading 060, intercepting
    "COURSE": 90.0,    # ILS 1 front course 090
    "NAVSRC": 0,       # VLOC1
    "CDI": 0.0,        # not received: a centred deflection
    "GSI": 0.0,
    "GSV": 0.0,        # no glideslope without the localizer
    "TOFROM": 0,       # a localizer has no TO/FROM
}
if cdiv != "absent":
    seed["CDIV"] = float(cdiv)
else:
    # _setup_fix re-initialises the FIX db on every render, so the "no such
    # key" rule has to be installed after it, not before.
    real_setup_fix = ri._setup_fix

    def setup_fix_without_cdiv():
        real_setup_fix()
        real_get_item = ri.fix.db.get_item

        def get_item(key, *args, **kwargs):
            if key == "CDIV":
                raise KeyError(key)
            return real_get_item(key, *args, **kwargs)

        ri.fix.db.get_item = get_item

    ri._setup_fix = setup_fix_without_cdiv

kind, path = ri.render_instrument(
    "horizontal_situation_indicator",
    options={"orientation": orientation},
    seed=seed, width=360, height=360, out_path=out)
print(kind, path)
