# AER-4326 evidence: Font size reaches six widgets (pyEfis #223, #229-#233)

Offscreen renders of the real widgets, built through the Screen path
(YAML `options.font_percent` -> builder -> `apply_options`). They were made on
the Beelink bench (2026-10-31) for its fonts, in a scratch directory, so the
live display and the bench checkout were not touched. Panels are 1:1. The
leftmost panel of each strip is `font_percent` unset, which is today's size.

| File | Left to right |
|---|---|
| `0-tab_section.png` | unset / 0.2 / 0.7 / 150. 0.2 and 0.7 both land on the 8 px label floor, because the bench's default label is about 11 px. |
| `1-tab_section-left.png` | `tab_position: left`: unset / 0.7 / 150. The side bar widens with the label. |
| `2-button.png` | unset / 0.5 / 0.8 |
| `3-listbox.png` | unset / 0.6 / 150. Rows follow the font. Column widths do not, so text clips at 150. |
| `4-data_status.png` | unset / 0.7 / 130. Only text scales. At 130 the message clips at its column. |
| `5-checklist.png` | unset / 0.6 / 150. The line pitch scales with the text, so 150 shows fewer lines. |

The dark-on-dark tab labels are a harness artifact. The renderer doesn't
apply the central screen palette that `screenbuilder.py` sets on the device.
Values over 1 are whole-number percents (150 = 150%). Only hand-written YAML
can reach them, because the configurator's Font size field is capped at 1.0.

## How to regenerate

From a pyEfis checkout:

    QT_QPA_PLATFORM=offscreen PYTHONPATH=src python \
        docs/aer-4326-evidence/render_font_percent.py <out_dir>

The scenes and values are the `SCENES` list in that script.
