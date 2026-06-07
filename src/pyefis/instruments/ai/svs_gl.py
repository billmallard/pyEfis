"""
GPU-backed SVS terrain renderer.

Step 4 of docs/svs_opengl_plan.md: the polar mesh's elevation comes
from a heightmap texture built from the SRTM3 tiles overlapping the
aircraft. The vertex shader samples height per vertex; the fragment
shader outputs greyscale-by-elevation so a recognisable terrain
silhouette appears at known poses. No Lambertian shading yet — that
arrives in Step 5.

GLSL bumps to ``#version 300 es`` / ``#version 130`` (selected at
shader-compile time based on the actual context's renderable type) so
we can use ``texture()`` and explicit fragment outputs. The Pi 5 V3D
supports ES 3.1; Windows native desktop GL supports GLSL 1.30+.

Any exception in construction or in :meth:`SVSGLRenderer.draw` is
caught by :class:`SVSRenderer`, which permanently downgrades the
configured renderer to ``polar``. So a missing GL driver, an
incompatible Qt build, a runtime shader compile error, or a context
issue degrades to the CPU path silently.
"""

from __future__ import annotations

import logging
import math

# PyOpenGL tracks per-context state by default; under Qt's EGL/eglfs
# context it can't find the "current context" and raises during
# stateful calls. Vertex setup goes through Qt-native QOpenGLBuffer +
# setAttributeBuffer; texture setup uses raw GL but the calls we make
# (glGenTextures / glTexImage2D / glTexParameteri / glBindTexture)
# don't store pointers per-context so they're safe.
import OpenGL
OpenGL.STORE_POINTERS = False
OpenGL.ERROR_ON_COPY = True
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


# Shader source bodies — the #version header gets prepended at compile
# time based on the actual context's renderable type (ES vs desktop).
# Body uses GLSL ES 3.00 / GLSL 1.30 modern syntax: in/out, texture(),
# user-defined fragment output.

_VERT_BODY = """
in vec2 a_t_az;                  // (t in [0,1], az in degrees from nose)

uniform float u_ac_lat;
uniform float u_ac_lon;
uniform float u_ac_alt_ft;
uniform float u_heading_deg;
uniform float u_pitch_deg;
uniform float u_roll_deg;
uniform float u_range_nm;
uniform float u_radial_warp;
uniform float u_r_min_nm;
uniform float u_pixels_per_deg;
uniform vec2  u_viewport;          // (width, height) in pixels
uniform sampler2D u_heightmap;     // R32F, single-channel elevation in metres
uniform vec4  u_patch_bounds;      // (lat_min, lat_max, lon_min, lon_max)
// Mesh dimensions — used by the fragment shader's grid-line
// detection so it knows where cell boundaries are in (t, az) space.
uniform float u_n_range;
uniform float u_n_az;
uniform float u_fov_deg;

out float v_clearance_ft;
out float v_intensity;
out float v_is_water;
// Mesh-grid coordinates scaled so that adjacent cell corners are
// exactly one unit apart. The fragment shader uses fwidth() on
// this varying to anti-alias the wireframe.
out vec2  v_grid;

const float PI            = 3.14159265358979;
const float DEG_PER_RAD   = 180.0 / PI;
const float M_PER_FT      = 0.3048;
const float FT_PER_M      = 3.28084;
const float M_PER_DEG_LAT = 111139.0;
// Round 2 tune (2026-06-02): Round 1 went 4.0/0.10 -> 2.0/0.25 and
// user confirmed mountains kept enough drama. This pass takes
// SLOPE_EXAG to 1.0 (no exaggeration, true geometric slopes) and
// AMBIENT to 0.35. Result: SRTM noise on flat terrain stays at its
// real 1-2 deg amplitude, shadow side of slopes sits at 35% — only
// reasonable mountain ridges or hills with real relief show
// noticeable shading. Closest to a "soft true-Lambertian" look.
// Kept in sync with the polar CPU tier in svs.py.
const float SLOPE_EXAG    = 1.0;
const float AMBIENT       = 0.35;
// Scaled to AMBIENT so AMBIENT + DIFFUSE * 1.0 = 1.0.
const float DIFFUSE       = 0.65;
const float WATER_THR_M   = -1000.0;   // SRTM water sentinel was -9999
const float PATCH_TEXELS  = 2402.0;    // 2 tiles × 1201 samples each

void main() {
    float t      = a_t_az.x;
    float az_deg = a_t_az.y;

    // Mesh-cell coordinates: integer at every vertex row / column,
    // so fract() over them in the fragment shader marks cell
    // boundaries. The fragment shader uses fwidth() on these
    // varyings to anti-alias a one-pixel-wide grid line.
    v_grid = vec2(
        t * max(u_n_range - 1.0, 1.0),
        (az_deg + u_fov_deg * 0.5) / max(u_fov_deg, 1.0) *
            max(u_n_az - 1.0, 1.0));

    // Same effective r_min / r_max as the polar CPU tier.
    float r_max_eff = u_range_nm * (1.0 - 1.0e-6);
    float r_min_eff = min(u_r_min_nm, u_range_nm * 0.01);
    float r_nm  = r_min_eff + (r_max_eff - r_min_eff) * pow(t, u_radial_warp);
    float r_deg = r_nm / 60.0;

    // Geographic bearing of this vertex from the aircraft.
    float brg_rad = radians(u_heading_deg + az_deg);
    float sin_b = sin(brg_rad);
    float cos_b = cos(brg_rad);

    // World (lat, lon) of the vertex.
    float lat_cos = cos(radians(u_ac_lat));
    float vert_lat = u_ac_lat + r_deg * cos_b;
    float vert_lon = u_ac_lon + r_deg * sin_b / max(lat_cos, 1.0e-3);

    // Sample the heightmap. Texture u runs west->east; v runs
    // south->north (we flip the SRTM tiles vertically at upload).
    vec2 patch_size_deg = vec2(
        u_patch_bounds.w - u_patch_bounds.z,
        u_patch_bounds.y - u_patch_bounds.x);
    vec2 uv = vec2(
        (vert_lon - u_patch_bounds.z) / max(patch_size_deg.x, 1.0e-6),
        (vert_lat - u_patch_bounds.x) / max(patch_size_deg.y, 1.0e-6));

    float elev_m_raw = texture(u_heightmap, uv).r;
    float is_water   = step(elev_m_raw, WATER_THR_M);
    float elev_m     = mix(elev_m_raw, 0.0, is_water);

    // Slope shading: finite differences against immediate neighbour
    // texels. Sentinel values get clamped first so coastlines don't
    // produce wild slopes.
    vec2 texel_uv = vec2(1.0 / PATCH_TEXELS);
    float elev_e_raw = texture(u_heightmap, uv + vec2(texel_uv.x, 0.0)).r;
    float elev_n_raw = texture(u_heightmap, uv + vec2(0.0, texel_uv.y)).r;
    float elev_e_m   = mix(elev_e_raw, 0.0, step(elev_e_raw, WATER_THR_M));
    float elev_n_m   = mix(elev_n_raw, 0.0, step(elev_n_raw, WATER_THR_M));

    // 1 texel size in metres along each geographic axis.
    vec2 texel_m = vec2(
        texel_uv.x * patch_size_deg.x * M_PER_DEG_LAT * lat_cos,
        texel_uv.y * patch_size_deg.y * M_PER_DEG_LAT);

    // Slope in (E, N) frame, in metres of elevation per metre of
    // horizontal distance. SLOPE_EXAG is the same factor the CPU
    // tier uses so the lighting feels comparable.
    float dE = ((elev_e_m - elev_m) / max(texel_m.x, 1.0)) * SLOPE_EXAG;
    float dN = ((elev_n_m - elev_m) / max(texel_m.y, 1.0)) * SLOPE_EXAG;
    float mag = sqrt(dE * dE + dN * dN + 1.0);
    vec3 normal = vec3(-dE / mag, -dN / mag, 1.0 / mag);

    // Sun in geographic (E, N, Up). Upper-NW — same as CPU code.
    vec3 sun_dir = normalize(vec3(-1.0, 1.0, 2.0));
    float diff = clamp(dot(normal, sun_dir), 0.0, 1.0);
    v_intensity = AMBIENT + DIFFUSE * diff;

    // Clearance for the bucket — positive = aircraft above terrain.
    float elev_ft = elev_m * FT_PER_M;
    v_clearance_ft = u_ac_alt_ft - elev_ft;
    v_is_water     = is_water;

    // Elevation angle from the aircraft to this vertex.
    float ac_alt_m = u_ac_alt_ft * M_PER_FT;
    float range_m  = r_deg * M_PER_DEG_LAT;
    float alt_diff_m = elev_m - ac_alt_m;
    float elev_angle_deg = atan(alt_diff_m / max(range_m, 1.0)) * DEG_PER_RAD;

    float x_ang = az_deg;
    float y_ang = elev_angle_deg - u_pitch_deg;

    float x_px =  x_ang * u_pixels_per_deg;
    float y_px = -y_ang * u_pixels_per_deg;

    float roll_rad = radians(-u_roll_deg);
    float cos_r = cos(roll_rad);
    float sin_r = sin(roll_rad);
    vec2 rotated = vec2(
        x_px * cos_r - y_px * sin_r,
        x_px * sin_r + y_px * cos_r);
    vec2 screen_xy = rotated + u_viewport * 0.5;

    gl_Position = vec4(
        2.0 * screen_xy.x / u_viewport.x - 1.0,
        1.0 - 2.0 * screen_xy.y / u_viewport.y,
        0.0, 1.0);
}
"""

_FRAG_BODY = """
in float v_clearance_ft;
in float v_intensity;
in float v_is_water;
in vec2  v_grid;
out vec4 outColor;

uniform float u_green_ft;        // clearance >= u_green_ft => SAFE
uniform float u_yellow_ft;       // clearance >= u_yellow_ft => CAUTION
uniform float u_near_airport;    // 1.0 => collapse to 2-colour SAFE/CONFLICT
uniform float u_grid_enabled;    // 1.0 => draw mesh grid lines

// Match the CPU tier's COLOR_* constants in svs.py.
const vec3 COLOR_SAFE     = vec3(0.0,   0.392, 0.0  );  // (  0, 100,   0)
const vec3 COLOR_CAUTION  = vec3(0.706, 0.510, 0.0  );  // (180, 130,   0)
const vec3 COLOR_WARNING  = vec3(0.784, 0.157, 0.0  );  // (200,  40,   0)
const vec3 COLOR_CONFLICT = vec3(0.706, 0.0,   0.706);  // (180,   0, 180)
const vec3 COLOR_WATER    = vec3(0.078, 0.314, 0.588);  // ( 20,  80, 150)

// How much to darken at a cell-boundary pixel. 0.35 reads clearly
// against any of the terrain colour bucket colours without
// dominating the shading.
const float GRID_DARKEN   = 0.35;

void main() {
    vec3 base;
    if (v_is_water > 0.5) {
        base = COLOR_WATER;
    } else if (v_clearance_ft < 0.0) {
        base = COLOR_CONFLICT;
    } else if (u_near_airport > 0.5) {
        // Airport-proximity 2-colour mode: warning/caution bands suppressed
        // so a normal landing approach doesn't paint half the screen red.
        // Matches svs.py near_airport branch in _keys_from().
        base = COLOR_SAFE;
    } else if (v_clearance_ft < u_yellow_ft) {
        base = COLOR_WARNING;
    } else if (v_clearance_ft < u_green_ft) {
        base = COLOR_CAUTION;
    } else {
        base = COLOR_SAFE;
    }
    vec3 shaded = base * v_intensity;

    // Mesh wireframe via fwidth-based edge detection on the (t, az)
    // grid coordinates. Standard polygon-wireframe technique that
    // works in pure OpenGL ES 3.0 with no extra geometry — uses the
    // fragment shader's screen-space derivatives to draw a one-
    // pixel-wide anti-aliased line at every cell boundary.
    if (u_grid_enabled > 0.5) {
        vec2 g_to_edge = abs(fract(v_grid) - 0.5);
        vec2 g_aa      = fwidth(v_grid) * 0.5;
        vec2 line_mask = vec2(1.0) - smoothstep(vec2(0.0), g_aa, g_to_edge);
        float wire = max(line_mask.x, line_mask.y);
        shaded = mix(shaded, shaded * (1.0 - GRID_DARKEN), wire);
    }

    outColor = vec4(shaded, 1.0);
}
"""

# ---------------------------------------------------------------------------
# Overlay shader (Phase 0 of the SVS-overlays-to-GPU plan).
# ---------------------------------------------------------------------------
# A "generic flat-color" vertex/fragment pair reused by every overlay we
# migrate off the CPU: water polygons (Phase 1), obstacle poles (Phase 2),
# runway polygon and side stripes (Phase 3), runway markings (Phase 4),
# airport flag poles (Phase 5).
#
# The vertex shader projects a single world-space point (lat, lon, elev_ft)
# to screen using the same math the terrain shader uses (atan2 azimuth +
# pitch/roll rotation). Every overlay shares the projection; only the
# uniform color and per-overlay vertex buffer differ.
#
# Vertices that fall behind the camera (x_fwd <= 0) get z=2.0 in clip
# space, which falls outside the [-w, +w] visible volume so GL clips them
# automatically. Triangles straddling the near plane get clipped per-pixel
# by the GL pipeline — much simpler than the Sutherland-Hodgman the CPU
# path runs.

_OVERLAY_VERT_BODY = """
in vec3 a_world_pos;   // (lat_deg, lon_deg, elev_ft)

uniform float u_ac_lat;
uniform float u_ac_lon;
uniform float u_ac_alt_ft;
uniform float u_heading_deg;
uniform float u_pitch_deg;
uniform float u_roll_deg;
uniform float u_pixels_per_deg;
uniform vec2  u_viewport;

const float PI            = 3.14159265358979;
const float DEG_PER_RAD   = 180.0 / PI;
const float M_PER_FT      = 0.3048;
const float M_PER_DEG_LAT = 111139.0;

void main() {
    float lat_cos = cos(radians(u_ac_lat));
    float d_lat = a_world_pos.x - u_ac_lat;
    float d_lon = (a_world_pos.y - u_ac_lon) * lat_cos;

    float head_rad = radians(u_heading_deg);
    float cos_h = cos(head_rad);
    float sin_h = sin(head_rad);
    float x_fwd   =  d_lat * cos_h + d_lon * sin_h;
    float x_right = -d_lat * sin_h + d_lon * cos_h;

    float range_deg = sqrt(x_fwd * x_fwd + x_right * x_right);
    float range_m   = max(range_deg * M_PER_DEG_LAT, 1.0);
    float alt_diff_m = (a_world_pos.z - u_ac_alt_ft) * M_PER_FT;
    float elev_angle_deg = atan(alt_diff_m, range_m) * DEG_PER_RAD;
    float x_ang = atan(x_right, x_fwd) * DEG_PER_RAD;
    float y_ang = elev_angle_deg - u_pitch_deg;

    float x_px =  x_ang * u_pixels_per_deg;
    float y_px = -y_ang * u_pixels_per_deg;

    float roll_rad = radians(-u_roll_deg);
    float cos_r = cos(roll_rad);
    float sin_r = sin(roll_rad);
    vec2 rotated = vec2(
        x_px * cos_r - y_px * sin_r,
        x_px * sin_r + y_px * cos_r);
    vec2 screen_xy = rotated + u_viewport * 0.5;

    // GL clip-space xy. The z component is pushed out of [-1, 1] when
    // the vertex falls behind the camera so GL discards it.
    float behind = step(x_fwd, 0.0);
    gl_Position = vec4(
        2.0 * screen_xy.x / u_viewport.x - 1.0,
        1.0 - 2.0 * screen_xy.y / u_viewport.y,
        mix(0.0, 2.0, behind),
        1.0);
}
"""

_OVERLAY_FRAG_BODY = """
uniform vec4 u_color;
out vec4 outColor;

void main() {
    outColor = u_color;
}
"""


# SRTM3 constants — see svs.py
SRTM3_SAMPLES = 1201
# 2-by-2 tile patch around the aircraft. The patch starts one degree
# below the aircraft on both axes so the aircraft is always near the
# centre, and is rebuilt when the aircraft crosses an integer degree
# boundary.
_PATCH_TILES = 2
_PATCH_PX    = _PATCH_TILES * SRTM3_SAMPLES   # one row of overlap removed below


class SVSGLRenderer:
    """Step 4: polar mesh sampling a heightmap texture.

    Per frame:

    1. ``makeCurrent`` our context onto the offscreen surface.
    2. Lazy-create FBO, program, mesh.
    3. Refresh the heightmap texture if the aircraft has crossed an
       integer-degree boundary.
    4. Set per-frame uniforms (aircraft state + viewport + patch bounds).
    5. Bind heightmap texture to unit 0; ``glDrawElements`` over the
       polar triangle list.
    6. ``fbo.toImage()`` to read pixels back as a ``QImage``.
    7. ``doneCurrent`` and restore the previous context.
    8. Hand the image off to the parent's ``QPainter``.
    """

    def __init__(self, parent_renderer):
        self._parent = parent_renderer

        # Build the OpenGL context. Any failure caught by the
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
        self._u: dict[str, int] = {}
        # Heightmap texture state. _patch_origin is (start_lat, start_lon)
        # in integer degrees; when it changes we rebuild.
        self._heightmap_tex_id: int | None = None
        self._patch_origin: tuple[int, int] | None = None
        self._patch_bounds = (0.0, 0.0, 0.0, 0.0)  # lat_min, lat_max, lon_min, lon_max

        # Overlay pass state (Phase 0 of the overlays-to-GPU plan).
        # The overlay shader is generic — every overlay draw call binds
        # this program, updates one VBO, sets the u_color uniform, and
        # issues a glDrawArrays. Lazily compiled on first frame.
        self._overlay_program: QOpenGLShaderProgram | None = None
        self._overlay_vao: QOpenGLVertexArrayObject | None = None
        self._overlay_vbo: QOpenGLBuffer | None = None
        self._overlay_vbo_capacity = 0   # current GL-side buffer size in floats
        self._overlay_a_world_pos = -1
        self._overlay_u: dict[str, int] = {}

        actual = self._ctx.format()
        log.info(
            "SVSGLRenderer Step 4 initialised — GL %s.%s",
            actual.majorVersion(), actual.minorVersion())

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------
    def draw(self, painter, w, h, ac_lat, ac_lon, ac_alt_ft,
             pitch_deg, roll_deg, heading_deg, pixels_per_deg,
             range_nm=None):
        prev_ctx = QOpenGLContext.currentContext()
        prev_surface = prev_ctx.surface() if prev_ctx is not None else None

        if not self._ctx.makeCurrent(self._surface):
            raise RuntimeError("QOpenGLContext.makeCurrent failed")

        try:
            self._ensure_fbo(w, h)
            self._ensure_program()
            self._ensure_mesh()
            self._ensure_heightmap(ac_lat, ac_lon)
            image = self._render_to_image(
                w, h, ac_lat, ac_lon, ac_alt_ft, pitch_deg, roll_deg,
                heading_deg, pixels_per_deg, range_nm)
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
    def _render_to_image(self, w, h, ac_lat, ac_lon, ac_alt_ft,
                         pitch_deg, roll_deg, heading_deg, pixels_per_deg,
                         range_nm=None):
        self._fbo.bind()
        try:
            gl.glViewport(0, 0, w, h)
            # Clear to transparent so areas the polar fan does not cover
            # (most importantly the bottom-corner wedges below the
            # innermost ring of the fan, which the mesh just cannot
            # reach at very low AGL) blit transparent on top of the AI
            # background and let the AI's "ground" colour show through
            # instead of replacing it with opaque black. The shader
            # emits alpha=1 on every drawn vertex so terrain pixels
            # composite normally.
            gl.glClearColor(0.0, 0.0, 0.0, 0.0)
            gl.glClear(gl.GL_COLOR_BUFFER_BIT)

            # Bind the heightmap to texture unit 0; the shader's
            # sampler2D uniform points at unit 0.
            gl.glActiveTexture(gl.GL_TEXTURE0)
            gl.glBindTexture(gl.GL_TEXTURE_2D, self._heightmap_tex_id)

            self._program.bind()
            self._vao.bind()
            try:
                p = self._parent
                self._program.setUniformValue(
                    self._u["u_ac_lat"], float(ac_lat))
                self._program.setUniformValue(
                    self._u["u_ac_lon"], float(ac_lon))
                self._program.setUniformValue(
                    self._u["u_ac_alt_ft"], float(ac_alt_ft))
                self._program.setUniformValue(
                    self._u["u_heading_deg"], float(heading_deg))
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
                # patch_bounds: (lat_min, lat_max, lon_min, lon_max)
                self._program.setUniformValue(
                    self._u["u_patch_bounds"],
                    float(self._patch_bounds[0]),
                    float(self._patch_bounds[1]),
                    float(self._patch_bounds[2]),
                    float(self._patch_bounds[3]))
                self._program.setUniformValue(
                    self._u["u_heightmap"], 0)   # sampler -> texture unit 0
                # Clearance thresholds (same defaults as polar CPU tier).
                self._program.setUniformValue(
                    self._u["u_green_ft"], float(p.green_ft))
                self._program.setUniformValue(
                    self._u["u_yellow_ft"], float(p.yellow_ft))
                self._program.setUniformValue(
                    self._u["u_near_airport"],
                    1.0 if self._near_airport(ac_lat, ac_lon) else 0.0)
                # Mesh dimensions for fragment-shader grid-line
                # detection. These are stable across the session
                # but feeding them as uniforms keeps the vertex
                # shader free of recompilation when n_range / n_az
                # change via config.
                self._program.setUniformValue(
                    self._u["u_n_range"], float(p._n_range))
                self._program.setUniformValue(
                    self._u["u_n_az"], float(p._n_az))
                self._program.setUniformValue(
                    self._u["u_fov_deg"], float(p._fov_deg))
                self._program.setUniformValue(
                    self._u["u_grid_enabled"],
                    1.0 if getattr(p, "grid_lines", False) else 0.0)

                gl.glDrawElements(
                    gl.GL_TRIANGLES, self._index_count,
                    gl.GL_UNSIGNED_INT, None)
            finally:
                self._vao.release()
                self._program.release()

            # Overlay pass (water, runways, obstacles, flags) draws
            # into the same FBO on top of the terrain. Phase 1 added
            # water; later phases wire up the rest.
            self._render_overlays(
                w, h, ac_lat, ac_lon, ac_alt_ft,
                pitch_deg, roll_deg, heading_deg, pixels_per_deg,
                range_nm)

            return self._fbo.toImage()
        finally:
            self._fbo.release()

    def _near_airport(self, ac_lat: float, ac_lon: float) -> bool:
        """Same proximity test the polar CPU tier runs at svs.py:359.
        Yields True if any airport in the database sits within
        ``airport_proximity_nm`` of the aircraft."""
        p = self._parent
        prox = float(getattr(p, "airport_proximity_nm", 0.0) or 0.0)
        if prox <= 0.0:
            return False
        db = getattr(p, "airport_db", None)
        if db is None or not getattr(db, "ready", False):
            return False
        for _ in db.airports_in_range(ac_lat, ac_lon, prox):
            return True
        return False

    def _ensure_fbo(self, w, h):
        size = QSize(w, h)
        if self._fbo is None or self._fbo_size != size:
            self._fbo = QOpenGLFramebufferObject(size)
            self._fbo_size = size

    # ------------------------------------------------------------------
    # Overlay pass (Phase 0 infrastructure for the overlays-to-GPU plan)
    # ------------------------------------------------------------------
    def _ensure_overlay_program(self):
        if self._overlay_program is not None:
            return
        header = self._shader_header()
        vsrc = header + _OVERLAY_VERT_BODY
        if "es" in header:
            fheader = "#version 300 es\nprecision mediump float;\n"
        else:
            fheader = header
        fsrc = fheader + _OVERLAY_FRAG_BODY
        prog = QOpenGLShaderProgram()
        if not prog.addShaderFromSourceCode(
                QOpenGLShader.ShaderTypeBit.Vertex, vsrc):
            raise RuntimeError(
                f"overlay vertex shader compile failed: {prog.log()}")
        if not prog.addShaderFromSourceCode(
                QOpenGLShader.ShaderTypeBit.Fragment, fsrc):
            raise RuntimeError(
                f"overlay fragment shader compile failed: {prog.log()}")
        if not prog.link():
            raise RuntimeError(f"overlay shader link failed: {prog.log()}")
        self._overlay_a_world_pos = prog.attributeLocation("a_world_pos")
        if self._overlay_a_world_pos < 0:
            raise RuntimeError("overlay shader: a_world_pos not found")
        for name in ("u_ac_lat", "u_ac_lon", "u_ac_alt_ft",
                     "u_heading_deg", "u_pitch_deg", "u_roll_deg",
                     "u_pixels_per_deg", "u_viewport", "u_color"):
            loc = prog.uniformLocation(name)
            if loc < 0:
                raise RuntimeError(f"overlay shader: {name} not found")
            self._overlay_u[name] = loc
        self._overlay_program = prog

        self._overlay_vao = QOpenGLVertexArrayObject()
        self._overlay_vao.create()
        self._overlay_vbo = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
        self._overlay_vbo.create()
        self._overlay_vbo.setUsagePattern(
            QOpenGLBuffer.UsagePattern.DynamicDraw)
        # Allocate the attribute binding once; subsequent draws just
        # re-upload the buffer contents.
        self._overlay_vao.bind()
        try:
            self._overlay_vbo.bind()
            try:
                prog.bind()
                prog.enableAttributeArray(self._overlay_a_world_pos)
                # vec3 floats interleaved, stride = 3 * 4 bytes.
                prog.setAttributeBuffer(
                    self._overlay_a_world_pos, gl.GL_FLOAT, 0, 3, 12)
                prog.release()
            finally:
                self._overlay_vbo.release()
        finally:
            self._overlay_vao.release()

    def _draw_overlay_primitive(self, vertices_np, color_rgba, mode):
        """Upload ``vertices_np`` (Nx3 float32 array of lat, lon, elev_ft)
        and issue one draw call. ``mode`` is a GL primitive type
        (GL_TRIANGLES, GL_LINES, etc.). ``color_rgba`` is a 4-tuple of
        floats in [0, 1].

        Caller must have already bound the overlay program, set its
        per-frame uniforms (aircraft state, viewport), and have the
        FBO active. This method handles only the buffer upload + draw.
        """
        if vertices_np is None or len(vertices_np) == 0:
            return
        if vertices_np.dtype != np.float32:
            vertices_np = vertices_np.astype(np.float32)
        n_floats = vertices_np.size
        n_bytes = n_floats * 4
        self._overlay_vao.bind()
        try:
            self._overlay_vbo.bind()
            try:
                if n_bytes > self._overlay_vbo_capacity:
                    # Allocate a fresh buffer at >= the requested size.
                    self._overlay_vbo.allocate(
                        vertices_np.tobytes(), n_bytes)
                    self._overlay_vbo_capacity = n_bytes
                else:
                    self._overlay_vbo.write(0, vertices_np.tobytes(),
                                            n_bytes)
            finally:
                self._overlay_vbo.release()
            self._overlay_program.setUniformValue(
                self._overlay_u["u_color"],
                float(color_rgba[0]), float(color_rgba[1]),
                float(color_rgba[2]), float(color_rgba[3]))
            gl.glDrawArrays(mode, 0, vertices_np.shape[0])
        finally:
            self._overlay_vao.release()

    def _render_overlays(self, w, h, ac_lat, ac_lon, ac_alt_ft,
                         pitch_deg, roll_deg, heading_deg, pixels_per_deg,
                         range_nm=None):
        """Run every overlay pass that has been migrated to the GPU
        pipeline. Bound after the terrain draw inside the FBO so the
        overlays composite directly with the terrain at full GPU
        speed.

        Phase 1: water polygons (this commit).
        Phase 2+: obstacles, runways, markings, airport flags.
        """
        self._ensure_overlay_program()
        prog = self._overlay_program
        prog.bind()
        try:
            prog.setUniformValue(self._overlay_u["u_ac_lat"],
                                 float(ac_lat))
            prog.setUniformValue(self._overlay_u["u_ac_lon"],
                                 float(ac_lon))
            prog.setUniformValue(self._overlay_u["u_ac_alt_ft"],
                                 float(ac_alt_ft))
            prog.setUniformValue(self._overlay_u["u_heading_deg"],
                                 float(heading_deg))
            prog.setUniformValue(self._overlay_u["u_pitch_deg"],
                                 float(pitch_deg))
            prog.setUniformValue(self._overlay_u["u_roll_deg"],
                                 float(roll_deg))
            prog.setUniformValue(self._overlay_u["u_pixels_per_deg"],
                                 float(pixels_per_deg))
            prog.setUniformValue(self._overlay_u["u_viewport"],
                                 float(w), float(h))

            # Phase 1 — water.
            p = self._parent
            if (getattr(p, "water_db", None) is not None
                    and p.water_db.ready
                    and range_nm is not None):
                with p._perf.time("water"):
                    with p._perf.time("water.collect"):
                        tris = p._collect_water_triangles(
                            ac_lat, ac_lon, range_nm)
                    if tris is not None and tris.size > 0:
                        # COLOR_WATER from svs.py = (20, 80, 150).
                        color = (20 / 255.0, 80 / 255.0,
                                 150 / 255.0, 1.0)
                        with p._perf.time("water.gl_draw"):
                            self._draw_overlay_primitive(
                                tris, color, gl.GL_TRIANGLES)

            # Phase 2 — obstacle poles. Each obstacle = one line
            # segment from base to top; we group by colour (conflict,
            # red-lit, white-lit, unlit) and issue one draw per
            # group. ``glLineWidth`` is honoured by V3D up to ~10 px;
            # 2.0 matches the QPen width the CPU path used.
            if (getattr(p, "obstacle_db", None) is not None
                    and p.obstacle_db.ready
                    and range_nm is not None):
                with p._perf.time("obstacles"):
                    with p._perf.time("obstacles.collect"):
                        groups = p._collect_obstacles(
                            ac_lat, ac_lon, ac_alt_ft, range_nm)
                    if groups:
                        with p._perf.time("obstacles.gl_draw"):
                            gl.glLineWidth(2.0)
                            for color, verts in groups.items():
                                if verts.size == 0:
                                    continue
                                self._draw_overlay_primitive(
                                    verts, color, gl.GL_LINES)
                            gl.glLineWidth(1.0)

            # Phase 3 — runway polygons (the asphalt-coloured quad).
            # One big triangle list across every visible runway, one
            # draw call. Side stripes / threshold bars / designator
            # text still CPU until Phase 4 lands.
            if (getattr(p, "airport_db", None) is not None
                    and p.airport_db.ready
                    and range_nm is not None):
                with p._perf.time("runway.polygon"):
                    with p._perf.time("runway.polygon.collect"):
                        rwy_tris = p._collect_runway_polygons(
                            ac_lat, ac_lon, ac_alt_ft, range_nm)
                    if rwy_tris is not None and rwy_tris.size > 0:
                        # RWY_FILL = (55, 55, 55) asphalt grey.
                        with p._perf.time("runway.polygon.gl_draw"):
                            self._draw_overlay_primitive(
                                rwy_tris,
                                (55/255.0, 55/255.0, 55/255.0, 1.0),
                                gl.GL_TRIANGLES)

            # Smoke-test triangle path (kept for diagnostics).
            if getattr(p, "_gl_overlay_smoketest", False):
                d_deg = 0.1
                test_elev = float(ac_alt_ft) - 2000.0
                tri = np.array([
                    [ac_lat + d_deg, ac_lon,        test_elev],
                    [ac_lat + d_deg, ac_lon + d_deg, test_elev],
                    [ac_lat,         ac_lon + d_deg, test_elev],
                ], dtype=np.float32)
                self._draw_overlay_primitive(
                    tri, (1.0, 0.0, 1.0, 1.0), gl.GL_TRIANGLES)
        finally:
            prog.release()

    def _shader_header(self) -> str:
        """Pick the right #version header for the active context."""
        fmt = self._ctx.format()
        if fmt.renderableType() == QSurfaceFormat.RenderableType.OpenGLES:
            # Pi 5 V3D supports ES 3.0+. precision required on ES.
            return "#version 300 es\nprecision highp float;\n"
        # Desktop GL 3.0 → GLSL 1.30; same in/out syntax, no precision
        # qualifier (it'd be a syntax error on desktop).
        return "#version 130\n"

    def _ensure_program(self):
        if self._program is not None:
            return
        header = self._shader_header()
        vsrc = header + _VERT_BODY
        # Fragment needs explicit precision for ES 3.0; on desktop it's
        # ignored. We add it inside the body's frag header below.
        fheader = header
        if "es" in header:
            # ES requires explicit precision in fragment too.
            fheader = ("#version 300 es\nprecision mediump float;\n"
                       "precision mediump sampler2D;\n")
        fsrc = fheader + _FRAG_BODY
        prog = QOpenGLShaderProgram()
        if not prog.addShaderFromSourceCode(
                QOpenGLShader.ShaderTypeBit.Vertex, vsrc):
            raise RuntimeError(
                f"vertex shader compile failed: {prog.log()}")
        if not prog.addShaderFromSourceCode(
                QOpenGLShader.ShaderTypeBit.Fragment, fsrc):
            raise RuntimeError(
                f"fragment shader compile failed: {prog.log()}")
        if not prog.link():
            raise RuntimeError(f"shader link failed: {prog.log()}")
        self._a_position = prog.attributeLocation("a_t_az")
        if self._a_position < 0:
            raise RuntimeError("a_t_az attribute missing after link")
        for name in ("u_ac_lat", "u_ac_lon", "u_ac_alt_ft", "u_heading_deg",
                     "u_pitch_deg", "u_roll_deg", "u_range_nm",
                     "u_radial_warp", "u_r_min_nm", "u_pixels_per_deg",
                     "u_viewport", "u_heightmap", "u_patch_bounds",
                     "u_green_ft", "u_yellow_ft", "u_near_airport",
                     "u_n_range", "u_n_az", "u_fov_deg",
                     "u_grid_enabled"):
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

        vao.bind()
        try:
            vbo = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
            if not vbo.create():
                raise RuntimeError("could not create vertex buffer")
            vbo.setUsagePattern(QOpenGLBuffer.UsagePattern.StaticDraw)
            vbo.bind()
            vbo.allocate(verts.tobytes(), int(verts.nbytes))

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

    @staticmethod
    def _patch_origin_for(ac_lat: float, ac_lon: float) -> tuple[int, int]:
        """Pick the 2x2-tile patch origin that keeps the aircraft at
        least 0.5 deg (~30 NM) from every edge. With ``floor(x - 0.5)``
        the rebuild happens at HALF-integer degree boundaries (..., -0.5,
        0.5, 1.5, ...); at every boundary the aircraft is 0.5 deg inside
        the new patch on the side it just crossed from, and 1.5 deg from
        the far edge.

        With the old ``floor(x - 1.0)`` the aircraft sat at the patch
        edge just before integer-degree crossings, so the
        ``GL_CLAMP_TO_EDGE`` heightmap sampler painted fake-flat terrain
        ahead of the nose."""
        return (int(math.floor(ac_lat - 0.5)),
                int(math.floor(ac_lon - 0.5)))

    def _ensure_heightmap(self, ac_lat: float, ac_lon: float):
        """(Re)build the heightmap texture when the aircraft crosses
        into a new 2x2-tile patch. See :meth:`_patch_origin_for` for
        the centring choice."""
        origin = self._patch_origin_for(ac_lat, ac_lon)
        start_lat, start_lon = origin
        if (self._heightmap_tex_id is not None
                and self._patch_origin == origin):
            return

        patch = self._build_patch(start_lat, start_lon)
        h, w = patch.shape    # (2402, 2402)

        if self._heightmap_tex_id is None:
            tex_id_arr = gl.glGenTextures(1)
            # PyOpenGL returns either an int or a numpy array of ints
            # depending on count; coerce to int either way.
            self._heightmap_tex_id = int(
                tex_id_arr if np.isscalar(tex_id_arr) else tex_id_arr[0])

        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self._heightmap_tex_id)
        gl.glTexImage2D(
            gl.GL_TEXTURE_2D, 0, gl.GL_R32F,
            w, h, 0,
            gl.GL_RED, gl.GL_FLOAT, patch.tobytes())
        # Linear filtering of float textures requires
        # OES_texture_float_linear on ES; if unavailable the driver
        # will fall back to nearest. Either is fine for Step 4.
        gl.glTexParameteri(gl.GL_TEXTURE_2D,
                           gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR)
        gl.glTexParameteri(gl.GL_TEXTURE_2D,
                           gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR)
        gl.glTexParameteri(gl.GL_TEXTURE_2D,
                           gl.GL_TEXTURE_WRAP_S, gl.GL_CLAMP_TO_EDGE)
        gl.glTexParameteri(gl.GL_TEXTURE_2D,
                           gl.GL_TEXTURE_WRAP_T, gl.GL_CLAMP_TO_EDGE)

        self._patch_origin = origin
        # Bounds: the 2x2 patch covers
        # lat ∈ [start_lat, start_lat + 2], lon ∈ [start_lon, start_lon + 2].
        self._patch_bounds = (
            float(start_lat), float(start_lat + 2),
            float(start_lon), float(start_lon + 2))
        log.info(
            "SVSGLRenderer heightmap built: 2x2 patch from (%d, %d), "
            "shape %dx%d",
            start_lat, start_lon, w, h)

    def _build_patch(self, start_lat: int, start_lon: int) -> np.ndarray:
        """Assemble four 1201x1201 SRTM tiles into a 2402x2402 float32
        elevation array with (0, 0) = SW corner."""
        cache = self._parent.cache
        N = SRTM3_SAMPLES
        patch = np.zeros((_PATCH_PX, _PATCH_PX), dtype=np.float32)
        # Tiles cover lat [start_lat, start_lat+2] (south to north)
        # and lon [start_lon, start_lon+2] (west to east).
        # Each SRTM3 tile has row 0 at the NORTH edge; we flip during
        # placement so the patch ends up with row 0 = SOUTH edge.
        for di in range(_PATCH_TILES):       # 0 = south tile, 1 = north tile
            for dj in range(_PATCH_TILES):   # 0 = west tile,  1 = east tile
                tile = cache.get(start_lat + di, start_lon + dj)
                if tile is None:
                    tile_data = np.zeros((N, N), dtype=np.float32)
                else:
                    # Tile in svs.py is float32; sentinel -9999 is
                    # already replaced with 0 for non-water cells.
                    tile_data = tile.astype(np.float32, copy=False)
                # Flip top-to-bottom so row 0 of the placement = south.
                tile_data = tile_data[::-1, :]
                # Place: northern tile (di=1) goes in upper half (rows
                # N..2N), southern tile (di=0) goes in lower half (0..N).
                # Western tile in left half, eastern in right half.
                row0 = di * N
                col0 = dj * N
                patch[row0:row0 + N, col0:col0 + N] = tile_data
        return patch

    def _build_polar_mesh(self):
        n_r = self._parent._n_range
        n_az = self._parent._n_az
        fov = self._parent._fov_deg

        ts = np.linspace(0.0, 1.0, n_r, dtype=np.float32)
        azs = np.linspace(-fov / 2.0, fov / 2.0, n_az, dtype=np.float32)
        T, Az = np.meshgrid(ts, azs, indexing='ij')
        verts = np.column_stack([T.ravel(), Az.ravel()]).astype(np.float32)

        i_grid, j_grid = np.mgrid[0:n_r - 1, 0:n_az - 1]
        v00 = (i_grid       * n_az + j_grid      ).ravel()
        v10 = ((i_grid + 1) * n_az + j_grid      ).ravel()
        v01 = (i_grid       * n_az + j_grid + 1  ).ravel()
        v11 = ((i_grid + 1) * n_az + j_grid + 1  ).ravel()
        indices = np.empty(v00.size * 6, dtype=np.uint32)
        indices[0::6] = v00
        indices[1::6] = v10
        indices[2::6] = v01
        indices[3::6] = v10
        indices[4::6] = v11
        indices[5::6] = v01

        return verts, indices
