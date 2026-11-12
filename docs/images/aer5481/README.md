# AER-5481: Data Status panel-change banner (CERT17)

Offscreen renders of the Data Status screen, with the panel-change banner
(`panel_change.pending` true) and without it (pending false). The text is the
proposal in makerplane-data `docs/panel_change_cue.md`, "Proposed cue".

Regenerate:

    QT_QPA_PLATFORM=offscreen PYTHONPATH=src python3 docs/images/aer5481/render.py

Rendered in the agent sandbox with Qt libs extracted from Debian packages and
DejaVu Sans as the font. DejaVu Sans Condensed is not installed there, so the
glass uses a narrower face than these images.
