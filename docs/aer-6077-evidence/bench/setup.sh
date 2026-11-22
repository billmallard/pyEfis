set -u
S=$HOME/bench-scratch/aer6077; mkdir -p $S/cfg; cd $S
[ -d fix-gateway ] || git clone -q --depth 1 -b dev https://github.com/billmallard/fix-gateway.git
[ -d pyEfis ] || git clone -q --depth 1 -b dev https://github.com/billmallard/pyEfis.git
echo "fgw $(git -C fix-gateway log --oneline -1)"; echo "pye $(git -C pyEfis log --oneline -1)"
grep -c DEMOLOOP fix-gateway/src/fixgw/config/database/demo.yaml pyEfis/src/pyefis/kiosk.py
rm -rf cfg/fixgw cfg/pyefis
cp -r fix-gateway/src/fixgw/config cfg/fixgw
sed -i "s/^\(\s*port:\s*\)3490\b/\13492/" cfg/fixgw/connections/netfix.yaml
cat > cfg/fixgw/connections/demo.yaml <<Y
# AER-6077 bench strip: show-unit demo, short route so a loop comes round in ~5 min
demo:
  load: DEMO
  module: fixgw.plugins.demo
  traffic: true
  profile: turn4-kmic-r32-faf30.yaml
  pages:
    - {at: 0, page: "PFD/Map"}
Y
cp -r $HOME/show/config/pyefis cfg/pyefis
for f in cfg/pyefis/main/*.yaml; do sed -i "s/^\(\s*FixPort:\s*\)[0-9]*/\13492/" $f; done
python3 - <<P
p="cfg/pyefis/default.yaml"; s=open(p).read()
i=s.index("\n# show-unit.sh (DEMO6)\nkiosk:")
s=s[:i]+"""
# AER-6077 bench strip (show-unit kiosk + DEMO12 defaults)
kiosk:
  enabled: true
  idle_return_s: 60
  defaults:
    NAVSRC: 2
    BARO: 29.92
    ALTSEL: 3000
    MAPRANGE: 2
"""
open(p,"w").write(s)
P
tail -11 cfg/pyefis/default.yaml
echo "--- fixgw cfg diff vs show (expect demo.yaml, netfix, DEMOLOOP and dev changes)"
diff -rq $HOME/show/config/fixgw cfg/fixgw
echo "--- state paths"; grep -rn "file\|path" cfg/fixgw/connections/state_persist.yaml 2>/dev/null | grep -v "^\s*#" | head -5
grep -rn "DEMO\b\|DEMO:" cfg/fixgw/preferences.yaml* | head
