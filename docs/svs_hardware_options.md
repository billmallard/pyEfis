# SVS Hardware Options

Hardware research notes for SVS performance benchmarking and potential
aircraft installation. Companion to [`svs_planning.md`](svs_planning.md)
section 4.

Prices and exact SKUs shift; verify everything before ordering.

## Two distinct purposes

A **lab box** for benchmarking and a candidate **aircraft-installable** unit
have different priorities. Buy the lab box first; only escalate to
aircraft-rated hardware after profiling proves it's needed.

---

## Lab / desk experimentation — Intel N100 class

For benchmarking SVS framerates against Pi 4 / Pi 5. Any of these will run
pyEfis at full `cpu_dense` / `cpu_ultra` and exercise the OpenGL tier when
it ships. None are aircraft-rated.

| Model | Chip | Price (approx) | Notes |
|---|---|---|---|
| Beelink Mini S13 | N150 | ~$170 | Fanless, 12V barrel, common 16/500 config |
| Beelink EQ14 | N150 | ~$200 | More I/O than the S-series |
| MeLE Quieter 4C | N100 | ~$220 | Smaller than Beelink, 12V |
| Trigkey Speed S5 / Mini K | N100 | ~$160 | Often the cheapest path to "real x86 perf" |

**Recommendation for desk benchmarking**: Beelink Mini S13. Cheap, well-known,
plenty of reviews. Run the SVS visual harness alongside one on a Pi 5 to get
direct comparison numbers.

---

## Aircraft-installable — 12V / 24V, fanless, vibration-tolerant

Aircraft-electrical-system-friendly. Three tiers; cost climbs steeply.

### Tier 1: DIY — Pi 5 + aviation power conditioning (~$150 total)

- **Raspberry Pi 5 8GB**, official active cooler (mandatory in an enclosed
  installation; passive cooling will throttle).
- DC step-down / conditioner:
  - **TracoPower TEN 8-2411WIN** — 9-36V → 5V, ~$30. Covers 12V and 24V
    aircraft systems with brownout tolerance during engine start.
  - **Mean Well DDR-15G-5** — 24-28V → 5V, DIN rail, ~$25.
- Add an EMI filter if alternator noise is rough.
- Cheapest and smallest. Compromise: ARM, slower than N100 for
  `cpu_dense+`, and you're integrating power yourself.

### Tier 2: Compulab Fitlet 3 / 4 (~$400-600)

- Fanless x86. Older **Fitlet 3** uses Atom/Celeron; newer **Fitlet 4**
  uses N100 / N305.
- **8-32V DC input** native — covers both 12V and 24V aircraft systems
  without external converter.
- Industrial temperature range. Conformal coating options.
- Israeli-made; reasonable track record in industrial / automotive use.

This is the sweet spot for experimental amateur-built aviation IMO. Not
overkill, not undersized.

### Tier 3: Onlogic (formerly Logic Supply) — ~$700-1500

- **HX310** / **CL210G** / **K430** — purpose-built fanless industrial PCs.
- Wide-input DC (typically 9-36V), rugged enclosure, certified vibration
  ratings.
- The closest to "aviation-grade" without going through TSO certification.
- Real spend; only justified if benchmarking proves x86 is required AND
  you've committed to a real installation.

---

## Other things to plan around when flying it

These are not covered by the box itself.

- **Vibration mounting** — Lord shock mounts on whatever box you pick. Even
  fanless designs have SSDs and connectors that hate vibration; modern NVMe
  is reasonably robust but isolation matters.
- **Display** — separate decision. Most experimental builders use a 7"-10"
  HDMI panel. Sunlight readability is the big one. Vendors: Faytech,
  Beetronics, PiHut, sometimes industrial OEMs.
- **Power sequencing / brownouts** — engine start can dip a 12V bus to
  ~7V momentarily. Make sure the supply has hold-up capacitance or "no
  brownout" rating. This bites people more than expected.
- **Heat** — fanless boxes need airflow. In a tightly-cowled installation
  with radiative-only cooling, an N100 can throttle on a hot day. Plan to
  temperature-log a hot-day flight test before committing.

---

## Recommended order of purchase

1. **Beelink Mini S13 (~$170)** for the desk. Run the SVS harness, get hard
   numbers. This tells you whether x86 unblocks anything you can't do on
   Pi 5.
2. **Hold off** on aircraft-grade hardware until lab benchmarking proves
   you need x86 in flight. The Pi 5 + TracoPower path remains viable until
   profiling rules it out.
3. **Escalate to Compulab Fitlet 4** only if (a) profiling proves x86 is
   required in flight, *and* (b) you've decided to invest in a real
   installation rather than further experimentation.
4. **Onlogic** is for after the experimental phase, when the design is
   stable and you want a hardened box. Don't buy speculatively — the
   $170 → $500 → $1500 ladder is steep and the Pi 5 may turn out to be
   enough.

---

## Open questions to resolve while researching

- **12V vs 24V aircraft system**: which one are you building for? Most
  small experimental aircraft are 12V; the answer narrows the power-supply
  choice.
- **Display already chosen?** Many of these mini-PCs come barebones —
  display is a separate ~$100-300 spend. Resolution and brightness drive
  the choice.
- **Performance ceiling target**: are you aiming for `cpu_ultra` at
  >20 Hz, or is `cpu_dense` at 20 Hz enough? The answer changes whether
  Pi 5 alone is sufficient.
- **Certification path**: experimental amateur-built only? Or any
  expectation of a TSO / PMA path later? The latter changes hardware
  selection significantly (Onlogic territory).
