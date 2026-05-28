"""
GPU-backed SVS terrain renderer.

Scaffolding for the OpenGL renderer tier described in
docs/svs_opengl_plan.md. Construction succeeds when PyQt6's OpenGL
bindings are importable; ``draw()`` raises ``NotImplementedError`` so
``SVSRenderer`` falls back to the polar (CPU) tier on the first call.

The plan's later steps replace the ``NotImplementedError`` with a real
FBO-render-and-blit pipeline (polar mesh, heightmap texture, vertex +
fragment shaders).

The fallback machinery in :class:`SVSRenderer` catches any exception
from this module — both during construction and during draw — and
downgrades the configured renderer to ``polar`` permanently. So the
worst case of a missing GL driver, an incompatible Qt build, or a
runtime shader error is "user gets the polar CPU renderer instead of
the GPU one," not a crashed cockpit display.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


class SVSGLRenderer:
    """Skeleton GPU renderer.

    Holds a back-reference to the parent :class:`SVSRenderer` so later
    steps can read its config (polar grid params, range, airport-
    proximity rule, tile cache) and reuse the existing data plumbing.

    Construction probes the Qt OpenGL bindings — if PyQt6 was built
    without OpenGL support the import below will fail, the parent
    catches the exception, and we silently downgrade to polar.
    """

    def __init__(self, parent_renderer):
        # Probe Qt OpenGL bindings at construction time so the failure
        # mode is "missing/incompatible Qt OpenGL bindings" rather than
        # "crash on first draw." Any failure here is caught by the
        # SVSRenderer fallback wrapper.
        from PyQt6.QtOpenGL import QOpenGLShaderProgram  # noqa: F401
        from PyQt6.QtGui import QSurfaceFormat            # noqa: F401

        self._parent = parent_renderer
        log.info(
            "SVSGLRenderer scaffolding loaded (no GL pipeline yet — see "
            "docs/svs_opengl_plan.md). First draw will fall back to polar."
        )

    def draw(self, painter, w, h, ac_lat, ac_lon, ac_alt_ft,
             pitch_deg, roll_deg, heading_deg, pixels_per_deg):
        """Stub. Will be replaced step-by-step per the OpenGL plan."""
        raise NotImplementedError(
            "SVSGLRenderer.draw not implemented yet; "
            "see docs/svs_opengl_plan.md for the remaining steps")
