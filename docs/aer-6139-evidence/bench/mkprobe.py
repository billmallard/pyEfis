# Builds aer6139/probe_launch.py from the AER-5934 probe, adding a count of
# traffic targets the SVS drew per report (wraps svs_traffic.build).
import sys
src = open(sys.argv[1]).read()
hook = '''
# AER-6139: count traffic targets drawn per frame.
S["tfc"] = []
try:
    from pyefis.instruments.ai import svs_traffic as _st
    _ob = _st.build

    def _b(*a, **k):
        g = _ob(*a, **k)
        S["tfc"].append(len(g.drawn))
        return g
    _st.build = _b
except Exception as e:  # noqa: BLE001
    S["tfc_err"] = repr(e)

'''
src = src.replace("\n_boot()\n", hook + "\n_boot()\n", 1)
old = '''    rec["ur_with_ai_s"] = with_ai / REPORT_S
'''
new = '''    rec["ur_with_ai_s"] = with_ai / REPORT_S
    tf = S["tfc"]
    S["tfc"] = []
    rec["tfc_frames"] = len(tf)
    rec["tfc_drawn_max"] = max(tf) if tf else 0
    rec["tfc_drawn_med"] = sorted(tf)[len(tf) // 2] if tf else 0
    if "tfc_err" in S:
        rec["tfc_err"] = S["tfc_err"]
'''
assert old in src and hook.strip() in src
src = src.replace(old, new, 1)
src = src.replace("AER-5934", "AER-5934, AER-6139")
open(sys.argv[2], "w").write(src)
print("ok")
