"""Run tools/svs_capture.py with SVS `palette` set from $SVS_PALETTE (AER-5141)."""
import os, runpy, sys
mod = runpy.run_path("tools/svs_capture.py", run_name="svs_capture_mod")
from pyefis.instruments.ai import AI
_orig = AI.set_svs_config
def _patched(self, cfg):
    cfg = dict(cfg); cfg["palette"] = os.environ["SVS_PALETTE"]
    return _orig(self, cfg)
AI.set_svs_config = _patched
sys.exit(mod["main"](sys.argv[1:]))
