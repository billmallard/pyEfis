# AER-806 bench evidence (FP6 `flight_plan` map layer)

Both captures are SIGUSR1 screenshots (`/tmp/pyefis_screenshot.png`) from the
Beelink bench, `moving_map` at `screens/map-controls-test.yaml` (`MAP_CTL_TEST`,
range bumped to 80 NM via the on-screen RNG+ button), staged on
`aer-806/moving-map-flight-plan-layer` against fix-gateway's `dev` (FP2, PR #25
merged) and driven live over the Net-FIX ASCII protocol (127.0.0.1:3490) --
not a mock: `pyefis.service` and `fixgw.service` were the real bench services.

A real KSBA/GVO/RZS/KSMX route was published, then activated and later
redirected, using a one-off netfix client (not part of the pyEfis codebase):

```python
def send(s, key, value, flags="000"):
    # value: float/int as str, bool as "T"/"F", string as-is (NOT "&"-prefixed --
    # that's only how the SERVER formats outbound string broadcasts; a real
    # client, e.g. pyavtools.fix.DB_Item.output_value(), sends the plain string).
    s.sendall(f"{key};{value};{flags}\n".encode("ascii"))

# Aircraft position (~2 NM off the route, so a later direct-to's FROM point
# visibly differs from any route slot), then the route block:
send(s, "LAT", 34.40); send(s, "LONG", -119.80)
send(s, "TRACKM", 310.0); send(s, "GS", 120.0); send(s, "MAGVAR", 12.0)
for i, (ident, lat, lon, wtype) in enumerate([
        ("KSBA", 34.42621, -119.84037, 1), ("GVO", 34.53142, -120.09106, 2),
        ("RZS", 34.02, -119.55, 2), ("KSMX", 34.89892, -120.45758, 1)], start=1):
    send(s, f"FPL{i}ID", ident); send(s, f"FPL{i}LAT", lat)
    send(s, f"FPL{i}LON", lon); send(s, f"FPL{i}TYPE", wtype); send(s, f"FPL{i}ROLE", 0)
send(s, "FPLCOUNT", 4); send(s, "FPLNAME", "KSBA-KSMX"); send(s, "FPLSEQ", 1)
```

## `plan-active-leg.png`

`FPLCMD;1 ACT 2;000` (activate the leg whose TO waypoint is slot 2, GVO).
KSBA -> GVO magenta and 3 px wide, GVO ringed magenta as the active TO
waypoint, GVO -> RZS -> KSMX still white (future, unflown).

## `plan-direct-to.png`

`FPLCMD;2 DTO 3;000` (direct-to slot 3, RZS) on top of the same plan. The
whole original route grays out; a new magenta line runs from the aircraft's
*live position* (not GVO, the previous route slot) to RZS, ringed magenta --
the exact `FPLFRLAT/LON` behaviour this layer's off-by-one fix (see the PR
body) depends on, demonstrated live against the real engine, not just the
unit tests.
