set -e
S=$HOME/bench-scratch/aer6086; cd $S
sed -i 's/port: 3490/port: 3492/' fgwcfg/connections/netfix.yaml
python3 - <<'PY'
p='fgwcfg/preferences.yaml.custom'
s=open(p).read()
s=s.replace('  KNOBSTER: true','  KNOBSTER: false').replace('enabled:\n','enabled:\n  XPLANE: false\n',1)
open(p,'w').write(s)
p='efiscfg/main/default.yaml'; s=open(p).read(); open(p,'w').write(s.replace('FixPort: 3490','FixPort: 3492'))
p='efiscfg/screens/managed.yaml'; s=open(p).read(); open(p,'w').write(s.replace('svs_enabled: true','svs_enabled: false',1))
PY
grep -n "port" fgwcfg/connections/netfix.yaml | head -2; grep -n "XPLANE\|KNOBSTER\|FLIGHTPLAN:" fgwcfg/preferences.yaml.custom
# Route state from the merged engine itself (FLOUT, TONIE, OSH from tests/sim/test_obs_tonie.py)
PYTHONPATH=fgw/src:fgw ~/pyefis-venv/bin/python - <<'PY'
import json, fixgw.geo as geo
from fixgw.plugins.flightplan.engine import Engine, Waypoint
import fixgw.plugins.flightplan.engine as engine
MAGVAR=-12.0; TONIE=(34.70,-120.20)
FLOUT=geo.destination_point(*TONIE, 310.0-MAGVAR+180.0, 40.0)
OSH=geo.destination_point(*TONIE, 40.0, 25.0)
route=[Waypoint("FLOUT",*FLOUT),Waypoint("TONIE",*TONIE),Waypoint("OSH",*OSH)]
e=Engine(); e.load_route(route,"OBS3 TONIE",1,engine.waypoint_segments(route))
json.dump(e.to_persisted_dict(), open("fgwcfg/flightplan_state.json","w"))
print("FLOUT",FLOUT,"OSH",OSH)
PY
