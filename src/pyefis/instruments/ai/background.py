"""
Background-renderer seam for the attitude widget (CERT12 brief R2b, U1).

The AI is primary-flight core; the SVS is not. Before CERT12b the AI
imported the SVS renderer, its camera and its pose interpolator at module
level (brief E1-E3), so every attitude indicator loaded numpy, the GL
bindings and the overlay databases whether or not it drew terrain. Now
the AI imports only this module, and a renderer reaches it through the
interface below.

The interface is the duck type the AI already read off the SVS, written
down:

- ``enabled``          configured on: the symbology registers with the
                       renderer's projection (``AI._svs_conformal``).
- ``ready``            has data to draw.
- ``gl_failed``        could not draw: the AI annunciates SVS UNAVAIL.
- ``drew_terrain``     drew on the last frame: the AI paints its land
                       area sky instead of the brown fail-safe ground.
- ``consume_async_dirty()``  a background worker landed a result with the
                       pose unchanged; the frame clock repaints.
- ``paint_frame(painter, pose)``  draw one frame for *pose*, a
                       ``FramePose``. The renderer reads nothing else off
                       the host.
- ``make_pose_source()``  optional: a position interpolator the host feeds
                       from its FIX position and dynamics inputs and
                       samples once per frame (``pose.PoseSource`` for the
                       SVS). Without a renderer the host interpolates
                       nothing.
- ``_perf``            optional perf logger; the AI reports its paint
                       time through it when present.

The renderer gets a frame's pose as a value, never the widget, so the
seam could later cross a process boundary: a frame plus the pose it was
rendered for (brief section 7).

Core module: standard library and PyQt6 only. It names a renderer module
once, as a string in ``_RENDERERS``; that string is the only route from
the core to SVS code.
"""

import importlib
from dataclasses import dataclass

# Renderer kinds the composition root may plug into the AI, by dotted
# path to a ``create(config) -> renderer`` callable. The one place the
# core names a non-core module, and only as a string (brief R2b).
_RENDERERS = {
    "svs": "pyefis.instruments.ai.svs:create_background_renderer",
}


def create_renderer(kind, config):
    """Build the background renderer registered as *kind* from *config*.
    Imports the renderer's module on first use, so a screen that never
    asks for one never loads it."""
    module_name, _, attr = _RENDERERS[kind].partition(":")
    return getattr(importlib.import_module(module_name), attr)(config)


@dataclass(frozen=True)
class FramePose:
    """Everything a background renderer needs to draw one frame,
    captured by the host at paint time.

    *heading_true_deg* is already corrected for magnetic variation.
    *roll_pivot_px* and *lens_shift_px* are pixels above the viewport
    centre (the AI's raised horizon reference, horizon_position).
    *position_valid* is False when LAT or LONG is old, bad or failed: the
    renderer must not draw terrain for that position (AER-4243).
    """
    width: int
    height: int
    lat: float
    lon: float
    alt_ft: float
    pitch_deg: float
    roll_deg: float
    heading_true_deg: float
    px_per_deg: float
    device_pixel_ratio: float
    roll_pivot_px: float
    lens_shift_px: float
    position_valid: bool


def make_background_item(host, renderer, paint_frame=None):
    """A scene item that draws *renderer* inside the host's paint pass, at
    the item's z-value.

    *host* supplies ``frame_pose()``. *paint_frame* defaults to the
    renderer's own ``paint_frame``; a renderer without one draws nothing.
    The item draws in viewport pixels, so its bounds are made large enough
    that Qt never culls it.
    """
    from PyQt6.QtCore import QRectF
    from PyQt6.QtWidgets import QGraphicsItem

    if paint_frame is None:
        paint_frame = getattr(renderer, "paint_frame", None)

    class _BackgroundItem(QGraphicsItem):
        def __init__(self):
            super().__init__()
            self._renderer = renderer

        def boundingRect(self):
            return QRectF(-1e6, -1e6, 2e6, 2e6)

        def paint(self, painter, option, widget=None):
            if paint_frame is not None:
                paint_frame(painter, host.frame_pose())

    return _BackgroundItem()
