# AER-3916 bench evidence: altimeter-setting units through a real config pull

Beelink bench (X11), 2026-10-26. pyEfis at `aer-3916/unit-group-defaults`
(`8110f8e`, this PR), staged with `bench-deploy.sh --ref`. The configurator side is
makerplane-data#109 at `6e47b1f`, run under `wrangler dev --local`. That PR was held
unmerged, so it could not be deployed to pyefis-dev.

| File | What it shows |
|---|---|
| `baro-before-after-crop.png` | 1:1 crop of the altimeter tape and BARO readout. Left: profile `baro_unit: inHg`. Right: profile `baro_unit: hPa`. Same panel, same BARO value. |
| `before-inhg-half.png`, `after-hpa-half.png` | The full 1920x1080 flight frames (x11grab after Continue), downscaled to 50%. |
| `test-panel.yaml` | The panel the local server served. It is the bench device's real pyefis-dev panel (v45) plus one stock-style BARO `numeric_display` (`pressure: true`) under the altimeter tape. v45 has no baro readout, and the tape's own baro box is #311. |

## How it was produced

1. Run makerplane-data#109's `configurator/` under
   `wrangler dev --local --persist-to <dir> --port 8787`, after
   `wrangler d1 migrations apply makerplane_configurator --local`.
   Seed one user, project and device (`device_token_hash` = base64url
   sha256 of a fresh token), a `configs` row pointing at `test-panel.yaml` in
   local R2, and an active `aircraft_profiles` row with `meta.baro_unit`.
2. `ssh -R 18787:127.0.0.1:8787` to the bench. Under the bench lock
   (`flock /tmp/pyefis-bench.lock`), run #109's updater from a scratch copy:
   `PYTHONPATH=<scratch> python -m pyefis_data.cli --config <scratch>/data.yaml config-pull --no-restart`,
   where the scratch `data.yaml` holds only `configurator_url: http://127.0.0.1:18787`
   and the local device token. The bench's own `data.yaml` and pairing were not touched.
3. `bench-deploy.sh --ref aer-3916/unit-group-defaults --owner AVIONICS --issue AER-3916`
   to restart pyEfis and capture the flight frame.
4. Flip the active profile to `baro_unit: hPa`, then repeat steps 2 and 3.

Pull transcript:

```
inHg profile: aircraft units: Pressure inHg / installed panel config v1 -> units: {Pressure: inHg}, config_etag "v1-pdc4f0da7e3e9"
hPa profile:  aircraft units: Pressure hPa  / installed panel config v1 -> units: {Pressure: hPa},  config_etag "v1-pcce300feb41a"
```

Both restarts: `pyefis.service: active`, no tracebacks or missing-screen errors.
Afterwards the bench's config files were restored from a backup taken first,
and the bench was returned to `dev` with `--restore`.
