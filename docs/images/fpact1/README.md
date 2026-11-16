# FPACT1 evidence (AER-5801)

FPL page at the Beelink portrait panel size (649x993), plan KSBA, KSMO, then
an RNAV 24 approach (SANFI, HKYFA, RW24) near KHKY, aircraft about 30 nm from
SANFI. Rendered offscreen with the bench's fonts:

- `fpl_before_activate.png`: the page before Activate Leg.
- `fpl_far_fix_question.png`: after Activate Leg on SANFI. The from-fix is
  KSMO, about 1,840 nm away, so the page asks before it sends `ACT`.

Regenerate (on any box with the pyEfis test dependencies):

    QT_QPA_PLATFORM=offscreen PYTHONPATH=src:. python -m pytest -c /dev/null \
        --rootdir . tests/instruments/flight_plan/render_fpact1_evidence.py -q
