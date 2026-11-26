#!/bin/sh
# AER-6706: put the fixgw config and the bench's standing route back.
D=$HOME/bench-scratch/efb4b
C=$HOME/makerplane/fixgw/config
cp -p $C/flightplan_state.json $D/flightplan_state.after-accept.json
flock -w 300 /tmp/pyefis-bench.lock sh -c "
  sudo systemctl stop fixgw &&
  rm -f $C/preferences.yaml.custom $C/connections/fpl_exchange.yaml $C/flightplan_state.json &&
  cp -p $D/preferences.yaml.custom.pre-AER-6706 $C/preferences.yaml.custom &&
  cp -p $D/fpl_exchange.yaml.pre-AER-6706 $C/connections/fpl_exchange.yaml &&
  cp -p $HOME/bench-scratch/aer6531/fgwcfg/flightplan_state.json $C/flightplan_state.json &&
  sudo systemctl start fixgw && sleep 8 && systemctl --user restart pyefis.service" 9>&-
cmp $D/preferences.yaml.custom.pre-AER-6706 $C/preferences.yaml.custom && cmp $D/fpl_exchange.yaml.pre-AER-6706 $C/connections/fpl_exchange.yaml && echo "fixgw configs identical to pre-AER-6706 copies"
sleep 10
echo "fixgw: $(systemctl is-active fixgw) pyefis: $(systemctl --user is-active pyefis) 8080 listening: $(ss -ltn | grep -c ':8080 ')"
sh $D/bus.sh
