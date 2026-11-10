"""AER-3865: run a checkout's own tools/svs_capture.py with the Pi bench's
LIVE virtual_vfr options (~/makerplane/pyefis/config/screens/managed.yaml,
the screen pyEfis serves: defaultScreen MAP_CTL_TEST) applied to the AI
widget, so the frame has the geometry Bill sees: pitchDegreesShown 25,
horizon_position 68, a 1248x1200 widget (130/200 columns of 1920x1200).

Usage: REPO=<checkout> python cap_live.py <svs_capture args...>
Options are applied the way screenbuilder_options.apply_options does
(plain setattr) just before set_svs_config, and the live svs_* appearance
keys are merged over svs_capture's own SVS config. svs_capture.py itself
is not modified.
"""
import os, sys, runpy
import yaml

repo = os.environ["REPO"]
live = yaml.safe_load(open(os.path.expanduser(
    "~/makerplane/pyefis/config/screens/managed.yaml")))
vvfr = next(i for i in live["MAP_CTL_TEST"]["instruments"]
            if i["type"] == "virtual_vfr")["options"]


def _coerce(v):
    # The screen builder coerces by each Prop's declared type; the YAML
    # carries some numbers quoted ('68', '5').
    if isinstance(v, str):
        for t in (int, float):
            try:
                return t(v)
            except ValueError:
                pass
    return v


attrs = {k: _coerce(v) for k, v in vvfr.items()
         if k != "svs" and not k.startswith("svs_")}
svs_look = {k[4:]: vvfr[k] for k in (
    "svs_palette", "svs_clearance_green_ft", "svs_clearance_yellow_ft",
    "svs_earth_curvature", "svs_haze", "svs_haze_distance_nm",
    "svs_terrain_fill") if k in vvfr}

tool = os.path.join(repo, "tools", "svs_capture.py")
sys.argv = [tool] + sys.argv[1:]
# Load the tool as a module (not __main__) so its own mock-FIX swap runs
# before anything imports pyefis, then patch the AI class it imported.
g = runpy.run_path(tool, run_name="aer3865_svs_capture")
AI = g["AI"]
_orig = AI.set_svs_config


def _set_svs_config(self, cfg):
    for k, v in attrs.items():
        setattr(self, k, v)
    cfg = dict(cfg)
    cfg.update(svs_look)
    return _orig(self, cfg)


AI.set_svs_config = _set_svs_config
import pyefis
print("pyefis from", pyefis.__file__, file=sys.stderr)
sys.exit(g["main"]())
