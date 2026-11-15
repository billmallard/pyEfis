#!/bin/sh
# batch.sh name spec... ; spec = label|ENV=V,ENV2=V|repro opts
cd ~/bench-scratch/aer5478; B=$1; shift
[ -s ~/.bench-claim ] && ! grep -q AER-5418 ~/.bench-claim && { echo "claim changed"; cat ~/.bench-claim; exit 9; }
for spec in "$@"; do
  L=$(echo "$spec" | cut -d'|' -f1); E=$(echo "$spec" | cut -d'|' -f2 | tr ',' ' '); O=$(echo "$spec" | cut -d'|' -f3)
  env $E sh run.sh $L 100 $O 2>/dev/null | grep -v Broken
done
echo BATCH-DONE
