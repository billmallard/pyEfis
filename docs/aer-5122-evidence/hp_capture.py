"""AER-5122 capture wrapper: run tools/svs_capture.py with the AI widget at
horizon_position HP (env, default 75) and pitchDegreesShown PDS (default 50).
svs_capture is imported first so its mock-FIX swap happens before pyefis."""
import importlib.util, os, sys
sys.path.insert(0, os.path.join(os.getcwd(), "src"))
spec = importlib.util.spec_from_file_location("svs_capture", "tools/svs_capture.py")
cap = importlib.util.module_from_spec(spec)
sys.modules["svs_capture"] = cap
spec.loader.exec_module(cap)
from pyefis.instruments.ai import ai_widget
_init = ai_widget.AI.__init__
def _patched(self, *a, **k):
    _init(self, *a, **k)
    self.horizon_position = float(os.environ.get("HP", "75"))
    self.pitchDegreesShown = float(os.environ.get("PDS", "50"))
ai_widget.AI.__init__ = _patched
sys.exit(cap.main(sys.argv[1:]))
