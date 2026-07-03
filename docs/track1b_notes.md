# Track 1b — per-level heightmap textures (working notes)

Branch: `track1b-per-level-heightmap-textures` (off display-changes @ cdcf917).
Session notes so any future session can resume cold. Update the STATE section
as increments land.

## Goal

Replace the single 2°x2° decimated heightmap texture with one small texture
per clipmap level, resolution matched to the level's vertex spacing:
native-resolution data under the aircraft, real data (not edge-clamp smear)
out to the horizon at altitude, and no more monolithic ~50 MB texture upload
at half-degree crossings.

## Key facts recon'd from the code (verify if resuming much later)

- `clipmap_cells = 64`, `clipmap_levels = 7` (svs.py config, `_clip_cells`).
  Level k spacing = `base_m * 2**k`; level origin snapped to its own spacing:
  `ox = floor(ac_e/spacing)*spacing - half`, `half = cells/2 * spacing`
  (draw loop ~svs_gl.py:860).
- ENU frame: origin = `_patch_origin` (integer-degree SW corner,
  `floor(ac - 0.5)`), east = `(lon-o_lon)*M_PER_DEG_LAT*lat_cos`,
  north = `(lat-o_lat)*M_PER_DEG_LAT`, with **lat_cos = cos(ac_lat) per
  frame** (drifts slowly; same convention as today's UV mapping — accept it,
  the noise anchoring via u_tex_xform already compensates separately).
  Inverse (texture build): `lon = o_lon + e/(M_PER_DEG_LAT*lat_cos)`,
  `lat = o_lat + n/M_PER_DEG_LAT`.
- `parent._sample_elevations(lat_grid, lon_grid) -> (elev_m, is_water)`,
  vectorised over TileCache, elev clamped >=0 where water; write the texture
  as `where(is_water, -9999.0, elev)` — shader WATER_THR_M = -1000 handles it.
- `base_m` is currently derived from `_patch_texels` (the big texture).
  Replace with native tile resolution: query cache tiles around the aircraft
  for max N (like `_build_patch` does), `base_m = M_PER_DEG_LAT/(N-1)`.
  GLO-30: 30.9 m (native! the whole point); SRTM3: 92.8 m (same as today).
- KEEP the `_patch_origin` / half-degree ENU rebase machinery (overlays,
  camera, tex_xform, frame_key caches all key off it) — only the giant
  texture build/upload goes away. On patch-origin change all level textures
  rebuild (cheap: 7 x 67^2 samples).
- Morph band (cdcf917) samples the NEXT-COARSER surface: with per-level
  textures this must read the coarser level's TEXTURE -> second sampler
  `u_heightmap_coarse` on unit 1 with its own origin/spacing/size uniforms.
  Outermost level: u_morph_on=0 (already).
- Texture size per level: cells+3 = 67 texels/side (65 mesh vertices +1
  guard texel each side for the slope finite-difference and morph corner
  fetches). Texel i at ENU `tex_origin + i*spacing`, tex_origin =
  level_origin - spacing (one guard cell SW). R32F, GL_LINEAR (vertices land
  exactly on texel centers; morph corner fetches too).
- UV mapping (edge-inclusive, texel-centred — same form as the patch fix):
  `uv = ((exy - u_hm_origin)/u_hm_spacing + 0.5) / u_hm_size`.
- Slope shading texel step becomes the LEVEL texel (1/u_hm_size), metres
  step = u_hm_spacing — resolution-matched shading per ring (improvement).

## Increment plan (commit after each; STATE below tracks progress)

1. CPU side: `_level_height_array()` pure function + per-level texture cache
   keyed (level, snapped_origin, patch_origin). Unit tests without GL:
   world-anchored stability across snaps, sentinel, guard band geometry.
2. Shader: per-level height sampling + coarse sampler for the morph band;
   draw loop binds/uploads per level; delete `_build_patch`/big texture
   (keep origin bookkeeping + `_patch_texels`-independent base_m).
3. Local GL validation (Windows GPU, SRTM3): (a) mountains pose looks
   equivalent to display-changes; (b) far-field: ALT 30000 RANGE 120 —
   old = edge-clamp smear beyond the 2° patch, new = real ranges.
4. Perf: log rebuild timings; verify rebuilds happen only on level snaps /
   patch rebase, never steady-state per frame.
5. Pi deploy ONLY after Bill approves (do not patch mid-flight; this is a
   renderer rewrite — branch stays off the Pi until validated locally).

## STATE (update as you go)

- [x] Branch created, notes committed.
- [x] Increment 1 — CPU builder + tests (see git log; 4 tests in tests/instruments/ai/test_track1b.py incl. bit-identity across snaps).
- [x] Increment 2 — shader + GL plumbing (per-level samplers, coarse
      sampler for the morph band, two-pass draw loop).
- [x] Increment 3 — mountains-pose parity vs old: mean|dL| 0.5 (identical);
      FL300 renders clean. Mid-field shading is now resolution-proportional
      (ring-matched) instead of constant-frequency -- visually smoother far
      out; _TEXELS_PER_CELL is the dial if Bill wants more far relief.
- [x] Increment 4 — clamp sampling to the 2x2 patch (coarsest ring was
      touching dozens of tiles: 1 s rebuild -> 17 ms) + 8-cell anchor grid
      (inner level rebuilds every ~250 m of travel, not every ~31 m). All
      levels 15-26 ms per rebuild on the dev box; async worker is the
      escape hatch if the Pi shows hitches.
- [x] Increment 5a — FIRST Pi flight test FAILED ("massive entire frame
      shifts"): (1) synchronous rebuilds stalled the Pi render thread,
      (2) lat_cos snap-back -- textures BAKE the east-scale at build time,
      so accumulated drift released as a whole-ring sideways JUMP at each
      rebuild (outer rings: hundreds of metres). Fixed by the async worker
      (svs-level-tex thread, latest-wins per level, GL thread only
      uploads; sync build only at startup/frame-rebase) + drift-bounded
      refresh (_drift_exceeded: rebuild when accumulated shift would
      exceed HALF A TEXEL at the texture's east extent -- snap-backs stay
      sub-texel) + clipmap_base_m config knob (0=native) for flight A/B
      of resolution vs cadence. 25 s sim-motion soak clean on the dev GPU.
- [ ] Increment 5b — Pi flight re-validation, then merge to
      display-changes + delete _build_patch dead code.

## NEXT SESSION OPENER: the ridge-crest sawtooth ("jagged edge")

Bill's long-standing "jagged edge" artifact -- reproduced locally at the
live X-Plane pose (35.862022, -82.440437, 8004 ft, hdg 110.73, pitch 3.77,
roll 2.60 -- Black Mountains near Mt. Mitchell; scratchpad mitchell_*.png):
evenly-spaced dark triangular teeth along ridge crests, glaring on a 21.5in
panel. A/B results (all at that pose):
- central-difference normals: teeth unchanged (shipped anyway, correct fix
  for shading symmetry);
- morph band OFF: teeth REDUCED but present -- the band amplifies crest
  notching (odd vertices mid-blend pull toward the coarse average, far
  below a knife-edge crest) but is not the root cause;
- _TEXELS_PER_CELL 2 -> 4: unchanged => NOT texture aliasing.
CONCLUSION: mesh geometry -- the clipmap index template splits every quad
along the SAME diagonal; crests running against the grain get alternate
triangles chopped = coherent sawtooth. Predates Track 1b (June clipmap).
FIX PLAN: alternate the split diagonal per quad parity (checkerboard) in
_build_clipmap_template (both the full grid and the annulus template);
literature-standard, index-buffer-only change. Secondary: consider
softening the morph band on high-curvature crests, or narrowing the band
(MORPH_START 0.85) if crest notching remains visible mid-band.

## Gotchas discovered along the way

- The old single texture gave coarse rings CONSTANT-frequency shading detail
  for free; ring-matched textures lose it. _TEXELS_PER_CELL=2 restores one
  octave; raise it if mid-field looks too smooth in flight.
- Coarse-ring sampling MUST be bounded: unclamped, the outermost ring spans
  ~780 km == dozens of tiles through a 9-tile LRU cache = 1 s rebuild and
  cache thrash. Clamped to the patch for now; real beyond-patch data (phase
  2) needs a tile-overview cache, not naive native sampling.
- Old dead code kept on purpose: _build_patch/_resample_tile (+ their
  test_glo30 tests) still exist for reference; delete in a cleanup pass
  after flight validation.

- M_PER_DEG_LAT lives in ai/camera.py (111139.0), not svs.py.
- _sample_elevations returns elev CLAMPED >=0 where water=True; write the
  sentinel from the water mask, not from elev values.
