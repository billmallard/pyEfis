#!/bin/sh
# run.sh <label> <cycles>: provenance + recorder + cycles under the bench lock
L=$1; N=$2; cd ~/bench-scratch/aer5326
[ -s ~/.bench-claim ] && ! grep -q AER-5326 ~/.bench-claim && { cat ~/.bench-claim; exit 9; }
prov() { echo "$1 $(date -u +%FT%T.%NZ) head=$(git -C ~/src/pyEfis rev-parse --short HEAD) pyefis=$(systemctl --user show -p MainPID --value pyefis) fixgw=$(systemctl --user show -p MainPID --value fixgw) load=$(cut -d' ' -f1-3 /proc/loadavg)" >> prov_$L.txt; }
prov start
mkdir -p glass_$L
setsid -f ~/pyefis-venv/bin/python glassrec.py glass_$L 1260 36 648 1004 30 </dev/null >glass_$L/rec.err 2>&1
sleep 2
python3 cycle.py $L $N
sleep 3
pkill -f "glassrec.py glass_$L" 
prov end
cat prov_$L.txt
