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
- [ ] Increment 1 — CPU builder + tests.
- [ ] Increment 2 — shader + GL plumbing.
- [ ] Increment 3 — local validation renders.
- [ ] Increment 4 — perf pass on rebuild cadence.
- [ ] Increment 5 — Pi flight validation, then merge to display-changes.

## Gotchas discovered along the way

- (add as found)
