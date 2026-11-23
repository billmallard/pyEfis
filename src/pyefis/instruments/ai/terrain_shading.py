#  SPDX-License-Identifier: GPL-2.0-or-later
"""One terrain shading rule for the SVS and the moving map (SVSSHADE2).

Design: docs/svs_terrain_shading_brief.md, candidate B (Bill, AER-6140,
2026-11-21). Both views paint the same hypsometric *base* -- the map's
sectional-style colours by elevation -- under their own lighting, and the
same *hazard bands* over it where clearance is low:

- conflict (magenta) where terrain is above ownship;
- warning (red) under ``clearance_yellow_ft``;
- caution (amber) under ``clearance_green_ft``;
- none on the runway environment: within ``airport_proximity_nm`` of an
  airport, terrain below field elevation + ``airport_gate_agl_ft`` gets no
  band (issue #32 Option B). Conflict still wins there.

A hazard band is never lit below ``HAZARD_LIGHT_FLOOR`` of full sun, so an
amber slope in shadow cannot sink into a sunlit tan one (the brief's
colour-separation table).

Everything here is plain Python + numpy (no Qt), so the map worker, the
GL renderer and the tests all read the same numbers. The GLSL in
``svs_gl.py`` is generated from these constants (``glsl_constants``).
"""

import numpy as np

# --- thresholds (ft of clearance below ownship) ----------------------------
# The SVS numbers, adopted by the map too (Bill, AER-6140). One pair: the SVS
# config defaults, the map attribute defaults and both editor Props read it.
CLEARANCE_GREEN_FT = 1000.0
CLEARANCE_YELLOW_FT = 500.0
AIRPORT_PROXIMITY_NM = 5.0
AIRPORT_GATE_AGL_FT = 400.0

# Lighting floor on hazard bands only. The base still goes down to the SVS
# ambient (0.35); the map's hillshade never goes below 0.75, so the floor is
# a no-op there but is applied by the same rule.
HAZARD_LIGHT_FLOOR = 0.7

# Band indices, shared by the numpy rule and the GLSL terrain_band().
BAND_NONE = 0
BAND_CAUTION = 1
BAND_WARNING = 2
BAND_CONFLICT = 3

# Gate used when ownship is near an airport whose record has no elevation:
# collapse everything below it (the pre-#32 two-colour scheme).
NO_FIELD_ELEV_GATE_FT = 1.0e9

# --- the base: hypsometric stops (elevation ft, r, g, b) -------------------
# Sectional-inspired; moved here from map/layers/terrain.py unchanged.
HYPSO_STOPS = (
    (-1000, 60, 110, 160),      # water sentinel band
    (0,     92, 130,  82),
    (1000, 110, 145,  88),
    (2000, 150, 160,  95),
    (4000, 185, 160, 100),
    (7000, 170, 130,  90),
    (10000, 160, 120, 105),
    (14000, 235, 235, 235),
)

_STOP_E = np.array([s[0] for s in HYPSO_STOPS], np.float64)
_STOP_R = np.array([s[1] for s in HYPSO_STOPS], np.float64)
_STOP_G = np.array([s[2] for s in HYPSO_STOPS], np.float64)
_STOP_B = np.array([s[3] for s in HYPSO_STOPS], np.float64)

# --- palettes: band colours (safe, caution, warning, conflict, water) ------
# The `palette` option (G69, issue #394). "clearance" is the stock scheme.
# `safe` only paints terrain under `terrain_shading: clearance`; the relief
# base replaces it. The map reads caution/warning/conflict from here too.
PALETTES = {
    "clearance": ((0, 100, 0), (180, 130, 0), (200, 40, 0), (180, 0, 180),
                  (20, 80, 150)),
    "subdued": ((20, 70, 25), (120, 95, 15), (140, 45, 15), (150, 0, 150),
                (25, 60, 105)),
    "high_contrast": ((0, 170, 0), (245, 190, 0), (235, 35, 0),
                      (230, 0, 230), (0, 120, 215)),
}
DEFAULT_PALETTE = "clearance"

# `terrain_shading` option values. relief is the default (candidate B);
# clearance is the all-over clearance colouring from before SVSSHADE2.
SHADINGS = ("relief", "clearance")
DEFAULT_SHADING = "relief"


def palette_rgb(name):
    """The five band colours of palette *name*; unknown names are stock."""
    return PALETTES.get(str(name or "").lower(), PALETTES[DEFAULT_PALETTE])


def shading_mode(name):
    """Normalise a `terrain_shading` value; anything unknown is relief."""
    s = str(name or "").lower()
    return s if s in SHADINGS else DEFAULT_SHADING


def hypso_rgb(elev_ft):
    """Vectorised hypsometric colour (0..255 float32 r, g, b) for elevation
    in FEET: piecewise-linear over HYPSO_STOPS, clamped at the end stops
    (np.interp -- one C pass per channel, #89)."""
    elev_ft = np.asarray(elev_ft, dtype=np.float64)
    e = elev_ft.ravel()
    shape = elev_ft.shape
    r = np.interp(e, _STOP_E, _STOP_R).astype(np.float32).reshape(shape)
    g = np.interp(e, _STOP_E, _STOP_G).astype(np.float32).reshape(shape)
    b = np.interp(e, _STOP_E, _STOP_B).astype(np.float32).reshape(shape)
    return r, g, b


def band(clearance_ft, elev_ft, gate_ft=None,
         green_ft=CLEARANCE_GREEN_FT, yellow_ft=CLEARANCE_YELLOW_FT):
    """The hazard band (BAND_*) per sample, vectorised.

    *clearance_ft* is ownship altitude minus terrain elevation; *elev_ft*
    the terrain elevation (MSL). *gate_ft* is the airport-collapse gate
    (``collapse_gate_ft``) or None when ownship is not near an airport.
    Same order as the GLSL terrain_band(): conflict, airport collapse,
    warning, caution."""
    clr = np.asarray(clearance_ft, dtype=np.float64)
    elev = np.asarray(elev_ft, dtype=np.float64)
    out = np.full(np.broadcast(clr, elev).shape, BAND_NONE, np.int8)
    out[clr < green_ft] = BAND_CAUTION
    out[clr < yellow_ft] = BAND_WARNING
    if gate_ft is not None:
        out[(elev < gate_ft) & (clr >= 0.0)] = BAND_NONE
    out[clr < 0.0] = BAND_CONFLICT
    return out


def hazard_light(bands, light):
    """Apply HAZARD_LIGHT_FLOOR to *light* wherever a band is painted."""
    light = np.asarray(light, dtype=np.float64)
    return np.where(np.asarray(bands) > BAND_NONE,
                    np.maximum(light, HAZARD_LIGHT_FLOOR), light)


def nearest_field(airport_db, lat, lon, proximity_nm=AIRPORT_PROXIMITY_NM):
    """``(near, field_elev_ft)``: whether any airport in *airport_db* lies
    within *proximity_nm* of (lat, lon), and the elevation of the nearest
    one that has an elevation (None if none does). Both views take the
    collapse gate from this."""
    if (proximity_nm <= 0.0 or airport_db is None
            or not getattr(airport_db, "ready", False)):
        return False, None
    hit = False
    best_elev = None
    best_d2 = None
    for ap in airport_db.airports_in_range(lat, lon, proximity_nm):
        hit = True
        ap_lat = getattr(ap, "ref_lat", None)
        ap_lon = getattr(ap, "ref_lon", None)
        elev = getattr(ap, "elev_ft", None)
        if elev is None:
            continue
        if ap_lat is None or ap_lon is None:
            d2 = 0.0
        else:
            d2 = (ap_lat - lat) ** 2 + (ap_lon - lon) ** 2
        if best_d2 is None or d2 < best_d2:
            best_d2 = d2
            best_elev = float(elev)
    return hit, (best_elev if hit else None)


def collapse_gate_ft(near, field_elev_ft, gate_agl_ft=AIRPORT_GATE_AGL_FT):
    """The MSL elevation below which terrain gets no band, or None when
    ownship is not near an airport."""
    if not near:
        return None
    if field_elev_ft is None:
        return NO_FIELD_ELEV_GATE_FT
    return float(field_elev_ft) + float(gate_agl_ft)


def glsl_constants():
    """GLSL constant declarations generated from this module, prepended to
    the SVS terrain fragment shader: the band indices, the hazard lighting
    floor and the hypsometric stops (colours in 0..1)."""
    rows = ",\n    ".join(
        "vec4(%.1f, %.6f, %.6f, %.6f)" % (e, r / 255.0, g / 255.0, b / 255.0)
        for e, r, g, b in HYPSO_STOPS)
    return (
        "const int BAND_NONE = %d;\n"
        "const int BAND_CAUTION = %d;\n"
        "const int BAND_WARNING = %d;\n"
        "const int BAND_CONFLICT = %d;\n"
        "const float HAZARD_LIGHT_FLOOR = %r;\n"
        "const int HYPSO_N = %d;\n"
        "const vec4 HYPSO[%d] = vec4[%d](\n    %s);\n"
        % (BAND_NONE, BAND_CAUTION, BAND_WARNING, BAND_CONFLICT,
           float(HAZARD_LIGHT_FLOOR), len(HYPSO_STOPS), len(HYPSO_STOPS),
           len(HYPSO_STOPS), rows))
