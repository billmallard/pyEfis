#!/usr/bin/env python3
#  SPDX-License-Identifier: GPL-2.0-or-later
"""SVSSHADE1 (AER-6140) design mock-ups: one terrain shading for the SVS
and the moving map, with the clearance-hazard colours laid over it.

For each preview scene this renders the SAME pose two ways:

* SVS view -- a CPU port of the GL terrain fragment shader in
  ``svs_gl.py`` (vertex lighting AMBIENT 0.35 + DIFFUSE 0.65 with the
  shader's sun vector, the alt-scaled exponential haze by 3D slant
  distance, earth curvature, the AER-1973 terrain HFOV pin), drawn with a
  front-to-back heightfield column raster. It is a mock-up of the shading,
  not the GL renderer: no clipmap LOD, no ground texture or fishnet, no
  water polygons, runways, roads or obstacles.
* Map view -- the REAL ``TerrainLayer`` from
  ``pyefis/instruments/map/layers/terrain.py``: its tile sampler, its
  ``_palette`` hypsometric stops and its hillshade. "Today" calls the
  layer's own ``_render`` in relief and caution modes; the candidates
  recolour the layer's own sampled elevations and hillshade.

Candidates (the shading functions below are the whole proposal):

  A  today      SVS: clearance bands everywhere (svs_gl.py main()).
                Map: relief, or caution (amber 100-1000 ft, red < 100 ft).
  B  solid      Shared hypsometric base (the map's _STOPS) lit per view;
                the palette's caution/warning/conflict colours REPLACE the
                base where clearance is under the SVS thresholds, and a
                hazard band is never lit below 0.7 of full sun.
  C  tint       Shared base, muted (50% toward its own luminance) so earth
                tones recede; the hazard colours are mixed over it at
                0.70 / 0.80 / 0.85 so the relief still reads through; the
                same 0.7 lighting floor on hazard bands.

B and C use the SVS thresholds (clearance_green_ft 1000, clearance_yellow_ft
500, conflict below 0) in BOTH views, and the SVS airport-proximity
collapse (5 NM, field elevation + 400 ft) in both views.

Usage:
  LD_LIBRARY_PATH=<qt libs> PYTHONPATH=src python3 tools/svs_shading_mockups.py \\
      --tiles <TERRAIN_ROOT with N39/N39W107.hgt ...> --out docs/images/svs_shading
"""

import argparse
import json
import math
import os
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from pyefis.instruments.map.layers import terrain as map_terrain

DEG = 180.0 / math.pi
FT_PER_M = 3.28084
M_PER_DEG_LAT = 111320.0
EARTH_CURV = 1.0 / (2.0 * 6371000.0)

# svs.py stock "clearance" palette (_PALETTES) as 0..1
PAL = {
    "safe": (0 / 255, 100 / 255, 0 / 255),
    "caution": (180 / 255, 130 / 255, 0 / 255),
    "warning": (200 / 255, 40 / 255, 0 / 255),
    "conflict": (180 / 255, 0 / 255, 180 / 255),
    "water": (20 / 255, 80 / 255, 150 / 255),
}
SAFE_LOW = (0.50, 0.46, 0.22)          # svs_gl.py COLOR_SAFE_LOW
HAZE = (0.65, 0.77, 0.90)              # svs_gl.py HAZE_COLOR
MAP_WATER = (60 / 255, 110 / 255, 160 / 255)
GREEN_FT, YELLOW_FT = 1000.0, 500.0    # svs.py defaults
GATE_AGL_FT, PROX_NM = 400.0, 5.0      # svs.py defaults

# Preview scenes: poses from tools/export_svs_preview_patch.py SCENES.
# The nearest airport (proximity collapse) is resolved there from the
# NASR pack at export time; here it is written out (NASR cycle 2611 ARP
# and field elevation of the named airport; svs.py takes the NEAREST record
# in range, which can be a heliport a few hundred feet higher).
SCENES = {
    "mountains": {"lat": 39.20, "lon": -106.85, "alt_ft": 12500.0,
                  "head": 150.0, "apt": ("KASE", 39.22188, -106.86823, 7837.9)},
    "approach": {"lat": 37.96933, "lon": -107.98168, "alt_ft": 10500.0,
                 "head": 105.0, "apt": ("KTEX", 37.95381, -107.90875, 9069.7)},
    "final": {"lat": 34.42721, "lon": -119.87481, "alt_ft": 611.0,
              "head": 89.0, "apt": ("KSBA", 34.42619, -119.84149, 13.5)},
    "coastal": {"lat": 34.4275, "lon": -119.8546, "alt_ft": 2500.0,
                "head": 0.0, "apt": ("KSBA", 34.42619, -119.84149, 13.5)},
}


# --------------------------------------------------------------------------
# elevation sampling (GLO-30, 3601^2 big-endian, bilinear)
# --------------------------------------------------------------------------
class Tiles:
    def __init__(self, root):
        self.root = root
        self.t = {}

    def _tile(self, la, lo):
        if (la, lo) not in self.t:
            name = "N%02dW%03d" % (la, -lo)
            p = os.path.join(self.root, "N%02d" % la, name + ".hgt")
            a = np.fromfile(p, dtype=">i2")
            side = int(round(math.sqrt(a.size)))
            self.t[(la, lo)] = a.reshape(side, side).astype(np.float32)
        return self.t[(la, lo)]

    def elev_m(self, lat, lon):
        lat = np.asarray(lat, np.float64)
        lon = np.asarray(lon, np.float64)
        out = np.zeros(lat.shape, np.float32)
        la = np.floor(lat).astype(int)
        lo = np.floor(lon).astype(int)
        for key in set(zip(la.ravel().tolist(), lo.ravel().tolist())):
            sel = (la == key[0]) & (lo == key[1])
            t = self._tile(*key)
            n = t.shape[0] - 1
            r = (key[0] + 1 - lat[sel]) * n
            c = (lon[sel] - key[1]) * n
            r0 = np.clip(np.floor(r).astype(int), 0, n - 1)
            c0 = np.clip(np.floor(c).astype(int), 0, n - 1)
            fr, fc = r - r0, c - c0
            v = (t[r0, c0] * (1 - fr) * (1 - fc) + t[r0, c0 + 1] * (1 - fr) * fc
                 + t[r0 + 1, c0] * fr * (1 - fc) + t[r0 + 1, c0 + 1] * fr * fc)
            out[sel] = v
        return out


# --------------------------------------------------------------------------
# shading candidates
# --------------------------------------------------------------------------
def hyps(elev_ft):
    """The map's hypsometric palette (its real _palette), 0..1."""
    r, g, b = map_terrain._palette(np.asarray(elev_ft, np.float64))
    return np.stack([r, g, b], -1) / 255.0


def _bands(clear_ft, collapse):
    conflict = clear_ft < 0.0
    hazard_ok = ~collapse
    warning = hazard_ok & ~conflict & (clear_ft < YELLOW_FT)
    caution = hazard_ok & ~conflict & ~warning & (clear_ft < GREEN_FT)
    return conflict, warning, caution


def shade_today_svs(elev_ft, clear_ft, collapse):
    """svs_gl.py fragment main(), palette 'clearance', safe_gradient on."""
    out = np.empty(elev_ft.shape + (3,), np.float32)
    t = np.clip((clear_ft - GREEN_FT) / 2500.0, 0, 1)[..., None]
    out[:] = np.array(SAFE_LOW) * (1 - t) + np.array(PAL["safe"]) * t
    conflict, warning, caution = _bands(clear_ft, collapse)
    out[collapse & ~conflict] = PAL["safe"]
    out[caution] = PAL["caution"]
    out[warning] = PAL["warning"]
    out[conflict] = PAL["conflict"]
    return out


def shade_solid(elev_ft, clear_ft, collapse):
    out = hyps(elev_ft).astype(np.float32)
    conflict, warning, caution = _bands(clear_ft, collapse)
    out[caution] = PAL["caution"]
    out[warning] = PAL["warning"]
    out[conflict] = PAL["conflict"]
    return out


def _mute(rgb, k=0.5):
    lum = (rgb * np.array([0.299, 0.587, 0.114])).sum(-1, keepdims=True)
    return rgb * (1 - k) + lum * k


def shade_tint(elev_ft, clear_ft, collapse):
    out = _mute(hyps(elev_ft)).astype(np.float32)
    conflict, warning, caution = _bands(clear_ft, collapse)
    for m, key, a in ((caution, "caution", 0.70), (warning, "warning", 0.80),
                      (conflict, "conflict", 0.85)):
        out[m] = out[m] * (1 - a) + np.array(PAL[key]) * a
    return out


def hazard_mask(clear_ft, collapse):
    conflict, warning, caution = _bands(clear_ft, collapse)
    return conflict | warning | caution


# (key, name, shading, hazard lighting floor). The floor keeps a hazard
# band from being darkened below that fraction of full sun on slopes facing
# away from the light (the base still goes down to AMBIENT 0.35), so an
# amber slope in shadow cannot sink into a tan or olive base colour. 0 =
# today's behaviour (hazard lit exactly like the base).
CANDIDATES = [
    ("A", "today", shade_today_svs, 0.0),
    ("B", "solid", shade_solid, 0.7),
    ("C", "tint", shade_tint, 0.7),
]


# --------------------------------------------------------------------------
# SVS view (CPU port of the shader, front-to-back heightfield columns)
# --------------------------------------------------------------------------
def render_svs(tiles, sc, shade, floor=0.0, W=800, H=480, pitch_deg_shown=40.0,
               hfov_pitch_deg=30.0):
    lat0, lon0, alt_ft, head = sc["lat"], sc["lon"], sc["alt_ft"], sc["head"]
    ac_u = alt_ft / FT_PER_M
    ppd_v = H / pitch_deg_shown
    ppd_h = H / hfov_pitch_deg
    cx, cy = W / 2.0, H / 2.0
    lat_cos = math.cos(math.radians(lat0))
    ch, sh = math.cos(math.radians(head)), math.sin(math.radians(head))

    tcol = ((np.arange(W) + 0.5 - cx) / (DEG * ppd_h))[None, :]   # right/fwd
    f = 40.0 * 1.0035 ** np.arange(0, 2600)
    f = f[f < 160000.0][:, None]                                  # fwd metres
    right = tcol * f
    e = ch * right + sh * f
    n = -sh * right + ch * f
    lat = lat0 + n / M_PER_DEG_LAT
    lon = lon0 + e / (M_PER_DEG_LAT * lat_cos)
    elev_m = tiles.elev_m(lat, lon)
    water = elev_m <= 0.0                       # GLO-30 ocean is literal 0
    elev_m = np.where(water, 0.0, elev_m)

    # Normal from finite differences (shader: SLOPE_EXAG 1, sun -1,1,2).
    d = 60.0
    eE = tiles.elev_m(lat, lon + d / (M_PER_DEG_LAT * lat_cos))
    eN = tiles.elev_m(lat + d / M_PER_DEG_LAT, lon)
    eE = np.where(eE <= 0, 0.0, eE)
    eN = np.where(eN <= 0, 0.0, eN)
    dE, dN = (eE - elev_m) / d, (eN - elev_m) / d
    mag = np.sqrt(dE * dE + dN * dN + 1.0)
    sun = np.array([-1.0, 1.0, 2.0]) / math.sqrt(6.0)
    diff = np.clip((-dE * sun[0] - dN * sun[1] + sun[2]) / mag, 0, 1)
    inten = 0.35 + 0.65 * diff

    horiz = np.hypot(right, f)
    drop = horiz * horiz * EARTH_CURV
    y = cy - (elev_m - drop - ac_u) / f * DEG * ppd_v
    slant = np.sqrt(horiz ** 2 + (elev_m - ac_u) ** 2)

    elev_ft = elev_m * FT_PER_M
    clear_ft = alt_ft - elev_ft
    collapse = _collapse(sc, lat, lon, elev_ft)
    rgb = shade(elev_ft, clear_ft, collapse)
    rgb[water] = PAL["water"]
    inten = np.where(hazard_mask(clear_ft, collapse),
                     np.maximum(inten, floor), inten)
    rgb = rgb * np.where(water, 1.0, inten)[..., None]
    haze_nm = min(max(40.0, 0.9 * 1.22 * math.sqrt(alt_ft)), 200.0)
    fog = (1.0 - np.exp(-slant / (haze_nm * 1852.0)))[..., None]
    rgb = rgb * (1 - fog) + np.array(HAZE) * fog

    img = np.zeros((H, W, 3), np.float32)
    rows = np.arange(H)
    top = np.array([0, 51, 102]) / 255.0
    hor = np.array([51, 153, 255]) / 255.0
    for i in range(W):
        cm = np.minimum.accumulate(y[:, i])
        k = np.searchsorted(-cm, -rows, side="left")   # first cm <= row
        sky = k >= cm.size
        kk = np.minimum(k, cm.size - 1)
        img[:, i] = rgb[kk, i]
        tsky = np.clip(rows / cy, 0, 1)[:, None]
        img[sky, i] = (top * (1 - tsky) + hor * tsky)[sky]
    return (np.clip(img, 0, 1) * 255).astype(np.uint8)


def _collapse(sc, lat, lon, elev_ft):
    """svs.py near_airport + airport_gate_agl_ft: inside PROX_NM of the
    airport, terrain below field elevation + 400 ft loses its bands."""
    _, alat, alon, aelev = sc["apt"]
    dn = (sc["lat"] - alat) * 60.0
    de = (sc["lon"] - alon) * 60.0 * math.cos(math.radians(alat))
    if math.hypot(dn, de) > PROX_NM:
        return np.zeros(elev_ft.shape, bool)
    return elev_ft < aelev + GATE_AGL_FT


# --------------------------------------------------------------------------
# map view (real TerrainLayer)
# --------------------------------------------------------------------------
class _Owner:
    def __init__(self, tile_path, mode):
        self.tile_path = tile_path
        self.terrain_mode = mode
        self.map_style = "standard"


def _layer(tiles_root, mode, alt_ft):
    lay = map_terrain.TerrainLayer()
    lay.configure(_Owner(tiles_root, mode))
    lay._alt_ft = alt_ft
    return lay


def _qimage_to_np(qimg):
    qimg = qimg.convertToFormat(qimg.Format.Format_RGBX8888)
    ptr = qimg.constBits()
    ptr.setsize(qimg.sizeInBytes())
    a = np.frombuffer(ptr, np.uint8).reshape(qimg.height(),
                                             qimg.bytesPerLine() // 4, 4)
    return a[:, :qimg.width(), :3].copy()


def render_map(tiles_root, sc, shade=None, floor=0.0, mode="relief",
               size=480,
               range_nm=15.0):
    """Track-up map image, ownship centred, *range_nm* to the edge."""
    lay = _layer(tiles_root, mode, sc["alt_ft"])
    job = (None, sc["lat"], sc["lon"], range_nm, size, size, size / 2.0)
    if shade is None:
        qimg, _meta = lay._render(job)
        img = _qimage_to_np(qimg)
    else:
        nn, mpp, lat_cos, lats, lons = lay._window(job)
        elev_m, water, _hit = lay._sample_window(sc["lat"], sc["lon"], mpp,
                                                 lats, lons)
        elev_ft = elev_m * FT_PER_M
        lat_g = np.repeat(lats[:, None], nn, 1)
        lon_g = np.repeat(lons[None, :], nn, 0)
        coll = _collapse(sc, lat_g, lon_g, elev_ft)
        rgb = shade(elev_ft, sc["alt_ft"] - elev_ft, coll)
        # the layer's own hillshade expression
        gy, gx = np.gradient(elev_m, mpp)
        hs = 0.75 + 0.25 * np.clip(
            (-gx + gy) / np.maximum(1e-3, np.hypot(gx, gy) + 8.0) + 0.5, 0, 1)
        hs = np.where(hazard_mask(sc["alt_ft"] - elev_ft, coll),
                      np.maximum(hs, floor), hs)
        rgb = rgb * hs[..., None]
        rgb[water] = MAP_WATER
        img = (np.clip(rgb, 0, 1) * 255).astype(np.uint8)
    pil = Image.fromarray(img).rotate(sc["head"], resample=Image.BILINEAR)
    w, h = pil.size
    pil = pil.crop(((w - size) // 2, (h - size) // 2,
                    (w + size) // 2, (h + size) // 2))
    _decorate_map(pil, size)
    return pil


def _decorate_map(pil, size):
    d = ImageDraw.Draw(pil)
    c = size / 2.0
    half = math.radians(25.0)                  # 800x480 panel: 50 deg HFOV
    for s in (-1, 1):
        d.line([(c, c), (c + s * c * math.sin(half),
                         c - c * math.cos(half))], fill=(255, 255, 255), width=1)
    for r in (c / 3, 2 * c / 3):
        d.ellipse([c - r, c - r, c + r, c + r], outline=(230, 230, 230))
    d.polygon([(c, c - 11), (c - 7, c + 8), (c + 7, c + 8)],
              fill=(255, 255, 255), outline=(0, 0, 0))


# --------------------------------------------------------------------------
# colour separation: how far each hazard colour sits from the base
# --------------------------------------------------------------------------
def _lab(rgb):
    rgb = np.asarray(rgb, np.float64)
    lin = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    m = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722],
                  [0.0193, 0.1192, 0.9505]])
    xyz = lin @ m.T / np.array([0.95047, 1.0, 1.08883])
    fx = np.where(xyz > 216 / 24389, np.cbrt(xyz), (24389 / 27 * xyz + 16) / 116)
    return np.stack([116 * fx[..., 1] - 16, 500 * (fx[..., 0] - fx[..., 1]),
                     200 * (fx[..., 1] - fx[..., 2])], -1)


def separation_table():
    """Minimum CIE76 delta-E between each hazard band and ANY colour the
    candidate paints on unhazarded terrain (0-14,000 ft), over every
    lighting level the SVS shader produces (AMBIENT 0.35 to full sun 1.0)
    on both sides -- so an amber slope in shadow is compared with a sunlit
    tan slope too. The hazard side uses the candidate's lighting floor, and
    "no_floor" shows the same candidate without it. Under about 10 is easy
    to confuse at a glance; over about 25 is clearly another colour."""
    elevs = np.arange(0, 14001, 100.0)
    lits = np.linspace(0.35, 1.0, 14)
    none = np.zeros(elevs.shape, bool)

    def lit_set(rgb, fl):
        return np.concatenate([rgb * max(l, fl) for l in lits])

    rows = {}
    for key, name, fn, floor in CANDIDATES:
        if name == "today":
            # every non-hazard colour today: the safe gradient
            base = shade_today_svs(elevs * 0, np.linspace(GREEN_FT, 6000,
                                                          elevs.size), none)
        else:
            base = fn(elevs, np.full(elevs.shape, 1e5), none)
        base_lab = _lab(lit_set(base, 0.0))
        rows[name] = {"floor": floor}
        for band, clr in (("caution", 600.0), ("warning", 200.0),
                          ("conflict", -100.0)):
            hz = fn(elevs, np.full(elevs.shape, clr), none)
            out = {}
            for label, fl in (("with_floor", floor), ("no_floor", 0.0)):
                de = np.linalg.norm(_lab(lit_set(hz, fl))[:, None, :]
                                    - base_lab[None, :, :], axis=-1)
                out[label] = round(float(de.min()), 1)
            rows[name][band] = out
    return rows


# --------------------------------------------------------------------------
def _label(img, text):
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 18)
    except OSError:
        font = ImageFont.load_default()
    d.rectangle([0, 0, 8 + 11 * len(text), 26], fill=(0, 0, 0))
    d.text((5, 3), text, fill=(255, 255, 255), font=font)
    return img


# AER-1203's on-device GL capture (svs_capture.py, Beelink, 2026-09-06,
# commit 261bbef) of the coastal pose. That build coupled the terrain HFOV
# to pitchDegreesShown 30, so the port renders it at 30/30 to match.
VALIDATION_POSE = {"lat": 34.4234216, "lon": -119.8544276, "alt_ft": 2500.0,
                   "head": 356.0, "apt": ("KSBA", 34.42619, -119.84149, 13.5)}
VALIDATION_REAL = os.path.join(
    "docs", "images", "aer1203_svs_water_los_coastal",
    "after_frame0000_water_los_masked.png")


def validate_port(tiles, out):
    """Top: the real GL frame. Bottom: this port, today's shading, same
    pose, same 1920x1080 frame, both shown at half size."""
    port = render_svs(tiles, VALIDATION_POSE, shade_today_svs, 0.0,
                      W=1920, H=1080, pitch_deg_shown=30.0)
    real = Image.open(VALIDATION_REAL).convert("RGB").resize((960, 540))
    port = Image.fromarray(port).resize((960, 540))
    sheet = Image.new("RGB", (960, 1088), (40, 40, 40))
    sheet.paste(_label(real, "real GL capture (AER-1203)"), (0, 0))
    sheet.paste(_label(port, "CPU port, today"), (0, 548))
    sheet.save(os.path.join(out, "port_validation_coastal.png"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tiles", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--scene", choices=list(SCENES))
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    tiles = Tiles(args.tiles)
    validate_port(tiles, args.out)
    try:
        rev = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"],
                                      text=True).strip()
    except Exception:
        rev = "unknown"
    meta = {"pyefis_rev": rev, "scenes": {}, "separation": separation_table()}
    for name in ([args.scene] if args.scene else list(SCENES)):
        sc = SCENES[name]
        meta["scenes"][name] = sc
        rows = []
        for key, cname, fn, floor in CANDIDATES:
            svs = Image.fromarray(render_svs(tiles, sc, fn, floor))
            if cname == "today":
                mp = render_map(args.tiles, sc, mode="caution")
            else:
                mp = render_map(args.tiles, sc, shade=fn, floor=floor)
            _label(svs, "%s %s - SVS" % (key, cname))
            _label(mp, "%s %s - map" % (key, cname
                                        if cname != "today" else "today (caution)"))
            rows.append((svs, mp))
        relief = render_map(args.tiles, sc, mode="relief")
        relief.save(os.path.join(args.out, "%s_A_today_map_relief.png" % name))
        sheet = Image.new("RGB", (800 + 480 + 8, len(rows) * (480 + 8) - 8),
                          (40, 40, 40))
        for i, (svs, mp) in enumerate(rows):
            sheet.paste(svs, (0, i * 488))
            sheet.paste(mp, (808, i * 488))
        sheet.save(os.path.join(args.out, "%s_sheet.png" % name))
    with open(os.path.join(args.out, "mockups.json"), "w") as fh:
        json.dump(meta, fh, indent=1)
    print(json.dumps(meta["separation"], indent=1))


if __name__ == "__main__":
    sys.exit(main())
