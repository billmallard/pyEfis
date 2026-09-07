# AER-701 / pyEfis#102 -- SVS water line-of-sight masking evidence

These two images are a synthetic top-down diagnostic, **not** a capture of the
live 3D SVS screen -- a real GL screen grab requires the AER-658
`driver.py`/`glReadPixels` capture pipeline, which is itself pending the
maos-workspace write-access gap tracked on AER-659 (explicitly out of scope
for this fix per Elon's AER-701 ruling: the coastal re-render is a
nice-to-have, not a dependency).

What they ARE: the actual production code (`SVSRenderer._collect_water_sync`,
`_los_masked_batch`, `_sample_elevations`) run end-to-end against a synthetic
SRTM tile (a flat plain + one 7000 ft east-west ridge) and a one-polygon water
database (a lake north of the ridge, geometrically the same shape as the
reported bug -- a water body behind a mountain from the aircraft's
viewpoint). The blue triangles drawn in each image are exactly what
`_collect_water_sync` returned for that run; nothing is hand-drawn.

- `before_water_through_ridge.png` -- `_los_masked_batch` stubbed to report
  "nothing occluded" (i.e. pre-#102 behaviour). The lake draws in full even
  though the ridge sits on the sight line from the aircraft, matching the
  reported defect (a water body rendering through a mountain).
- `after_water_los_masked.png` -- the real, unmodified fix. Both lake
  triangles have an occluded vertex, so `_collect_water_sync` returns zero
  triangles; the dashed white line marks where the lake would have been.

Regenerate with:

```bash
cd pyEfis
export QT_QPA_PLATFORM=offscreen
export PYTHONPATH="$PWD/src:$PWD"
python3 docs/images/aer701_svs_water_los/render_evidence.py /tmp/aer701_out
```

(`render_evidence.py` is the exact script used to produce these PNGs, kept
alongside them per repo convention.)
