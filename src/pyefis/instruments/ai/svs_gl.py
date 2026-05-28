"""
GPU-backed SVS terrain renderer.

Step 2 of docs/svs_opengl_plan.md: minimal coloured quad rendered to an
FBO and blitted into the painter via ``QPainter.drawImage()``. Establishes
that we can put GPU-rendered pixels where SVS terrain used to go; later
steps replace the solid colour with the actual terrain mesh, shading,
and clearance colouring.

Any exception in construction or in :meth:`SVSGLRenderer.draw` is caught
by :class:`SVSRenderer`, which downgrades the configured renderer to
``polar`` permanently. So a missing GL driver, an incompatible Qt build,
or a runtime shader error degrades to the CPU path silently.
"""

from __future__ import annotations

import logging

# PyOpenGL tracks vertex-attribute pointers in per-context storage by
# default; under Qt's EGL/eglfs context it can't find the "current
# context" and raises during glVertexAttribPointer. We avoid that call
# entirely by going through QOpenGLBuffer + setAttributeBuffer for
# vertex setup — so we only need PyOpenGL for stateless calls (glClear,
# glDrawArrays, etc.). Disabling the pointer store removes the last
# trace of context tracking for the calls we do make.
import OpenGL
OpenGL.STORE_POINTERS = False
OpenGL.ERROR_ON_COPY = True   # required when STORE_POINTERS is False
from OpenGL import GL as gl  # noqa: E402

import numpy as np  # noqa: E402
from PyQt6.QtCore import QSize  # noqa: E402
from PyQt6.QtGui import (  # noqa: E402
    QOffscreenSurface, QOpenGLContext, QSurfaceFormat,
)
from PyQt6.QtOpenGL import (  # noqa: E402
    QOpenGLBuffer,
    QOpenGLFramebufferObject,
    QOpenGLShader,
    QOpenGLShaderProgram,
    QOpenGLVertexArrayObject,
)

log = logging.getLogger(__name__)


# Pre-3.0 GLSL — works on every Qt OpenGL backend we care about
# (OpenGL ES 2.0+ on Pi 5 V3D, OpenGL 2.1+ on desktop / Mesa). When
# Step 4 introduces heightmap-texture sampling we'll bump to
# GLSL ES 3.00 (#version 300 es) and the in-shader-rule preamble
# the desktop driver tolerates.
_VERT_SRC = """
attribute vec2 a_position;
void main() {
    gl_Position = vec4(a_position, 0.0, 1.0);
}
"""

_FRAG_SRC = """
precision mediump float;
uniform vec3 u_color;
void main() {
    gl_FragColor = vec4(u_color, 1.0);
}
"""

# A teal that's recognisable in screenshots and never produced by the
# polar / rectangular tiers' clearance bucketing.
_STEP2_COLOR = (0.18, 0.55, 0.55)


class SVSGLRenderer:
    """Step 2: paint a teal full-screen quad via the GPU.

    Holds a back-reference to :class:`SVSRenderer` so later steps can
    reach the polar config, the tile cache, and the airport-proximity
    state without re-implementing them. Per frame:

    1. ``makeCurrent`` our context onto the offscreen surface.
    2. Lazy-create / size-match an FBO and the shader program.
    3. Render the test quad into the FBO.
    4. ``fbo.toImage()`` to read pixels back as a ``QImage``.
    5. ``doneCurrent`` and restore whatever context Qt had current.
    6. Hand the image off to the parent's ``QPainter``.
    """

    def __init__(self, parent_renderer):
        self._parent = parent_renderer

        # Build the OpenGL context. Any failure here is caught by the
        # SVSRenderer fallback wrapper.
        fmt = QSurfaceFormat()
        fmt.setVersion(3, 0)
        fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.NoProfile)
        fmt.setDepthBufferSize(0)      # no depth needed for a 2-D quad
        fmt.setStencilBufferSize(0)
        self._ctx = QOpenGLContext()
        self._ctx.setFormat(fmt)
        if not self._ctx.create():
            raise RuntimeError("could not create QOpenGLContext")

        # Offscreen surface the context can be made current against.
        # Qt requires this be created on the GUI thread, which we already
        # are (SVS draw is invoked from QGraphicsItem.paint).
        self._surface = QOffscreenSurface()
        self._surface.setFormat(fmt)
        self._surface.create()
        if not self._surface.isValid():
            raise RuntimeError("could not create QOffscreenSurface")

        # Per-context resources — built lazily on first draw so the
        # construction failure mode is clean (just "couldn't create
        # context") rather than "context exists but shaders won't link."
        self._fbo: QOpenGLFramebufferObject | None = None
        self._fbo_size = QSize(0, 0)
        self._program: QOpenGLShaderProgram | None = None
        self._a_position = -1
        # Core-profile desktop drivers require a bound VAO for any
        # glVertexAttribPointer call — even legacy GLSL like ours.
        # ES doesn't strictly need it but having one bound is a no-op
        # there. Created on first draw inside makeCurrent.
        self._vao: QOpenGLVertexArrayObject | None = None
        # Static fullscreen-quad VBO. Built once per context, reused
        # every frame.
        self._quad_vbo: QOpenGLBuffer | None = None

        actual = self._ctx.format()
        log.info(
            "SVSGLRenderer Step 2 initialised — GL %s.%s",
            actual.majorVersion(), actual.minorVersion())

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------
    def draw(self, painter, w, h, ac_lat, ac_lon, ac_alt_ft,
             pitch_deg, roll_deg, heading_deg, pixels_per_deg):
        # Save whatever context Qt's painter had current so we don't
        # disturb the rest of the widget tree.
        prev_ctx = QOpenGLContext.currentContext()
        prev_surface = prev_ctx.surface() if prev_ctx is not None else None

        if not self._ctx.makeCurrent(self._surface):
            raise RuntimeError("QOpenGLContext.makeCurrent failed")

        try:
            self._ensure_fbo(w, h)
            self._ensure_program()
            self._ensure_vao()
            image = self._render_to_image(w, h)
        finally:
            self._ctx.doneCurrent()
            if prev_ctx is not None and prev_surface is not None:
                prev_ctx.makeCurrent(prev_surface)

        # Blit the GPU result through the parent's CPU painter so we
        # land in exactly the same QGraphicsItem.paint() pipeline as
        # the polar tier — the scene-graph z-order and CPU overlays
        # don't notice.
        painter.save()
        painter.resetTransform()
        painter.drawImage(0, 0, image)
        painter.restore()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _render_to_image(self, w, h):
        """Bind the FBO, draw the test quad, return the result as QImage.

        Vertex setup (VBO + attribute pointer) goes through Qt-native
        wrappers (QOpenGLBuffer + QOpenGLShaderProgram) so we never
        call ``glVertexAttribPointer`` through PyOpenGL — that's the
        call that fails on Pi/eglfs because of PyOpenGL's context
        tracking. The remaining raw calls (glClear, glDrawArrays) are
        stateless and work fine via PyOpenGL on both Windows and Pi.
        """
        self._fbo.bind()
        try:
            gl.glViewport(0, 0, w, h)
            gl.glClearColor(0.0, 0.0, 0.0, 0.0)
            gl.glClear(gl.GL_COLOR_BUFFER_BIT)

            self._program.bind()
            self._vao.bind()
            self._quad_vbo.bind()
            try:
                self._program.setUniformValue(
                    self._program.uniformLocation("u_color"),
                    float(_STEP2_COLOR[0]),
                    float(_STEP2_COLOR[1]),
                    float(_STEP2_COLOR[2]))
                # setAttributeBuffer wires the shader attribute to the
                # currently-bound VBO at byte offset 0, two floats per
                # vertex. This goes through QOpenGLShaderProgram, not
                # raw glVertexAttribPointer.
                self._program.enableAttributeArray(self._a_position)
                self._program.setAttributeBuffer(
                    self._a_position, gl.GL_FLOAT, 0, 2, 0)
                gl.glDrawArrays(gl.GL_TRIANGLE_STRIP, 0, 4)
                self._program.disableAttributeArray(self._a_position)
            finally:
                self._quad_vbo.release()
                self._vao.release()
                self._program.release()

            return self._fbo.toImage()
        finally:
            self._fbo.release()

    def _ensure_fbo(self, w, h):
        size = QSize(w, h)
        if self._fbo is None or self._fbo_size != size:
            self._fbo = QOpenGLFramebufferObject(size)
            self._fbo_size = size

    def _ensure_program(self):
        if self._program is not None:
            return
        prog = QOpenGLShaderProgram()
        if not prog.addShaderFromSourceCode(
                QOpenGLShader.ShaderTypeBit.Vertex, _VERT_SRC):
            raise RuntimeError(
                f"vertex shader compile failed: {prog.log()}")
        if not prog.addShaderFromSourceCode(
                QOpenGLShader.ShaderTypeBit.Fragment, _FRAG_SRC):
            raise RuntimeError(
                f"fragment shader compile failed: {prog.log()}")
        if not prog.link():
            raise RuntimeError(f"shader link failed: {prog.log()}")
        self._a_position = prog.attributeLocation("a_position")
        if self._a_position < 0:
            raise RuntimeError("a_position attribute missing after link")
        self._program = prog

    def _ensure_vao(self):
        if self._vao is not None:
            return
        vao = QOpenGLVertexArrayObject()
        if not vao.create():
            raise RuntimeError("could not create QOpenGLVertexArrayObject")
        # Bind it once so the VBO setup below is recorded inside it,
        # then upload the static fullscreen-quad geometry.
        vao.bind()
        try:
            vbo = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
            if not vbo.create():
                raise RuntimeError("could not create vertex buffer")
            vbo.setUsagePattern(QOpenGLBuffer.UsagePattern.StaticDraw)
            vbo.bind()
            verts = np.array(
                [-1.0, -1.0,  1.0, -1.0, -1.0, 1.0, 1.0, 1.0],
                dtype=np.float32)
            vbo.allocate(verts.tobytes(), int(verts.nbytes))
            vbo.release()
            self._quad_vbo = vbo
        finally:
            vao.release()
        self._vao = vao
