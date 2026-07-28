# docs/ index

Routing file for this docs tree: what each document is and whether it is
**live reference** or a **historical record**. Read this before trusting any
individual doc — plans that shipped are kept for the record, not as guidance.

**Conventions**

- New docs start with a one-line `Status:` header (`SPEC | PLAN | ACTIVE |
  COMPLETE — historical | ARCHIVED`), dated.
- When a plan is executed, mark it `COMPLETE — historical` in place (links keep
  working); move only *session-scoped handoffs* to `archive/`.
- When you find yourself correcting a doc's guidance twice, fix the doc, not
  just your work (edit the source, not the output).
- Adding a doc? Add its line here.

Live workstream state lives outside the repo in the workspace ledger
(`makerplane/STATE.md`, local umbrella dir).

## Reference (live — trust these)

| Doc | What |
|---|---|
| [avionics_reference.md](avionics_reference.md) | Page-cited FAA standards basis for the instrument-verification workstream |
| [instrument_spec.md](instrument_spec.md) | Instrument definition specification (active pilot) |
| [adding_an_instrument.md](adding_an_instrument.md) | How-to: add/change an instrument + its configurator twin without drift |
| [screenbuilder.md](screenbuilder.md) | Screen YAML / screenbuilder reference (upstream-origin) |
| [requirements.md](requirements.md) | pyEfis display requirements (upstream-origin) |
| [wiki/Headless-Linux-Appliance.md](wiki/Headless-Linux-Appliance.md) | x86-64 headless Linux source install + boot-to-EFIS kiosk notes/gotchas (eglfs-vs-wheel, X/xcb, systemd) — published to the wiki |
| [svs_rendering.md](svs_rendering.md) | SVS renderer tiers, polar config, runway markings |
| [svs_data_refresh.md](svs_data_refresh.md) | Manual FAA data refresh workflow (NASR/CIFP/DOF) |
| [water_database.md](water_database.md) | Water DB build + format |
| [terrain_mip_pyramid.md](terrain_mip_pyramid.md) | Terrain mip pyramid (now built by the makerplane-data cloud pipeline) |
| [canaerospace_background.md](canaerospace_background.md) | CANaerospace protocol background |
| [wiki-publishing.md](wiki-publishing.md) | How the docs/wiki pages publish to the GitHub wiki |
| [project_template.md](project_template.md) | Transferable new-project playbook |

## Upstream landing package (live)

[validation_checklist.md](validation_checklist.md) — the ~30-min PASS/FAIL pass
for reviewers · [reviewer_notes.md](reviewer_notes.md) — behavioral-change +
risk table, tested-where matrix · [running_from_source.md](running_from_source.md)

## Instrument verification (live workstream)

[instrument_verification_status.md](instrument_verification_status.md) is the
tracker — 7/7 instruments verified + deployed as of 2026-07-01. Per-instrument
specs with requirement IDs: [ai](ai_widget_spec.md) ·
[airspeed](airspeed_widget_spec.md) · [altimeter](altimeter_widget_spec.md) ·
[heading](heading_widget_spec.md) · [hsi](hsi_widget_spec.md) ·
[tc](tc_widget_spec.md) · [vsi](vsi_widget_spec.md)

## Plans & specs (open — not yet implemented)

| Doc | Status |
|---|---|
| [svs_papi_plan.md](svs_papi_plan.md) | Open plan — VASI/PAPI adoption into GL SVS (#38) |
| [map_layers_roadmap.md](map_layers_roadmap.md) | PLAN 2026-07-10 — roads/rivers LOD + FAA raster charts |
| [map_wide_range_perf_plan.md](map_wide_range_perf_plan.md) | PLAN 2026-07-10 — largely executed by the mosaic/mip work; reconcile before acting |
| [gcu_design.md](gcu_design.md) | DRAFT — open GCU control head (parked) |
| [instrument_bugs_design.md](instrument_bugs_design.md) | DRAFT — selected-value bug markers (companion to GCU) |
| [fixgw_canaerospace_in_spec.md](fixgw_canaerospace_in_spec.md) | Spec, future work (untracked; out of landing scope) |
| [fixgw_dronecan_in_spec.md](fixgw_dronecan_in_spec.md) | Spec, future work (untracked; out of landing scope) |
| [SVS_QUICKSTART.md](SVS_QUICKSTART.md) | WIP quickstart (untracked) |
| [moving_map_spec.md](moving_map_spec.md) | Spec — NOTE: its "development not started" header is stale; Phases A–D shipped and are flying |

## Historical (executed / superseded — record only)

| Doc | Why kept |
|---|---|
| [svs_structural_plan.md](svs_structural_plan.md) | P0–P5 structural plan — landed |
| [svs_opengl_plan.md](svs_opengl_plan.md) | GL terrain renderer plan — COMPLETE |
| [svs_overlays_to_gpu_plan.md](svs_overlays_to_gpu_plan.md) | Overlays-to-GPU plan — COMPLETE |
| [svs_planning.md](svs_planning.md) | Original SVS/VirtualVfr rationale (Issue #28) — shipped |
| [svs_hardware_options.md](svs_hardware_options.md) | Hardware trade study — Pi 5 chosen and flying |
| [perf_baseline_gpu_required.md](perf_baseline_gpu_required.md) | P0 perf baseline artifact (2026-06-10) |
| [data_manager_strategy.md](data_manager_strategy.md) | Superseded — canonical copy lives in makerplane-data |
| [data_manager_implementation.md](data_manager_implementation.md) | Superseded — canonical copy lives in makerplane-data |
| archive/ | Session-scoped handoffs (`next_session.md`, `map_perf_deploy_handoff.md`) |

Also here: `wiki/` (the widget/screen manual, mirrored to the GitHub wiki),
`images/` (manual screenshots), the legacy Sphinx scaffold (`*.rst`, `conf.py`,
`Makefile`, upstream-origin), and `190-02246-01_f.pdf` (GNX-375 install manual,
untracked source material).
