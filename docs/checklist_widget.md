# Checklist instrument

Status: ACTIVE, 2026-07-30 (Phase 1 of the cross-repo checklist feature)

The `checklist` instrument renders an interactive challenge-response checklist
the pilot works through with the encoder or a soft/physical button. It reads
**no FIX keys** — checklist state (which item is current, what is acknowledged)
is entirely local to the widget.

This is **Phase 1** of the checklist feature (CAP-115). The full plan —
per-aircraft checklist authoring in the configurator, a `checklist_ref` binding,
and resolve-and-inline delivery — is in the workspace brief
`makerplane/briefs/checklist_instrument_plan.md`. Phase 1 is pyEfis-only: the
checklist set is supplied **inline** in the screen YAML, so the widget is
provable on the bench before any configurator work exists. Later phases replace
the inline payload with a reference binding, but the widget's internal interface
(it consumes a resolved checklist set) is unchanged.

## Config

One inline `checklists` option: a list of checklist objects. Each object is
`{id, title, category, sections|items}`. Categories `normal | abnormal |
emergency` drive the header colour (green / amber / red). Sections are optional
sugar; a checklist may be a flat `items` list.

```yaml
- type: checklist
  options:
    hmi_group: left           # optional; targets this widget from a Button
    checklists:
      - id: before-takeoff
        title: Before Takeoff
        category: normal
        sections:
          - title: Runup
            items:
              - {text: Throttle, response: 1700 RPM}
              - {text: Magnetos, response: CHECK}
              - {note: Confirm the runway is clear}   # informational, not acked
      - id: engine-failure
        title: Engine Failure
        category: emergency
        items:
          - {text: Airspeed, response: BEST GLIDE}
          - {text: Fuel, response: 'ON'}
```

An item is `{text, response?, note?}`. A row with `text` is an
acknowledgeable challenge-response item; a `note`-only row is an informational
line that cannot be acknowledged. Acknowledged state is in-memory and **resets
on restart** — a fresh checklist every flight is the intended behaviour, not a
gap.

Appearance is tuned with the `text_color`, `response_color`, `done_color`,
`current_color` and `section_color` options.

## Control

- **Encoder** (set `encoder_order` on the instrument to include it in the
  screen's encoder cycle): turn to move the current item, click to acknowledge
  the current item and auto-advance to the next un-acknowledged one.
- **HMI actions** (a Button's condition/action, or a real panel key): `checklist
  next item`, `checklist previous item`, `checklist toggle item`, `checklist
  next unacked`, `checklist next list`, `checklist previous list`, `checklist
  reset`. The action argument is a target group (the widget's `hmi_group`); a
  blank argument addresses every checklist on the screen.

## Code

- Widget + pure `ChecklistModel`: `src/pyefis/instruments/checklist/__init__.py`
- Registration: `screens/screenbuilder_factory.py` (`build_checklist` + the
  `checklist` `InstrumentSpec`).
- HMI verbs: `hmi/actionclass.py` (signals) + `editor/schema.py` (`_ACTIONS`).
- Tests: `tests/instruments/checklist/test_checklist.py`.
