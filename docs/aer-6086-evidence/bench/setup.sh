set -e
S=$HOME/bench-scratch/aer6086; mkdir -p $S; cd $S
[ -d fgw ] || git clone -q --reference $HOME/src/fix-gateway https://github.com/billmallard/fix-gateway.git fgw
git -C fgw fetch -q origin dev && git -C fgw checkout -q e2f7bf208468707e4a4aa66e845273d69af8fac7
[ -d pyefis ] || git clone -q --reference $HOME/src/pyEfis https://github.com/billmallard/pyEfis.git pyefis
git -C pyefis fetch -q origin aer-6086/obs3-gps-obs && git -C pyefis checkout -q 981a56767255a82f10d245ec7a615a2d5a548dd4
rm -rf fgwcfg efiscfg; cp -a $HOME/makerplane/fixgw/config fgwcfg; cp -a $HOME/makerplane/pyefis/config efiscfg
rm -f fgwcfg/flightplan_state.json fgwcfg/persist_state.json
git -C fgw log --oneline -1; git -C pyefis log --oneline -1
