"""One AER-6080 strip frame: the AI at a pinned pose, rendered offscreen
through tools/svs_capture.py's GL target, in one of three modes.

  svs          SVS plugged in and drawing terrain (svs_capture as is).
  symbology    SVS plugged in, disabled (svs_capture --symbology-only).
  none         No renderer at all: set_svs_config is never called.

Adds --horizon-position (svs_capture applies no screen options; deployed
SVS panels set 68), so the frames exercise the lens shift and roll pivot
the AI hands the renderer. Runs against whichever tree is on PYTHONPATH,
so the same file drives the dev and branch checkouts.

    PYTHONPATH=<tree>/src python strip_capture.py --tree <tree> \
        --mode svs --horizon-position 68 -- <svs_capture args>
"""
import argparse
import runpy
import sys
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--tree", required=True)
    p.add_argument("--mode", choices=("svs", "symbology", "none"),
                   required=True)
    p.add_argument("--horizon-position", type=float, default=50.0)
    ours, rest = p.parse_known_args()
    if rest and rest[0] == "--":
        rest = rest[1:]
    if ours.mode == "symbology":
        rest = rest + ["--symbology-only"]

    # Load the tool first: its mock-FIX swap must precede any pyefis import.
    tool = runpy.run_path(str(Path(ours.tree) / "tools" / "svs_capture.py"),
                          run_name="svs_capture_mod")
    AI = tool["AI"]

    if ours.mode != "none":
        orig = AI.set_svs_config

        def set_svs_config(self, cfg):
            self.horizon_position = ours.horizon_position
            orig(self, cfg)

        AI.set_svs_config = set_svs_config
        return tool["main"](rest)
    return render_without_renderer(tool, ours.horizon_position, rest)


def render_without_renderer(tool, horizon_position, argv):
    """svs_capture's offscreen path minus set_svs_config: same mock FIX
    seed, same GL target, same render and readback functions."""
    args = tool["parse_args"](argv)
    tool["seed_mock_fix"](args)
    QApplication = tool["QApplication"]
    Qt = tool["Qt"]
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication([])
    target = tool["make_offscreen_target"](args.width, args.height)
    if target is None:
        print("could not create an offscreen GL target", file=sys.stderr)
        return 3
    surface, ctx, fbo, paint_device = target
    widget = tool["AI"](None)
    widget.terrain_only = False
    widget.horizon_position = horizon_position
    tool["resize_for_offscreen_capture"](widget, args.width, args.height)
    for _ in range(5):
        app.processEvents()
        tool["render_offscreen_frame"](widget, ctx, surface, fbo,
                                       paint_device)
    if not ctx.makeCurrent(surface) or not fbo.bind():
        return 3
    if not tool["_readback_pixels"](args.width, args.height, args.out):
        return 4
    print(f"captured {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
