#!/bin/bash
cd ~/bench-scratch/aer6086
got_on=0; got_from=0
for i in $(seq 1 240); do
  IFS=, read -r wall lat lon dist st crs xtk tf rest <<< "$(tail -1 run/feed.csv)"
  if [ $got_on = 0 ] && [ "$tf" = "1" ] && awk "BEGIN{exit !($xtk<0.3 && $xtk>-0.3)}"; then WAIT=0.2 ./g.sh s12_on_course; got_on=1; fi
  if [ $got_from = 0 ] && [ "$tf" = "2" ] && awk "BEGIN{exit !($dist>1.5)}"; then touch run/hold; WAIT=1.5 ./g.sh s13_from_past_tonie; got_from=1; break; fi
  sleep 1
done
echo done on=$got_on from=$got_from
