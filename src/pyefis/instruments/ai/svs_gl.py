"""
GPU-backed SVS terrain renderer.

Step 3 of docs/svs_opengl_plan.md: the polar (range, azimuth) mesh
moves to the GPU. The vertex shader carries the polar→aircraft-frame→
screen projection (mirroring SVSRenderer's polar tier on the CPU);
the fragment shader colours each cell by its range band so the fan
topology is visible. Terrain elevation is still ignored — that
arrives in Step 4 as a heightmap texture.

Any exception in construction or in :meth:`SVSGLRenderer.draw` is
caught by :class:`SVSRenderer`, which permanently downgrades the
configured renderer to ``polar``. So a missing GL driver, an
incompatible Qt build, a runtime shader compile error, or a context
issue degrades to the CPU path silently.
"""

from __future__ import annotations

import logging

# PyOpenGL tracks per-context state by default; under Qt's EGL/eglfs
# context it can't find the "current context" and raises during stateful
# calls. We avoid the stateful path entirely (vertex setup goes through
# Qt-native QOpenGLBuffer + setAttributeBuffer) and disable pointer
# tracking for the few stateless calls we do make.
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


# Pre-3.0 GLSL — works on Pi 5 V3D (ES 2.0/3.0/3.1) and any reasonable
# desktop driver. Will bump to GLSL ES 3.00 in Step 4 when we need
# texture sampling for the heightmap.

_VERT_SRC = """
attribute vec2 a_t_az;          // (t in [0,1], az in degrees from nose)

uniform float u_ac_alt_ft;
uniform float u_pitch_deg;
uniform float u_roll_deg;
uniform float u_range_nm;
uniform float u_radial_warp;
uniform float u_r_min_nm;
uniform float u_pixels_per_deg;
uniform vec2  u_viewport;        // (width, height) in pixels

varying float v_t;

const float PI            = 3.14159265358979;
const float DEG_PER_RAD   = 180.0 / PI;
const float M_PER_FT      = 0.3048;
const float M_PER_DEG_LAT = 111139.0;

void main() {
    float t       = a_t_az.x;
    float az_deg  = a_t_az.y;

    // Match the CPU polar tier's effective r_min / r_max so the mesh
    // covers the same world area as the polar fallback.
    float r_max_eff = u_range_nm * (1.0 - 1.0e-6);
    float r_min_eff = min(u_r_min_nm, u_range_nm * 0.01);

    // Radial position with warp (matches CPU code).
    float r_nm = r_min_eff + (r_max_eff - r_min_eff) * pow(t, u_radial_warp);
    float r_deg = r_nm / 60.0;

    // Elevation angle to z=0 (sea level — Step 3 ignores terrain).
    float ac_alt_m = u_ac_alt_ft * M_PER_FT;
    float range_m  = r_deg * M_PER_DEG_LAT;
    float elev_angle_deg = -atan(ac_alt_m / max(range_m, 1.0)) * DEG_PER_RAD;

    // Aircraft-frame screen offsets in degrees.
    // For a polar (r, az) fan, x_ang collapses to az_deg algebraically
    // (atan2(r sin az, r cos az) = az).
    float x_ang = az_deg;
    float y_ang = elev_angle_deg - u_pitch_deg;

    // To pixels relative to viewport centre.
    float x_px =  x_ang * u_pixels_per_deg;
    float y_px = -y_ang * u_pixels_per_deg;

    // Roll rotation around the viewport centre.
    float roll_rad = radians(-u_roll_deg);
    float cos_r = cos(roll_rad);
    float sin_r = sin(roll_rad);
    vec2 rotated = vec2(
        x_px * cos_r - y_px * sin_r,
        x_px * sin_r + y_px * cos_r
    );

    vec2 screen_xy = rotated + u_viewport * 0.5;

    // NDC. Qt's screen y goes down so we flip the y axis.
    gl_Position = vec4(
        2.0 * screen_xy.x / u_viewport.x - 1.0,
        1.0 - 2.0 * screen_xy.y / u_viewport.y,
        0.0, 1.0);

    v_t = t;
}
"""

_FRAG_SRC = """
precision mediump float;
varying float v_t;

void main() {
    // 8-band radial debug palette (concentric arcs).
    float band = floor(v_t * 8.0);
    vec3 color;
    if (band < 0.5)      color = vec3(0.80, 0.20, 0.20);
    else if (band < 1.5) color = vec3(0.80, 0.50, 0.20);
    else if (band < 2.5) color = vec3(0.80, 0.80, 0.20);
    else if (band < 3.5) color = vec3(0.50, 0.80, 0.20);
    else if (band < 4.5) color = vec3(0.20, 0.80, 0.20);
    else if (band < 5.5) color = vec3(0.20, 0.80, 0.80);
    else if (band < 6.5) color = vec3(0.20, 0.50, 0.80);
    else                 color = vec3(0.20, 0.20, 0.80);
    gl_FragColor = vec4(color, 1.0);
}
"""


class SVSGLRenderer:
    """Step 3: polar mesh + per-band debug colouring on the GPU.

    Per frame:

    1. ``makeCurrent`` our context onto the offscreen surface.
    2. Lazy-create the FBO (size-matched), program, and polar mesh.
    3. Set per-frame uniforms (aircraft state + viewport).
    4. ``glDrawElements`` over the polar triangle list.
    5. ``fbo.toImage()`` to read pixels back as a ``QImage``.
    6. ``doneCurrent`` and restore the previous context.
    7. Hand the image off to the parent's ``QPainter``.
    """

    def __init__(self, parent_renderer):
        self._parent = parent_renderer

        # Build the OpenGL context. Any failure is caught by the
        # SVSRenderer fallback wrapper.
        fmt = QSurfaceFormat()
        fmt.setVersion(3, 0)
        fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.NoProfile)
        fmt.setDepthBufferSize(0)
        fmt.setStencilBufferSize(0)
        self._ctx = QOpenGLContext()
        self._ctx.setFormat(fmt)
        if not self._ctx.create():
            raise RuntimeError("could not create QOpenGLContext")

        self._surface = QOffscreenSurface()
        self._surface.setFormat(fmt)
        self._surface.create()
        if not self._surface.isValid():
            raise RuntimeError("could not create QOffscreenSurface")

        # Per-context resources — built lazily on first draw.
        self._fbo: QOpenGLFramebufferObject | None = None
        self._fbo_size = QSize(0, 0)
        self._program: QOpenGLShaderProgram | None = None
        self._a_position = -1
        self._vao: QOpenGLVertexArrayObject | None = None
        self._vbo: QOpenGLBuffer | None = None
        self._ibo: QOpenGLBuffer | None = None
        self._index_count = 0
        # Uniform locations cached after linking.
        self._u: dict[str, int] = {}

        actual = self._ctx.format()
        log.info(
            "SVSGLRenderer Step 3 initialised — GL %s.%s",
            actual.majorVersion(), actual.minorVersion())

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------
    def draw(self, painter, w, h, ac_lat, ac_lon, ac_alt_ft,
             pitch_deg, roll_deg, heading_deg, pixels_per_deg):
        prev_ctx = QOpenGLContext.currentContext()
        prev_surface = prev_ctx.surface() if prev_ctx is not None else None

        if not self._ctx.makeCurrent(self._surface):
            raise RuntimeError("QOpenGLContext.makeCurrent failed")

        try:
            self._ensure_fbo(w, h)
            self._ensure_program()
            self._ensure_mesh()
            image = self._render_to_image(
                w, h, ac_alt_ft, pitch_deg, roll_deg,
                heading_deg, pixels_per_deg)
        finally:
            self._ctx.doneCurrent()
            if prev_ctx is not None and prev_surface is not None:
                prev_ctx.makeCurrent(prev_surface)

        painter.save()
        painter.resetTransform()
        painter.drawImage(0, 0, image)
        painter.restore()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _render_to_image(self, w, h, ac_alt_ft, pitch_deg, roll_deg,
                         heading_deg, pixels_per_deg):
        """Bind FBO, set uniforms, draw the polar mesh, return QImage."""
        self._fbo.bind()
        try:
            gl.glViewport(0, 0, w, h)
            gl.glClearColor(0.05, 0.05, 0.05, 1.0)
            gl.glClear(gl.GL_COLOR_BUFFER_BIT)

            self._program.bind()
            self._vao.bind()
            try:
                p = self._parent
                # Match the polar tier's "use configured range_nm" path
                # (no auto_range for Step 3 — that will come in a
                # later step).
                self._program.setUniformValue(
                    self._u["u_ac_alt_ft"], float(ac_alt_ft))
                self._program.setUniformValue(
                    self._u["u_pitch_deg"], float(pitch_deg))
                self._program.setUniformValue(
                    self._u["u_roll_deg"], float(roll_deg))
                self._program.setUniformValue(
                    self._u["u_range_nm"], float(p.range_nm))
                self._program.setUniformValue(
                    self._u["u_radial_warp"], float(p._radial_warp))
                self._program.setUniformValue(
                    self._u["u_r_min_nm"], float(p._r_min_nm))
                self._program.setUniformValue(
                    self._u["u_pixels_per_deg"], float(pixels_per_deg))
                self._program.setUniformValue(
                    self._u["u_viewport"], float(w), float(h))

                gl.glDrawElements(
                    gl.GL_TRIANGLES, self._index_count,
                    gl.GL_UNSIGNED_INT, None)
            finally:
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
        self._a_position = prog.attributeLocation("a_t_az")
        if self._a_position < 0:
            raise RuntimeError("a_t_az attribute missing after link")
        # Cache uniform locations.
        for name in ("u_ac_alt_ft", "u_pitch_deg", "u_roll_deg",
                     "u_range_nm", "u_radial_warp", "u_r_min_nm",
                     "u_pixels_per_deg", "u_viewport"):
            loc = prog.uniformLocation(name)
            if loc < 0:
                log.warning("uniform %s not found (optimised out?)", name)
            self._u[name] = loc
        self._program = prog

    def _ensure_mesh(self):
        if self._vao is not None:
            return

        vao = QOpenGLVertexArrayObject()
        if not vao.create():
            raise RuntimeError("could not create QOpenGLVertexArrayObject")

        verts, indices = self._build_polar_mesh()

        # Bind VAO; subsequent VBO bind + attribute-pointer + IBO bind
        # are recorded inside it for fast per-frame draws.
        vao.bind()
        try:
            vbo = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
            if not vbo.create():
                raise RuntimeError("could not create vertex buffer")
            vbo.setUsagePattern(QOpenGLBuffer.UsagePattern.StaticDraw)
            vbo.bind()
            vbo.allocate(verts.tobytes(), int(verts.nbytes))

            # Wire attribute → buffer offset/stride. This records in
            # the VAO so we don't have to repeat it per frame.
            self._program.bind()
            try:
                self._program.enableAttributeArray(self._a_position)
                self._program.setAttributeBuffer(
                    self._a_position, gl.GL_FLOAT, 0, 2, 0)
            finally:
                self._program.release()

            ibo = QOpenGLBuffer(QOpenGLBuffer.Type.IndexBuffer)
            if not ibo.create():
                raise RuntimeError("could not create index buffer")
            ibo.setUsagePattern(QOpenGLBuffer.UsagePattern.StaticDraw)
            ibo.bind()
            ibo.allocate(indices.tobytes(), int(indices.nbytes))
        finally:
            vao.release()

        self._vao = vao
        self._vbo = vbo
        self._ibo = ibo
        self._index_count = int(indices.size)

        log.info(
            "SVSGLRenderer mesh: %d vertices, %d indices (n_range=%d, "
            "n_az=%d, fov=%s deg)",
            verts.shape[0], self._index_count,
            self._parent._n_range, self._parent._n_az,
            self._parent._fov_deg)

    def _build_polar_mesh(self):
        """Build the (t, az) polar grid as a vertex buffer plus a
        triangle-list index buffer."""
        n_r = self._parent._n_range
        n_az = self._parent._n_az
        fov = self._parent._fov_deg

        ts = np.linspace(0.0, 1.0, n_r, dtype=np.float32)
        azs = np.linspace(-fov / 2.0, fov / 2.0, n_az, dtype=np.float32)
        T, Az = np.meshgrid(ts, azs, indexing='ij')
        verts = np.column_stack([T.ravel(), Az.ravel()]).astype(np.float32)

        # Triangle list: 2 triangles per (n_r-1) × (n_az-1) cell.
        # Vectorised so we don't pay Python loop overhead for 6k cells.
        i_grid, j_grid = np.mgrid[0:n_r - 1, 0:n_az - 1]
        v00 = (i_grid       * n_az + j_grid      ).ravel()
        v10 = ((i_grid + 1) * n_az + j_grid      ).ravel()
        v01 = (i_grid       * n_az + j_grid + 1  ).ravel()
        v11 = ((i_grid + 1) * n_az + j_grid + 1  ).ravel()
        # tri1 = (v00, v10, v01), tri2 = (v10, v11, v01)
        indices = np.empty(v00.size * 6, dtype=np.uint32)
        indices[0::6] = v00
        indices[1::6] = v10
        indices[2::6] = v01
        indices[3::6] = v10
        indices[4::6] = v11
        indices[5::6] = v01

        return verts, indices
