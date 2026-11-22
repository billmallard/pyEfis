"""
Horizontal projection shared by the attitude widget and the SVS camera.

Core module (primary-flight core, CERT12 brief U2): the AI places its
heading ticks and the FPM's drift on this scale when a background
renderer registers with it, and the SVS camera (``camera.py``) imports
it from here. Before CERT12b it lived in ``camera.py``, so the AI pulled
the whole SVS camera module (and numpy) in for one function. The
direction of the import is what moved; the arithmetic did not.

Standard library only.
"""

import math

DEG_PER_RAD = 57.29577951308232

# Terrain horizontal scale, as a pitchDegreesShown-equivalent: the
# terrain projects h / TERRAIN_HFOV_PITCH_DEG pixels per degree across,
# whatever the AI widget's live pitchDegreesShown is (AER-1799 settled the
# field, AER-1806/AER-1973 pinned it). Lives here, not in svs_gl.py, so the
# AI widget can place horizontal symbology on the same scale without
# importing the GL renderer.
TERRAIN_HFOV_PITCH_DEG = 30.0


def terrain_horizontal_px(bearing_deg, viewport_h):
    """Screen-x offset, in pixels from the roll pivot, at which the SVS
    terrain draws a point on the horizon *bearing_deg* off the nose,
    wings level and pitch 0: the same tangent projection view_projection
    applies. Horizontal symbology that has to sit over terrain (heading
    ticks, the FPM's drift) uses this instead of bearing * pixelsPerDeg,
    which is the vertical scale and is linear (pyEfis #304)."""
    ppd_h = viewport_h / TERRAIN_HFOV_PITCH_DEG
    b = max(-89.0, min(89.0, float(bearing_deg)))
    return DEG_PER_RAD * ppd_h * math.tan(math.radians(b))
